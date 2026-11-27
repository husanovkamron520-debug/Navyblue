# Supply Chain multi-company rollout

## Current state (2026-11-27)

- The production Supply Chain store is still one JSONB document in `public.bot_storage`, key `supply_chain_data`.
- The legacy document was observed at version 20 and has not been modified by tenant setup or migration code.
- Tenant registry, membership, invitation, and per-company snapshot tables are in place.
- Telegram Web App `initData` can authenticate any Telegram user for onboarding; the legacy session route remains owner-only.
- Company creation, membership listing, invite redemption, invite creation, and company-bound bearer sessions are available through `POST /sc-api/v1/tenant/session`.
- Mini App company selection, create/join, invite generation, and explicit migration controls are implemented.
- Inventory archive and Excel import now use the authenticated tenant session, live `inventory.write` membership checks, and company-scoped snapshot CAS commits. UI controls are limited to `owner`, `admin`, and `warehouse`.
- Public self-registration is disabled by default (`SC_PUBLIC_SIGNUP_ENABLED=false`); the configured system owner can create the initial company, and other users join by invitation.
- Tenant-bound GET API requests re-check active membership and role against Supabase, then load only that company's `sc_company_snapshots.data`.
- Tenant archive/import writes persist bounded operation receipts in the same CAS-protected snapshot. Repeating one of the most recent 200 operation IDs with the same actor, permission, and request hash returns its original result; reusing an ID for a different payload is rejected.
- A one-time legacy migration action is implemented for the configured system owner. It only writes into a pristine version-1 company snapshot and leaves the legacy `bot_storage` row untouched. This action must be explicitly invoked; it does not run automatically.
- Existing classroom tables remain separate and are not reused for production company tenancy.

## Tenant database security

- `public.sc_companies`: tenant/company registry.
- `public.sc_company_members`: Telegram user membership and company-scoped roles.
- `public.sc_company_invites`: hashed, expiring, usage-limited invitation codes.
- `public.sc_company_snapshots`: one JSONB data snapshot per company, with database-side version/CAS commits.

All tenant tables have RLS enabled and forced, with access revoked from `PUBLIC`, `anon`, and `authenticated`; server-side operations use `service_role`. Invite codes cannot grant the `owner` role. Company-bound sessions are short-lived and never accept a company ID or role from later API requests as authorization proof.

Roles: `owner`, `admin`, `warehouse`, `purchasing`, `transport`, `viewer`.

## Important: not yet public-ready

The current work is a staged migration, not a finished SaaS release:

- The company onboarding UI is implemented; its latest frontend changes are awaiting deployment verification.
- Inventory archive and Excel import are tenant-aware. Telegram has a narrow tenant inventory path: `/sc` company selection, `/sc_ombor` read-only overview, `/sc_qosh` product creation, and `/sc_kirim` / `/sc_chiqim` stock movements. These writes use live role checks, company-scoped CAS and replay receipts. The legacy bot menu and all other domain workflows remain owner-only.
- Telegram bot handlers, exports, AI context, scheduled jobs, and background workflows have not all been threaded through verified tenant context.
- Cross-company read isolation is wired for the tenant GET path; full end-to-end read/write/export/import isolation tests are not complete.
- Public signup and public company access must remain disabled until all paths are tenant-aware.

## Required next implementation stages

1. Add Mini App company selection, company creation, invite joining, and selected-company session handling.
2. Add a clear owner-only migration confirmation flow. The migration helper checks that the target company's snapshot is still pristine; it copies the legacy data into the company snapshot at the next version and preserves the source row.
3. Extend company-scoped CAS and role permissions to the remaining domain mutations; archive and Excel inventory import are the first tenant write paths.
4. Extend verified company context to procurement, logistics, planning, exports, AI snapshot/context, inline search, scheduled reports, and background jobs; retain the owner-only legacy boundary until each path is tested.
5. Add end-to-end tests using at least three companies and several users. Verify cross-company reads, writes, exports, imports, invitations, role changes, revoked memberships, and CAS conflicts.
6. Only after all tests pass, enable public onboarding.

## Non-regression constraints

- Never overwrite or delete the legacy `supply_chain_data` row during migration.
- Never let a request-supplied company ID or role determine authorization.
- Do not change education/classroom tables as part of the Supply Chain company rollout.
- Do not grant broad `anon` or `authenticated` access to tenant tables.
- Keep the existing owner workflow operational until the tenant-aware path has passed isolation tests.
