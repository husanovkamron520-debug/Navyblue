"""Static contract checks for the Telegram Mini App shell and guarded import."""
from pathlib import Path
import unittest


class SupplyChainMiniAppShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).resolve().parents[1] / "supply_chain_mini_app.html").read_text(
            encoding="utf-8"
        )
        cls.bot = (Path(__file__).resolve().parents[1] / "bot.py").read_text(
            encoding="utf-8"
        )


    def test_read_api_has_rate_limits_and_bounded_query_inputs(self):
        self.assertIn('_SC_API_LIMITER = sc_api.RateLimiter(max_requests=120, window_seconds=60)', self.bot)
        self.assertIn('len(self.path.encode("utf-8")) > 8192', self.bot)
        self.assertIn('max_num_fields=32', self.bot)
        self.assertIn('> 120', self.bot)
        self.assertIn('> 128', self.bot)

    def test_shell_is_mobile_first_and_has_dashboard_inventory_views(self):
        self.assertIn('name="viewport"', self.html)
        self.assertIn('data-view="dashboard"', self.html)
        self.assertIn('data-view="inventory"', self.html)
        self.assertIn('data-view="analytics"', self.html)
        self.assertIn('data-view="procurement"', self.html)
        self.assertIn('data-view="logistics"', self.html)
        self.assertIn('data-view="reports"', self.html)
        self.assertIn('id="inventory-mobile"', self.html)

    def test_shell_authenticates_with_telegram_init_data(self):
        self.assertIn("tg.initData", self.html)
        self.assertIn('"/sc-api/v1/session"', self.html)
        self.assertIn("Authorization", self.html)
        self.assertIn("Bearer ", self.html)

    def test_shell_uses_read_models_and_has_one_scoped_import_endpoint(self):
        self.assertIn('"/sc-api/v1/dashboard"', self.html)
        self.assertIn('"/sc-api/v1/inventory?"', self.html)
        self.assertIn('"/sc-api/v1/analytics/demand"', self.html)
        self.assertIn('"/sc-api/v1/analytics/abc"', self.html)
        self.assertIn('"/sc-api/v1/analytics/eoq"', self.html)
        self.assertIn('"/sc-api/v1/analytics/replenishment"', self.html)
        self.assertIn('"/sc-api/v1/procurement/orders?page_size=50"', self.html)
        self.assertIn('"/sc-api/v1/logistics/shipments?page_size=50"', self.html)
        self.assertIn('"/sc-api/v1/inventory/import"', self.html)
        self.assertNotIn("/sc-api/v1/imports", self.html)
        self.assertNotIn("/sc-api/v1/inventory/movements", self.html)

    def test_excel_workspace_parses_csv_and_xlsx_locally_before_confirmed_import(self):
        self.assertIn('data-view="excel"', self.html)
        self.assertIn('id="excel-file"', self.html)
        self.assertIn('id="map-unit"', self.html)
        self.assertIn('function parseCSV(text)', self.html)
        self.assertIn('file.size>5*1024*1024', self.html)
        self.assertIn('rows.length>10001', self.html)
        self.assertIn('renderExcelPreview()', self.html)
        self.assertIn('Saqlash faqat alohida tasdiqdan keyin bajariladi', self.html)
        self.assertIn('accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"', self.html)
        self.assertNotIn('/sc-api/v1/imports', self.html)

    def test_excel_preview_does_not_mutate_inventory(self):
        self.assertIn('CSV UTF-8 va Excel .xlsx fayllar brauzerda tekshiriladi', self.html)
        self.assertIn('id="excel-import-confirm"', self.html)
        self.assertIn('id="excel-confirm-check"', self.html)
        self.assertIn('addEventListener("change",event=>', self.html)
        self.assertIn('addEventListener("click",confirmInventoryImport)', self.html)
        preview = self.html[self.html.find('function renderExcelPreview'):self.html.find('async function renderImportDiff')]
        self.assertNotIn('method:"POST"', preview)
        self.assertIn('renderImportDiff(valid)', preview)

    def test_import_endpoint_is_owner_authenticated_bounded_and_versioned(self):
        self.assertIn('"/sc-api/v1/inventory/import"', self.bot)
        self.assertIn('_SC_IMPORT_LIMITER = sc_api.RateLimiter(max_requests=3, window_seconds=60)', self.bot)
        self.assertIn('_SC_SESSIONS.authenticate(self._sc_bearer(), OWNER_CHAT_ID)', self.bot)
        self.assertIn('else 8_000_000', self.bot)
        self.assertIn('sc_import.commit_inventory_import(_get_sc_commit_adapter(), payload)', self.bot)
        self.assertIn('version_conflict', self.bot)
        self.assertIn('outcome_unknown', self.bot)

    def test_excel_workspace_reads_xlsx_locally_and_supports_multiple_sheets(self):
        self.assertIn('cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js', self.html)
        self.assertIn('accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"', self.html)
        self.assertIn('XLSX.read(bytes,{type:"array",cellDates:true,sheetRows:10002})', self.html)
        self.assertIn("function inspectXlsxArchive(bytes)", self.html)
        self.assertIn("entryCount>2000", self.html)
        self.assertIn("uncompressed>20*1024*1024", self.html)
        self.assertIn("totalUncompressed>40*1024*1024", self.html)
        self.assertIn("inspectXlsxArchive(bytes);", self.html)
        self.assertIn('XLSX.utils.sheet_to_json', self.html)
        self.assertIn('id="excel-sheet"', self.html)
        self.assertIn('names.length>20', self.html)
        self.assertIn('range.e.c>=100', self.html)
        self.assertIn('headers.length>100', self.html)
        self.assertIn('ch==="\\n"', self.html)
        self.assertIn('ch==="\\r"', self.html)
        self.assertIn(r'/\s/g', self.html)
        self.assertIn(r'/^\uFEFF/', self.html)
        self.assertIn('Saqlash faqat alohida tasdiqdan keyin bajariladi', self.html)
        self.assertNotIn('/sc-api/v1/imports', self.html)

    def test_reports_export_only_uses_read_endpoints_and_csv_download(self):
        self.assertIn('data-view="reports"', self.html)
        self.assertIn('id="export-inventory"', self.html)
        self.assertIn('id="export-orders"', self.html)
        self.assertIn('id="export-shipments"', self.html)
        self.assertIn("function fetchAllPages(path)", self.html)
        self.assertIn("function downloadCSV(filename,headers,rows)", self.html)
        self.assertIn("function downloadXLSX(filename,headers,rows)", self.html)
        self.assertIn("XLSX.utils.aoa_to_sheet", self.html)
        self.assertIn("XLSX.writeFile(workbook,filename)", self.html)
        self.assertIn('id="export-inventory-xlsx"', self.html)
        self.assertIn('id="export-orders-xlsx"', self.html)
        self.assertIn('id="export-shipments-xlsx"', self.html)
        self.assertIn("String.fromCharCode(65279)", self.html)
        self.assertIn("URL.createObjectURL(new Blob", self.html)
        self.assertIn("trimStart()[0]", self.html)
        self.assertIn("setTimeout(()=>URL.revokeObjectURL(url),1000)", self.html)
        self.assertIn("repeat(auto-fit,minmax(min(100%,220px),1fr))", self.html)
        self.assertIn('"/sc-api/v1/inventory"', self.html)
        self.assertIn('"/sc-api/v1/procurement/orders"', self.html)
        self.assertIn('"/sc-api/v1/logistics/shipments"', self.html)
        self.assertNotIn("/sc-api/v1/imports", self.html)

    def test_inventory_rows_open_read_only_product_detail(self):
        self.assertIn('id="inventory-detail"', self.html)
        self.assertIn('id="detail-movements"', self.html)
        self.assertIn('id="detail-demand"', self.html)
        self.assertIn('async function openInventoryDetail(sku)', self.html)
        self.assertIn('"/sc-api/v1/inventory/"+encodeURIComponent(sku)', self.html)
        self.assertIn('data.recent_movements', self.html)
        self.assertIn('data.demand_history', self.html)
        self.assertIn('addEventListener("click",()=>openInventoryDetail(p.sku))', self.html)
        self.assertIn('id="detail-close"', self.html)
        self.assertNotIn('/sc-api/v1/inventory/movements', self.html)

    def test_reports_can_be_printed_or_saved_as_pdf_without_server_writes(self):
        self.assertIn('id="export-inventory-pdf"', self.html)
        self.assertIn('id="export-orders-pdf"', self.html)
        self.assertIn('id="export-shipments-pdf"', self.html)
        self.assertIn('async function printReport(kind)', self.html)
        self.assertIn('window.print()', self.html)
        self.assertIn("rows.length>5000", self.html)
        self.assertIn('id="print-area"', self.html)
        self.assertIn('@media print', self.html)
        self.assertIn('window.addEventListener("afterprint"', self.html)
        self.assertIn('Save as PDF / PDF sifatida saqlash', self.html)
        self.assertNotIn('/sc-api/v1/imports', self.html)

    def test_dynamic_business_values_are_not_inserted_as_html(self):
        self.assertNotIn("innerHTML", self.html)
        self.assertIn("textContent", self.html)


if __name__ == "__main__":
    unittest.main()
