# Supply Chain — Regression Test Plan and Current Risks

Status: regression suite and Mini App import tests are implemented on the isolated branch. This plan also records historical risks and remaining release checks. No production database or deployment has been changed.

## 1. Test-suite discovery

A repository code search for common test names and frameworks (`test_supply_chain`, `pytest`, `unittest`) did not return an existing Supply Chain test file. This is not proof that no tests exist anywhere in the repository; the next implementation step should inspect the full repository tree and CI workflow before adding a new test harness.

Recommended initial test location: `tests/test_supply_chain_regression.py`, subject to checking the repository's existing test conventions and dependency setup.

## 2. Test strategy

Use three layers:

1. Pure-function tests: deterministic calculations and parser helpers with in-memory dictionaries.
2. State-transition tests: inventory, purchase-order and shipment actions using a deep-copied fixture and fake load/save callbacks.
3. API contract tests (later): authentication, owner-only authorization, response envelopes, pagination, stale/not-ready behavior and no-write guarantees.

Every test must use isolated fixture data. Never point tests at the production Supabase project or the live `supply_chain_data` storage key.

## 3. Golden fixture

Create a small synthetic fixture with:
- 3 products: one healthy, one at/below reorder point, one missing optional cost/demand values.
- 2 suppliers: one normal lead time and one long lead time/low rating.
- 3 purchase orders: draft, ordered and received.
- 2 vehicles: one low-cost/slow and one higher-cost/faster, both with different capacities.
- 3 shipments: planned, dispatched and delivered.
- 6 consecutive monthly demand records for one SKU, 2 records for another, and no history for the third.
- 1 feasible and 1 infeasible production scenario.

Use clearly fictional SKUs, names and amounts. Store expected outputs as golden values only after the current production functions are executed and reviewed. Do not invent expected values from the documentation.

## 4. Regression matrix

### Inventory and movement
- Add a valid product; assert SKU uniqueness, normalized values and timestamps.
- Reject duplicate SKU/name cases according to existing rules.
- Receive stock; assert quantity increases and exactly one inbound movement is appended.
- Issue stock within available quantity; assert quantity decreases and one outbound movement is appended.
- Reject issue quantity greater than available stock; assert the entire object remains unchanged.
- Test zero, negative, NaN, infinity, numeric strings and malformed legacy values.
- Test missing optional cost/reorder fields without crashing dashboard or analytics.
- Verify reads and calculations do not mutate the source fixture.

### Demand forecast
- 0, 1 and 2 months: no forecast; insufficient-history state/message is returned.
- 3 months: weighted average uses weights 1, 2, 3.
- 6 months: only the latest six sorted months are used with weights 1 through 6.
- More than 6 months: older observations do not affect the forecast.
- Out-of-order records: sorting by YYYY-MM produces the same output.
- Same SKU/month update: one row remains; quantity is updated.
- Zero demand: forecast zero and coverage is represented as undefined/infinite according to existing behavior, not divided by zero.
- Invalid month, negative quantity and duplicate month cases.

### EOQ and ABC
- EOQ baseline: verify `sqrt(2DS/H)` against independently calculated expected values.
- Missing/non-positive holding cost: verify the current fallback assumption (including its exact basis and value) and expose the assumption in UI metadata.
- Zero annual demand, zero order cost, zero/negative holding cost and malformed values.
- Display rounding must not change internal precision.
- ABC: verify annual demand × unit cost ranking, cumulative contribution, 80/15/5 boundaries, ties and zero-total-value case.
- Verify the same input snapshot produces identical results on repeated calls.

### Purchase orders and AVCO
- Draft → ordered is allowed.
- Ordered → received is allowed once.
- Draft → received is rejected.
- Received → received is rejected (no duplicate receipt).
- Cancel draft/ordered is allowed according to current rules; cancel received is rejected.
- AVCO calculation is verified independently:
  `new_cost = (old_qty × old_cost + received_qty × purchase_price) / new_qty`.
- Existing stock with missing/non-positive cost is rejected without changing quantity, order status or movements.
- Invalid quantity/price and missing product/supplier must not partially mutate data.
- Successful receipt updates stock, weighted-average unit cost, order receipt fields and exactly one inbound movement.

### Transport and shipment
- Vehicle selector excludes insufficient capacity and invalid speed/cost records.
- Among feasible vehicles, lowest cost is selected; ETA is tie-breaker.
- Shipment planning does not decrement stock.
- Planned → dispatched decrements stock once and appends one outbound movement.
- Dispatch with insufficient stock is rejected without changing any field.
- Re-dispatch is rejected and cannot double-decrement stock.
- Planned → cancelled does not change stock.
- Dispatched → delivered updates status only; stock is not decremented again.
- Invalid transitions are rejected.
- Estimated cost and time are checked against distance × rate and distance ÷ speed.

