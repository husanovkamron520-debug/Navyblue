import unittest
import sys
import types
from unittest.mock import patch
from types import SimpleNamespace

from supply_chain_telegram_tenants import (
    TelegramTenantContextError,
    clear_active_company,
    resolve_telegram_tenant_context,
    select_active_company,
    telegram_company_list,
    telegram_company_select,
    telegram_inventory_overview,
    telegram_inventory_add,
    telegram_inventory_movement,
    telegram_supplier_add,
    telegram_purchase_order_add,
    telegram_purchase_order_transition,
    telegram_vehicle_add,
    telegram_shipment_plan,
    telegram_shipment_list,
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
        allowed = {
            "owner": {"*"}, "admin": {"*"},
            "warehouse": {"inventory.read", "inventory.write", "movement.write", "reports.read"},
            "purchasing": {"inventory.read", "procurement.read", "procurement.write", "reports.read"},
            "transport": {"inventory.read", "logistics.read", "logistics.write", "reports.read"},
            "viewer": {"inventory.read", "procurement.read", "logistics.read", "reports.read"},
        }.get(self.role, set())
        if "*" not in allowed and permission not in allowed:
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
        class Button:
            def __init__(self, text, callback_data):
                self.text = text
                self.callback_data = callback_data

        class Markup:
            def __init__(self, inline_keyboard):
                self.inline_keyboard = inline_keyboard

        telegram_stub = types.ModuleType("telegram")
        telegram_stub.InlineKeyboardButton = Button
        telegram_stub.InlineKeyboardMarkup = Markup
        with patch.dict(sys.modules, {"telegram": telegram_stub}):
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


class InventoryWriteStore(SelectorStore):
    def __init__(self, allowed_company=COMPANY_A, role="warehouse"):
        super().__init__(allowed_company=allowed_company, role=role)
        self.data = {"version": 1, "products": {}}
        self.receipts = {}

    def load_snapshot_record(self, company_id):
        import copy
        self.snapshot_calls.append(company_id)
        return {"company_id": company_id, "version": self.data["version"],
                "data": copy.deepcopy(self.data)}

    def mutate_snapshot(self, company_id, telegram_user_id, permission, mutator,
                        expected_version=None, operation_id=None, request_hash=None):
        import copy
        self.require_permission(company_id, telegram_user_id, permission)
        prior = self.receipts.get(operation_id)
        if prior:
            if prior["hash"] != request_hash:
                raise ValueError("idempotency conflict")
            return {"result": prior["result"], "version": prior["version"],
                    "replayed": True}
        if expected_version != self.data["version"]:
            raise RuntimeError("version conflict")
        candidate = copy.deepcopy(self.data)
        result = mutator(candidate)
        candidate["version"] += 1
        self.data = candidate
        self.receipts[operation_id] = {
            "hash": request_hash, "result": copy.deepcopy(result),
            "version": candidate["version"],
        }
        return {"result": result, "version": candidate["version"], "replayed": False}


class TelegramInventoryAddTests(unittest.IsolatedAsyncioTestCase):
    def make_update(self, text, update_id=700, chat_type="private"):
        message = FakeMessage()
        message.text = text
        return SimpleNamespace(
            update_id=update_id,
            effective_chat=SimpleNamespace(type=chat_type),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        ), message

    async def test_inventory_add_is_tenant_scoped_and_replay_safe(self):
        store = InventoryWriteStore()
        update_obj, message = self.make_update(
            "/sc_qosh SKU-03 | Shakar | 100 | kg | 10"
        )
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        await telegram_inventory_add(update_obj, context, lambda: store)
        self.assertIn("SKU-03", store.data["products"])
        self.assertEqual(store.data["products"]["SKU-03"]["quantity"], 100)
        self.assertIn("qo'shildi", message.text.lower())
        self.assertEqual(store.data["version"], 2)

        # Telegram redelivery uses the same update ID and must replay, not add again.
        update_obj2, message2 = self.make_update(
            "/sc_qosh SKU-03 | Shakar | 100 | kg | 10"
        )
        update_obj2.update_id = update_obj.update_id
        await telegram_inventory_add(update_obj2, context, lambda: store)
        self.assertEqual(len(store.data["products"]), 1)
        self.assertIn("takroriy so'rov", message2.text.lower())
        self.assertEqual(store.data["version"], 2)

    async def test_inventory_add_rejects_foreign_company_before_write(self):
        store = InventoryWriteStore(allowed_company=COMPANY_A)
        update_obj, message = self.make_update(
            "/sc_qosh SKU-04 | Un | 20 | qop | 2"
        )
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_B})
        await telegram_inventory_add(update_obj, context, lambda: store)
        self.assertEqual(store.data["products"], {})
        self.assertIn("tekshirib bo'lmadi", message.text.lower())

    async def test_inventory_add_rejects_invalid_numbers_and_duplicate_sku(self):
        store = InventoryWriteStore()
        update_obj, message = self.make_update(
            "/sc_qosh SKU-05 | Un | -3 | qop | 2"
        )
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        await telegram_inventory_add(update_obj, context, lambda: store)
        self.assertEqual(store.data["products"], {})
        self.assertIn("manfiy", message.text.lower())

        update_obj2, message2 = self.make_update(
            "/sc_qosh SKU-06 | Un | 3 | qop | 2"
        )
        # Pre-seed the duplicate SKU to verify the mutation refuses overwrite.
        store.data["products"]["SKU-06"] = {"sku": "SKU-06", "name": "Existing"}
        await telegram_inventory_add(update_obj2, context, lambda: store)
        self.assertEqual(store.data["products"]["SKU-06"]["name"], "Existing")
        self.assertIn("allaqachon mavjud", message2.text.lower())


