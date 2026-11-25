import sys
import types
import unittest

# Supply Chain calculations are pure Python; stub Telegram's runtime-only types
# so these accounting tests do not need the bot framework installed.
telegram = types.ModuleType("telegram")
telegram.InlineKeyboardButton = object
telegram.InlineKeyboardMarkup = object
telegram.Update = object
constants = types.ModuleType("telegram.constants")
constants.ChatType = type("ChatType", (), {"PRIVATE": "private"})
ext = types.ModuleType("telegram.ext")
ext.Application = object
ext.CallbackQueryHandler = object
ext.CommandHandler = object
ext.ContextTypes = type("ContextTypes", (), {"DEFAULT_TYPE": object})
ext.MessageHandler = object
ext.filters = object()
sys.modules.setdefault("telegram", telegram)
sys.modules.setdefault("telegram.constants", constants)
sys.modules.setdefault("telegram.ext", ext)

import supply_chain


class SupplyChainAccountingTests(unittest.TestCase):
    def test_telegram_excel_import_handlers_and_sheet_mapping_are_wired(self):
        self.assertTrue(callable(supply_chain._handle_excel_document))
        self.assertTrue(callable(supply_chain._excel_finish_import))
        mapped = supply_chain._excel_mapping_from_text(
            "OrderList!J=product_name, OrderList!M=quantity, FreightRates!A=ignore"
        )
        self.assertEqual(mapped["OrderList"], {"J": "product_name", "M": "quantity"})
        self.assertEqual(mapped["FreightRates"], {"A": "ignore"})

    def test_purchase_receipt_recalculates_avco(self):
        data = {
            "products": {
                "P-001": {
                    "sku": "P-001", "name": "Paxta", "quantity": 100,
                    "unit_cost": 28000, "updated_at": "old",
                }
            },
            "movements": [],
        }
        order = {
            "id": "PO-AVCO", "sku": "P-001", "quantity": 100,
            "unit_price": 32000, "status": "ordered",
        }

        message = supply_chain._receive_purchase_order(data, order)

        product = data["products"]["P-001"]
        self.assertEqual(product["quantity"], 200)
        self.assertEqual(product["unit_cost"], 30000)
        self.assertEqual(order["status"], "received")
        self.assertEqual(order["received_unit_cost"], 30000)
        self.assertEqual(data["movements"][0]["unit_cost"], 32000)
        self.assertIn("30 000", message)

    def test_receipt_blocks_avco_when_existing_stock_has_no_cost(self):
        data = {
            "products": {
                "P-001": {"sku": "P-001", "name": "Paxta", "quantity": 100, "unit_cost": 0}
            },
            "movements": [],
        }
        order = {
            "id": "PO-NOCOST", "sku": "P-001", "quantity": 100,
            "unit_price": 32000, "status": "ordered",
        }

        with self.assertRaisesRegex(ValueError, "tannarxi kiritilmagan"):
            supply_chain._receive_purchase_order(data, order)

        self.assertEqual(data["products"]["P-001"]["quantity"], 100)
        self.assertEqual(order["status"], "ordered")
        self.assertEqual(data["movements"], [])

    def test_stockout_risk_uses_each_products_linked_supplier(self):
        products = {
            "P-FAST": {
                "sku": "P-FAST", "name": "Tez mahsulot", "quantity": 100,
                "reorder_point": 0, "annual_demand": 3600, "unit_cost": 1000,
            },
            "P-SLOW": {
                "sku": "P-SLOW", "name": "Sekin mahsulot", "quantity": 100,
                "reorder_point": 0, "annual_demand": 3600, "unit_cost": 1000,
            },
        }
        data = {
            "products": products,
            "suppliers": {
                "SUP-FAST": {"id": "SUP-FAST", "name": "Tez yetkazuvchi", "lead_time_days": 2, "rating": 4},
                "SUP-SLOW": {"id": "SUP-SLOW", "name": "Sekin yetkazuvchi", "lead_time_days": 15, "rating": 4},
            },
            "orders": [
                {"sku": "P-FAST", "supplier_id": "SUP-FAST", "status": "received"},
                {"sku": "P-SLOW", "supplier_id": "SUP-SLOW", "status": "received"},
            ],
            "demand_history": [
                {"sku": sku, "month": month, "quantity": 300}
                for sku in products
                for month in ("2026-08", "2026-09", "2026-10")
            ],
        }

        risks = supply_chain._risk_assessment(data, today="2026-11-25")
        stockout = {
            risk["title"]: risk["probability"]
            for risk in risks
            if risk["category"] == "Ombor" and "zaxirasi tugashi" in risk["title"]
        }

        self.assertEqual(stockout["Tez mahsulot zaxirasi tugashi"], 3)
        self.assertEqual(stockout["Sekin mahsulot zaxirasi tugashi"], 4)

    def test_eoq_screen_explains_holding_cost_unit_and_period(self):
        text = supply_chain._eoq_text({"products": {}})
        self.assertIn("1 dona/kg mahsulotni 1 yil", text)
        self.assertIn("oylik ijarasini H sifatida kiritmang", text)


if __name__ == "__main__":
    unittest.main()
