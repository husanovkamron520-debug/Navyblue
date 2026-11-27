import unittest
import hashlib
import hmac
import json
from urllib.parse import quote

import supply_chain_api as api


COMPANY_A = "11111111-1111-4111-8111-111111111111"
COMPANY_B = "22222222-2222-4222-8222-222222222222"


class TelegramInitDataTenantAuthTests(unittest.TestCase):
    def _signed_init_data(self, user_id, auth_date=1000):
        bot_token = "test-bot-token"
        values = {
            "auth_date": str(auth_date),
            "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
        }
        check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        signature = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return "&".join(f"{key}={quote(value)}" for key, value in values.items()) + "&hash=" + signature, bot_token

    def test_valid_telegram_user_can_authenticate_for_tenant_onboarding(self):
        init_data, token = self._signed_init_data(987654321)
        user = api.validate_init_data(init_data, token, now=1000)
        self.assertEqual(user["id"], 987654321)

    def test_legacy_owner_validation_still_restricts_owner(self):
        init_data, token = self._signed_init_data(987654321)
        with self.assertRaises(api.AuthError):
            api.validate_init_data(init_data, token, owner_id=123456789, now=1000)

    def test_invalid_signature_is_rejected_for_tenant_onboarding(self):
        init_data, token = self._signed_init_data(987654321)
        init_data = init_data.replace("hash=", "hash=0", 1)
        with self.assertRaises(api.AuthError):
            api.validate_init_data(init_data, token, now=1000)


class TenantSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.sessions = api.TenantSessionStore(ttl_seconds=120)

    def test_session_is_bound_to_one_user_company_and_role(self):
        token, ttl = self.sessions.issue(101, COMPANY_A, "warehouse", now=1000)
        self.assertEqual(ttl, 120)
        self.assertEqual(
            self.sessions.authenticate(token, now=1001),
            {"user_id": 101, "company_id": COMPANY_A, "role": "warehouse"},
        )

    def test_company_context_cannot_be_overridden_by_request_data(self):
        token, _ = self.sessions.issue(101, COMPANY_A, "viewer", now=1000)
        context = self.sessions.authenticate(token, now=1001)
        self.assertEqual(context["company_id"], COMPANY_A)
        self.assertNotEqual(context["company_id"], COMPANY_B)

    def test_permissions_follow_server_stored_role(self):
        token, _ = self.sessions.issue(101, COMPANY_A, "warehouse", now=1000)
        context = self.sessions.authenticate(token, now=1001)
        self.assertTrue(self.sessions.allows(context, "inventory.read"))
        self.assertTrue(self.sessions.allows(context, "inventory.write"))
        self.assertFalse(self.sessions.allows(context, "procurement.write"))

    def test_expired_session_is_rejected(self):
        token, _ = self.sessions.issue(101, COMPANY_A, "viewer", now=1000)
        self.assertIsNone(self.sessions.authenticate(token, now=1120))

    def test_revocation_can_target_one_company(self):
        token_a, _ = self.sessions.issue(101, COMPANY_A, "viewer", now=1000)
        token_b, _ = self.sessions.issue(101, COMPANY_B, "viewer", now=1000)
        self.assertEqual(self.sessions.revoke_user(101, COMPANY_A), 1)
        self.assertIsNone(self.sessions.authenticate(token_a, now=1001))
        self.assertEqual(self.sessions.authenticate(token_b, now=1001)["company_id"], COMPANY_B)

    def test_invalid_role_and_company_are_rejected(self):
        with self.assertRaises(api.AuthError):
            self.sessions.issue(101, COMPANY_A, "superadmin", now=1000)
        with self.assertRaises(api.AuthError):
            self.sessions.issue(101, "not-a-uuid", "viewer", now=1000)


class FakeTenantDB:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return self.response


