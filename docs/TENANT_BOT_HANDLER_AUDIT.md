# Telegram Supply Chain handler tenant-safety audit

Date: 2026-11-27
Branch: `tenant-company-write-primitive`

## Current boundary (intentional)

The Telegram Supply Chain module (`supply_chain.py`) remains **owner-only**. Its `_allowed(update)` guard requires a private chat where both chat ID and Telegram user ID equal configured `OWNER_CHAT_ID`. The command, callback, free-text, document, voice/photo, inline-query and scheduled-job paths must not be opened to company members until they have a server-validated company context.

The Mini App tenant bearer is not a Telegram bot authorization token. A company ID held in `context.user_data`, callback data, or a user message is not sufficient authorization. Never route tenant users through the legacy global `supply_chain_data` row.

## Handler inventory

| Entry point | Current behavior | Data access / mutation | Tenant status |
|---|---|---|---|
| `/supply` / `open_supply` | Opens the owner Supply Chain menu | Reads global owner snapshot | Owner-only |
| `_serialized_callback` / `_callback` | Handles menu, shipment/order state, magic document confirmation, AI-assisted order draft and alert controls | Reads global snapshot; writes shipment dispatch/delivery/cancel, purchase order transitions, magic inventory updates, AI draft orders and alert state | Owner-only |
| `_serialized_text` / `_text` / `_magic_text` | Free-text inventory/product, movement, supplier, vehicle, demand, purchase order, shipment and scenario inputs; Excel confirmation; optional AI analysis | Mutates global snapshot through `_APPLY` or import; AI question path is read-only | Owner-only |
| `_serialized_excel_document` / `_handle_excel_document` | Receives workbook, maps columns, previews, confirms import | Reads and writes global snapshot on confirmation | Owner-only |
| `_serialized_voice` / `_serialized_magic_photo` | Voice/photo-assisted inventory entry | Can create a pending document; confirmation callback applies changes to global snapshot | Owner-only |
| `_inline_inventory_search` | Telegram inline inventory search | Reads global owner snapshot | Owner-only |
| `daily_report_loop` | Daily 09:00 inventory digest | Reads global owner snapshot and global report-state key; sends to owner | Owner-only scheduled job |
| `_proactive_alert_job` / `_weekly_supply_summary_job` | Scheduled alerts and weekly summary | Read owner Supply Chain data; alert state may be written | Owner-only scheduled jobs |

## Mutating domains found

- Inventory: create/update product, stock-in, stock-out, Excel import, magic/voice/photo-confirmed movements.
- Procurement: supplier creation, purchase order creation, order status transitions (ordered/received/cancelled), AI-generated draft orders.
- Logistics: vehicle creation, shipment creation, shipment dispatch (also decrements inventory and appends a movement), delivery and cancellation.
- Planning: demand-history records and scenario records.
- Alerting: snooze/alert-state changes and scheduled alert bookkeeping.

## Permission groundwork added (not yet enforced by Telegram handlers)

- `supply_chain.tenant_permissions_for_action(action, source)` now provides an explicit, fail-closed action permission map for text, callback and view actions.
- Unknown action/source returns `None` (deny); known navigation/preview actions return an empty permission tuple.
- Shipment dispatch requires both `logistics.write` and `inventory.write`; purchase-order receipt requires both `procurement.write` and `inventory.write`.
- The mapping is currently groundwork only. The Telegram handlers still use the owner-only guard and do not yet invoke this map for tenant authorization.

## Tenant context boundary added (not yet connected to handlers)

A separate `supply_chain_telegram_tenants.py` module now provides a fail-closed resolver for future Telegram tenant handlers:

- The active company ID in `context.user_data` is treated only as a selector; it never grants access.
- The actor ID is taken from Telegram's authenticated `effective_user`, and tenant access is restricted to private chats.
- Every declared permission is rechecked against live Supabase membership before the company snapshot is loaded.
- Empty permission declarations, missing/invalid selectors, group chats, membership failures and snapshot mismatches are denied.
- The returned role comes from the live membership lookup, not client/user state.
- Unit tests cover cross-company selection, permission ordering, no-selector behavior, role spoofing and selector validation.

Legacy Telegram Supply Chain handlers do not call this resolver; their owner-only guard remains unchanged. The tenant-specific commands below use the resolver directly and never enter the legacy global `_data()` / `_save()` path.

