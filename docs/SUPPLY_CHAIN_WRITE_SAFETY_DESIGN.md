# Supply Chain Write Safety Design

**Status:** the original design findings remain historical context. The isolated branch now implements a Mini App inventory-import path using a JSONB compare-and-swap adapter; it is not merged or deployed.

**Scope:** future Mini App operations that mutate the company Supply Chain dataset, especially Excel import/apply, stock adjustments, purchase-order actions and shipment status changes.

## 1. Current persistence behavior

The current application stores the Supply Chain dataset under the `supply_chain_data` key in the existing `bot_storage.data` JSONB record.

Observed behavior in `bot.py`:

1. `load_json()` ensures the key is loaded and returns a deep copy of the process cache.
2. `save_json()` replaces the in-memory cache, copies the value into the in-memory `_pending` queue and returns `True`.
3. A background writer removes pending data from the queue and calls `_db_save()`; it retries failures and requeues the data after the retry limit.
4. `_db_save()` sends a Supabase REST upsert and requests a minimal response.

**Important consequence:** `save_json() == True` means the cache was updated and a write was queued. It does not prove that Supabase durably stored the new value. The Mini App must not report a successful inventory mutation based on this return value.

The Mini App read endpoints remain read-only. The isolated branch additionally exposes one narrowly scoped, owner-authenticated Excel inventory-import POST route; other Mini App business mutations remain deferred.


## 1.1 Additional persistence findings from code review

A focused review of the current writer implementation confirms several details that must be handled before adding acknowledged commits:

- `_writer_loop()` removes a key from `_pending` before the Supabase request starts. That write is then in-flight but is no longer represented in the pending map.
- `save_json()` can enqueue a newer snapshot for the same key while the older snapshot is in-flight. The single writer thread currently preserves order for its own queue, but a future synchronous commit must coordinate with both the in-flight write and the pending replacement; simply adding a second direct `_db_save()` call would introduce a stale-overwrite race.
- `flush_storage()` copies and clears the pending map, then calls `_db_save()` outside the writer thread. It does not wait for or coordinate with a write already in-flight for the same key. Shutdown flushing therefore is not a safe commit primitive.
- The `timeout` argument to `flush_storage(timeout=15)` is currently unused. The function makes one attempt per copied item and logs failures; it does not provide a bounded wait or durable completion signal.
- `_db_save()` uses Supabase `return=minimal`. A successful HTTP response confirms that the REST upsert request succeeded, but the application currently has no commit receipt, revision identifier or read-back verification tied to a particular queued snapshot.
- In local-file fallback mode, `save_json()` writes synchronously using a temporary file and `os.replace()`, but it does not fsync the file or containing directory. That may be acceptable for ordinary local development, but it should not be described as crash-durable without an explicit durability decision.

**Implementation consequence:** do not build an acknowledged Mini App write endpoint by calling `_db_save()` directly, by waiting for `_pending` to become empty, or by using `flush_storage()`. None of those methods can prove that the exact requested revision was durably committed without racing the current writer. The adapter must own queueing, in-flight tracking, ordering and per-revision completion under one synchronization protocol.

## 2. Required invariants

Every future write path must preserve all of these invariants:

- **Durable success:** return a success response only after the storage layer confirms the commit.
- **No lost updates:** serialize the complete read → validate → mutate → persist operation for the Supply Chain storage key.
- **No stale overwrite:** queued background writes and new synchronous/acknowledged writes must share one ordering mechanism.
- **Idempotent retry:** a client retry after a timeout must not apply the same operation twice.
- **Optimistic concurrency:** reject an apply request if the dataset changed after the user's preview.
- **Atomic audit:** the business-data change, version increment, idempotency record and audit entry must be committed together.
- **No silent replacement:** imports must show a row-level preview and the exact create/update behavior before the user confirms.
- **Calculation compatibility:** do not change existing EOQ, forecast, ABC, AVCO, transport or scenario calculations as a side effect of storage work.
- **Simulation separation:** classroom and scenario data must never be written into the live company dataset.

## 3. Proposed commit protocol

This is the target behavior, not code that is already present.