class TelegramInventoryMovementTests(unittest.IsolatedAsyncioTestCase):
    def make_update(self, text, update_id=901):
        message = FakeMessage()
        message.text = text
        return SimpleNamespace(
            update_id=update_id,
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        ), message

    async def test_stock_in_and_out_are_company_scoped_and_replay_safe(self):
        store = InventoryWriteStore()
        store.data["products"]["SKU-1"] = {
            "sku": "SKU-1", "name": "Shakar", "quantity": 10, "unit": "kg"
        }
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})

        incoming, in_message = self.make_update("/sc_kirim SKU-1 | 5 | Yetkazib beruvchi")
        await telegram_inventory_movement(incoming, context, lambda: store, "in")
        self.assertEqual(store.data["products"]["SKU-1"]["quantity"], 15)
        self.assertEqual(store.data["movements"][-1]["type"], "in")
        self.assertIn("Kirim", in_message.text)

        # Re-delivery of the same Telegram update cannot add stock twice.
        replay, replay_message = self.make_update("/sc_kirim SKU-1 | 5 | Yetkazib beruvchi")
        replay.update_id = incoming.update_id
        await telegram_inventory_movement(replay, context, lambda: store, "in")
        self.assertEqual(store.data["products"]["SKU-1"]["quantity"], 15)
        self.assertIn("qayta qo'shilmadi", replay_message.text)

        outgoing, out_message = self.make_update("/sc_chiqim SKU-1 | 4 | Ishlab chiqarish")
        await telegram_inventory_movement(outgoing, context, lambda: store, "out")
        self.assertEqual(store.data["products"]["SKU-1"]["quantity"], 11)
        self.assertEqual(store.data["movements"][-1]["type"], "out")
        self.assertIn("Chiqim", out_message.text)

    async def test_stock_out_cannot_make_inventory_negative(self):
        store = InventoryWriteStore()
        store.data["products"]["SKU-1"] = {
            "sku": "SKU-1", "name": "Un", "quantity": 2, "unit": "qop"
        }
        update_obj, message = self.make_update("/sc_chiqim SKU-1 | 3 | Sarf")
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        await telegram_inventory_movement(update_obj, context, lambda: store, "out")
        self.assertEqual(store.data["products"]["SKU-1"]["quantity"], 2)
        self.assertEqual(store.data.get("movements", []), [])
        self.assertIn("yetarli qoldiq yo'q", message.text)

    async def test_movement_rejects_foreign_company_before_snapshot_change(self):
        store = InventoryWriteStore(allowed_company=COMPANY_A)
        store.data["products"]["SKU-1"] = {
            "sku": "SKU-1", "name": "Un", "quantity": 10, "unit": "qop"
        }
        update_obj, message = self.make_update("/sc_kirim SKU-1 | 5 | Qabul")
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_B})
        await telegram_inventory_movement(update_obj, context, lambda: store, "in")
        self.assertEqual(store.data["products"]["SKU-1"]["quantity"], 10)
        self.assertIn("tekshirib bo'lmadi", message.text.lower())


