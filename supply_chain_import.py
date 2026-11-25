"""Safe, dependency-free XLSX reader and column mapper for Supply Chain imports.

The importer deliberately separates workbook inspection from mutation. Unknown
columns are surfaced to the caller so the bot can ask the owner before mapping.
"""
from __future__ import annotations

import io
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_CANONICAL = {
    "product_name": {"mahsulot", "mahsulot nomi", "tovar", "tovar nomi", "nomenklatura", "nomi", "product", "product name", "item", "item name", "товар", "наименование", "номенклатура"},
    "sku": {"sku", "kod", "mahsulot kodi", "tovar kodi", "article", "artikul", "артикул", "код"},
    "quantity": {"miqdor", "soni", "qoldiq", "ombor qoldigi", "zaxira", "stock", "quantity", "qty", "balance", "остаток", "количество"},
    "unit": {"birlik", "olchov birligi", "o'lchov birligi", "unit", "uom", "единица", "ед изм"},
    "unit_cost": {"narx", "birlik narxi", "tannarx", "xarid narxi", "cost", "unit cost", "price", "purchase price", "цена", "себестоимость"},
    "reorder_point": {"minimum", "min", "qayta buyurtma nuqtasi", "minimal qoldiq", "reorder point", "safety stock", "минимальный остаток"},
    "annual_demand": {"yillik talab", "yillik sotuv", "annual demand", "yearly sales"},
    "order_cost": {"buyurtma xarajati", "zakaz xarajati", "ordering cost", "order cost"},
    "holding_cost": {"saqlash xarajati", "holding cost", "storage cost"},
    "supplier_name": {"yetkazib beruvchi", "yetkazuvchi", "ta'minotchi", "taminotchi", "supplier", "supplier name", "vendor", "поставщик"},
    "contact": {"aloqa", "telefon", "tel", "email", "contact", "phone", "контакт", "телефон"},
    "lead_time_days": {"yetkazish muddati", "yetkazib berish muddati", "lead time", "delivery days", "muddat kun", "срок поставки"},
    "rating": {"reyting", "baho", "rating", "score", "рейтинг"},
    "month": {"oy", "davr", "month", "period", "sana", "date", "месяц", "период"},
    "demand_quantity": {"talab", "sotuv", "sotuv miqdori", "realizatsiya", "sales", "demand", "sales qty", "продажи"},
    "order_id": {"buyurtma id", "order id", "order", "zakaz raqami"},
    "order_quantity": {"buyurtma miqdori", "order quantity", "ordered qty"},
    "expected_date": {"kutilgan sana", "yetkazish sanasi", "expected date", "delivery date", "дата поставки"},
    "status": {"holat", "status", "статус"},
    "movement_type": {"harakat", "operatsiya", "kirim chiqim", "movement", "type", "operation"},
}
_ALIAS_TO_FIELD = {}
for _field, _aliases in _CANONICAL.items():
    for _alias in _aliases:
        _ALIAS_TO_FIELD[re.sub(r"[^a-z0-9а-я]+", "", _alias.casefold().replace("ё", "е"))] = _field

_REQUIRED = {
    "products": {"product_name", "quantity"},
    "suppliers": {"supplier_name"},
    "demand": {"product_name", "month", "demand_quantity"},
    "orders": {"product_name", "supplier_name", "order_quantity"},
    "movements": {"product_name", "quantity", "movement_type"},
}


def _norm(value: Any) -> str:
    value = str(value or "").strip().casefold().replace("ё", "е")
    return re.sub(r"[^a-z0-9а-я]+", "", value)


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return 0
    out = 0
    for char in letters.group(0):
        out = out * 26 + ord(char) - 64
    return out - 1


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.findall(".//m:t", _NS)) for si in root.findall("m:si", _NS)]


def _workbook_sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {r.attrib["Id"]: r.attrib["Target"] for r in rels.findall("rel:Relationship", _NS)}
    result = []
    for sheet in wb.findall("m:sheets/m:sheet", _NS):
        rid = sheet.attrib.get("{" + _NS["r"] + "}id")
        target = targets.get(rid, "")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = "xl/" + target.lstrip("/")
        result.append((sheet.attrib.get("name", path), path))
    return result


