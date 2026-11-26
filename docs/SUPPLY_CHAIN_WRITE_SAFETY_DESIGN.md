# Supply Chain Write Safety Design

**Status:** design only — no write endpoint or storage behavior is implemented by this document.

**Scope:** future Mini App operations that mutate the company Supply Chain dataset, especially Excel import/apply, stock adjustments, purchase-order actions and shipment status changes.

## 1. Current persistence behavior

The current application stores the Supply Chain dataset under the `supply_chain_data` key in the existing `bot_storage.data` JSONB record.

Observed behavior in `bot.py`:

1. `load_json()` ensures the key is loaded and returns a deep copy of the process cache.
2. `save_json()` replaces the in-memory cache, copies the value into the in-memory `_pending` queue and returns `True`.
3. A background writer removes pending data from the queue and calls `_db_save()`; it retries failures and requeues the data after the retry limit.
4. `_db_save()` sends a Supabase REST upsert and requests a minimal response.

**Important consequence:** `save_json() == True` means the cache was updated and a write was queued. It does not prove that Supabase durably stored the new value. The Mini App must not report a successful inventory mutation based on this return value.

The current read API is deliberately read-only. Keep it that way until the requirements below are implemented and tested.

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

The current browser-side CSV/XLSX workflow remains **local preview only**. It does not upload files or modify inventory.

Future apply should follow this sequence:

1. Parse the workbook locally and show the selected worksheet and mapped columns.
2. Send a bounded, normalized preview payload — not an opaque workbook — to the server.
3. Server validates the payload independently: file/row/column limits, required fields, numeric bounds, duplicate SKUs, SKU normalization and business rules.
4. Server returns a row-level diff with counts for create, update, unchanged and rejected rows, plus the current `data_version`.
5. User reviews the exact diff and explicitly confirms.
6. Apply request includes the same expected version, preview fingerprint and idempotency key.
7. Server revalidates and commits the entire import atomically. If any required row fails, default behavior is **all-or-nothing**; partial import must not happen silently.
8. Return the committed version and a row-level result report.

Import modes must be explicit. Recommended initial modes:

- **Analysis only:** never changes stored data.
- **Create missing products:** creates only new SKUs; existing records remain unchanged.
- **Update selected fields:** user explicitly chooses which existing fields may be updated; movement history and unrelated metadata are preserved.

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
- A legacy background write cannot overwrite a newer acknowledged Mini App commit.
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
- No Mini App write endpoints.
- No change to `save_json()` behavior for existing bot modules.
- No inventory mutation from Excel preview.
- No automatic purchase order or stock adjustment.
- No merge to `main` and no Render deployment.

**Decision gate:** implement the persistence adapter and concurrency tests first. Only after those pass should a narrowly scoped write operation (preferably create-missing-products import) be considered for a separate reviewed change.