class TenantStoreTests(unittest.TestCase):
    def test_create_company_uses_safe_unique_slug_and_authenticated_owner_id(self):
        import re
        import supply_chain_tenants as tenants

        company_id = "33333333-3333-4333-8333-333333333333"
        db = FakeTenantDB({"id": company_id, "name": "Samarqand Logistika"})
        store = tenants.TenantStore(db)
        created = store.create_company("Samarqand Logistika", 987654321)

        self.assertEqual(created["id"], company_id)
        method, path, payload = db.calls[0]
        self.assertEqual((method, path), ("POST", "rpc/sc_create_company"))
        self.assertEqual(payload["p_owner_telegram_id"], 987654321)
        self.assertRegex(payload["p_slug"], re.compile(r"^[a-z0-9-]{2,63}$"))

    def test_non_latin_company_name_gets_safe_slug(self):
        import re
        import supply_chain_tenants as tenants

        db = FakeTenantDB({"id": "33333333-3333-4333-8333-333333333333"})
        tenants.TenantStore(db).create_company("Самарқанд корхонаси", 987654321)
        slug = db.calls[0][2]["p_slug"]
        self.assertRegex(slug, re.compile(r"^[a-z0-9-]{2,63}$"))

    def test_invite_persists_only_sha256_hash_and_returns_raw_code_once(self):
        import supply_chain_tenants as tenants

        invite_id = "44444444-4444-4444-8444-444444444444"
        db = FakeTenantDB(invite_id)
        invite = tenants.TenantStore(db).create_invite(
            "33333333-3333-4333-8333-333333333333",
            987654321,
            "warehouse",
        )
        payload = db.calls[0][2]
        self.assertEqual(payload["p_code_hash"], hashlib.sha256(invite["code"].encode()).hexdigest())
        self.assertNotEqual(payload["p_code_hash"], invite["code"])
        self.assertEqual(len(payload["p_code_hash"]), 64)
        self.assertEqual(invite["invite_id"], invite_id)
        self.assertEqual(invite["role"], "warehouse")

    def test_owner_role_cannot_be_granted_by_invite_helper(self):
        import supply_chain_tenants as tenants

        db = FakeTenantDB("unused")
        with self.assertRaises(ValueError):
            tenants.TenantStore(db).create_invite(
                "33333333-3333-4333-8333-333333333333",
                987654321,
                "owner",
            )
        self.assertEqual(db.calls, [])

    def test_membership_permission_is_checked_server_side(self):
        import supply_chain_tenants as tenants

        row = {
            "company_id": COMPANY_A,
            "telegram_user_id": 101,
            "role": "warehouse",
            "status": "active",
        }
        db = FakeTenantDB([row])
        store = tenants.TenantStore(db)
        member = store.require_permission(COMPANY_A, 101, "inventory.write")
        self.assertEqual(member["role"], "warehouse")
        self.assertEqual(db.calls[0][0], "GET")
        self.assertIn("company_id=eq." + COMPANY_A, db.calls[0][1])

    def test_membership_absence_denies_access(self):
        import supply_chain_tenants as tenants

        db = FakeTenantDB([])
        with self.assertRaises(tenants.MembershipRequired):
            tenants.TenantStore(db).require_permission(COMPANY_A, 101, "inventory.read")

    def test_warehouse_cannot_write_procurement(self):
        import supply_chain_tenants as tenants

        db = FakeTenantDB([{
            "company_id": COMPANY_A,
            "telegram_user_id": 101,
            "role": "warehouse",
            "status": "active",
        }])
        with self.assertRaises(tenants.PermissionDenied):
            tenants.TenantStore(db).require_permission(COMPANY_A, 101, "procurement.write")

    def test_snapshot_compare_and_swap_requires_next_version(self):
        import supply_chain_tenants as tenants

        db = FakeTenantDB(2)
        store = tenants.TenantStore(db)
        next_version = store.commit_snapshot(
            COMPANY_A,
            1,
            {"version": 2, "products": {"SKU-1": {"quantity": 10}}},
        )
        self.assertEqual(next_version, 2)
        self.assertEqual(db.calls[0][1], "rpc/sc_commit_company_snapshot")
        self.assertEqual(db.calls[0][2]["p_expected_version"], 1)

        with self.assertRaises(ValueError):
            store.commit_snapshot(COMPANY_A, 1, {"version": 3})