1. Authenticate the Telegram owner and validate the request schema and size.
2. Require an `expected_data_version` from the preview or last read response.
3. Require a client-generated idempotency key (UUID) and compute a canonical request hash on the server.
4. Acquire a per-storage-key operation lock that covers the entire read-modify-write lifecycle.
5. Load the latest dataset while holding that lock. If its version differs from `expected_data_version`, return **409 Conflict** with a fresh version; do not apply any row.
6. Look up the idempotency key:
   - Same key + same request hash: return the previously committed result without applying again.
   - Same key + different request hash: return **409 Conflict**.
7. Apply the validated domain operation to a deep copy. Validate every affected SKU and business rule again on the server.
8. Increment the dataset version and append an audit record and idempotency result to the same document.
9. Send the new document through a **single serialized persistence path** shared with the existing background writer. Wait for a durable acknowledgement.
10. Only after acknowledgement, publish the committed value to the in-memory cache and return success.

A network timeout after the database may have committed is an **unknown outcome**, not proof of failure. The client must retry with the same idempotency key; the server must discover the committed idempotency record and return the original result.

### Persistence adapter requirements

Before implementing the protocol, refactor storage behind one writer/commit adapter:

- Give each queued write a monotonically increasing in-process revision and a completion signal/result.
- Track pending and in-flight writes so a new commit cannot race an older write.
- Make both legacy queued writes and Mini App acknowledged writes use the same serialization/ordering mechanism.
- Acknowledge only after the Supabase request succeeds (or the local atomic file replacement succeeds in local fallback mode).
- On failure, preserve the newest pending revision and expose a failure result to the waiting operation.
- Do not mutate the live cache optimistically for a write that has not been acknowledged.
- Preserve the current `save_json()` interface for existing modules until each caller is deliberately migrated and regression-tested.

A process-local lock is sufficient only while the service is guaranteed to run as a single writer. If multiple Render instances or processes may write the same storage key, a process-local lock is insufficient. Before horizontal scaling, use a database-side transaction/compare-and-swap or a dedicated transactional RPC. That may require a schema or database-function change and must be separately reviewed and explicitly approved.


## 3.1 Acknowledged commit adapter (wired on the isolated branch)

The branch implements the acknowledged commit path without changing the Supabase schema:

- `supply_chain_persistence.py` — `SerializedCommitAdapter` serializes the complete load/version-check/mutate/persist operation within one process. It creates a new document revision, stores bounded audit and idempotency records in the candidate document, and returns success only when the persistence callback returns an explicit `True`.
- `tests/test_supply_chain_persistence.py` — focused tests for acknowledged commits, persistence failure, idempotent replay, mismatched idempotency reuse, stale preview versions, concurrent same-version requests and missing acknowledgements.

The adapter requires an injected `persist_snapshot(candidate, expected_version, new_version)` callback. In `bot.py`, that callback is backed by `JsonbCompareAndSwap` and a conditional PostgREST PATCH against `bot_storage`, filtered by `storage_key` and the embedded JSONB `version`. It returns success only after the returned representation confirms the new version, or after a reload proves that the exact idempotency record was committed. An ambiguous outcome is retried with the same operation ID and never reported as success without verification.

Idempotency records and audit entries are bounded by count (default 1,000); they are not retained for a guaranteed 30-day period. After eviction, an old retry may no longer be recognized. Production policy must either increase/define retention and/or use a durable operation ledger before offering a long retry guarantee.

**Limitations:** the lock and storage-save lock coordinate one Python process only. The conditional PATCH has fake-store/unit coverage but has not yet been tested against a disposable staging row/project. Any other process or legacy writer using blind upsert for the same key can bypass CAS. Those are release blockers, not completed validations.



## 3.0 Supply Chain handler serialization

The isolated branch also wraps the three state-changing Telegram entry points (callback actions, Excel document import flow, and free-text Supply Chain actions) with one shared `asyncio.Lock`. This serializes their read-modify-save lifecycles within the single bot event loop and prevents two owner actions from simultaneously loading the same old snapshot and overwriting each other's changes. A focused async concurrency test verifies that the three entry points share the same gate. The synchronous Supabase CAS request is dispatched with `asyncio.to_thread`, so waiting for the database does not block the Telegram event loop; a unit test verifies the callback runs on a worker thread.

