"""Safe all-or-nothing inventory import for the Supply Chain Mini App.

Browser-side validation is only a preview. This module validates every row
again on the server and returns a mutation function for the CAS commit adapter.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone

MAX_ROWS = 10_000
MAX_SKU = 128
MAX_NAME = 240
MAX_NUMBER = 1_000_000_000_000


class ImportValidationError(ValueError):
    pass


def normalize_payload(payload):
    if not isinstance(payload, dict):
        raise ImportValidationError("JSON object talab qilinadi.")
    operation_id = payload.get("operation_id")
    if (not isinstance(operation_id, str) or not operation_id.strip()
            or len(operation_id) > 128
            or not re.fullmatch(r"[A-Za-z0-9._:-]+", operation_id)):
        raise ImportValidationError("Import identifikatori noto'g'ri.")
    expected = payload.get("expected_version")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ImportValidationError("Ma'lumot versiyasi noto'g'ri.")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise ImportValidationError("1 dan 10 000 tagacha qator yuborilishi kerak.")

    clean, seen = [], set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ImportValidationError(f"{index}-qator noto'g'ri.")
        sku, name = row.get("sku"), row.get("name")
        if not isinstance(sku, str) or not sku.strip() or len(sku.strip()) > MAX_SKU:
            raise ImportValidationError(f"{index}-qatorda SKU noto'g'ri.")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME:
            raise ImportValidationError(f"{index}-qatorda mahsulot nomi noto'g'ri.")
        sku = sku.strip()
        if sku.casefold() in seen:
            raise ImportValidationError(f"{index}-qatorda takroriy SKU bor.")
        seen.add(sku.casefold())

        def number(field, optional=False):
            value = row.get(field)
            if value is None and optional:
                return None
            if isinstance(value, bool):
                raise ImportValidationError(f"{index}-qatorda {field} noto'g'ri.")
            try:
                parsed = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ImportValidationError(f"{index}-qatorda {field} raqam bo'lishi kerak.") from exc
            if not math.isfinite(parsed) or parsed < 0 or parsed > MAX_NUMBER:
                raise ImportValidationError(f"{index}-qatorda {field} ruxsat etilgan chegaradan tashqarida.")
            return parsed

        clean.append({
            "sku": sku, "name": name.strip(),
            "quantity": number("quantity"),
            "unit_cost": number("unit_cost", optional=True),
            "reorder_point": number("reorder_point", optional=True),
        })

    canonical = {"expected_version": expected, "rows": clean}
    digest = hashlib.sha256(json.dumps(
        canonical, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return operation_id, expected, clean, digest


def mutate_inventory(snapshot, rows):
    products = snapshot.get("products")
    if not isinstance(products, dict):
        raise ImportValidationError("Saqlangan mahsulotlar ro'yxati noto'g'ri.")
    movements = snapshot.get("movements", [])
    if not isinstance(movements, list):
        raise ImportValidationError("Saqlangan kirim-chiqim tarixi noto'g'ri.")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    created = updated = unchanged = 0
    changes = []
    for row in rows:
        sku = row["sku"]
        existing_key = next((key for key in products if str(key).casefold() == sku.casefold()), None)
        if existing_key is None:
            product = {
                "sku": sku, "name": row["name"], "quantity": row["quantity"],
                "unit": "pcs", "created_at": now, "updated_at": now,
            }
            if row["unit_cost"] is not None:
                product["unit_cost"] = row["unit_cost"]
            if row["reorder_point"] is not None:
                product["reorder_point"] = row["reorder_point"]
            products[sku] = product
            created += 1
            changes.append({"sku": sku, "action": "created", "before": None,
                            "after": row["quantity"]})
            delta = row["quantity"]
        else:
            product = products[existing_key]
            if not isinstance(product, dict):
                raise ImportValidationError(f"{existing_key} mahsulot yozuvi buzilgan.")
            old_quantity = product.get("quantity", 0)
            unknown_before = old_quantity is None
            if unknown_before:
                old_quantity = 0.0
            if isinstance(old_quantity, bool):
                raise ImportValidationError(f"{existing_key} ombor miqdori noto'g'ri.")
            try:
                old_quantity = float(old_quantity)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ImportValidationError(f"{existing_key} ombor miqdori noto'g'ri.") from exc
            if not math.isfinite(old_quantity) or old_quantity < 0:
                raise ImportValidationError(f"{existing_key} ombor miqdori noto'g'ri.")
            product["name"] = row["name"]
            product["quantity"] = row["quantity"]
            if row["unit_cost"] is not None:
                product["unit_cost"] = row["unit_cost"]
            if row["reorder_point"] is not None:
                product["reorder_point"] = row["reorder_point"]
            product["updated_at"] = now
            delta = row["quantity"] - old_quantity
            updated += 1
            if abs(delta) < 1e-12 and not unknown_before:
                unchanged += 1
            else:
                changes.append({"sku": str(existing_key), "action": "updated",
                                "before": None if unknown_before else old_quantity,
                                "after": row["quantity"]})

        if abs(delta) >= 1e-12:
            movements.append({
                "id": "excel-" + hashlib.sha256(
                    f"{sku}|{now}|{len(movements)}".encode()
                ).hexdigest()[:16],
                "sku": sku, "type": "in" if delta > 0 else "out",
                "quantity": abs(delta),
                "note": "Excel import — opening balance (previous quantity unknown)" if existing_key is not None and unknown_before else "Excel import — stock adjustment",
                "created_at": now,
            })

    snapshot["movements"] = movements[-50_000:]
    return {
        "processed": len(rows), "created": created, "updated": updated,
        "unchanged_quantity": unchanged, "changes": changes[:100],
        "changes_truncated": len(changes) > 100,
    }


def commit_inventory_import(adapter, payload):
    operation_id, expected, rows, request_hash = normalize_payload(payload)

    def apply(snapshot):
        return mutate_inventory(snapshot, rows)

    return adapter.commit(
        expected_version=expected,
        operation_id=operation_id,
        request_hash=request_hash,
        mutate=apply,
    )
