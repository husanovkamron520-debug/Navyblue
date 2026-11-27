import unittest
from types import SimpleNamespace

from supply_chain_telegram_tenants import (
    TelegramTenantContextError,
    clear_active_company,
    resolve_telegram_tenant_context,
    select_active_company,
    telegram_company_list,
    telegram_company_select,
    telegram_inventory_overview,
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


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edited = None

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    async def edit_message_text(self, text):
        self.edited = text


class FakeMessage:
    def __init__(self):
        self.text = None
        self.reply_markup = None

    async def reply_text(self, text, reply_markup=None):
        self.text = text
        self.reply_markup = reply_markup


class SelectorStore(FakeTenantStore):
    def load_snapshot_record(self, company_id):
        self.snapshot_calls.append(company_id)
        return {"company_id": company_id, "version": 3, "data": {
            "version": 3, "products": {
                "SKU-2": {"name": "Shakar", "quantity": 100700, "unit": "kg", "reorder_point": 700},
                "SKU-1": {"name": "Un", "quantity": 50, "unit": "qop", "reorder_point": 5},
            }}}

    def require_permission(self, company_id, telegram_user_id, permission):
        self.permission_calls.append((company_id, telegram_user_id, permission))
        if company_id != self.allowed_company or telegram_user_id != 42:
            raise PermissionError("membership denied")
        if permission != "inventory.read" or self.role not in {"owner", "admin", "warehouse", "purchasing", "transport", "viewer"}:
            raise PermissionError("permission denied")
        return {"company_id": company_id, "telegram_user_id": telegram_user_id,
                "role": self.role, "status": "active"}

    def list_companies(self, user_id):
        if user_id != 42:
            raise PermissionError("wrong user")
        return [{"company_id": COMPANY_A, "role": "warehouse",
                 "sc_companies": {"id": COMPANY_A, "name": "Alpha"}}]

    def membership(self, company_id, user_id):
        if company_id != self.allowed_company or user_id != 42:
            return None
        return {"company_id": company_id, "role": self.role, "status": "active"}


class TelegramCompanySelectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_company_list_only_shows_callers_memberships(self):
        message = FakeMessage()
        update_obj = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        )
        await telegram_company_list(update_obj, SimpleNamespace(), SelectorStore)
        self.assertIn("tanlang", message.text.lower())
        self.assertEqual(len(message.reply_markup.inline_keyboard), 1)
        self.assertEqual(
            message.reply_markup.inline_keyboard[0][0].callback_data,
            "sctenant:" + COMPANY_A,
        )

    async def test_selection_rechecks_membership_and_stores_only_selector(self):
        query = FakeQuery("sctenant:" + COMPANY_A)
        update_obj = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            callback_query=query,
        )
        user_data = {}
        await telegram_company_select(
            update_obj, SimpleNamespace(user_data=user_data), SelectorStore
        )
        self.assertEqual(user_data["sc_active_company_id"], COMPANY_A)
        self.assertIn("faqat tanlov", query.edited.lower())

    async def test_revoked_or_foreign_membership_cannot_select_company(self):
        query = FakeQuery("sctenant:" + COMPANY_B)
        update_obj = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            callback_query=query,
        )
        user_data = {"sc_active_company_id": COMPANY_A}
        await telegram_company_select(
            update_obj, SimpleNamespace(user_data=user_data),
            lambda: SelectorStore(allowed_company=COMPANY_A),
        )
        self.assertEqual(user_data["sc_active_company_id"], COMPANY_A)
        self.assertTrue(query.answers)
        self.assertIsNone(query.edited)

    async def test_group_chat_cannot_select(self):
        query = FakeQuery("sctenant:" + COMPANY_A)
        update_obj = SimpleNamespace(
            effective_chat=SimpleNamespace(type="group"),
            effective_user=SimpleNamespace(id=42),
            callback_query=query,
        )
        user_data = {}
        await telegram_company_select(
            update_obj, SimpleNamespace(user_data=user_data), SelectorStore
        )
        self.assertEqual(user_data, {})
        self.assertEqual(query.answers, [])


    async def test_inventory_overview_reads_only_selected_company_and_is_read_only(self):
        message = FakeMessage()
        update_obj = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        )
        user_data = {"sc_active_company_id": COMPANY_A}
        store = SelectorStore()
        await telegram_inventory_overview(
            update_obj, SimpleNamespace(user_data=user_data), lambda: store
        )
        self.assertIn("Ombor", message.text)
        self.assertIn("Shakar", message.text)
        self.assertIn("100700 kg", message.text)
        self.assertIn("faqat ko'rish", message.text)
        self.assertEqual(store.permission_calls, [(COMPANY_A, 42, "inventory.read")])
        self.assertEqual(store.snapshot_calls, [COMPANY_A])

    async def test_inventory_overview_does_not_read_snapshot_without_permission(self):
        message = FakeMessage()
        update_obj = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        )
        user_data = {"sc_active_company_id": COMPANY_B}
        store = SelectorStore(allowed_company=COMPANY_A)
        await telegram_inventory_overview(
            update_obj, SimpleNamespace(user_data=user_data), lambda: store
        )
        self.assertIn("tekshirib bo'lmadi", message.text.lower())
        self.assertEqual(store.snapshot_calls, [])


if __name__ == "__main__":
    unittest.main()