This is still a single-process guarantee. It does not coordinate multiple bot instances, external writers, process restarts, or any future Mini App write API. The lock is held across each handler's awaited work, so it favors correctness over parallel throughput for this owner-only module.

## 3.1 Single-process write-queue hardening (isolated branch)

The current branch now routes ordinary `save_json` snapshots through `SnapshotWriteQueue`:

- Cache publication and queue insertion are serialized by one save lock, so each call's cache update and queue insertion happen together in the same critical section. This preserves the order in which callers acquire that lock; it does not resolve stale read-modify-write snapshots created before the call.
- The Supabase writer remains the sole thread that performs queued `bot_storage` upserts.
- A key is tracked as in-flight until the request attempt finishes.
- If an in-flight write fails after retries, its snapshot is requeued only when no newer snapshot for that key is already pending.
- `flush_storage(timeout)` no longer steals pending items and writes them concurrently. It waits, with a real timeout, for both pending and in-flight work to drain.
- The queue has focused unit tests for newer-snapshot precedence, in-flight flush waiting, defensive snapshot copies, and retry requeue.

This removes the known same-process writer/flush race for ordinary datasets. It does **not** make generic REST upserts transactional or protect against another bot process or independent writer. The `supply_chain_data` key is special-cased and never enters this generic queue: its `save_json` path uses the acknowledged CAS adapter synchronously, publishing cache state only after commit acknowledgement. This remains a single-process policy and must be validated against staging before production.


## 3.2 Branch implementation: JSONB compare-and-swap without schema changes

The existing `bot_storage` row for `supply_chain_data` was read without changing it. Its `data` value is a JSONB object and its embedded `version` is currently a JSON number (`1`). No dedicated version column or reusable CAS RPC exists.

