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


def make_multi_xlsx(sheet_rows):
    out = io.BytesIO()
    workbook_sheets = []
    relationships = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, (sheet_name, rows) in enumerate(sheet_rows.items(), 1):
            cells = []
            for row_no, values in enumerate(rows, 1):
                row_cells = []
                for col_no, value in enumerate(values):
                    ref = f"{_col(col_no)}{row_no}"
                    row_cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
                cells.append(f'<row r="{row_no}">{"".join(row_cells)}</row>')
            sheet_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(cells)}</sheetData></worksheet>'
            )
            zf.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml)
            workbook_sheets.append(f'<sheet name="{sheet_name}" sheetId="{index}" r:id="rId{index}"/>')
            relationships.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
            )
        workbook = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(workbook_sheets)}</sheets></workbook>'
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(relationships)}</Relationships>'
        )
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
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
        raw = make_xlsx([["Xomashyo tavsifi", "Count"], ["Paxta", "15"]])
        preview = supply_chain_import.inspect_workbook(raw)
        self.assertEqual({q["column"] for q in preview["questions"]}, {"A", "B"})
        mapped = supply_chain_import.inspect_workbook(raw, {"A": "product_name", "B": "quantity"})
        self.assertEqual(mapped["questions"], [])
        self.assertEqual(mapped["sheets"][0]["kind"], "products")
    def test_sheet_specific_column_mapping_does_not_leak_between_sheets(self):
        raw = make_multi_xlsx({
            "OrderList": [["Product ID", "Unit quantity"], ["1700106", "808"]],
            "WhCapacities": [["Plant ID", "Daily Capacity"], ["PLANT01", "1070"]],
        })
        preview = supply_chain_import.inspect_workbook(raw, {
            "OrderList": {"A": "product_name", "B": "quantity"},
            "WhCapacities": {"A": "ignore", "B": "ignore"},
        })
        self.assertEqual(preview["questions"], [])
        order_sheet = next(x for x in preview["sheets"] if x["name"] == "OrderList")
        self.assertEqual(order_sheet["kind"], "products")
        self.assertEqual(order_sheet["records"][0]["product_name"], "1700106")
        self.assertTrue(any(e["sheet"] == "WhCapacities" for e in preview["errors"]))

    def test_logistics_dataset_headers_are_not_guessed_as_inventory_fields(self):
        raw = make_multi_xlsx({
            "OrderList": [["Order ID", "Order Date", "Carrier", "Product ID", "Unit quantity", "Weight"],
                          ["1447296446.7", "2013-05-26", "V44_3", "1700106", "808", "14.3"]],
            "FreightRates": [["Carrier", "orig_port_cd", "dest_port_cd", "minimum cost", "rate", "tpt_day_cnt"],
                             ["V444_6", "PORT08", "PORT09", "43.22", "0.71", "2"]],
        })
        preview = supply_chain_import.inspect_workbook(raw)
        self.assertTrue(preview["questions"])
        self.assertEqual(preview["sheets"], [])
        self.assertFalse(any(q["header"] in {"Product ID", "Unit quantity"} and q["sheet"] == "OrderList"
                             for q in preview["questions"]) is False)

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


    def test_uzbek_cyrillic_letters_are_preserved_in_normalization(self):
        self.assertNotEqual(supply_chain_import._norm("Ғалла"), supply_chain_import._norm("Алла"))
        self.assertNotEqual(supply_chain_import._norm("Қанд"), supply_chain_import._norm("Канд"))
        self.assertNotEqual(supply_chain_import._norm("Ҳисоб"), supply_chain_import._norm("Исоб"))

    def test_product_sku_never_matches_another_products_name(self):
        data = {"products": {
            "SKU-1": {"sku": "SKU-1", "name": "Existing product", "quantity": 10}
        }, "suppliers": {}}
        validated = {"valid": [{
            "kind": "products", "product_name": "SKU-1", "sku": "SKU-2",
            "quantity": 25, "unit": "kg", "unit_cost": None,
            "reorder_point": None, "annual_demand": None,
            "order_cost": None, "holding_cost": None,
            "sheet": "Products", "source_row": 2,
        }], "errors": []}
        result = supply_chain_import.apply_import(data, validated)
        self.assertEqual(result["products"], 1)
        self.assertEqual(data["products"]["SKU-1"]["quantity"], 10)
        self.assertEqual(data["products"]["SKU-2"]["quantity"], 25)

    def test_cyrillic_product_names_do_not_merge(self):
        data = {"products": {
            "SKU-1": {"sku": "SKU-1", "name": "Алла", "quantity": 10}
        }, "suppliers": {}}
        validated = {"valid": [{
            "kind": "products", "product_name": "Ғалла", "sku": "",
            "quantity": 25, "unit": "kg", "unit_cost": None,
            "reorder_point": None, "annual_demand": None,
            "order_cost": None, "holding_cost": None,
            "sheet": "Products", "source_row": 2,
        }], "errors": []}
        supply_chain_import.apply_import(data, validated)
        self.assertEqual(data["products"]["SKU-1"]["quantity"], 10)
        self.assertEqual(len(data["products"]), 2)

    def test_explicit_zero_cost_and_reorder_values_overwrite_existing_values(self):
        data = {"products": {
            "SKU-1": {"sku": "SKU-1", "name": "Sugar", "quantity": 10,
                      "unit_cost": 500, "reorder_point": 25}
        }, "suppliers": {}}
        validated = {"valid": [{
            "kind": "products", "product_name": "Sugar", "sku": "SKU-1",
            "quantity": 12, "unit": "kg", "unit_cost": 0,
            "reorder_point": 0, "annual_demand": None,
            "order_cost": None, "holding_cost": None,
            "sheet": "Products", "source_row": 2,
        }], "errors": []}
        supply_chain_import.apply_import(data, validated)
        self.assertEqual(data["products"]["SKU-1"]["unit_cost"], 0)
        self.assertEqual(data["products"]["SKU-1"]["reorder_point"], 0)

    def test_xlsx_cell_reference_has_bounded_row_and_column(self):
        self.assertEqual(supply_chain_import._column_index("A1"), 0)
        self.assertEqual(supply_chain_import._column_index("CV1"), 99)
        with self.assertRaises(ValueError):
            supply_chain_import._column_index("CW1")
        with self.assertRaises(ValueError):
            supply_chain_import._column_index("ZZZZZZZ1")
        with self.assertRaises(ValueError):
            supply_chain_import._column_index("A99999999")

    def test_xlsx_uncompressed_size_is_bounded(self):
        from unittest.mock import patch
        raw = make_xlsx([["Tovar"], ["X" * 2000]])
        with patch.object(supply_chain_import, "MAX_XLSX_UNCOMPRESSED", 1024):
            with self.assertRaisesRegex(ValueError, "64 MB"):
                supply_chain_import.read_workbook(raw)


if __name__ == "__main__":
    unittest.main()
