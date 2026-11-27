import unittest
from types import SimpleNamespace

import supply_chain
from telegram.constants import ChatType


class SupplyChainOwnerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.previous_owner = supply_chain._OWNER_ID
        supply_chain._OWNER_ID = 100

    def tearDown(self):
        supply_chain._OWNER_ID = self.previous_owner

    @staticmethod
    def update(chat_id, user_id, chat_type=ChatType.PRIVATE, user_data=None):
        return SimpleNamespace(
            effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
            effective_user=SimpleNamespace(id=user_id),
            user_data=user_data or {},
        )

    def test_non_owner_cannot_enter_legacy_supply_chain_even_with_company_selector(self):
        update = self.update(
            200, 200, user_data={"active_company_id": "company-a", "role": "owner"}
        )
        self.assertFalse(supply_chain._allowed(update))

    def test_owner_must_use_matching_private_chat_and_user_identity(self):
        self.assertTrue(supply_chain._allowed(self.update(100, 100)))
        self.assertFalse(supply_chain._allowed(self.update(100, 101)))
        self.assertFalse(supply_chain._allowed(self.update(200, 100)))
        self.assertFalse(supply_chain._allowed(
            self.update(100, 100, chat_type=ChatType.GROUP)
        ))

    def test_missing_owner_configuration_denies_everyone(self):
        supply_chain._OWNER_ID = None
        self.assertFalse(supply_chain._allowed(self.update(100, 100)))


    def test_tenant_action_permission_map_is_fail_closed(self):
        self.assertIsNone(supply_chain.tenant_permissions_for_action("unknown_action", "callback"))
        self.assertIsNone(supply_chain.tenant_permissions_for_action("in", "unknown_source"))
        self.assertEqual(supply_chain.tenant_permissions_for_action("home", "callback"), ())

    def test_cross_domain_actions_require_both_permissions(self):
        self.assertEqual(
            set(supply_chain.tenant_permissions_for_action("ship_dispatch", "callback")),
            {"logistics.write", "inventory.write"},
        )
        self.assertEqual(
            set(supply_chain.tenant_permissions_for_action("ord_received", "callback")),
            {"procurement.write", "inventory.write"},
        )

    def test_every_free_text_mutator_has_an_explicit_write_permission(self):
        for action in supply_chain._APPLY:
            permissions = supply_chain.tenant_permissions_for_action(action, "text")
            self.assertIsNotNone(permissions, f"Missing permission mapping for {action}")
            self.assertTrue(permissions, f"Mutating action {action} cannot have empty permissions")
            self.assertTrue(
                any(permission.endswith(".write") for permission in permissions),
                f"Mutating action {action} must require a write permission",
            )

    def test_text_actions_are_scoped_to_their_business_domain(self):
        self.assertEqual(
            supply_chain.tenant_permissions_for_action("in", "text"),
            ("inventory.write",),
        )
        self.assertEqual(
            supply_chain.tenant_permissions_for_action("supplier_add", "text"),
            ("procurement.write",),
        )
        self.assertEqual(
            supply_chain.tenant_permissions_for_action("shipment_add", "text"),
            ("logistics.write",),
        )
        self.assertEqual(
            supply_chain.tenant_permissions_for_action("demand_add", "text"),
            ("planning.write",),
        )


if __name__ == "__main__":
    unittest.main()