class SupplierWriteStore(InventoryWriteStore):
    def __init__(self, allowed_company=COMPANY_A):
        super().__init__(allowed_company=allowed_company, role="purchasing")
        self.data["suppliers"] = {}

class TelegramSupplierAddTests(unittest.IsolatedAsyncioTestCase):
    def make_update(self, text, update_id=1101):
        message = FakeMessage()
        message.text = text
        return SimpleNamespace(
            update_id=update_id,
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        ), message

    async def test_supplier_creation_is_tenant_scoped_and_replay_safe(self):
        store = SupplierWriteStore()
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        update_obj, message = self.make_update(
            "/sc_yetkazuvchi SUP-01 | Atlas Textile | 7"
        )
        await telegram_supplier_add(update_obj, context, lambda: store)
        self.assertEqual(store.data["suppliers"]["SUP-01"]["name"], "Atlas Textile")
        self.assertEqual(store.data["suppliers"]["SUP-01"]["lead_time_days"], 7)
        self.assertIn("qo'shildi", message.text)

        replay, replay_message = self.make_update(
            "/sc_yetkazuvchi SUP-01 | Atlas Textile | 7",
            update_id=update_obj.update_id,
        )
        await telegram_supplier_add(replay, context, lambda: store)
        self.assertEqual(len(store.data["suppliers"]), 1)
        self.assertIn("qayta yaratilmadi", replay_message.text)

    async def test_supplier_creation_denies_foreign_company(self):
        store = SupplierWriteStore(allowed_company=COMPANY_A)
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_B})
        update_obj, message = self.make_update(
            "/sc_yetkazuvchi SUP-02 | Atlas | 4"
        )
        await telegram_supplier_add(update_obj, context, lambda: store)
        self.assertEqual(store.data["suppliers"], {})
        self.assertIn("tekshirib bo'lmadi", message.text.lower())

    async def test_supplier_creation_validates_lead_time(self):
        store = SupplierWriteStore()
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        update_obj, message = self.make_update(
            "/sc_yetkazuvchi SUP-03 | Atlas | -2"
        )
        await telegram_supplier_add(update_obj, context, lambda: store)
        self.assertEqual(store.data["suppliers"], {})
        self.assertIn("0–3650", message.text)


class PurchaseOrderWriteStore(InventoryWriteStore):
    def __init__(self, role="owner", allowed_company=COMPANY_A):
        super().__init__(allowed_company=allowed_company, role=role)
        self.data["products"] = {
            "SKU-01": {"sku": "SKU-01", "name": "Un", "quantity": 10,
                       "unit": "qop", "unit_cost": 100.0}
        }
        self.data["suppliers"] = {
            "SUP-01": {"id": "SUP-01", "name": "Atlas Textile", "lead_time_days": 5}
        }
        self.data["orders"] = []

