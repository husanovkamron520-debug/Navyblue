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

    def test_read_services_do_not_mutate_snapshot(self):
        import copy
        before = copy.deepcopy(self.snapshot)
        api.build_bootstrap(self.snapshot)
        api.build_dashboard(self.snapshot)
        api.list_inventory(self.snapshot)
        self.assertEqual(self.snapshot, before)

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


if __name__ == "__main__":
    unittest.main()