class SequencedTenantDB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if not self.responses:
            raise AssertionError("Unexpected database request")
        return self.responses.pop(0)


class TenantLegacyMigrationTests(unittest.TestCase):
    def test_owner_can_copy_legacy_data_once_without_mutating_source(self):
        import copy
        import supply_chain_tenants as tenants

        company_id = "33333333-3333-4333-8333-333333333333"
        member = {"company_id": company_id, "telegram_user_id": 101,
                  "role": "owner", "status": "active"}
        empty_snapshot = {"version": 1, "products": {}, "orders": [],
                          "shipments": [], "suppliers": {}, "vehicles": [],
                          "movements": [], "scenarios": [], "demand_history": [],
                          "alert_state": {}}
        db = SequencedTenantDB([[member], [{"data": empty_snapshot}], 2])
        store = tenants.TenantStore(db)
        legacy = {"version": 20, "products": {"SKU-1": {"quantity": 12}},
                  "orders": [], "custom_config": {"currency": "UZS"}}
        original = copy.deepcopy(legacy)

        result = store.migrate_legacy_snapshot(company_id, 101, 101, legacy)

        self.assertTrue(result["legacy_preserved"])
        self.assertEqual(result["product_count"], 1)
        self.assertEqual(legacy, original)
        self.assertEqual(db.calls[-1][1], "rpc/sc_commit_company_snapshot")
        self.assertEqual(db.calls[-1][2]["p_expected_version"], 1)
        self.assertEqual(db.calls[-1][2]["p_data"]["version"], 2)
        self.assertEqual(db.calls[-1][2]["p_data"]["products"], legacy["products"])

    def test_non_owner_cannot_migrate_legacy_data(self):
        import supply_chain_tenants as tenants

        db = SequencedTenantDB([])
        store = tenants.TenantStore(db)
        with self.assertRaises(tenants.PermissionDenied):
            store.migrate_legacy_snapshot(COMPANY_A, 101, 999, {"version": 20})
        self.assertEqual(db.calls, [])

    def test_migration_refuses_to_overwrite_nonempty_company_snapshot(self):
        import supply_chain_tenants as tenants

        company_id = "33333333-3333-4333-8333-333333333333"
        member = {"company_id": company_id, "telegram_user_id": 101,
                  "role": "owner", "status": "active"}
        occupied = {"version": 1, "products": {"EXISTING": {"quantity": 1}}}
        db = SequencedTenantDB([[member], [{"data": occupied}]])
        store = tenants.TenantStore(db)
        with self.assertRaises(tenants.TenantError):
            store.migrate_legacy_snapshot(company_id, 101, 101, {"version": 20})
        self.assertEqual(len(db.calls), 2)


class TenantReadRouteWiringTests(unittest.TestCase):
    def test_get_routes_load_snapshot_from_verified_tenant_company(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
        self.assertIn("def _sc_tenant_context(self, permission):", source)
        self.assertIn("tenant_store.require_permission(", source)
        self.assertIn('snapshot = sc_tenants.TenantStore(_db_request).load_snapshot(', source)
        self.assertIn("if not is_tenant_request and (", source)

    def test_public_signup_is_disabled_by_default_and_legacy_migration_is_owner_gated(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("SC_PUBLIC_SIGNUP_ENABLED", "false")', source)
        self.assertIn("if (not SC_PUBLIC_SIGNUP_ENABLED", source)
        self.assertIn('if action == "migrate_legacy":', source)
        self.assertIn("telegram_user_id != int(OWNER_CHAT_ID)", source)

    def test_tenant_membership_is_rechecked_and_revoked_sessions_are_removed(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
        self.assertIn("_SC_TENANT_SESSIONS.revoke_user(", source)
        self.assertIn('tenant_context.get("company_id")', source)
        self.assertIn('tenant_context.get("user_id")', source)


if __name__ == "__main__":
    unittest.main()
