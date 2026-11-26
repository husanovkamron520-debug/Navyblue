"""Security and read-only contract tests for Supply Chain Mini App primitives."""
from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

import supply_chain_api as api


BOT_TOKEN = "123456:TEST_TOKEN"
OWNER_ID = 123456789


def signed_init_data(user_id=OWNER_ID, auth_date=1_800_000_000):
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAExample",
        "user": json.dumps({"id": user_id, "first_name": "Owner"}, separators=(",", ":")),
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class TelegramInitDataTests(unittest.TestCase):
    def test_valid_owner_init_data_is_accepted(self):
        user = api.validate_init_data(signed_init_data(), BOT_TOKEN, OWNER_ID, now=1_800_000_100)
        self.assertEqual(user["id"], OWNER_ID)

    def test_tampered_init_data_is_rejected(self):
        raw = signed_init_data().replace("Owner", "Attacker")
        with self.assertRaises(api.AuthError):
            api.validate_init_data(raw, BOT_TOKEN, OWNER_ID, now=1_800_000_100)

    def test_expired_init_data_is_rejected(self):
        with self.assertRaisesRegex(api.AuthError, "expired"):
            api.validate_init_data(signed_init_data(auth_date=1_800_000_000),
                                   BOT_TOKEN, OWNER_ID, now=1_800_000_601)

    def test_non_owner_is_rejected(self):
        with self.assertRaisesRegex(api.AuthError, "not authorized"):
            api.validate_init_data(signed_init_data(user_id=7), BOT_TOKEN, OWNER_ID,
                                   now=1_800_000_100)

    def test_duplicate_fields_are_rejected(self):
        with self.assertRaises(api.AuthError):
            api.validate_init_data(signed_init_data() + "&auth_date=1800000000",
                                   BOT_TOKEN, OWNER_ID, now=1_800_000_100)

    def test_init_data_with_excessive_field_count_is_rejected(self):
        raw = signed_init_data() + "".join(f"&extra{i}=x" for i in range(30))
        with self.assertRaises(api.AuthError):
            api.validate_init_data(raw, BOT_TOKEN, OWNER_ID, now=1_800_000_100)


class ReadOnlyApiServiceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "version": 1,
            "products": {
                "SKU-1": {"name": "Cotton", "quantity": 5, "reorder_point": 10,
                          "unit_cost": 20, "unit": "kg", "secret": "must-not-leak"},
                "SKU-2": {"name": "Wheat", "quantity": 50, "reorder_point": 10,
                          "unit_cost": 4, "unit": "kg"},
            },
            "orders": [{"status": "ordered"}, {"status": "received"}],
            "shipments": [{"status": "dispatched"}],
            "suppliers": {"S-1": {"name": "Supplier", "contact": "private"}},
        }

    def test_dashboard_kpis_are_derived_from_snapshot(self):
        result = api.build_dashboard(self.snapshot)["data"]["kpis"]
        self.assertEqual(result["product_count"], 2)
        self.assertEqual(result["total_units"], 55)
        self.assertEqual(result["inventory_value"], 300)
        self.assertEqual(result["low_stock_count"], 1)
        self.assertEqual(result["open_order_count"], 1)
        self.assertEqual(result["active_shipment_count"], 1)

    def test_inventory_search_filter_pagination_and_allowlist(self):
        result = api.list_inventory(self.snapshot, search="cot", status="low",
                                    page=1, page_size=10)["data"]
        self.assertEqual(result["pagination"]["total"], 1)
        self.assertEqual(result["items"][0]["sku"], "SKU-1")
        self.assertNotIn("secret", result["items"][0])
        self.snapshot["products"]["SKU-2"]["quantity"] = 100
        high = api.list_inventory(self.snapshot, status="high")["data"]
        self.assertEqual(high["items"][0]["stock_level"], "high")
        self.assertEqual(high["items"][0]["reorder_multiple"], 10.0)
        self.assertEqual(api.list_inventory(self.snapshot, status="healthy")["data"]["pagination"]["total"], 0)

    def test_read_services_do_not_mutate_snapshot(self):
        import copy
        before = copy.deepcopy(self.snapshot)
        api.build_bootstrap(self.snapshot)
        api.build_dashboard(self.snapshot)
        api.list_inventory(self.snapshot)
        self.assertEqual(self.snapshot, before)

    def test_bootstrap_returns_only_last_ten_allowlisted_import_records(self):
        self.snapshot["import_history"] = [
            {"file_name": f"file-{i}.xlsx", "sheet": "Sheet1", "created_at": "2026-11-26",
             "processed": i, "created": 1, "updated": 2, "unchanged": 4, "unchanged_quantity": 3,
             "private": "must-not-leak"}
            for i in range(12)
        ]
        recent = api.build_bootstrap(self.snapshot)["data"]["recent_imports"]
        self.assertEqual(len(recent), 10)
        self.assertEqual(recent[0]["file_name"], "file-2.xlsx")
        self.assertEqual(recent[0]["unchanged"], 4)
        self.assertNotIn("private", recent[0])

    def test_session_expires_and_is_revocable(self):
        sessions = api.SessionStore(ttl_seconds=20)
        token, ttl = sessions.issue(OWNER_ID, now=100)
        self.assertEqual(ttl, 20)
        self.assertTrue(sessions.authenticate(token, OWNER_ID, now=119))
        self.assertFalse(sessions.authenticate(token, OWNER_ID, now=120))
        token, _ = sessions.issue(OWNER_ID, now=200)
        sessions.revoke_all()
        self.assertFalse(sessions.authenticate(token, OWNER_ID, now=201))

    def test_session_rate_limiter_blocks_after_window_limit(self):
        limiter = api.RateLimiter(max_requests=2, window_seconds=10)
        self.assertTrue(limiter.allow("session", now=100))
        self.assertTrue(limiter.allow("session", now=101))
        self.assertFalse(limiter.allow("session", now=102))
        self.assertTrue(limiter.allow("session", now=111))

    def test_rate_limiter_buckets_are_independent(self):
        limiter = api.RateLimiter(max_requests=1, window_seconds=10)
        self.assertTrue(limiter.allow("one", now=100))
        self.assertFalse(limiter.allow("one", now=101))
        self.assertTrue(limiter.allow("two", now=101))

    def test_rate_limiter_bounds_unique_client_buckets_and_prunes_expired(self):
        limiter = api.RateLimiter(max_requests=1, window_seconds=10, max_buckets=1)
        self.assertTrue(limiter.allow("client-a", now=100))
        self.assertFalse(limiter.allow("client-b", now=101))
        self.assertTrue(limiter.allow("client-b", now=111))
        self.assertEqual(len(limiter._events), 1)

    def test_malformed_nested_records_and_history_arrays_do_not_crash_views(self):
        snapshot = {
            "version": "not-a-version",
            "products": {"SKU-1": {"name": "Valid"}, "BROKEN": "not-an-object"},
            "orders": [{"sku": "BROKEN", "supplier_id": "BAD", "status": "ordered"}],
            "suppliers": {"BAD": ["not", "an", "object"]},
            "shipments": [{"sku": "BROKEN", "vehicle_id": "BAD", "status": "planned"}],
            "vehicles": [{"id": "BAD", "name": "Bad vehicle"}],
            "movements": "not-a-list",
            "demand_history": {"not": "a-list"},
        }
        dashboard = api.build_dashboard(snapshot)["data"]["kpis"]
        self.assertEqual(dashboard["product_count"], 1)
        self.assertEqual(api.list_purchase_orders(snapshot)["data"]["items"][0]["supplier_name"], "")
        self.assertEqual(api.list_shipments(snapshot)["data"]["items"][0]["product_name"], "BROKEN")
        detail = api.get_inventory_detail(snapshot, "SKU-1")["data"]
        self.assertEqual(detail["recent_movements"], [])
        self.assertEqual(detail["demand_history"], [])
        self.assertEqual(api.build_dashboard(snapshot)["meta"]["data_version"], 1)

    def test_demand_analytics_weighted_forecast_and_minimum_history(self):
        self.snapshot["demand_history"] = [
            {"sku": "SKU-1", "month": "2026-01", "quantity": 10},
            {"sku": "SKU-1", "month": "2026-02", "quantity": 20},
            {"sku": "SKU-1", "month": "2026-03", "quantity": 30},
            {"sku": "SKU-2", "month": "2026-03", "quantity": 12},
        ]
        result = api.build_demand_analytics(self.snapshot)["data"]["items"]
        first = next(x for x in result if x["sku"] == "SKU-1")
        second = next(x for x in result if x["sku"] == "SKU-2")
        self.assertEqual(first["forecast_next_month"], 23.3333)
        self.assertEqual(first["forecast_status"], "available")
        self.assertEqual(second["forecast_status"], "insufficient_history")
        self.assertIsNone(second["forecast_next_month"])

    def test_abc_uses_annual_demand_times_unit_cost_midpoint_bands(self):
        self.snapshot["products"] = {
            "A": {"name": "A", "annual_demand": 80, "unit_cost": 10},
            "B": {"name": "B", "annual_demand": 15, "unit_cost": 10},
            "C": {"name": "C", "annual_demand": 5, "unit_cost": 10},
        }
        result = api.build_abc_analysis(self.snapshot)["data"]
        self.assertEqual([x["category"] for x in result["items"]], ["A", "B", "C"])
        self.assertEqual(result["groups"]["A"]["share_percent"], 80.0)

    def test_eoq_preserves_twenty_percent_holding_cost_fallback(self):
        self.snapshot["products"] = {
            "A": {"name": "A", "annual_demand": 100, "order_cost": 25, "unit_cost": 10},
        }
        result = api.build_eoq_analysis(self.snapshot)["data"]["items"][0]
        self.assertEqual(result["holding_cost_used"], 2.0)
        self.assertTrue(result["holding_cost_assumed"])
        self.assertAlmostEqual(result["eoq"], (2500) ** 0.5)

    def test_replenishment_subtracts_open_order_quantity(self):
        self.snapshot["demand_history"] = [
            {"sku": "SKU-1", "month": "2026-01", "quantity": 10},
            {"sku": "SKU-1", "month": "2026-02", "quantity": 20},
            {"sku": "SKU-1", "month": "2026-03", "quantity": 30},
        ]
        self.snapshot["orders"] = [
            {"sku": "SKU-1", "quantity": 3, "status": "draft"},
            {"sku": "SKU-1", "quantity": 5, "status": "ordered"},
            {"sku": "SKU-1", "quantity": 90, "status": "received"},
            {"sku": "SKU-1", "quantity": 90, "status": "cancelled"},
        ]
        result = api.build_replenishment(self.snapshot)["data"]["items"]
        first = next(x for x in result if x["sku"] == "SKU-1")
        self.assertEqual(first["draft_order_quantity"], 3)
        self.assertEqual(first["ordered_quantity"], 5)
        self.assertEqual(first["inbound_quantity"], 5)
        self.assertEqual(first["open_order_quantity"], 8)
        self.assertEqual(first["suggested_order_quantity"], 20.33)

    def test_replenishment_exposes_stock_cover_capital_and_indicative_surplus(self):
        self.snapshot["products"]["SKU-2"].update({"quantity": 1000, "unit_cost": 12})
        self.snapshot["demand_history"] = [
            {"sku": "SKU-2", "month": "2026-01", "quantity": 10},
            {"sku": "SKU-2", "month": "2026-02", "quantity": 10},
            {"sku": "SKU-2", "month": "2026-03", "quantity": 10},
        ]
        self.snapshot["orders"] = [
            {"sku": "SKU-2", "quantity": 5, "status": "ordered"},
            {"sku": "SKU-2", "quantity": 7, "status": "draft"},
            {"sku": "SKU-2", "quantity": 50, "status": "received"},
        ]
        item = next(x for x in api.build_replenishment(self.snapshot)["data"]["items"]
                    if x["sku"] == "SKU-2")
        self.assertEqual(item["inventory_value"], 12000)
        self.assertEqual(item["days_of_stock_cover"], 3000)
        self.assertEqual(item["supply_including_confirmed_inbound"], 1005)
        self.assertEqual(item["demand_over_review_horizon"], 30)
        self.assertEqual(item["indicative_surplus_quantity"], 975)
        self.assertEqual(item["indicative_surplus_value"], 11700)
        self.assertEqual(item["surplus_review_status"], "review")
        self.assertEqual(item["draft_order_quantity"], 7)
        self.assertEqual(item["ordered_quantity"], 5)

    def test_replenishment_does_not_guess_surplus_without_demand_history_or_cost(self):
        self.snapshot["products"]["SKU-1"]["unit_cost"] = None
        item = next(x for x in api.build_replenishment(self.snapshot)["data"]["items"]
                    if x["sku"] == "SKU-1")
        self.assertIsNone(item["days_of_stock_cover"])
        self.assertIsNone(item["inventory_value"])
        self.assertIsNone(item["indicative_surplus_quantity"])
        self.assertIsNone(item["indicative_surplus_value"])
        self.assertEqual(item["surplus_review_status"], "insufficient_data")

    def test_inventory_detail_is_read_only_and_scoped_to_sku(self):
        self.snapshot["movements"] = [
            {"sku": "SKU-1", "type": "in", "quantity": 5, "created_at": "2026-01-01"},
            {"sku": "SKU-2", "type": "out", "quantity": 9, "created_at": "2026-01-02"},
        ]
        import copy
        before = copy.deepcopy(self.snapshot)
        result = api.get_inventory_detail(self.snapshot, "SKU-1")["data"]
        self.assertEqual(len(result["recent_movements"]), 1)
        self.assertEqual(result["recent_movements"][0]["type"], "in")
        self.assertNotIn("secret", result["recent_movements"][0])
        self.assertEqual(self.snapshot, before)

    def test_procurement_lists_do_not_expose_supplier_contact(self):
        self.snapshot["orders"] = [{"id": "PO-1", "sku": "SKU-1", "supplier_id": "S-1",
                                    "quantity": 10, "unit_price": 2, "status": "ordered",
                                    "expected_date": "2026-12-01", "created_at": "2026-11-20"}]
        orders = api.list_purchase_orders(self.snapshot)["data"]["items"]
        suppliers = api.list_suppliers(self.snapshot)["data"]["items"]
        self.assertEqual(orders[0]["supplier_name"], "Supplier")
        self.assertNotIn("contact", suppliers[0])
        self.assertNotIn("private", str(suppliers))

    def test_logistics_lists_return_allowlisted_shipments_and_vehicles(self):
        self.snapshot["vehicles"] = [{"id": "TR-1", "name": "Truck", "capacity": 100,
                                      "cost_per_km": 5, "speed_kmh": 60, "secret": "x"}]
        self.snapshot["shipments"] = [{"id": "SH-1", "sku": "SKU-1", "quantity": 4,
                                       "destination": "Samarkand", "distance_km": 20,
                                       "vehicle_id": "TR-1", "estimated_hours": 1,
                                       "estimated_cost": 100, "status": "planned"}]
        shipment = api.list_shipments(self.snapshot)["data"]["items"][0]
        vehicle = api.list_vehicles(self.snapshot)["data"]["items"][0]
        self.assertEqual(shipment["vehicle_name"], "Truck")
        self.assertNotIn("secret", vehicle)


if __name__ == "__main__":
    unittest.main()
