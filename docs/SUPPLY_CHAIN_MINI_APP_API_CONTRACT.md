# Supply Chain Mini App — Current Data Map and API Contract

Status: isolated-branch implementation. The read-only API primitives and first HTTP routes are implemented on `docs/supply-chain-mini-app-blueprint`; they are not merged or deployed. This document records verified behavior and the remaining scope. No Supabase schema changes or write endpoints are included.

## 1. Verified current implementation

### Persistence path
- `supply_chain.py` defines `DATA_FILE = "supply_chain_data.json"`.
- `supply_chain.install(...)` receives the bot's `load_json` and `save_json` callbacks.
- The bot derives a Supabase `storage_key` from the filename stem, so this object is stored under `supply_chain_data` in `bot_storage.data`.
- On startup, `init_storage()` preloads this key into a process cache.
- `load_json()` returns a deep copy of cached data.
- `save_json()` replaces the cached deep copy and queues a background write to Supabase. Without Supabase environment configuration, the fallback is a local JSON file.
- The bot has a custom `ThreadingHTTPServer` in `run_health_server()`. The isolated branch now adds `/sc-api/v1/health`, `/sc-api/v1/session`, `/sc-api/v1/bootstrap`, `/sc-api/v1/dashboard` and `/sc-api/v1/inventory` routes alongside existing routes.
- The HTTP server thread starts before storage initialization finishes. `_SC_STORAGE_READY` is set only after `init_storage_with_retry()` returns; business endpoints return HTTP 503 until then.

### Current access control
- The Telegram Supply Chain module currently permits only the configured owner in a private Telegram chat.
- The Mini App must not trust a client-supplied Telegram user ID. It must validate Telegram Web App `initData` on the server, then enforce the same owner authorization.
- The current owner-only boundary is not a multi-user/company role system. Do not quietly broaden access as part of the first Mini App release.

## 2. Current JSON data contract

The top-level object is initialized with:
```json
{
  "version": 1,
  "products": {},
  "movements": [],
  "suppliers": {},
  "orders": [],
  "vehicles": [],
  "shipments": [],
  "demand_history": [],
  "scenarios": []
}
```

### products — dictionary keyed by SKU
Observed product fields:
- `sku`: string identifier (examples generated with prefix `P-`)
- `name`: product name
- `quantity`: current on-hand quantity (number)
- `unit`: unit label
- `reorder_point`: threshold quantity
- `unit_cost`: current unit cost
- `annual_demand`: annual demand input
- `order_cost`: cost per order
- `holding_cost`: annual holding cost per unit
- `created_at`, `updated_at`: UTC ISO timestamps

### movements — append-style list
Observed fields:
- `id`, `sku`, `type` (`in` / `out`), `quantity`, `note`, `created_at`
- Optional references/cost fields include `shipment_id`, `order_id`, `unit_cost`, `total_cost`
- Movement records are used for audit/history and must not be silently rewritten by a dashboard.

### suppliers — dictionary keyed by supplier ID
Observed fields:
- `id`, `name`, `contact`, `lead_time_days`, `rating`, `created_at`, `updated_at`
- Default values exist in current entry logic when details are omitted (e.g. lead time 0 and rating 3/5); the UI must label defaults/assumptions rather than presenting them as measured facts.

### orders — purchase order list
Observed fields:
- `id` (PO-prefixed identifier), `sku`, `supplier_id`, `quantity`, `unit_price`, `expected_date`, `status`, `created_at`
- Receiving adds `received_at`, `previous_unit_cost`, `received_unit_cost`
- Status flow observed: `draft` → `ordered` → `received`; `cancelled` is also supported.
- Receiving changes product quantity and unit cost using moving weighted-average cost (AVCO), and appends an inbound movement. This is a business mutation and must use one guarded service operation.

### vehicles — list
Observed fields:
- `id`, `name`, `capacity`, `cost_per_km`, `speed_kmh`, `created_at`
- Current input may assume speed 60 km/h if omitted; show this as an assumption.

### shipments — list
Observed fields:
- `id`, `sku`, `quantity`, `destination`, `distance_km`, `vehicle_id`, `estimated_hours`, `estimated_cost`, `status`, `created_at`
- Status flow observed: `planned` → `dispatched` → `delivered`; planned shipments can be cancelled.
- Dispatch reduces stock and appends an outbound movement; delivery updates status/timestamp. Shipment dispatch must be atomic from the user's perspective.