class TelegramPurchaseOrderTests(unittest.IsolatedAsyncioTestCase):
    def make_update(self, text, update_id=2201):
        message = FakeMessage()
        message.text = text
        return SimpleNamespace(
            update_id=update_id,
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        ), message

    async def test_create_order_is_company_scoped_and_replay_safe(self):
        store = PurchaseOrderWriteStore(role="purchasing")
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        update_obj, message = self.make_update(
            "/sc_buyurtma SKU-01 | SUP-01 | 5 | 200 | 2026-12-05"
        )
        await telegram_purchase_order_add(update_obj, context, lambda: store)
        self.assertEqual(len(store.data["orders"]), 1)
        order = store.data["orders"][0]
        self.assertEqual(order["sku"], "SKU-01")
        self.assertEqual(order["supplier_id"], "SUP-01")
        self.assertEqual(order["status"], "draft")
        self.assertEqual(store.data["products"]["SKU-01"]["quantity"], 10)

        replay, replay_message = self.make_update(
            "/sc_buyurtma SKU-01 | SUP-01 | 5 | 200 | 2026-12-05",
            update_id=update_obj.update_id,
        )
        await telegram_purchase_order_add(replay, context, lambda: store)
        self.assertEqual(len(store.data["orders"]), 1)
        self.assertIn("ikkinchi buyurtma yaratilmadi", replay_message.text)

    async def test_order_requires_supplier_and_product_from_same_company(self):
        store = PurchaseOrderWriteStore()
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_B})
        update_obj, message = self.make_update(
            "/sc_buyurtma SKU-01 | SUP-01 | 5 | 200 | 2026-12-05"
        )
        await telegram_purchase_order_add(update_obj, context, lambda: store)
        self.assertEqual(store.data["orders"], [])
        self.assertIn("tekshirib bo'lmadi", message.text.lower())

    async def test_order_transition_and_receipt_update_avco_once(self):
        store = PurchaseOrderWriteStore(role="owner")
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        create, created_message = self.make_update(
            "/sc_buyurtma SKU-01 | SUP-01 | 5 | 200 | 2026-12-05", 2202
        )
        await telegram_purchase_order_add(create, context, lambda: store)
        order_id = store.data["orders"][0]["id"]
        mark, mark_message = self.make_update(f"/sc_buyurtma_ber {order_id}", 2203)
        await telegram_purchase_order_transition(mark, context, lambda: store, "ordered")
        self.assertEqual(store.data["orders"][0]["status"], "ordered")
        receive, receive_message = self.make_update(f"/sc_buyurtma_qabul {order_id}", 2204)
        await telegram_purchase_order_transition(receive, context, lambda: store, "received")
        self.assertEqual(store.data["orders"][0]["status"], "received")
        self.assertEqual(store.data["products"]["SKU-01"]["quantity"], 15)
        self.assertEqual(store.data["products"]["SKU-01"]["unit_cost"], (10*100+5*200)/15)
        self.assertEqual(len(store.data["movements"]), 1)

        replay, replay_message = self.make_update(f"/sc_buyurtma_qabul {order_id}", 2204)
        await telegram_purchase_order_transition(replay, context, lambda: store, "received")
        self.assertEqual(store.data["products"]["SKU-01"]["quantity"], 15)
        self.assertEqual(len(store.data["movements"]), 1)
        self.assertIn("qayta qo'llanmadi", replay_message.text)

    async def test_purchasing_role_cannot_receive_without_inventory_write(self):
        store = PurchaseOrderWriteStore(role="purchasing")
        store.data["orders"].append({
            "id": "PO-TEST", "sku": "SKU-01", "quantity": 2, "unit_price": 150,
            "status": "ordered"
        })
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        update_obj, message = self.make_update("/sc_buyurtma_qabul PO-TEST", 2205)
        await telegram_purchase_order_transition(update_obj, context, lambda: store, "received")
        self.assertEqual(store.data["products"]["SKU-01"]["quantity"], 10)
        self.assertEqual(store.data["orders"][0]["status"], "ordered")
        self.assertIn("tekshirib bo'lmadi", message.text.lower())



if __name__ == "__main__":
    unittest.main()


