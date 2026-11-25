import io
import unittest
import zipfile

import supply_chain_import


def _col(n):
    out = ""
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def make_xlsx(rows, sheet_name="Sheet1"):
    cells = []
    for row_no, values in enumerate(rows, 1):
        row_cells = []
        for col_no, value in enumerate(values):
            ref = f"{_col(col_no)}{row_no}"
            text = str(value)
            row_cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
            )
        cells.append(f'<row r="{row_no}">{"".join(row_cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(cells)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return out.getvalue()


class SupplyChainImportTests(unittest.TestCase):
    def test_tovar_and_soni_headers_are_recognized(self):
        raw = make_xlsx([["Tovar", "Soni", "Birlik", "Narxi"], ["Paxta ipi", "120", "kg", "28000"]])
        preview = supply_chain_import.inspect_workbook(raw)
        self.assertEqual(preview["sheets"][0]["kind"], "products")
        self.assertEqual(preview["sheets"][0]["columns"]["A"], "product_name")
        self.assertEqual(preview["sheets"][0]["columns"]["B"], "quantity")
        validated = supply_chain_import.validate_records(preview)
        self.assertEqual(validated["valid_count"], 1)
        data = {"products": {}, "suppliers": {}, "demand_history": [], "orders": [], "movements": []}
        result = supply_chain_import.apply_import(data, validated)
        self.assertEqual(result["products"], 1)
        self.assertEqual(next(iter(data["products"].values()))["quantity"], 120.0)

    def test_unknown_nonempty_column_requires_mapping_or_ignore(self):
        raw = make_xlsx([["Tovar", "Soni", "Ombor guruhi"], ["Paxta", "12", "A-1"]])
        preview = supply_chain_import.inspect_workbook(raw)
        self.assertEqual(preview["questions"][0]["column"], "C")
        mapped = supply_chain_import.inspect_workbook(raw, {"C": "ignore"})
        self.assertEqual(mapped["questions"], [])
        self.assertEqual(len(mapped["sheets"][0]["records"]), 1)

    def test_fully_unrecognized_headers_are_asked_not_silently_skipped(self):
        raw = make_xlsx([["Nomenklatura", "Count"], ["Paxta", "15"]])
        preview = supply_chain_import.inspect_workbook(raw)
        self.assertEqual({q["column"] for q in preview["questions"]}, {"A", "B"})
        mapped = supply_chain_import.inspect_workbook(raw, {"A": "product_name", "B": "quantity"})
        self.assertEqual(mapped["questions"], [])
        self.assertEqual(mapped["sheets"][0]["kind"], "products")
    def test_bad_quantity_is_reported_with_exact_row(self):
        raw = make_xlsx([["Mahsulot", "Miqdor"], ["Paxta", "ikki yuz"]])
        preview = supply_chain_import.inspect_workbook(raw)
        validated = supply_chain_import.validate_records(preview)
        self.assertEqual(validated["valid_count"], 0)
        self.assertTrue(any(e["row"] == 2 and "raqam" in e["message"].lower() for e in validated["errors"]))

    def test_order_sheet_can_use_generic_quantity_column(self):
        raw = make_xlsx([["Tovar", "Yetkazuvchi", "Miqdor", "Narx"],
                         ["Paxta", "Atlas", "50", "18000"]], "Buyurtmalar")
        preview = supply_chain_import.inspect_workbook(raw)
        self.assertEqual(preview["sheets"][0]["kind"], "orders")
        validated = supply_chain_import.validate_records(preview)
        self.assertEqual(validated["valid_count"], 1)
        self.assertEqual(validated["valid"][0]["quantity"], 50.0)


if __name__ == "__main__":
    unittest.main()