A private `/sc` command and `sctenant:` callback are now registered when Supabase is configured. They list only the caller's active memberships, then re-check membership before storing the selected company ID in `context.user_data`. The callback explicitly tells the user that selection is not authorization. The read-only `/sc_ombor` command revalidates `inventory.read` before loading the selected company's snapshot. `/sc_qosh SKU | Nomi | Miqdor | Birlik | ROP` creates a product with `inventory.write`; `/sc_kirim SKU | Miqdor | Izoh` and `/sc_chiqim SKU | Miqdor | Izoh` apply stock movements with `movement.write`; `/sc_yetkazuvchi ID | Nomi | Yetkazish muddati (kun)` creates a supplier with `procurement.write`; `/sc_buyurtma SKU | Supplier ID | Miqdor | Narx | YYYY-MM-DD` creates a draft purchase order, `/sc_buyurtma_ber PO-ID` marks it ordered, and `/sc_buyurtma_qabul PO-ID` receives it with AVCO costing and both `procurement.write` + `inventory.write`. `/sc_transport_qosh ID | Nomi | Sig'im | 1 km xarajati | Tezlik km/soat` adds a company-scoped vehicle with `logistics.write`; `/sc_yuk_reja SKU | Miqdor | Manzil | Masofa km` creates a planned shipment after checking tenant stock and selecting the cheapest eligible vehicle; `/sc_yuklar` reads only that company's shipment list with `logistics.read`. All tenant mutations use company-scoped CAS and operation receipts bound to Telegram update ID and request hash. Stock-out cannot make inventory negative. Shipment planning does not reserve/decrement stock. Shipment dispatch/delivery/cancel transitions remain owner-only; legacy menus, callbacks, free text, document/voice/photo flows, inline search, planning, AI, exports and scheduled jobs remain owner-only.


## Tenant-enabled command additions

The separate tenant adapter now also exposes:

- `/sc_transport_qosh ID | Nomi | Sig'im | 1 km xarajati | Tezlik km/soat` — creates a vehicle in the selected company's `vehicles` list with live `logistics.write`, CAS, duplicate-ID checks and replay receipts.
- `/sc_yuk_reja SKU | Miqdor | Manzil | Masofa km` — validates the selected company's product and available stock, chooses the lowest-cost vehicle whose capacity covers the shipment, and creates a `planned` shipment with `logistics.write`, CAS and replay receipts. Planning does not reserve or decrement inventory.
- `/sc_yuklar` — reads only the selected company's latest shipment records after live `logistics.read`.

Shipment dispatch, delivery and cancellation are still not tenant-enabled. Dispatch must atomically require both `logistics.write` and `inventory.write`, revalidate available stock inside the CAS mutator, decrement once, append a movement, and be replay-safe. Delivery/cancel transitions must reject invalid state changes. Legacy global callbacks remain owner-only.

## Required design before enabling company-member Telegram handlers

1. Establish an explicit company selection for each Telegram user, but treat it only as a selector. Re-read active membership and role from Supabase on every command, callback and message.
2. Add a tenant operation context scoped to one update. Resolve `telegram_user_id`, `company_id` and the current database role server-side; never accept role/company authority from callback data or client payloads.
3. Replace the module's global `_data()` / `_save()` storage path with an injected tenant snapshot repository for the active operation. Reads must use only `sc_company_snapshots`; writes must use `TenantStore.mutate_snapshot` and CAS.
4. Define action-to-permission mapping before entering the handler. Suggested starting boundaries:
   - `inventory.read` / `inventory.write`: inventory views, product/movement changes, import and magic-confirm operations.
   - `procurement.read` / `procurement.write`: suppliers and purchase orders.
   - `logistics.read` / `logistics.write`: vehicles, shipments and shipment status transitions.
   - `reports.read`: dashboards, exports, forecasts and analytics.
   Multi-domain actions (e.g. dispatch changes both logistics and inventory) must require both permissions atomically.
5. Give every Telegram mutation a stable operation ID derived from the Telegram update identity and bind it to a canonical request hash. Replays must return the original result; never re-run a stock decrement.
6. Scope AI context, inline search, exports, notification loops and scheduled jobs to a company. Do not run a single global job over tenant data or send one company's information to another company's chat.
7. Add cross-company tests for every handler family, role matrix tests, replay tests for shipment dispatch/order receipt/magic confirmation, and revocation tests.
8. Only after these checks pass, enable tenant Telegram entry points. Keep the current owner-only guard and legacy owner row untouched until then.

## Explicitly not done

- No Telegram company-member handler has been enabled.
- No tenant company selector for Telegram has been added.
- No migration or rewrite of the legacy `supply_chain_data` row has occurred.
- Scheduled jobs and inline search remain owner-only.
- This audit is a plan and inventory, not evidence of tenant support in those handlers.