def _cell_value(cell: ET.Element, shared: list[str]) -> Any:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.findall(".//m:t", _NS))
    value = cell.find("m:v", _NS)
    raw = value.text if value is not None else ""
    if kind == "s" and raw:
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    if kind == "b":
        return raw == "1"
    return raw


def _read_sheet(zf: zipfile.ZipFile, path: str, shared: list[str]) -> list[tuple[int, list[Any]]]:
    root = ET.fromstring(zf.read(path))
    output = []
    for row in root.findall(".//m:sheetData/m:row", _NS):
        cells = row.findall("m:c", _NS)
        if not cells:
            continue
        vals: list[Any] = []
        for cell in cells:
            idx = _column_index(cell.attrib.get("r", ""))
            if idx < 0:
                continue
            if len(vals) <= idx:
                vals.extend([""] * (idx + 1 - len(vals)))
            vals[idx] = _cell_value(cell, shared)
        output.append((int(row.attrib.get("r", len(output) + 1)), vals))
    return output


def read_workbook(raw: bytes) -> list[dict[str, Any]]:
    if not raw or len(raw) > 12 * 1024 * 1024:
        raise ValueError("Excel fayl bo'sh yoki 12 MB limitdan katta.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = set(zf.namelist())
            if "xl/workbook.xml" not in names:
                raise ValueError("Bu fayl haqiqiy .xlsx Excel fayli emas.")
            shared = _shared_strings(zf)
            sheets = []
            for name, path in _workbook_sheets(zf):
                if path not in names:
                    continue
                sheets.append({"name": name, "rows": _read_sheet(zf, path, shared)})
            return sheets
    except zipfile.BadZipFile as exc:
        raise ValueError("Excel fayl ochilmadi: .xlsx formatida qayta yuboring.") from exc


def _header_map(values: list[Any], overrides: dict[str, str] | None = None) -> tuple[dict[int, str], list[dict[str, Any]]]:
    mapping: dict[int, str] = {}
    unknown = []
    overrides = overrides or {}
    for idx, value in enumerate(values):
        label = str(value or "").strip()
        if not label:
            continue
        letter = _excel_col(idx)
        forced = overrides.get(letter) or overrides.get(label)
        if forced and str(forced).casefold() in {"ignore", "skip", "kerak emas"}:
            continue
        field = forced if forced in _CANONICAL else _ALIAS_TO_FIELD.get(_norm(forced)) if forced else _ALIAS_TO_FIELD.get(_norm(label))
        if field:
            mapping[idx] = field
        else:
            unknown.append({"column": letter, "header": label})
    return mapping, unknown


def _excel_col(index: int) -> str:
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def inspect_workbook(raw: bytes, overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """Return a non-mutating import preview; unknown headers are never guessed."""
    sheets_out = []
    questions = []
    errors = []
    for sheet in read_workbook(raw):
        rows = sheet["rows"]
        best = None
        for pos, (excel_row, values) in enumerate(rows[:20]):
            mapped, unknown = _header_map(values, overrides)
            score = len(mapped)
            if best is None or score > best["score"]:
                best = {"pos": pos, "excel_row": excel_row, "values": values, "mapping": mapped, "unknown": unknown, "score": score}
        if not best:
            continue
        unknown_nonempty = []
        for item in best["unknown"]:
            col_idx = _column_index(item["column"])
            if any(col_idx < len(row) and str(row[col_idx] or "").strip() for _, row in rows[best["pos"] + 1:]):
                unknown_nonempty.append(item)
                questions.append({"sheet": sheet["name"], **item})
        if best["score"] == 0:
            if not unknown_nonempty:
                errors.append({"sheet": sheet["name"], "row": best["excel_row"], "message": "Ustunlardan birortasi tanilmadi; mos ustunlarni ko‘rsatish kerak."})
            continue
        fields = set(best["mapping"].values())
        kind = None
        for candidate in ("demand", "orders", "movements", "products", "suppliers"):
            required = _REQUIRED[candidate]
            if required.issubset(fields) or (candidate == "orders" and {"product_name", "supplier_name", "quantity"}.issubset(fields)) or (candidate == "demand" and {"product_name", "month", "quantity"}.issubset(fields)) or (candidate == "suppliers" and {"product_name", "lead_time_days"}.issubset(fields)):
                kind = candidate
                break
        if kind is None:
            missing = []
            for candidate, required in _REQUIRED.items():
                if fields & required:
                    missing.append(candidate + ": " + ", ".join(sorted(required - fields)))
            errors.append({"sheet": sheet["name"], "row": best["excel_row"], "message": "Jadval turi aniqlanmadi yoki majburiy ustun yetishmaydi. " + "; ".join(missing[:3])})
            continue
        records = []
        for excel_row, values in rows[best["pos"] + 1:]:
            if not any(str(v or "").strip() for v in values):
                continue
            record = {"_row": excel_row}
            for idx, field in best["mapping"].items():
                record[field] = values[idx] if idx < len(values) else ""
            if kind == "orders" and "order_quantity" not in record and "quantity" in record:
                record["order_quantity"] = record["quantity"]
            if kind == "demand" and "demand_quantity" not in record and "quantity" in record:
                record["demand_quantity"] = record["quantity"]
            if kind == "suppliers" and "supplier_name" not in record and "product_name" in record:
                record["supplier_name"] = record["product_name"]
            if any(str(v or "").strip() for k, v in record.items() if k != "_row"):
                records.append(record)

        sheets_out.append({
            "name": sheet["name"], "kind": kind, "header_row": best["excel_row"],
            "columns": { _excel_col(i): f for i, f in best["mapping"].items() },
            "unknown": unknown_nonempty, "records": records,
        })
    return {"sheets": sheets_out, "questions": questions, "errors": errors,
            "record_count": sum(len(s["records"]) for s in sheets_out)}


def _num(value: Any, sheet: str, row: int, field: str, errors: list[dict[str, Any]], default: float | None = None) -> float | None:
    if value is None or str(value).strip() == "":
        return default
    raw = str(value).strip().replace(" ", "").replace(",", ".")
    try:
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError
        return number
    except (ValueError, TypeError):
        errors.append({"sheet": sheet, "row": row, "message": f"{field}: raqam kutilgan, lekin {value!r} keldi."})
        return None


def _month(value: Any) -> str | None:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}", raw):
        year, month = re.split(r"[-/.]", raw)
        if 1 <= int(month) <= 12:
            return f"{int(year):04d}-{int(month):02d}"
    if re.fullmatch(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{4}", raw):
        a, b, year = map(int, re.split(r"[-/.]", raw))
        month = b if a > 12 else a
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    return None


def validate_records(preview: dict[str, Any]) -> dict[str, Any]:
    """Validate values and return normalized rows plus row-level errors."""
    valid, errors = [], list(preview.get("errors", []))
    for sheet in preview.get("sheets", []):
        for rec in sheet["records"]:
            row = {"sheet": sheet["name"], "kind": sheet["kind"], "source_row": rec["_row"]}
            if sheet["kind"] in ("products", "demand", "orders", "movements"):
                name = str(rec.get("product_name") or "").strip()
                if not name:
                    errors.append({"sheet": sheet["name"], "row": rec["_row"], "message": "Mahsulot/tovar nomi bo'sh."})
                    continue
                row["product_name"] = name
            if sheet["kind"] == "products":
                qty = _num(rec.get("quantity"), sheet["name"], rec["_row"], "Miqdor", errors)
                if qty is None or qty < 0:
                    if qty is not None:
                        errors.append({"sheet": sheet["name"], "row": rec["_row"], "message": "Miqdor manfiy bo'lmasligi kerak."})
                    continue
                row.update(quantity=qty, sku=str(rec.get("sku") or "").strip(), unit=str(rec.get("unit") or "dona").strip() or "dona")
                for field in ("unit_cost", "reorder_point", "annual_demand", "order_cost", "holding_cost"):
                    val = _num(rec.get(field), sheet["name"], rec["_row"], field, errors, 0.0)
                    if val is None or val < 0:
                        if val is not None:
                            errors.append({"sheet": sheet["name"], "row": rec["_row"], "message": f"{field} manfiy bo'lmasligi kerak."})
                        row = None
                        break
                    row[field] = val
                if row is not None:
                    valid.append(row)
            elif sheet["kind"] == "suppliers":
                name = str(rec.get("supplier_name") or "").strip()
                if not name:
                    errors.append({"sheet": sheet["name"], "row": rec["_row"], "message": "Yetkazib beruvchi nomi bo'sh."})
                    continue
                lead = _num(rec.get("lead_time_days"), sheet["name"], rec["_row"], "Yetkazish muddati", errors, 0.0)
                rating = _num(rec.get("rating"), sheet["name"], rec["_row"], "Reyting", errors, 3.0)
                if lead is None or rating is None or lead < 0 or not 0 <= rating <= 5:
                    errors.append({"sheet": sheet["name"], "row": rec["_row"], "message": "Yetkazish muddati >= 0, reyting 0–5 bo'lishi kerak."})
                    continue
                valid.append({**row, "supplier_name": name, "contact": str(rec.get("contact") or ""), "lead_time_days": lead, "rating": rating})
            elif sheet["kind"] == "demand":
                month = _month(rec.get("month"))
                qty = _num(rec.get("demand_quantity"), sheet["name"], rec["_row"], "Talab/sotuv", errors)
                if not month or qty is None or qty < 0:
                    errors.append({"sheet": sheet["name"], "row": rec["_row"], "message": "Oy YYYY-MM bo'lishi va talab manfiy bo'lmasligi kerak."})
                    continue
                valid.append({**row, "month": month, "quantity": qty})
            elif sheet["kind"] == "orders":
                supplier = str(rec.get("supplier_name") or "").strip()
                qty = _num(rec.get("order_quantity"), sheet["name"], rec["_row"], "Buyurtma miqdori", errors)
                price = _num(rec.get("unit_cost"), sheet["name"], rec["_row"], "Birlik narxi", errors, 0.0)
                if not supplier or qty is None or qty <= 0 or price is None or price < 0:
                    errors.append({"sheet": sheet["name"], "row": rec["_row"], "message": "Supplier nomi, musbat miqdor va manfiy bo'lmagan narx kerak."})
                    continue
                valid.append({**row, "supplier_name": supplier, "quantity": qty, "unit_cost": price,
                              "expected_date": str(rec.get("expected_date") or ""), "status": str(rec.get("status") or "draft").strip().lower()})
            elif sheet["kind"] == "movements":
                qty = _num(rec.get("quantity"), sheet["name"], rec["_row"], "Harakat miqdori", errors)
                movement = str(rec.get("movement_type") or "").strip().casefold()
                direction = "in" if movement in {"kirim", "in", "income", "kelib tushdi"} else "out" if movement in {"chiqim", "out", "sale", "sotuv"} else ""
                if qty is None or qty <= 0 or not direction:
                    errors.append({"sheet": sheet["name"], "row": rec["_row"], "message": "Harakat turi kirim/chiqim va miqdor musbat bo'lishi kerak."})
                    continue
                valid.append({**row, "quantity": qty, "direction": direction})
    return {"valid": valid, "errors": errors, "valid_count": len(valid), "error_count": len(errors)}


def apply_import(data: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    """Apply only validated records to a copy supplied by the caller."""
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    products = data.setdefault("products", {})
    suppliers = data.setdefault("suppliers", {})
    result = {"products": 0, "suppliers": 0, "demand": 0, "orders": 0, "movements": 0, "errors": validated.get("errors", [])}
    has_product_snapshot = any(row.get("kind") == "products" for row in validated.get("valid", []))

    def find_product(name: str):
        norm = _norm(name)
        return next((p for p in products.values() if _norm(p.get("name")) == norm or _norm(p.get("sku")) == norm), None)

    def find_supplier(name: str):
        norm = _norm(name)
        return next((s for s in suppliers.values() if _norm(s.get("name")) == norm), None)

    priority = {"products": 0, "suppliers": 1, "demand": 2, "orders": 3, "movements": 4}
    for row in sorted(validated.get("valid", []), key=lambda item: priority.get(item["kind"], 9)):
        kind = row["kind"]
        if kind == "products":
            existing = find_product(row["product_name"])
            sku = row["sku"] or (existing or {}).get("sku") or ("P-" + uuid.uuid4().hex[:8].upper())
            if existing:
                existing.update(quantity=row["quantity"], unit=row["unit"], updated_at=now)
                for f in ("unit_cost", "reorder_point", "annual_demand", "order_cost", "holding_cost"):
                    if row.get(f, 0) != 0:
                        existing[f] = row[f]
            else:
                if sku in products:
                    result["errors"].append({"sheet": row["sheet"], "row": row["source_row"], "message": f"SKU {sku} boshqa mahsulotda band; mavjud yozuv ustidan yozilmadi."})
                    continue
                products[sku] = {"sku": sku, "name": row["product_name"], "quantity": row["quantity"], "unit": row["unit"],
                    "unit_cost": row.get("unit_cost", 0), "reorder_point": row.get("reorder_point", 0),
                    "annual_demand": row.get("annual_demand", 0), "order_cost": row.get("order_cost", 0),
                    "holding_cost": row.get("holding_cost", 0), "created_at": now, "updated_at": now}
            result["products"] += 1
        elif kind == "suppliers":
            existing = find_supplier(row["supplier_name"])
            if existing:
                existing.update(contact=row["contact"], lead_time_days=row["lead_time_days"], rating=row["rating"], updated_at=now)
            else:
                sid = "SUP-" + uuid.uuid4().hex[:8].upper()
                suppliers[sid] = {"id": sid, "name": row["supplier_name"], "contact": row["contact"],
                    "lead_time_days": row["lead_time_days"], "rating": row["rating"], "created_at": now, "updated_at": now}
            result["suppliers"] += 1
        elif kind == "demand":
            product = find_product(row["product_name"])
            if not product:
                result["errors"].append({"sheet": row["sheet"], "row": row["source_row"], "message": f"'{row['product_name']}' mahsuloti topilmadi; avval mahsulotlar jadvalini import qiling."})
                continue
            existing = next((x for x in data.setdefault("demand_history", []) if x.get("sku") == product["sku"] and x.get("month") == row["month"]), None)
            if existing:
                existing.update(quantity=row["quantity"], created_at=now)
            else:
                data["demand_history"].append({"sku": product["sku"], "month": row["month"], "quantity": row["quantity"], "created_at": now})
            result["demand"] += 1
        elif kind == "orders":
            product, supplier = find_product(row["product_name"]), find_supplier(row["supplier_name"])
            if not product or not supplier:
                result["errors"].append({"sheet": row["sheet"], "row": row["source_row"], "message": "Buyurtma uchun mahsulot yoki supplier topilmadi; tegishli jadvallarni avval import qiling."})
                continue
            oid = "PO-" + uuid.uuid4().hex[:8].upper()
            data.setdefault("orders", []).append({"id": oid, "sku": product["sku"], "supplier_id": supplier["id"],
                "quantity": row["quantity"], "unit_price": row["unit_cost"], "expected_date": row["expected_date"],
                "status": "draft", "created_at": now})
            result["orders"] += 1
        elif kind == "movements":
            product = find_product(row["product_name"])
            if not product:
                result["errors"].append({"sheet": row["sheet"], "row": row["source_row"], "message": f"'{row['product_name']}' mahsuloti topilmadi."})
                continue
            qty = row["quantity"]
            if row["direction"] == "out" and float(product.get("quantity", 0)) < qty:
                result["errors"].append({"sheet": row["sheet"], "row": row["source_row"], "message": "Chiqim uchun omborda yetarli qoldiq yo'q."})
                continue
            if not has_product_snapshot:
                product["quantity"] = float(product.get("quantity", 0)) + (qty if row["direction"] == "in" else -qty)
                product["updated_at"] = now
            note = "Excel import (history; stock snapshot unchanged)" if has_product_snapshot else "Excel import"
            data.setdefault("movements", []).append({"id": uuid.uuid4().hex[:12], "sku": product["sku"], "type": row["direction"],
                "quantity": qty, "note": note, "created_at": now})
            result["movements"] += 1
    return result
