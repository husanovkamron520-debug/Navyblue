# Supply Chain multi-company rollout

## Current state (2026-11-27)

- The production Supply Chain store is currently one JSONB document in `public.bot_storage`, key `supply_chain_data`.
- The live document was observed at version 20. It was not modified by the foundation migration.
- The Mini App API currently labels the tenant mode `single_company`.
- The Telegram bot and Mini App currently authorize the single configured owner; this is not yet a public company-member authorization flow.
- Existing classroom tables are for the education/simulation workflow and are not reused as production company tenancy.

## Foundation deployed

The following backend-only tables have been created:

- `public.sc_companies`: tenant/company registry.
- `public.sc_company_members`: Telegram user membership and company-scoped roles.
- `public.sc_company_invites`: hashed, expiring, usage-limited invitation codes.

All three tables:
- have RLS enabled and forced;
- revoke access from `PUBLIC`, `anon`, and `authenticated`;
- grant access only to `service_role` for server-side operations;
- contain no seeded real companies or members yet.

Roles currently allowed: `owner`, `admin`, `warehouse`, `purchasing`, `transport`, `viewer`. Invite codes cannot grant the `owner` role.

## Important: not yet public-ready

Do not turn on public signup or expose company selection yet. The business data path is still a single shared JSONB snapshot. Adding tenant tables alone does not isolate that data.

## Required next implementation stages

1. Add server-side Telegram identity verification and company membership lookup. Never trust a client-provided company ID or role.
2. Add owner-only company creation, cryptographically random one-time invite generation, hashed invite storage, expiry/use limits, revocation, and safe invite redemption.
3. Replace the process-global Supply Chain snapshot with company-scoped snapshots or normalized company-scoped tables. Preserve the current version/CAS/idempotency protections per company.
4. Thread the verified company context through every Telegram handler, Mini App endpoint, export/import, AI snapshot, scheduled report, and background job.
5. Add role checks per operation (not merely per screen).
6. Add cross-tenant isolation tests: user A cannot read, mutate, export, import, or infer company B's data.
7. Only after tests pass, migrate the existing owner dataset into a designated first company and enable public onboarding.

## Non-regression constraints

- Do not overwrite or delete the current `supply_chain_data` row during the migration.
- Do not change education/classroom tables as part of the Supply Chain company rollout.
- Do not enable broad `anon` or `authenticated` access to the new tenant tables.
- Keep the existing owner workflow operational until the new tenant-aware path has passed tests.
