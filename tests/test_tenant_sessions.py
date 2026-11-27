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
        check = "\\n".join(f"{key}={values[key]}" for key in sorted(values))
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


if __name__ == "__main__":
    unittest.main()
