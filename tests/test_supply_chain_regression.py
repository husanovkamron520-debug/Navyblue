"""Regression tests for the existing Supply Chain calculations and XLSX flow.

Run with: python -m unittest discover -s tests -v

These tests intentionally capture current behavior. They are not a proposal to
change formulas; update expected values only after an explicitly reviewed
business-rule change.
"""
from __future__ import annotations

import copy
import unittest

import supply_chain
import supply_chain_import


def empty_data():
    return {
        "version": 1,
        "products": {},
        "movements": [],
        "suppliers": {},
        "orders": [],
        "vehicles": [],
        "shipments": [],
        "demand_history": [],
        "scenarios": [],
    }


class SupplyChainCalculationRegressionTests(unittest.TestCase):
    def test_eoq_uses_twenty_percent_unit_cost_fallback(self):
        product = {
            "annual_demand": 1200,
            "order_cost": 150,
            "unit_cost": 100,
            "holding_cost": 0,
        }
        value = supply_chain._eoq_value(product)
        self.assertIsNotNone(value)
        quantity, assumed = value
        self.assertTrue(assumed)
        self.assertAlmostEqual(quantity, 134.16407864998737, places=8)

    def test_eoq_prefers_explicit_holding_cost(self):
        product = {
            "annual_demand": 1200,
            "order_cost": 150,
            "unit_cost": 100,
            "holding_cost": 30,
        }
        quantity, assumed = supply_chain._eoq_value(product)
        self.assertFalse(assumed)
        self.assertAlmostEqual(quantity, (12000 ** 0.5), places=8)

    def test_forecast_requires_three_months_of_history(self):
        data = empty_data()
        data["products"]["P-001"] = {"name": "Cotton yarn", "quantity": 50, "reorder_point": 10}
        data["demand_history"] = [
            {"sku": "P-001", "month": "2026-01", "quantity": 10},
            {"sku": "P-001", "month": "2026-02", "quantity": 20},
        ]
        text = supply_chain._forecast_text(data)
        self.assertIn("kamida 3 oylik tarix kerak", text.lower())
        self.assertNotIn("Keyingi oy prognozi:", text)

    def test_forecast_is_weighted_toward_newer_months(self):
        data = empty_data()
        data["products"]["P-001"] = {
            "name": "Cotton yarn", "quantity": 100, "reorder_point": 10, "unit": "kg"
        }
        data["demand_history"] = [
            {"sku": "P-001", "month": "2026-01", "quantity": 10},
            {"sku": "P-001", "month": "2026-02", "quantity": 20},
            {"sku": "P-001", "month": "2026-03", "quantity": 30},
        ]
        text = supply_chain._forecast_text(data)
        self.assertIn("Keyingi oy prognozi: **23.33 kg**", text)
        self.assertIn("Tavsiya etiladigan xarid: **0.00 kg**", text)

    def test_abc_uses_annual_demand_times_unit_cost_and_midpoint_bands(self):
        data = empty_data()
        data["products"] = {
            "A": {"name": "A item", "annual_demand": 80, "unit_cost": 10},
            "B": {"name": "B item", "annual_demand": 15, "unit_cost": 10},
            "C": {"name": "C item", "annual_demand": 5, "unit_cost": 10},
        }
        text = supply_chain._abc_text(data)
        self.assertIn("**A guruhi** — 1 ta | 80.0% qiymat", text)
        self.assertIn("**B guruhi** — 1 ta | 15.0% qiymat", text)
        self.assertIn("**C guruhi** — 1 ta | 5.0% qiymat", text)

    def test_vehicle_selection_uses_lowest_cost_then_eta(self):
        data = empty_data()
        data["vehicles"] = [
            {"id": "slow-cheap", "name": "Slow cheap", "capacity": 100, "cost_per_km": 2, "speed_kmh": 40},
            {"id": "fast-expensive", "name": "Fast expensive", "capacity": 100, "cost_per_km": 3, "speed_kmh": 90},
            {"id": "too-small", "name": "Too small", "capacity": 5, "cost_per_km": 0.1, "speed_kmh": 100},
        ]
        selected = supply_chain._best_vehicle(data, quantity=50, distance_km=100)
        self.assertEqual(selected["id"], "slow-cheap")

    def test_scenario_simulation_does_not_mutate_inventory(self):
        data = empty_data()
        data["products"]["P-001"] = {"name": "Raw cotton", "quantity": 100}
        before = copy.deepcopy(data)
        result = supply_chain._simulate_scenario(data, {
            "sku": "P-001", "target_qty": 80, "usage_per_unit": 2,
            "daily_capacity": 10, "days": 5, "demand_qty": 60,
        })
        self.assertEqual(result["material_limit"], 50)
        self.assertEqual(result["capacity_limit"], 50)
        self.assertEqual(result["feasible_qty"], 50)
        self.assertEqual(result["remaining_stock"], 0)
        self.assertEqual(data, before)

    def test_purchase_receipt_updates_stock_and_weighted_average_cost(self):
        data = empty_data()
        data["products"]["P-001"] = {
            "sku": "P-001", "name": "Cotton yarn", "quantity": 10, "unit_cost": 20
        }
        order = {
            "id": "PO-TEST", "sku": "P-001", "quantity": 10,
            "unit_price": 40, "status": "ordered",
        }
        data["orders"].append(order)
        supply_chain._receive_purchase_order(data, order)
        self.assertEqual(data["products"]["P-001"]["quantity"], 20)
        self.assertAlmostEqual(data["products"]["P-001"]["unit_cost"], 30)
        self.assertEqual(order["status"], "received")
        self.assertEqual(len(data["movements"]), 1)
        self.assertEqual(data["movements"][0]["type"], "in")
        self.assertEqual(data["movements"][0]["total_cost"], 400)

    def test_purchase_receipt_rejects_missing_existing_stock_cost(self):
        data = empty_data()
        data["products"]["P-001"] = {
            "sku": "P-001", "name": "Cotton yarn", "quantity": 10, "unit_cost": 0
        }
        order = {"id": "PO-TEST", "sku": "P-001", "quantity": 5, "unit_price": 40}
        with self.assertRaisesRegex(ValueError, "tannarxi kiritilmagan"):
            supply_chain._receive_purchase_order(data, order)
        self.assertEqual(data["products"]["P-001"]["quantity"], 10)
        self.assertEqual(data["movements"], [])

    def test_risk_assessment_flags_overdue_order_with_fixed_date(self):
        data = empty_data()
        data["suppliers"]["SUP-001"] = {
            "id": "SUP-001", "name": "Supplier A", "rating": 4, "lead_time_days": 5
        }
        data["orders"].append({
            "id": "PO-LATE", "supplier_id": "SUP-001", "sku": "P-001",
            "expected_date": "2026-11-20", "status": "ordered",
        })
        risks = supply_chain._risk_assessment(data, today="2026-11-25")
        overdue = [risk for risk in risks if risk["category"] == "Xarid"]
        self.assertEqual(len(overdue), 1)
        self.assertIn("5 kun kechikkan", overdue[0]["evidence"])
        self.assertEqual(overdue[0]["score"], 16)

    def test_generated_xlsx_can_be_inspected_without_mutating_source(self):
        data = empty_data()
        data["products"]["P-001"] = {
            "sku": "P-001", "name": "Cotton yarn", "quantity": 125,
            "unit": "kg", "reorder_point": 20, "unit_cost": 30,
            "annual_demand": 900, "order_cost": 100, "holding_cost": 5,
        }
        before = copy.deepcopy(data)
        workbook = supply_chain._xlsx_bytes(data)
        preview = supply_chain_import.inspect_workbook(workbook)
        product_sheets = [sheet for sheet in preview["sheets"] if sheet["kind"] == "products"]
        self.assertTrue(product_sheets)
        record = product_sheets[0]["records"][0]
        self.assertEqual(record["product_name"], "Cotton yarn")
        self.assertEqual(float(record["quantity"]), 125)
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
