# Supply Chain Mini App — Architecture Blueprint

Status: design specification (no production code or database changes)
Scope: one company initially; schema and service boundaries must support future multi-company expansion.

## 1. Product principles

1. Preserve and reuse the existing Supply Chain calculation logic. Do not silently change formulas or assumptions.
2. Charts and data tables are first-class product surfaces; prose is concise and used for interpretation.
3. Mobile-first responsive interface, with desktop support.
4. Telegram bot and Mini App must read the same canonical Supply Chain data and calculation outputs.
5. AI is opt-in only: no automatic/background model calls. Deterministic calculations, sorting, filtering and chart preparation use normal code.
6. Excel imports are staged, validated and previewed. Persistent inventory changes require explicit user confirmation.
7. The current deployment and unrelated Navyblue features must remain untouched during design work.

## 2. Current-state audit (observed)

- The existing `supply_chain.py` module contains dashboard summaries, inventory/product data, suppliers, orders, shipments, risks and Excel import/confirmation flow.
- Existing analysis capabilities include inventory/reorder checks, demand history and forecast, EOQ, ABC-style classification, purchasing and logistics information.
- Telegram dashboard currently renders a long text summary.
- Supplier and product lists are rendered as text; inventory output is capped in the current text view.
- The current Supply Chain state is persisted through the bot's JSON storage path (the code uses the existing load/save abstraction and `supply_chain_data.json` key); it is not yet a dedicated normalized business schema.
- The connected Supabase project also contains classroom/simulation tables such as `inventory`, `orders`, `suppliers`, `purchase_orders` and `shipments` whose columns include `classroom_id` and/or `scenario_id`. These should not be repurposed as the real company's inventory tables without a deliberate migration.
- `public.bot_storage` contains JSONB storage. Existing data and policies must be inspected before changing its use.
- `public.kb_notes` was observed with RLS disabled. Do not change it as part of this Mini App work without first reviewing intended access and defining policies.
- No database schema, production code, or Render deployment was changed during this audit/design phase.

## 3. Information architecture

Primary navigation:
1. Dashboard
2. Inventory
3. Analytics
4. Procurement & Logistics
5. Excel Workspace
6. Reports

### Dashboard
- KPI cards: product count, inventory quantity/value (only where unit/cost data is valid), items below reorder point, open purchase orders, supplier count, shipment status.
- Charts: inventory value trend (when dated snapshots exist), demand trend, stock-risk distribution, procurement spend.
- Alert list: critical stock, overdue/at-risk replenishment, delayed shipments.
- Every KPI has a definition and data coverage indicator. Missing values must not be silently interpreted as zero.

### Inventory
- Search by SKU/name.
- Filters: stock status, ABC class, category, warehouse (when enabled), supplier.
- Sort: critical stock first, then below reorder point, then healthy; secondary sorts by quantity/value/demand.
- Table columns: SKU, product, unit, on-hand, reorder point, days of cover (only if demand history supports it), unit cost, inventory value, stock status, ABC class.
- Product detail: stock movement history, demand history, supplier and replenishment parameters.
- Pagination: 8–10 rows on mobile, configurable larger page size on desktop.

### Analytics
- Demand: actual vs forecast line chart; show forecast horizon, method and history coverage.
- EOQ: sortable table with rounded display quantities; show annual demand, order cost, holding cost, EOQ, orders/year and total-cost comparison in detail.
- ABC: Pareto chart and grouped table; expose threshold/method used.
- Reorder planning: current stock vs reorder point and suggested replenishment quantity.
- Inventory: stock distribution and value concentration.
- Procurement/logistics: supplier lead-time, order status, on-time performance and transport cost where source data exists.

### Procurement & Logistics
- Supplier table and detail.
- Purchase order register with status, expected/received quantity, cost and supplier response.
- Shipment table with origin, destination, carrier, ETA and status.
- Do not show performance percentages unless there are enough dated observations to calculate them reliably.

### Excel Workspace
- Upload workbook, inspect sheets/headers, map columns, validate types/units, preview records and identify duplicates.
- Distinguish “analyze this file only” from “apply changes to permanent inventory”.
- Import summary must show creates, updates, skipped rows and validation errors.
- Confirmation is required before persistent changes.
- Preserve the original file/import metadata for traceability, subject to retention policy.

### Reports
- Date-range and product filters.
- Export tables and chart data to XLSX/CSV; PDF summary can follow.
- Store report metadata and calculation timestamp/version.

## 4. Chart and table standards

