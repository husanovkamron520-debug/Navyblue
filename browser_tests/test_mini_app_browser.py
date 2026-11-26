import json
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class MiniAppBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(QuietHandler, directory=str(ROOT))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, args=["--no-sandbox"])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def setUp(self):
        self.api_calls = []
        self.context = self.browser.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True)
        self.context.add_init_script("""
            Object.defineProperty(window, "print", {
              configurable: true,
              value: () => { window.__printCalled = true; }
            });
        """)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.fail(f"Browser JavaScript error: {error}"))
        self.page.route("https://telegram.org/js/telegram-web-app.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript",
            body="""window.Telegram={WebApp:{initData:"browser-test-init-data",
              initDataUnsafe:{user:{first_name:"QA"}},ready(){},expand(){}}};"""
        ))
        self.page.route("https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript",
            body="""window.XLSX={read(){throw new Error("XLSX parser stub reached");},
              utils:{}};"""
        ))
        self.page.route("**/sc-api/v1/**", self._mock_api)

    def tearDown(self):
        self.context.close()

    def _mock_api(self, route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        query = parse_qs(parsed.query)
        self.api_calls.append((request.method, path, query, request.headers.get("authorization")))

        if path == "/sc-api/v1/session":
            route.fulfill(status=200, json={"data": {"token": "browser-test-token"}})
            return
        if request.headers.get("authorization") != "Bearer browser-test-token":
            route.fulfill(status=401, json={"error": {"message": "Unauthorized"}})
            return

        if request.method == "POST" and path == "/sc-api/v1/inventory/import":
            self.import_payload = json.loads(request.post_data or "{}")
            route.fulfill(status=200, json={"data": {"version": 2, "replayed": False,
                "result": {"processed": len(self.import_payload.get("rows", [])), "created": 2,
                           "updated": 0, "unchanged_quantity": 0}}})
            return
        if path == "/sc-api/v1/bootstrap":
            data = {"data_version": 1}
        elif path == "/sc-api/v1/dashboard":
            data = {"kpis": {"product_count": 2, "total_units": 15, "inventory_value": 1500,
                "low_stock_count": 1, "open_order_count": 1, "active_shipment_count": 1,
                "unknown_stock_count": 0}}
        elif path == "/sc-api/v1/inventory":
            items = [
                {"sku": "SKU-001", "name": "Test Product", "quantity": 5, "unit": "pcs",
                 "reorder_point": 10, "unit_cost": 100, "annual_demand": 120},
                {"sku": "SKU-002", "name": "Healthy Product", "quantity": 10, "unit": "pcs",
                 "reorder_point": 3, "unit_cost": 200, "annual_demand": 240},
            ]
            search = query.get("search", [""])[0].lower()
            if search:
                items = [item for item in items if search in item["sku"].lower() or search in item["name"].lower()]
            data = {"items": items, "pagination": {"page": 1, "pages": 1, "total": len(items)}}
        elif path.startswith("/sc-api/v1/inventory/"):
            data = {"item": {"sku": "SKU-001", "name": "Test Product", "quantity": 5, "unit": "pcs",
                    "reorder_point": 10, "unit_cost": 100, "annual_demand": 120, "updated_at": "2026-11-26"},
                "recent_movements": [{"type": "in", "quantity": 5, "created_at": "2026-11-25", "note": "Initial stock"}],
                "demand_history": [{"month": "2026-10", "quantity": 8}]}
        elif path == "/sc-api/v1/analytics/demand":
            data = {"items": [{"sku": "SKU-001", "name": "Test Product", "history_months": 3,
                "forecast_next_month": 10, "unit": "pcs", "days_of_stock_cover": 15, "forecast_status": "available"}]}
        elif path == "/sc-api/v1/analytics/abc":
            data = {"groups": {key: {"product_count": 1, "share_percent": share} for key, share in
                    (("A", 80), ("B", 15), ("C", 5))},
                "items": [{"sku": "SKU-001", "name": "Test Product", "category": "A", "share_percent": 80}]}
        elif path == "/sc-api/v1/analytics/eoq":
            data = {"items": [{"sku": "SKU-001", "name": "Test Product", "eoq": 12,
                "orders_per_year": 10, "holding_cost_assumed": True, "status": "available"}]}
        elif path == "/sc-api/v1/analytics/replenishment":
            data = {"items": [{"sku": "SKU-001", "name": "Test Product", "quantity": 5,
                "open_order_quantity": 0, "status": "low", "suggested_order_quantity": 8}]}
        elif path == "/sc-api/v1/procurement/orders":
            data = {"items": [{"id": "PO-001", "product_name": "Test Product", "supplier_name": "Supplier A",
                "quantity": 10, "expected_date": "2026-12-01", "status": "ordered"}],
                "pagination": {"page": 1, "pages": 1, "total": 1}}
        elif path == "/sc-api/v1/procurement/suppliers":
            data = {"items": [{"id": "SUP-001", "name": "Supplier A", "lead_time_days": 4, "rating": 4.5}]}
        elif path == "/sc-api/v1/logistics/shipments":
            data = {"items": [{"id": "SH-001", "product_name": "Test Product", "quantity": 2,
                "destination": "Samarkand", "vehicle_name": "Van", "distance_km": 10,
                "estimated_cost": 100, "status": "planned"}],
                "pagination": {"page": 1, "pages": 1, "total": 1}}
        elif path == "/sc-api/v1/logistics/vehicles":
            data = {"items": [{"id": "V-001", "name": "Van", "capacity": 100, "cost_per_km": 10}]}
        else:
            route.fulfill(status=404, json={"error": {"message": f"Unmocked API route: {path}"}})
            return
        route.fulfill(status=200, json={"data": data})

    def _open_app(self):
        self.page.goto(self.base_url + "/supply_chain_mini_app.html", wait_until="load")
        self.page.locator("#connection").filter(has_text="Ulangan").wait_for(timeout=10000)
        self.page.locator("#kpis .kpi-value").first.wait_for()
        self.page.wait_for_function("document.querySelector('#kpis .kpi-value')?.textContent?.trim() !== '—'")

    def test_dashboard_auth_inventory_detail_and_responsive_layout(self):
        self._open_app()
        self.assertEqual(self.page.locator("#welcome").inner_text(), "Xush kelibsiz, QA")
        self.assertEqual(self.page.locator("#kpis .kpi-value").first.inner_text(), "2")

        self.page.get_by_role("button", name="Ombor").click()
        self.page.locator("#inventory-mobile .product-card").first.wait_for()
        self.assertEqual(self.page.locator("#inventory-mobile .product-card").count(), 2)
        self.assertEqual(self.page.locator("#inventory-view .table-wrap").first.evaluate("(e)=>getComputedStyle(e).display"), "none")
        self.page.locator("#inventory-mobile .product-card").first.click()
        self.page.locator("#inventory-detail:not([hidden])").wait_for()
        self.page.wait_for_function("document.querySelector('#detail-name')?.textContent === 'Test Product'")
        self.assertIn("Test Product", self.page.locator("#detail-name").inner_text())
        self.assertIn("Initial stock", self.page.locator("#detail-movements").inner_text())

        self.page.set_viewport_size({"width": 1280, "height": 900})
        self.assertEqual(self.page.locator("#inventory-view .table-wrap").first.evaluate("(e)=>getComputedStyle(e).display"), "block")
        self.assertEqual(self.page.locator("#inventory-mobile").evaluate("(e)=>getComputedStyle(e).display"), "none")
        self.assertTrue(all(method == "GET" or path == "/sc-api/v1/session"
                            for method, path, _query, _auth in self.api_calls))

    def test_navigation_analytics_procurement_and_logistics_render(self):
        self._open_app()
        for label, section, marker in [
            ("Analytics", "#analytics-view", "#forecast-table"),
            ("Xarid", "#procurement-view", "#orders-table"),
            ("Logistika", "#logistics-view", "#shipments-table"),
        ]:
            self.page.get_by_role("button", name=label).click()
            self.page.locator(section).wait_for()
            self.page.locator(marker).wait_for()
        self.assertIn("Test Product", self.page.locator("#forecast-table").inner_text())
        self.assertIn("Supplier A", self.page.locator("#orders-table").inner_text())
        self.assertIn("Samarkand", self.page.locator("#shipments-table").inner_text())

    def test_local_csv_preview_and_invalid_xlsx_archive_guard(self):
        self._open_app()
        self.page.get_by_role("button", name="Excel Workspace").click()
        csv_bytes = b"SKU,Product,Quantity,Unit Cost,Reorder Point\nSKU-100,Local Item,7,12,3\nSKU-101,Second Item,4,5,2\n"
        self.page.locator("#excel-file").set_input_files({
            "name": "sample.csv", "mimeType": "text/csv", "buffer": csv_bytes
        })
        self.page.wait_for_function("document.querySelector('#excel-rows').textContent.trim() === '2'")
        self.assertEqual(self.page.locator("#excel-valid").inner_text(), "2")
        self.assertIn("Local Item", self.page.locator("#excel-preview").inner_text())
        self.assertFalse(any(method != "GET" and path != "/sc-api/v1/session" for method, path, _query, _auth in self.api_calls))

        self.page.locator("#excel-file").set_input_files({
            "name": "broken.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "buffer": b"not-a-zip-archive"
        })
        self.page.get_by_text("to‘g‘ri ZIP/XLSX arxiv emas").wait_for()
        self.assertFalse(any(path == "/sc-api/v1/imports" for _method, path, _query, _auth in self.api_calls))

    def test_excel_import_requires_explicit_confirmation_and_posts_preview_version(self):
        self._open_app()
        self.page.get_by_role("button", name="Excel Workspace").click()
        csv_bytes = b"SKU,Product,Quantity,Unit Cost,Reorder Point\\nSKU-100,Local Item,7,12,3\\nSKU-101,Second Item,4,5,2\\n"
        self.page.locator("#excel-file").set_input_files({
            "name": "inventory.csv", "mimeType": "text/csv", "buffer": csv_bytes
        })
        self.page.wait_for_function("document.querySelector('#excel-diff').textContent.includes('Yangi SKU')")
        confirm = self.page.locator("#excel-import-confirm")
        self.assertTrue(confirm.is_disabled())
        self.assertFalse(any(method == "POST" and path == "/sc-api/v1/inventory/import"
                             for method, path, _query, _auth in self.api_calls))

        self.page.locator("#excel-confirm-check").check()
        self.assertTrue(confirm.is_enabled())
        confirm.click()
        self.page.wait_for_function("document.querySelector('#excel-import-status').textContent.includes('Saqlandi')")
        self.assertEqual(self.import_payload["expected_version"], 1)
        self.assertEqual(len(self.import_payload["rows"]), 2)
        self.assertEqual(self.import_payload["rows"][0]["sku"], "SKU-100")
        self.assertEqual(self.import_payload["rows"][0]["unit_cost"], 12)
        self.assertTrue(any(method == "POST" and path == "/sc-api/v1/inventory/import"
                            for method, path, _query, _auth in self.api_calls))

    def test_csv_export_and_print_preview_use_read_only_api(self):
        self._open_app()
        self.page.get_by_role("button", name="Hisobotlar").click()
        with self.page.expect_download() as download_info:
            self.page.locator("#export-inventory").click()
        download = download_info.value
        self.assertEqual(download.suggested_filename, "supply-chain-inventory.csv")

        self.page.locator("#export-inventory-pdf").click()
        self.page.wait_for_function("window.__printCalled === true")
        self.assertIn("Ombor hisoboti", self.page.locator("#print-title").inner_text())
        self.assertIn("SKU-001", self.page.locator("#print-body").inner_text())
        self.assertTrue(all(method == "GET" or path == "/sc-api/v1/session"
                            for method, path, _query, _auth in self.api_calls))


if __name__ == "__main__":
    unittest.main()