class TelegramTenantTransportTests(unittest.IsolatedAsyncioTestCase):
    def make_update(self, text, update_id=3301):
        message = FakeMessage()
        message.text = text
        return SimpleNamespace(
            update_id=update_id,
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        ), message

    async def test_vehicle_add_is_tenant_scoped_and_replay_safe(self):
        store = InventoryWriteStore(role="owner")
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        update_obj, message = self.make_update("/sc_transport_qosh TR-01 | Isuzu | 5000 | 2500 | 60")
        await telegram_vehicle_add(update_obj, context, lambda: store)
        self.assertEqual(len(store.data["vehicles"]), 1)
        self.assertEqual(store.data["vehicles"][0]["capacity"], 5000)
        replay, replay_message = self.make_update("/sc_transport_qosh TR-01 | Isuzu | 5000 | 2500 | 60", update_obj.update_id)
        await telegram_vehicle_add(replay, context, lambda: store)
        self.assertEqual(len(store.data["vehicles"]), 1)
        self.assertIn("qayta yaratilmadi", replay_message.text)

    async def test_vehicle_add_rejects_foreign_company_and_bad_capacity(self):
        store = InventoryWriteStore(role="owner")
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_B})
        update_obj, message = self.make_update("/sc_transport_qosh TR-02 | Isuzu | 5000 | 2500 | 60")
        await telegram_vehicle_add(update_obj, context, lambda: store)
        self.assertEqual(store.data.get("vehicles", []), [])
        self.assertIn("tekshirib bo'lmadi", message.text.lower())
        context.user_data["sc_active_company_id"] = COMPANY_A
        bad, bad_message = self.make_update("/sc_transport_qosh TR-03 | Isuzu | 0 | 2500 | 60", 3302)
        await telegram_vehicle_add(bad, context, lambda: store)
        self.assertEqual(store.data.get("vehicles", []), [])
        self.assertIn("Sig'im", bad_message.text)

    async def test_shipment_plan_selects_cheapest_eligible_vehicle_without_stock_decrement(self):
        store = InventoryWriteStore(role="owner")
        store.data["products"]["SKU-1"] = {"sku": "SKU-1", "name": "Un", "quantity": 200, "unit": "qop"}
        store.data["vehicles"] = [
            {"id": "TR-1", "name": "Katta", "capacity": 500, "cost_per_km": 3000, "speed_kmh": 50},
            {"id": "TR-2", "name": "Tejamkor", "capacity": 250, "cost_per_km": 2000, "speed_kmh": 60},
        ]
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        update_obj, message = self.make_update("/sc_yuk_reja SKU-1 | 100 | Toshkent | 300")
        await telegram_shipment_plan(update_obj, context, lambda: store)
        self.assertEqual(len(store.data["shipments"]), 1)
        self.assertEqual(store.data["shipments"][0]["vehicle_id"], "TR-2")
        self.assertEqual(store.data["shipments"][0]["status"], "planned")
        self.assertEqual(store.data["products"]["SKU-1"]["quantity"], 200)
        self.assertIn("qaytirmaydi", message.text.lower())

    async def test_shipment_plan_denies_foreign_company_and_insufficient_stock(self):
        store = InventoryWriteStore(role="owner")
        store.data["products"]["SKU-1"] = {"sku": "SKU-1", "name": "Un", "quantity": 2, "unit": "qop"}
        store.data["vehicles"] = [{"id": "TR-1", "name": "Truck", "capacity": 50, "cost_per_km": 2, "speed_kmh": 50}]
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_B})
        foreign, foreign_message = self.make_update("/sc_yuk_reja SKU-1 | 1 | Toshkent | 300", 3303)
        await telegram_shipment_plan(foreign, context, lambda: store)
        self.assertEqual(store.data.get("shipments", []), [])
        self.assertIn("tekshirib bo'lmadi", foreign_message.text.lower())
        context.user_data["sc_active_company_id"] = COMPANY_A
        short, short_message = self.make_update("/sc_yuk_reja SKU-1 | 3 | Toshkent | 300", 3304)
        await telegram_shipment_plan(short, context, lambda: store)
        self.assertEqual(store.data.get("shipments", []), [])
        self.assertIn("yetarli qoldiq yo'q", short_message.text.lower())

    async def test_shipment_list_is_read_only_and_tenant_scoped(self):
        store = InventoryWriteStore(role="owner")
        store.data["shipments"] = [{"id": "SH-1", "sku": "SKU-1", "quantity": 1,
                                    "destination": "Toshkent", "status": "planned"}]
        context = SimpleNamespace(user_data={"sc_active_company_id": COMPANY_A})
        update_obj, message = self.make_update("/sc_yuklar", 3305)
        await telegram_shipment_list(update_obj, context, lambda: store)
        self.assertIn("SH-1", message.text)
        self.assertEqual(store.data["version"], 1)
        self.assertEqual(store.permission_calls[-1][2], "logistics.read")