- Prefer charts with clear units, labels, legends, date ranges and tooltips.
- Actual and forecast series must be visually distinct and forecast periods clearly marked.
- Every chart has an equivalent accessible data table.
- Avoid 3D charts, decorative gauges and misleading truncated axes.
- Tables support search, sort, filters, pagination, empty states and export.
- Highlight critical rows with a restrained status color and text label; never rely on color alone.
- Round display values appropriately (e.g. whole-unit order quantities) while retaining full precision in calculations and detail views.
- Use localizable number/date formatting and show units/currency explicitly.
- On mobile, use compact rows or horizontally scrollable tables only where necessary; provide a readable card/list alternative for key records.

## 5. Data architecture — target state

Use a company boundary from day one even while only one company exists. The initial company is the only active tenant, but every business-owned record should carry `company_id` or be reachable through a company-scoped parent.

Suggested normalized business entities:
- `companies`: tenant/company profile and settings.
- `warehouses`: company-owned physical/logical warehouses.
- `products`: SKU, name, category, unit, active status and default supplier references.
- `inventory_balances`: current on-hand/reserved quantities by company, warehouse and product.
- `stock_movements`: immutable receipts, issues, adjustments and transfers; source reference and actor.
- `suppliers`: company-specific supplier records and lead-time details.
- `purchase_orders` and `purchase_order_lines`: header/line separation, quantities, costs, status and expected dates.
- `shipments`: shipment status, carrier, origin/destination and ETA.
- `demand_observations`: dated actual demand by product and source.
- `excel_imports` and `excel_import_rows`: file metadata, mapping, validation results and import status.
- `analysis_runs`: algorithm/method, parameters, data window, run timestamp and version.
- `analysis_results`: typed or structured outputs linked to an analysis run.
- `report_exports`: generated report metadata and storage reference.

Do not create these tables until the current JSON schema, Supabase policies, ownership model and migration strategy have been reviewed. Existing classroom/simulation tables remain separate.

### Tenant and access model
- Initially configure one company and one owner/admin.
- Every read/write must be company-scoped on the server, not merely hidden in the UI.
- Use Supabase RLS policies for company membership and role-based access when the normalized schema is introduced.
- Never expose service-role secrets to the browser/Mini App.
- Keep classroom/simulation data isolated from real company data.

## 6. Canonical calculation/service layer

Extract calculation functions behind stable interfaces without changing their formulas in the first pass:
- inventory metrics and reorder status
- demand forecast
- EOQ
- ABC classification
- replenishment suggestions
- supplier and logistics metrics

Each result should include:
- value(s) and unit(s)
- source records/time window
- assumptions/defaults used
- data sufficiency/quality status
- calculation method and version
- calculated-at timestamp

The Telegram bot and Mini App call the same service layer. The Mini App must not reimplement formulas in JavaScript.

## 7. Excel import lifecycle

1. Upload and create a staged import.
2. Inspect workbook sheets, headers, formats and units.
3. Map columns; allow the user to explain unknown columns.
4. Validate required fields, numeric ranges, dates, units and duplicate keys.
5. Show a preview and row-level errors.
6. User selects either analysis-only or apply-to-inventory.
7. For apply-to-inventory, show exact creates/updates and before/after values.
8. Require explicit confirmation.
9. Apply transactionally where possible and record an audit trail.
10. Provide a completion report and rollback/correction path.

Never overwrite existing balances silently. Conflicts between workbook quantity and system quantity must be shown explicitly with a resolution choice.

## 8. Telegram and Mini App experience

Telegram:
- concise summary, top critical alerts and short paginated lists;
- buttons to open the relevant Mini App section;
- “Batafsil” links to the selected product/report/table;
- no 25-item text walls.

Mini App:
- deep-link to the selected company, product, import or analysis;
- responsive dashboard and data workspaces;
- shared authentication/session and server-side authorization;
- same data definitions and calculation version as Telegram.

## 9. Non-functional requirements

- Mobile-first responsive layout and accessible contrast.
- Fast initial load; paginate and query data server-side for larger datasets.
- Loading, empty, error and stale-data states for every data view.
- Audit log for imports and inventory-changing actions.
- Backups and tested restore procedure before schema migration.
- Observability for API failures and calculation errors without logging secrets or sensitive workbook contents.
- Automated tests for existing calculation outputs before refactoring.

## 10. Delivery phases

Phase 0 — Freeze and baseline:
- snapshot current branch/state and representative input/output fixtures;
- add regression tests around existing calculations and Excel import.

Phase 1 — Data contract:
- document current JSON keys/types and data ownership;
- define API response contracts and metric definitions;
- decide which values are current-state vs historical observations.

Phase 2 — Read-only Mini App foundation:
- authentication and company context;
- Dashboard and Inventory read views;
- responsive tables, search, sort, filters and pagination.

Phase 3 — Analytics:
- charts and tables driven by the canonical calculation layer;
- demand/forecast, EOQ, ABC, reorder and risk views.