### demand_history — list
Observed fields:
- `sku`, `month` (YYYY-MM), `quantity`, `created_at`
- Current entry logic updates the existing SKU/month row instead of adding a duplicate.

### scenarios — list
Observed fields:
- `id`, `name`, `sku`, `target_qty`, `usage_per_unit`, `daily_capacity`, `days`, `demand_qty`, `created_at`
- Scenario calculation is currently read-only with respect to stock.

These are observed fields, not a guarantee that every historical record contains every optional field. The API must validate and normalize legacy records defensively.

## 3. Existing calculation behavior to preserve

- Demand forecast: weighted moving average using up to the last six months; current readiness threshold and exact weighting must be retained from the existing calculation function and covered by regression tests.
- EOQ: `sqrt(2 × annual_demand × order_cost / holding_cost)`. If holding cost is absent/non-positive and the current function applies the documented 20% of unit cost assumption, return an explicit `assumption_applied` flag and the assumed amount.
- ABC: annual demand × unit cost; current text view uses 80% / 15% / 5% cumulative value bands. Preserve boundary behavior exactly and test it.
- Inventory value: current on-hand quantity × unit cost. It is only meaningful when unit and cost data are valid/consistent.
- Purchase order receipt: weighted-average cost (AVCO); never reimplement this calculation in the frontend.
- Transport recommendation: currently selects the lowest-cost vehicle among those with sufficient capacity, based on distance × cost_per_km.
- Risk assessment and scenario simulation are deterministic code paths. They should be exposed as service outputs, not re-created in JavaScript.
- Missing data is sometimes converted to numeric zero by existing helper functions. API/UI must distinguish “unknown / missing” from a genuine zero where possible; do not silently change calculation outputs during the first release.

## 4. Same-origin API — implemented subset and planned remainder

Base path: `/sc-api/v1`

All routes require a validated Telegram Web App session and owner authorization, except a minimal health/readiness route that returns no business data.

### Implemented on the isolated branch
- `GET /sc-api/v1/health` — public readiness response with no business data; returns HTTP 503 while storage is starting.
- `POST /sc-api/v1/session` — validates Telegram Web App `initData` HMAC, enforces the configured owner ID, rejects stale/future auth dates and duplicate fields, then issues a 30-minute process-local bearer session. Session creation is limited to 8 attempts per 60-second process-wide window.
- `GET /sc-api/v1/bootstrap` — supported sections and metric definitions.
- `GET /sc-api/v1/dashboard` — product, inventory value, low-stock, open-order and active-shipment KPIs.
- `GET /sc-api/v1/inventory?search=&status=&sort=&page=&page_size=` — paginated, allow-listed product rows.
- Authenticated responses set `Cache-Control: no-store`; JSON responses set `X-Content-Type-Options: nosniff`. No permissive CORS is configured.
- Session credentials are in-memory, expire after 30 minutes and are cleared automatically on process restart.
- The current session rate limiter is process-local and global to the app instance; it is a basic abuse-control layer, not a distributed limiter or a substitute for edge/network controls.

### Planned read-only endpoints
- `GET /sc-api/v1/inventory/{sku}` — product detail, movement history, demand history, supplier links and replenishment inputs.
- `GET /sc-api/v1/analytics/demand?sku=&months=&horizon=` — actual and forecast points plus method/coverage metadata.
- `GET /sc-api/v1/analytics/abc` — ranked product contribution, cumulative percentage and class.
- `GET /sc-api/v1/analytics/eoq` — EOQ inputs, outputs, assumption flags and sorted rows.
- `GET /sc-api/v1/analytics/replenishment` — below-reorder list and suggested quantity only where a defensible rule exists.
- `GET /sc-api/v1/procurement/orders?status=&page=&page_size=` — purchase order list.
- `GET /sc-api/v1/procurement/suppliers` — supplier list and observed data completeness.
- `GET /sc-api/v1/logistics/shipments?status=&page=&page_size=` — shipment list.
- `GET /sc-api/v1/logistics/vehicles` — vehicle list.

### Later controlled mutations (not part of read-only milestone)
- `POST /sc-api/v1/imports/preview` — stage an upload and return sheet/column mapping, validation errors and preview; does not change inventory.
- `POST /sc-api/v1/imports/{import_id}/apply` — apply a reviewed import only after an explicit confirmation token and before/after diff.
- `POST /sc-api/v1/orders/{id}/transition` — allow only valid status transitions through the existing business rules.
- `POST /sc-api/v1/shipments/{id}/transition` — allow only valid transitions; dispatch must atomically decrement stock and append movement.
- `POST /sc-api/v1/inventory/movements` — validate and record a stock movement through the canonical service.