Official PostgREST documentation describes JSON/JSONB arrow-path filters and conditional PATCH updates. The isolated branch implements that combination: `PATCH bot_storage` filtered by both `storage_key=eq.supply_chain_data` and `data->>version=eq.<expected>`, with `Prefer: return=representation`. A returned updated row acknowledges the conditional update; an empty result triggers a database reload and version/idempotency check. On an ambiguous network result, the same candidate is retried once and its operation ID is checked before the outcome is classified. See the [PostgREST JSON-column filtering and PATCH reference](https://docs.postgrest.org/en/stable/references/api/tables_views.html).

Integration on the isolated branch:
- `bot.save_json` special-cases only `supply_chain_data`: it commits synchronously through `SerializedCommitAdapter` and `JsonbCompareAndSwap`, rather than putting this dataset in the legacy blind-upsert queue.
- The adapter reads the current database snapshot, checks the expected embedded version, preserves audit/idempotency metadata, increments the version and uses the conditional PATCH callback.
- Supply Chain callback, Excel-import and free-text mutation handlers share one async lock, preventing overlapping in-process read-modify-save operations.
- Version conflicts are surfaced without overwriting newer data. Ambiguous outcomes warn the user not to repeat the action until the inventory state is checked.
- Other bot datasets continue using the latest-snapshot queue described below.

This implementation is covered by fake-store/unit tests only. **No live PATCH was sent to Supabase**, and no schema, row or production state was changed. Before any production deployment, the exact PostgREST query encoding, service-role response shape, conflict handling and concurrent-client behavior must be validated against a disposable staging row/project. Any separate process still using a blind upsert for the same storage key can bypass this CAS, so all writers must be upgraded or disabled before enabling writes. The Mini App has one scoped write route for explicitly confirmed Excel inventory imports; receipts, manual movements, purchase-order transitions and shipment transitions remain read-only/deferred.

## 3.3 Read-only Supabase storage inspection (2026-11-26)

The connected project was inspected without changing its schema or data:

- `public.bot_storage` has exactly three columns: `storage_key text NOT NULL`, `data jsonb NOT NULL DEFAULT '{}'`, and `updated_at timestamptz NOT NULL DEFAULT now()`.
- There is no dedicated revision/version column on the row.
- The existing public function catalog contains no Supply Chain storage compare-and-swap or acknowledged-commit RPC that can safely be reused.
- The current Supply Chain dataset's own `version` is inside the JSONB document, not a separate database column.

Supabase's current JavaScript/PostgREST filter documentation confirms that filters can be applied to update requests and that JSON-column paths can be filtered (for example, `address->postcode`). This makes a conditional update against the JSONB version worth prototyping without adding a table column. It is **not yet approved or verified as the production solution**: the exact PostgREST filter for the nested document must be tested against a disposable row, and a conditional PATCH alone does not protect against the existing background upsert writer. Every writer for the `supply_chain_data` key must share one ordering protocol before this can be enabled.

A database RPC using a transaction and row-level compare-and-swap remains the clearest robust option, but creating that function is a database change. No SQL, migration, function, table, or data was changed during this inspection. Any RPC implementation requires separate explicit approval.


## 4. Audit and idempotency record

Keep the audit entry in the same JSONB document as the business change so the change and its audit record cannot be committed separately.

Suggested bounded record shape:

```json
{
  "id": "operation-uuid",
  "actor_user_id": 123456789,
  "action": "excel_import_apply",
  "created_at": "2026-11-26T10:00:00+05:00",
  "previous_version": 12,
  "new_version": 13,
  "request_hash": "sha256:...",
  "summary": {
    "created": 3,
    "updated": 5,
    "unchanged": 2,
    "rejected": 0
  }
}
```

Requirements:

- Store no Telegram initData, bearer token, bot token, service-role key or unnecessary personal contact data in the audit log.
- Retain a bounded history (initial proposal: latest 1,000 operations) and a bounded idempotency lookup window (initial proposal: 30 days); finalize retention before implementation.
- Preserve the operation result needed to answer an idempotent retry.
- A duplicate operation ID with a different request hash is always rejected.
- Audit entries are append-only through normal application workflows; corrections are new compensating operations, not silent edits to old entries.

## 5. Excel import/apply contract

The browser-side CSV/XLSX preview remains local and read-only. It fetches the current inventory/version for the before/after diff but does not upload workbook bytes or mutate inventory. The implemented apply route follows this sequence:

1. Parse the workbook locally and show the selected worksheet and mapped columns.
2. Fetch the current inventory and embedded `data_version` through authenticated GET endpoints; calculate the before/after field diff in the browser. Workbook bytes are never uploaded.
3. User reviews the diff and explicitly checks the confirmation box, then presses the separate Apply button.
4. Only after confirmation, POST the normalized rows, source filename/worksheet, expected version and operation ID to the authenticated import endpoint.
5. Server independently validates every row, normalizes the request and calculates its canonical SHA-256 request hash.
6. The commit adapter reloads the latest JSONB snapshot, checks the expected version and idempotency record, mutates a deep copy, appends audit/import history and persists with conditional JSONB-version PATCH.
7. If any row or stored record is invalid, the entire candidate is rejected; no partial import is committed.
8. Return the committed version and summary counts (created, actually updated, fully unchanged and unchanged quantity). The browser refreshes dashboard and import history.

Current behavior is one explicit **create-or-update** mode: missing SKUs are created; matching SKUs update the name and quantity, plus unit/cost/reorder point only when those optional columns are mapped. Omitted optional fields are preserved. Rows with no field changes are counted as unchanged; quantity changes append a stock-adjustment movement. The preview is analysis-only until the user confirms apply. Separate create-only and selected-field modes are not currently exposed.

Do not offer a full-dataset replacement mode until backup, restore, audit and conflict handling are proven.

## 6. HTTP response behavior

| Situation | Expected response |
|---|---:|
| Durable commit completed | 200 or 201 |
| Invalid payload or failed server-side validation | 400 or 422 |
| Preview version is stale | 409 |
| Idempotency key reused with a different request | 409 |
| Not authenticated | 401 |
| Rate limit reached | 429 |
| Storage unavailable before commit | 503 |
| Commit outcome unknown after timeout | 503/504 with retry guidance; client reuses the same idempotency key |

Never return a success-shaped response while the write is merely queued.

## 7. Required test gates before enabling writes

- Durable acknowledgement: success only after storage confirms persistence.
- Simulated Supabase failure, retry exhaustion and recovery.
- Timeout after commit with same-key retry returns the original result and does not duplicate it.
- Same key with different payload is rejected.
- Two simultaneous operations with the same expected version: at most one commits; the other receives 409.
- Same-process Supply Chain Telegram writes and Mini App imports share the storage-save lock and CAS path; stale external bot replicas or independent blind upsert writers remain a release blocker.
- Cache remains unchanged when persistence fails.
- Process restart and retry behavior is deterministic.
- Import preview and apply revalidate the same normalized data and detect changed dataset versions.
- Duplicate SKUs, malformed numbers, negative quantities, oversized imports and unknown columns are rejected or explicitly mapped.
- Audit record and business-data update are committed together.
- Existing Supply Chain calculation regression suite remains unchanged and passes.
- No live deployment until HTTPS, Telegram Android WebView, backup/restore and owner-auth checks are complete.

## 8. Explicit non-goals for this phase

- No Supabase schema changes.
- No new database tables or RPC functions.
- No additional Mini App write endpoints beyond the confirmed Excel inventory-import route.
- No change to `save_json()` behavior for existing bot modules.
- No inventory mutation during Excel preview; only explicit confirmed apply may mutate inventory.
- No automatic purchase-order creation, replenishment, dispatch or delivery actions. Stock adjustments occur only as part of an explicitly confirmed Excel import and are recorded as movements.
- No merge to `main` and no Render deployment.

**Decision gate:** the adapter, server-side import validation and explicit-confirmation flow are implemented on this isolated branch, and fake-store/CI tests pass. Staging validation of the exact PostgREST conditional PATCH, concurrent-client behavior, HTTPS Render and Telegram Android WebView remain mandatory before merge or deployment.


## 3.3 Mini App inventory import implementation on isolated branch

The first browser write is deliberately limited to a user-confirmed inventory import:

- `supply_chain_mini_app_import.py` validates the entire payload before mutation, enforces SKU uniqueness case-insensitively, rejects negative/non-finite/boolean values and caps rows/field sizes.
- `POST /sc-api/v1/inventory/import` requires an existing owner bearer session, configured Supabase storage, JSON content type, an 8 MB body limit and a process-local limit of 3 import requests per 60 seconds.
- The request carries `operation_id` and `expected_version`. The server computes the canonical SHA-256 request hash; it does not trust a browser-provided hash.
- The commit uses `SerializedCommitAdapter` plus `JsonbCompareAndSwap`; the browser does not receive or use Supabase credentials.
- Existing quantities are replaced by the confirmed spreadsheet quantities. New products use the mapped unit when supplied, otherwise `pcs`; optional unit/cost/reorder values update only when present. Sanitized source filename/worksheet metadata and a bounded 100-entry import history are stored in the same JSONB document. Quantity deltas append inbound/outbound movement records.
- The UI displays a preview against the current inventory and requires a separate checkbox plus confirmation button. Preview alone never POSTs.
- Version conflicts are rejected; ambiguous outcomes are not reported as success and the UI warns against blindly repeating the import.

### Tests added

- `tests/test_supply_chain_mini_app_import.py` covers payload validation, duplicate SKUs, invalid numeric values, row limits, stock movements, optional-field preservation, unit mapping, sanitized source metadata, import history, idempotent replay, stale versions, unchanged-row counts and all-or-nothing validation.
- `browser_tests/test_mini_app_browser.py` covers preview-only behavior, explicit-confirmation POST behavior, import controls locked during an active commit and recent import-history display.

### Remaining release gates

- Validate the exact PostgREST JSONB path filter and response shape against a disposable staging row/project.
- Confirm all other processes/writers are unable to bypass the CAS with a legacy blind upsert.
- Run the full CI suite and inspect failures on the final branch head.
- Test the live HTTPS endpoint and actual Telegram Android WebView before merge/deploy.

No live Supabase PATCH or production write has been performed by this implementation.
