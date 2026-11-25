"""Static contract checks for the read-only Telegram Mini App shell."""
from pathlib import Path
import unittest


class SupplyChainMiniAppShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).resolve().parents[1] / "supply_chain_mini_app.html").read_text(
            encoding="utf-8"
        )

    def test_shell_is_mobile_first_and_has_dashboard_inventory_views(self):
        self.assertIn('name="viewport"', self.html)
        self.assertIn('data-view="dashboard"', self.html)
        self.assertIn('data-view="inventory"', self.html)
        self.assertIn('data-view="analytics"', self.html)
        self.assertIn('id="inventory-mobile"', self.html)

    def test_shell_authenticates_with_telegram_init_data(self):
        self.assertIn("tg.initData", self.html)
        self.assertIn('"/sc-api/v1/session"', self.html)
        self.assertIn("Authorization", self.html)
        self.assertIn("Bearer ", self.html)

    def test_shell_uses_only_read_only_business_endpoints(self):
        self.assertIn('"/sc-api/v1/dashboard"', self.html)
        self.assertIn('"/sc-api/v1/inventory?"', self.html)
        self.assertIn('"/sc-api/v1/analytics/demand"', self.html)
        self.assertIn('"/sc-api/v1/analytics/abc"', self.html)
        self.assertIn('"/sc-api/v1/analytics/eoq"', self.html)
        self.assertIn('"/sc-api/v1/analytics/replenishment"', self.html)
        self.assertNotIn("/sc-api/v1/imports", self.html)
        self.assertNotIn("/sc-api/v1/inventory/movements", self.html)

    def test_dynamic_business_values_are_not_inserted_as_html(self):
        self.assertNotIn("innerHTML", self.html)
        self.assertIn("textContent", self.html)


if __name__ == "__main__":
    unittest.main()