### Production scenarios and risk
- Scenario simulation calculates feasible quantity as the minimum of target, material limit and capacity limit.
- Scenario simulation must never mutate inventory.
- Zero/negative usage and zero days are rejected.
- Risk assessment must be deterministic when passed a fixed `today` value.
- Low-stock risk, overdue PO, low supplier rating, long lead time, demand spike, scenario shortfall and delayed shipment each get a targeted fixture.
- Risk scan must not mutate the fixture.
- Missing demand history must not invent daily consumption.
- Product-specific supplier lead times must not leak from unrelated products.

### Dashboard and read models
- KPI counts match source fixture.
- Missing/unknown fields are not silently shown as confirmed zero in the Mini App.
- Empty datasets render valid empty states.
- Sorting is stable for ties.
- Pagination has no duplicate/missing rows across pages.
- Search/filter combinations compose correctly.
- Every chart's tabular data matches the same underlying series.

### Excel import (existing import module)
- Valid workbook and supported sheet.
- Missing required columns and ambiguous mapping.
- Duplicate SKU rows and duplicate keys.
- Invalid numeric values, dates, units and blank rows.
- Workbook size/file-type boundary and corrupted workbook.
- Preview and analysis-only paths do not mutate persistent inventory.
- Apply path requires explicit confirmation and reports before/after differences.
- Import retry does not double-apply the same rows.

## 5. High-priority implementation risks discovered

### A. In-memory object mutation before save
The module's `_data()` returns the loaded object, and several callbacks mutate that object directly before calling `_save(data)`. The module lock protects the load/save callback windows, but does not automatically serialize every full read-modify-write operation across all call sites. The Mini App must not add a second independent writer that can race with Telegram callbacks.

**Required design:** one shared Supply Chain service lock and a single read-modify-write transaction boundary used by both Telegram and Mini App mutations. Read-only endpoints should take one consistent snapshot and never return a live mutable reference.

### B. Storage writer queue is asynchronous
The bot's `save_json()` updates process cache and queues a background Supabase write. A successful return means the cache/queue accepted the data, not necessarily that Supabase has durably committed it at that exact moment.

**Required design:** the first Mini App release is read-only. Before adding browser-side mutations, define write acknowledgement, queue failure handling, flush semantics and recovery behavior. Do not claim a mutation is durable until the persistence layer confirms it.

### C. Health server starts before storage initialization
The health HTTP thread starts before `init_storage_with_retry()` finishes. The current simple health response does not establish that Supply Chain data is loaded.

**Required design:** expose a readiness state distinct from process liveness. Supply Chain API routes return a controlled 503/not-ready response until storage is initialized.

### D. Owner-only Telegram gate is not Web App authentication
The existing module checks private-chat and owner identity through Telegram Update objects. An HTTP request does not have that trusted Update context.

**Required design:** validate Telegram Web App initData on the server, check auth age/signature, then enforce the configured owner ID. Do not trust a client-provided Telegram user ID or query parameter.

### E. Current report functions are text renderers
Forecast, EOQ and ABC outputs are currently primarily formatted text functions. The Mini App needs structured data for charts and tables.

**Required design:** extract/test pure calculation functions that return structured rows/results, then keep the existing Telegram text renderers as adapters over those results. First capture golden outputs so extraction does not alter calculations.

### F. Some metrics contain implicit assumptions
Examples include the 60 km/h default vehicle speed, the holding-cost fallback in EOQ (confirm exact implementation before coding), and zero-default helpers for missing values.

**Required design:** each API metric includes status, units, source coverage and assumption metadata. Never disguise a default as an observed fact.

## 6. Release gates

Before a read-only Mini App is merged:
- Existing calculation outputs are captured as golden fixtures.
- Unit and state-transition tests pass.
- Read-only functions are proven not to mutate source data.
- Telegram and Mini App calculations use the same service functions.
- API authentication and owner authorization tests pass.
- Not-ready, malformed request, oversized request and storage failure tests pass.
- No direct browser access to Supabase service credentials exists.
- No changes are made to the production branch until explicit approval.

Before any Mini App write feature:
- Shared lock/transaction strategy is implemented and tested against Telegram callback concurrency.
- Durable write acknowledgement and recovery behavior are defined.
- Import diff, explicit confirmation, audit history and rollback/correction path are tested.


## 6. Implemented Mini App import tests

`tests/test_supply_chain_mini_app_import.py` now covers:
- Request schema, operation ID, version, row count and numeric bounds.
- Case-insensitive duplicate SKU rejection.
- All-or-nothing validation before commit.
- New product creation and existing product updates.
- Inbound/outbound movement generation and optional-field preservation.
- Idempotent replay and operation-ID payload mismatch.
- Stale preview version rejection.
- Sanitized workbook filename/worksheet metadata and bounded import history.
- Optional unit-of-measure validation, application and preservation.

`browser_tests/test_mini_app_browser.py` verifies that loading and previewing a CSV does not write, the confirm button remains disabled until the owner checks the confirmation box, and the expected preview version plus normalized rows are sent to the authenticated import endpoint.

Remaining gaps: staging PostgREST integration, actual Render HTTPS, and real Telegram Android WebView verification.
