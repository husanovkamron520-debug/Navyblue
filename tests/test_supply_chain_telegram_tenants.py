import unittest
from types import SimpleNamespace

from supply_chain_telegram_tenants import (
    TelegramTenantContextError,
    clear_active_company,
    resolve_telegram_tenant_context,
    select_active_company,
)


COMPANY_A = "11111111-1111-4111-8111-111111111111"
COMPANY_B = "22222222-2222-4222-8222-222222222222"


class FakeTenantStore:
    def __init__(self, allowed_company=COMPANY_A, role="warehouse"):
        self.allowed_company = allowed_company
        self.role = role
        self.permission_calls = []
        self.snapshot_calls = []

    def require_permission(self, company_id, telegram_user_id, permission):
        self.permission_calls.append((company_id, telegram_user_id, permission))
        if company_id != self.allowed_company or telegram_user_id != 42:
            raise PermissionError("membership denied")
        return {"company_id": company_id, "telegram_user_id": telegram_user_id,
                "role": self.role, "status": "active"}

    def load_snapshot_record(self, company_id):
        self.snapshot_calls.append(company_id)
        return {"company_id": company_id, "version": 7,
                "data": {"version": 7, "products": {"A": {"quantity": 5}}}}


def update(chat_type="private", user_id=42):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(type=chat_type),
        effective_user=SimpleNamespace(id=user_id),
    )


class TelegramTenantContextTests(unittest.TestCase):
    def test_selector_is_not_authority_and_live_membership_is_checked(self):
        user_data = {}
        select_active_company(user_data, COMPANY_A)
        store = FakeTenantStore()
        context = resolve_telegram_tenant_context(
            update(), user_data, store, ("inventory.read",)
        )
        self.assertEqual(context.company_id, COMPANY_A)
        self.assertEqual(context.role, "warehouse")
        self.assertEqual(context.version, 7)
        self.assertEqual(store.snapshot_calls, [COMPANY_A])

    def test_all_permissions_are_checked_before_snapshot_load(self):
        user_data = {"sc_active_company_id": COMPANY_A}
        store = FakeTenantStore()
        context = resolve_telegram_tenant_context(
            update(), user_data, store,
            ("logistics.write", "inventory.write"),
        )
        self.assertEqual(
            [call[2] for call in store.permission_calls],
            ["logistics.write", "inventory.write"],
        )
        self.assertEqual(context.company_id, COMPANY_A)
        self.assertEqual(store.snapshot_calls, [COMPANY_A])

    def test_membership_failure_prevents_snapshot_read(self):
        user_data = {"sc_active_company_id": COMPANY_B}
        store = FakeTenantStore(allowed_company=COMPANY_A)
        with self.assertRaises(TelegramTenantContextError):
            resolve_telegram_tenant_context(
                update(), user_data, store, ("inventory.read",)
            )
        self.assertEqual(store.snapshot_calls, [])

    def test_missing_selector_and_group_chat_fail_closed(self):
        store = FakeTenantStore()
        with self.assertRaises(TelegramTenantContextError):
            resolve_telegram_tenant_context(update(), {}, store, ("inventory.read",))
        with self.assertRaises(TelegramTenantContextError):
            resolve_telegram_tenant_context(
                update(chat_type="group"),
                {"sc_active_company_id": COMPANY_A},
                store, ("inventory.read",),
            )
        self.assertEqual(store.snapshot_calls, [])

    def test_no_permission_declaration_is_denied(self):
        store = FakeTenantStore()
        with self.assertRaises(TelegramTenantContextError):
            resolve_telegram_tenant_context(
                update(), {"sc_active_company_id": COMPANY_A}, store, ()
            )
        self.assertEqual(store.snapshot_calls, [])

    def test_client_role_is_ignored_and_server_role_is_returned(self):
        user_data = {"sc_active_company_id": COMPANY_A, "role": "owner"}
        store = FakeTenantStore(role="viewer")
        context = resolve_telegram_tenant_context(
            update(), user_data, store, ("inventory.read",)
        )
        self.assertEqual(context.role, "viewer")

    def test_selector_validation_and_clear(self):
        user_data = {}
        with self.assertRaises(ValueError):
            select_active_company(user_data, "not-a-uuid")
        select_active_company(user_data, COMPANY_A)
        clear_active_company(user_data)
        self.assertNotIn("sc_active_company_id", user_data)


if __name__ == "__main__":
    unittest.main()
