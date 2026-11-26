"""Tests for the explicit Mini App inventory import transaction."""
import copy
import unittest

import supply_chain_mini_app_import as importer
from supply_chain_persistence import IdempotencyConflict, SerializedCommitAdapter, VersionConflict


class Store:
    def __init__(self):
        self.data = {
            "version": 1,
            "products": {
                "SKU-1": {"sku": "SKU-1", "name": "Cotton", "quantity": 5,
                          "unit": "kg", "unit_cost": 10, "reorder_point": 2}
            },
            "movements": [],
        }

    def load(self):
        return copy.deepcopy(self.data)

    def persist(self, candidate, expected, new):
        if self.data["version"] != expected:
            raise VersionConflict("stale")
        if candidate["version"] != new:
            raise AssertionError("version mismatch")
        self.data = copy.deepcopy(candidate)
        return True


def payload(rows=None, **overrides):
    value = {
        "operation_id": "excel-import-001",
        "expected_version": 1,
        "rows": rows if rows is not None else [
            {"sku": "SKU-1", "name": "Cotton Grade A", "quantity": 8,
             "unit_cost": 12, "reorder_point": 3},
            {"sku": "SKU-2", "name": "Wheat", "quantity": 15,
             "unit_cost": 4, "reorder_point": 5},
        ],
    }
    value.update(overrides)
    return value


class MiniAppImportValidationTests(unittest.TestCase):
    def test_normalizes_payload_and_creates_stable_hash(self):
        first = importer.normalize_payload(payload())
        second = importer.normalize_payload(payload())
        self.assertEqual(first, second)
        self.assertEqual(len(first[3]), 64)

    def test_rejects_duplicate_skus_case_insensitively(self):
        rows = [
            {"sku": "SKU-1", "name": "A", "quantity": 1},
            {"sku": "sku-1", "name": "B", "quantity": 2},
        ]
        with self.assertRaisesRegex(importer.ImportValidationError, "takroriy"):
            importer.normalize_payload(payload(rows))

    def test_rejects_nan_infinity_negative_and_boolean_values(self):
        for value in (float("nan"), float("inf"), -1, True, "not-a-number"):
            with self.subTest(value=value):
                rows = [{"sku": "SKU-1", "name": "A", "quantity": value}]
                with self.assertRaises(importer.ImportValidationError):
                    importer.normalize_payload(payload(rows))

    def test_rejects_empty_and_oversized_row_sets(self):
        with self.assertRaises(importer.ImportValidationError):
            importer.normalize_payload(payload([]))
        rows = [{"sku": f"S{i}", "name": "A", "quantity": 1}
                for i in range(importer.MAX_ROWS + 1)]
        with self.assertRaises(importer.ImportValidationError):
            importer.normalize_payload(payload(rows))

    def test_source_filename_is_sanitized_and_part_of_request_hash(self):
        body = payload(source_name="../../inventory.csv", source_sheet="Main")
        normalized = importer.normalize_payload(body)
        self.assertEqual(normalized[4], "inventory.csv")
        self.assertEqual(normalized[5], "Main")
        self.assertEqual(len(normalized[3]), 64)

    def test_rejects_malformed_operation_id_and_version(self):
        with self.assertRaises(importer.ImportValidationError):
            importer.normalize_payload(payload(operation_id="bad op"))
        with self.assertRaises(importer.ImportValidationError):
            importer.normalize_payload(payload(expected_version=True))


class MiniAppImportCommitTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.adapter = SerializedCommitAdapter(self.store.load, self.store.persist)

    def test_import_updates_and_creates_products_with_stock_movements(self):
        result = importer.commit_inventory_import(self.adapter, payload())
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["result"]["created"], 1)
        self.assertEqual(result["result"]["updated"], 1)
        saved = self.store.load()
        self.assertEqual(saved["products"]["SKU-1"]["quantity"], 8)
        self.assertEqual(saved["products"]["SKU-1"]["unit"], "kg")
        self.assertEqual(saved["products"]["SKU-2"]["quantity"], 15)
        self.assertEqual(len(saved["movements"]), 2)
        self.assertEqual(saved["movements"][0]["type"], "in")
        self.assertEqual(saved["movements"][1]["type"], "in")

    def test_optional_unit_is_applied_to_new_products(self):
        rows = [{"sku": "SKU-2", "name": "Wheat", "quantity": 5, "unit": "kg"}]
        importer.commit_inventory_import(self.adapter, payload(rows))
        self.assertEqual(self.store.load()["products"]["SKU-2"]["unit"], "kg")

    def test_non_string_unit_is_rejected(self):
        rows = [{"sku": "SKU-2", "name": "Wheat", "quantity": 5, "unit": 123}]
        with self.assertRaises(importer.ImportValidationError):
            importer.commit_inventory_import(self.adapter, payload(rows))

    def test_import_history_records_source_file_and_sheet(self):
        body = payload(source_name="inventory.xlsx", source_sheet="Warehouse")
        importer.commit_inventory_import(self.adapter, body)
        history = self.store.load()["import_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["file_name"], "inventory.xlsx")
        self.assertEqual(history[0]["sheet"], "Warehouse")
        self.assertEqual(history[0]["processed"], 2)

    def test_fully_unchanged_product_is_not_counted_as_updated(self):
        rows = [{"sku": "SKU-1", "name": "Cotton", "quantity": 5,
                 "unit": "kg", "unit_cost": 10, "reorder_point": 2}]
        result = importer.commit_inventory_import(self.adapter, payload(rows))
        self.assertEqual(result["result"]["updated"], 0)
        self.assertEqual(result["result"]["unchanged"], 1)
        self.assertEqual(result["result"]["unchanged_quantity"], 1)
        self.assertEqual(self.store.load()["movements"], [])

    def test_metadata_only_change_is_counted_as_update_without_stock_movement(self):
        rows = [{"sku": "SKU-1", "name": "Cotton Grade B", "quantity": 5,
                 "unit": "kg", "unit_cost": 10, "reorder_point": 2}]
        result = importer.commit_inventory_import(self.adapter, payload(rows))
        self.assertEqual(result["result"]["updated"], 1)
        self.assertEqual(result["result"]["unchanged"], 0)
        self.assertEqual(self.store.load()["movements"], [])

    def test_optional_fields_are_preserved_when_not_in_file(self):
        rows = [{"sku": "SKU-1", "name": "Cotton", "quantity": 5}]
        importer.commit_inventory_import(self.adapter, payload(rows))
        product = self.store.load()["products"]["SKU-1"]
        self.assertEqual(product["unit_cost"], 10)
        self.assertEqual(product["reorder_point"], 2)
        self.assertEqual(product["unit"], "kg")

    def test_unknown_existing_quantity_is_recorded_as_opening_balance(self):
        self.store.data["products"]["SKU-1"]["quantity"] = None
        rows = [{"sku": "SKU-1", "name": "Cotton", "quantity": 4}]
        importer.commit_inventory_import(self.adapter, payload(rows))
        movement = self.store.load()["movements"][0]
        self.assertEqual(movement["type"], "in")
        self.assertEqual(movement["quantity"], 4)
        self.assertIn("unknown", movement["note"])

    def test_stock_decrease_creates_outbound_adjustment(self):
        rows = [{"sku": "SKU-1", "name": "Cotton", "quantity": 2}]
        importer.commit_inventory_import(self.adapter, payload(rows))
        movement = self.store.load()["movements"][0]
        self.assertEqual(movement["type"], "out")
        self.assertEqual(movement["quantity"], 3)

    def test_same_operation_replay_does_not_duplicate_movements(self):
        body = payload()
        first = importer.commit_inventory_import(self.adapter, body)
        second = importer.commit_inventory_import(self.adapter, body)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(self.store.load()["version"], 2)
        self.assertEqual(len(self.store.load()["movements"]), 2)

    def test_ambiguous_existing_casefold_duplicate_skus_are_rejected(self):
        self.store.data["products"]["sku-1"] = {
            "sku": "sku-1", "name": "Duplicate legacy key", "quantity": 1
        }
        before = self.store.load()
        rows = [{"sku": "SKU-1", "name": "Cotton", "quantity": 8}]
        with self.assertRaisesRegex(importer.ImportValidationError, "takroriy"):
            importer.commit_inventory_import(self.adapter, payload(rows))
        self.assertEqual(self.store.load(), before)

    def test_stale_preview_version_is_rejected(self):
        importer.commit_inventory_import(self.adapter, payload())
        with self.assertRaises(VersionConflict):
            importer.commit_inventory_import(self.adapter, payload(
                operation_id="excel-import-002", expected_version=1
            ))
        self.assertEqual(self.store.load()["version"], 2)

    def test_invalid_later_row_prevents_any_commit(self):
        before = self.store.load()
        rows = [
            {"sku": "SKU-2", "name": "Wheat", "quantity": 10},
            {"sku": "SKU-3", "name": "Rice", "quantity": -4},
        ]
        with self.assertRaises(importer.ImportValidationError):
            importer.commit_inventory_import(self.adapter, payload(rows))
        self.assertEqual(self.store.load(), before)

    def test_hash_mismatch_for_reused_operation_id_is_rejected(self):
        importer.commit_inventory_import(self.adapter, payload())
        changed = payload(rows=[{"sku": "SKU-1", "name": "Cotton", "quantity": 999}],
                          expected_version=1)
        with self.assertRaises(IdempotencyConflict):
            importer.commit_inventory_import(self.adapter, changed)
        self.assertEqual(self.store.load()["products"]["SKU-1"]["quantity"], 8)


if __name__ == "__main__":
    unittest.main()