Current isolated-branch implementation update (2026-11-25):

The read-only Mini App now has a static mobile-first shell with Dashboard, Inventory, Analytics, Procurement and Logistics views. The existing Telegram HTTP server serves the shell at `/supply-chain`; the Supply Chain Telegram menu adds a Web App launch button when `RENDER_EXTERNAL_URL` is HTTPS.

Implemented read-only service/API coverage:
- Inventory list and SKU detail with allow-listed product, movement and demand-history fields.
- Demand forecast using the existing up-to-six-month weighted moving average and three-month minimum.
- ABC classification using annual demand × unit cost and the existing midpoint 80/15/5 bands.
- EOQ using the existing 20%-of-unit-cost holding-cost fallback.
- Replenishment suggestions accounting for known open ordered quantities.
- Purchase-order, supplier, shipment and vehicle read views. Supplier contact details are not exposed.
- Mobile UI views for forecast, ABC, EOQ, replenishment, orders/suppliers and shipments/fleet.

Still not implemented:
- Excel Workspace upload/preview/apply in the Mini App (existing Telegram Excel import remains separate).
- Reports/export UI and downloadable report workflows.
- Browser-side write operations and confirmation flows for receipts, dispatches, movements or order transitions.
- End-to-end runtime testing against a deployed HTTPS Render instance.
- Complete production hardening and durable write semantics.

All new Mini App business endpoints remain read-only. No new database schema or production deployment is part of this branch.

Phase 4 — Excel Workspace:
- staged import, mapping, validation, preview and explicit apply flow.

Phase 5 — Procurement, logistics and reports:
- supplier, purchase order, shipment and export views.

Phase 6 — Hardening and rollout:
- RLS and tenant isolation tests;
- mobile QA, performance checks, backup/restore verification;
- deploy only after explicit review and test approval.

## 11. Acceptance criteria

- Existing calculation regression tests pass with unchanged expected results.
- Telegram and Mini App show matching values for the same data snapshot.
- Inventory list can search, filter, sort and paginate.
- Critical/low-stock items are prioritized consistently.
- Charts show units, period, source coverage and a matching table.
- Missing data is labelled as unavailable, not fabricated as zero.
- Excel analysis-only never mutates permanent inventory.
- Applying an import requires explicit confirmation and records an audit trail.
- No automatic AI calls occur.
- No classroom/simulation records leak into company inventory.
- Company-scoped authorization is enforced server-side.
- No production deployment occurs without a separate approval.


### Excel Workspace progress (2026-11-26)
- Added a mobile-first Excel Workspace view to the isolated Mini App branch.
- Current phase accepts CSV UTF-8 exported from Excel, parses it locally in the browser, and supports column mapping for SKU, product name, quantity, unit cost and reorder point.
- Validates required fields, non-negative numeric values, duplicate SKUs, file size (5 MB) and row count (10,000); shows a 20-row preview and validation summary.
- This is analysis-only: no file is uploaded to the server, no inventory data is changed, and no import/apply endpoint exists.
- Direct .xlsx parsing, server-side validation, persistent import history, and an explicitly confirmed durable apply flow remain future work. Do not implement inventory writes until persistence acknowledgement and operation-level locking are designed and tested.


### Reports & export progress (2026-11-26)
- Added a Reports view with inventory, purchase-order, and shipment CSV exports.
- Exports read all available API pages (100 rows per page) and generate UTF-8 BOM CSV files in the browser for spreadsheet compatibility.
- Export endpoints are read-only; no import, update, or inventory mutation is performed.
- Browser-side Excel parsing remains CSV-only in this phase; direct XLSX parsing and end-to-end browser runtime validation remain outstanding.


### Direct XLSX preview progress (2026-11-26)
- Excel Workspace now accepts .xlsx files as well as CSV UTF-8.
- XLSX workbooks are parsed locally in the browser with pinned SheetJS 0.18.5; users can choose among up to 20 worksheets.
- Parsing is capped at 5 MB per file and 10,002 parsed rows per worksheet; the preview rejects more than 10,000 data rows.
- CSV parser newline, carriage-return, whitespace and UTF-8 BOM handling was corrected.
- Column mapping validates duplicate SKUs and non-negative quantity, optional unit cost and reorder point values.
- No workbook bytes are uploaded, no import/apply endpoint is called, and inventory remains unchanged. The SheetJS library is loaded from a version-pinned CDN, so XLSX preview requires that CDN to be reachable.


### Excel report exports progress (2026-11-26)
- Reports view now offers both CSV and XLSX downloads for inventory, purchase orders and shipments.
- XLSX files are generated in the browser using the same version-pinned SheetJS library; report data is still read from authenticated, read-only API endpoints.
- No report export writes back to the server or changes inventory.
