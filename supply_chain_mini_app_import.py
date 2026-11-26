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
    source_name = payload.get("source_name", "inventory-import")
    source_sheet = payload.get("source_sheet", "")
    if not isinstance(source_name, str) or not isinstance(source_sheet, str):
        raise ImportValidationError("Import fayl metama'lumoti noto'g'ri.")
    source_name = source_name.replace("\\", "/").split("/")[-1].strip()
    source_name = "".join(ch for ch in source_name if ord(ch) >= 32 and ord(ch) != 127)[:180]
    source_sheet = "".join(ch for ch in source_sheet if ord(ch) >= 32 and ord(ch) != 127).strip()[:120]
    if not source_name:
        source_name = "inventory-import"
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
        unit = row.get("unit")
        if unit is not None:
            if not isinstance(unit, str) or len(unit.strip()) > 32:
                raise ImportValidationError(f"{index}-qatorda birlik noto'g'ri.")
            unit = "".join(ch for ch in unit.strip() if ord(ch) >= 32 and ord(ch) != 127) or None
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
            "sku": sku, "name": name.strip(), "unit": unit,
            "quantity": number("quantity"),
            "unit_cost": number("unit_cost", optional=True),
            "reorder_point": number("reorder_point", optional=True),
        })

    canonical = {"expected_version": expected, "source_name": source_name,
                 "source_sheet": source_sheet, "rows": clean}
    digest = hashlib.sha256(json.dumps(
        canonical, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return operation_id, expected, clean, digest, source_name, source_sheet


def mutate_inventory(snapshot, rows, source_name="inventory-import", source_sheet=""):
    products = snapshot.get("products")
    if not isinstance(products, dict):
        raise ImportValidationError("Saqlangan mahsulotlar ro'yxati noto'g'ri.")
    movements = snapshot.get("movements", [])
    if not isinstance(movements, list):
        raise ImportValidationError("Saqlangan kirim-chiqim tarixi noto'g'ri.")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    created = updated = unchanged = unchanged_quantity = 0
    changes = []
    for row in rows:
        sku = row["sku"]
        existing_key = next((key for key in products if str(key).casefold() == sku.casefold()), None)
        if existing_key is None:
            product = {
                "sku": sku, "name": row["name"], "quantity": row["quantity"],
                "unit": row["unit"] or "pcs", "created_at": now, "updated_at": now,
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
            changed_fields = []
            if product.get("name") != row["name"]:
                product["name"] = row["name"]
                changed_fields.append("name")
            if row["unit"] is not None and product.get("unit") != row["unit"]:
                product["unit"] = row["unit"]
                changed_fields.append("unit")
            if row["unit_cost"] is not None:
                try:
                    old_cost = float(product.get("unit_cost"))
                except (TypeError, ValueError, OverflowError):
                    old_cost = None
                if old_cost != row["unit_cost"]:
                    product["unit_cost"] = row["unit_cost"]
                    changed_fields.append("unit_cost")
            if row["reorder_point"] is not None:
                try:
                    old_reorder = float(product.get("reorder_point"))
                except (TypeError, ValueError, OverflowError):
                    old_reorder = None
                if old_reorder != row["reorder_point"]:
                    product["reorder_point"] = row["reorder_point"]
                    changed_fields.append("reorder_point")
            delta = row["quantity"] - old_quantity
            if unknown_before or abs(delta) >= 1e-12:
                product["quantity"] = row["quantity"]
                changed_fields.append("quantity")
            if changed_fields:
                product["updated_at"] = now
                updated += 1
                changes.append({"sku": str(existing_key), "action": "updated",
                                "fields": changed_fields,
                                "before": None if unknown_before else old_quantity,
                                "after": row["quantity"]})
            else:
                unchanged += 1
            if abs(delta) < 1e-12 and not unknown_before:
                unchanged_quantity += 1

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
    result = {
        "processed": len(rows), "created": created, "updated": updated,
        "unchanged": unchanged, "unchanged_quantity": unchanged_quantity,
        "changes": changes[:100],
        "changes_truncated": len(changes) > 100,
        "source_name": source_name, "source_sheet": source_sheet,
    }
    history = snapshot.get("import_history", [])
    if not isinstance(history, list):
        raise ImportValidationError("Import tarixi noto'g'ri.")
    history.append({
        "file_name": source_name, "sheet": source_sheet, "created_at": now,
        "processed": len(rows), "created": created, "updated": updated,
        "unchanged": unchanged, "unchanged_quantity": unchanged_quantity,
    })
    snapshot["import_history"] = history[-100:]
    return result


def commit_inventory_import(adapter, payload):
    operation_id, expected, rows, request_hash, source_name, source_sheet = normalize_payload(payload)

    def apply(snapshot):
        return mutate_inventory(snapshot, rows, source_name, source_sheet)

    return adapter.commit(
        expected_version=expected,
        operation_id=operation_id,
        request_hash=request_hash,
        mutate=apply,
    )