Do not expose a generic endpoint that accepts arbitrary JSON and overwrites the whole `supply_chain_data` object from the browser.

## 5. Response conventions

Use a stable envelope:
```json
{
  "data": {},
  "meta": {
    "generated_at": "ISO-8601 UTC",
    "data_version": 1,
    "source": "supply_chain_data",
    "coverage": {}
  },
  "error": null
}
```

Errors should return a stable machine-readable code, short user-safe message and request ID. Do not expose stack traces, environment values, Supabase keys or raw workbook content.

Numeric metric shape:
```json
{
  "value": 123.4,
  "unit": "UZS",
  "status": "available",
  "assumption_applied": false,
  "assumptions": [],
  "source_window": null
}
```

Use `status` values such as `available`, `partial`, `unavailable` and `insufficient_history`; distinguish zero from unknown.

## 6. API implementation architecture

Recommended boundaries:
1. HTTP adapter: parse path/query/body, enforce body size and content type, set security headers, serialize JSON.
2. Authentication adapter: validate Telegram initData and create short-lived server-side session.
3. Authorization: enforce configured owner identity for the first release.
4. Supply Chain service: load a consistent snapshot, call existing calculation functions, normalize legacy records.
5. Repository adapter: use the existing `load_json/save_json` abstraction initially; no direct browser-to-Supabase access.
6. Presentation contract: API returns chart-ready arrays and table-ready rows; frontend handles only presentation, not business formulas.

Because the current server uses `ThreadingHTTPServer` and storage writes are cached/queued, all write operations must be serialized behind one Supply Chain service lock and must operate on a fresh, consistent snapshot. Avoid read-modify-write races between Telegram callbacks and Mini App requests. Read endpoints should use a single snapshot per response. Add an explicit storage-ready gate because the HTTP thread starts before `init_storage_with_retry()` completes.

## 7. Security checklist

- Validate Telegram `initData` HMAC server-side using the bot token; reject expired `auth_date` values and malformed fields.
- Never trust `user.id` sent separately by frontend.
- Enforce owner ID server-side on every business endpoint.
- Keep Supabase service-role key and Telegram bot token on the server only.
- Same-origin API; do not enable permissive wildcard CORS.
- Set `Cache-Control: no-store` on authenticated/business responses.
- Apply request body limits, timeouts, input validation and rate limits.
- Use HTTPS only; do not put session tokens or initData in URLs.
- Do not return contact details unless the UI needs them.
- Log request IDs and operation outcomes, not secrets, tokens or entire uploaded workbooks.
- Do not expose classroom/simulation data through these endpoints.

## 8. Frontend route map

- `/` — dashboard
- `/inventory` — searchable, sortable, filterable inventory table
- `/inventory/:sku` — product detail and movement history
- `/analytics/demand` — actual vs forecast
- `/analytics/abc` — Pareto and ABC table
- `/analytics/eoq` — order quantity and cost comparison
- `/analytics/replenishment` — reorder priority
- `/procurement/orders` — purchase orders
- `/procurement/suppliers` — suppliers
- `/logistics/shipments` — shipments and statuses
- `/logistics/vehicles` — fleet parameters
- `/imports` — staged Excel workspace (later phase)

Every page must support loading, empty, error, stale-data and insufficient-data states. Tables must have a mobile-friendly fallback and charts must have equivalent data tables.

## 9. Recommended implementation sequence

1. Add regression fixtures/tests for the current calculation functions and representative legacy JSON.
2. Build a pure read-only service layer around a deep-copied data snapshot.
3. Implement Telegram initData validation and owner-only session handling.
4. Add read-only API endpoints and storage-ready gating.
5. Build the Mini App shell and Dashboard/Inventory views.
6. Add analytics views using the same existing Python calculation functions.
7. Add staged Excel import and guarded mutations only after read-only behavior is proven.
8. Plan normalized database migration separately, with export/backup, mapping, dry-run, reconciliation and rollback.

## 10. Explicit non-goals for this stage

- No changes to `main` or the production branch.
- No changes to `supply_chain.py` business calculations.
- No new Supabase tables or policies.
- No change to existing classroom tables or `bot_storage` schema.
- No Mini App write endpoints or automatic AI features.
- No Render configuration or deployment changes.
