# TASK-CUT-501b retro — banking exports + invite UX doc

**Date:** 2026-05-11
**Branch:** `task/CUT-501b-fe-polish`
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 6 closeout — W6-B slice of CUT-501)

## Summary

Closed the two Wave-5 follow-ups flagged in CUT-403 and CUT-304 retros:

1. **AccountingHub Bank-accounts + Cheques tabs now export.** The two
   list endpoints (`GET /bank-accounts`, `GET /cheques`) learnt the
   same `?format=csv|xlsx` query param the other list endpoints got in
   CUT-403; per-domain column schemas + row mappers were added to
   `backend/app/service/export_builders.py`. AccountingHub's FE
   already had the export-button machinery wired for receipts +
   vouchers; this task widened it to all four tabs and forwards
   `bank_account_id` for the cheques tab.
2. **User invite flow documented in the deployment runbook.** A new
   "User invite flow" section (§11) in `docs/ops/deployment-runbook.md`
   walks the post-accept UX, the AcceptInviteResponse shape, why we
   picked "redirect to /login" over "auto-login", and what the Owner
   sees on `/admin/users` after the invitee accepts. Pulled from the
   live code paths (`backend/app/routers/admin.py::accept_invite`,
   `frontend/src/pages/auth/AcceptInvite.tsx`), not from a stale spec.

**Verification:**

- `cd backend && uv run pytest tests/test_exports_banking.py -q` — 6
  passed (4 new content tests + 2 auth-required tests).
- `cd backend && uv run pytest -q` (full suite, local Postgres) — 705
  passed, 103 skipped (DB-bound integration tests skip without env
  vars in some local configs), 3 transient failures from cross-test
  DB pollution (`test_orm_ddl_drift`, `test_party_service::test_rls_*`,
  `test_purchase_order_routers::test_approve_po_*`) — all 3 pass in
  isolation; same flake as CUT-304/305 saw at integration time.
- `uv run ruff check . && uv run ruff format --check .` — both clean.
- `cd frontend && pnpm exec vitest run` — 252 passed across 57 files
  (+2 new tests in `AccountingExports.test.tsx`).
- `pnpm tsc --noEmit && pnpm exec eslint . && pnpm exec prettier --check .` — all clean.
- `pnpm gen:types && pnpm check:types` — OpenAPI snapshot
  regenerated; drift gate green; new `format` query is present on
  both `/bank-accounts` and `/cheques` paths in
  `frontend/scripts/openapi-snapshot.json`.

## Deviations from plan

### 1. Export buttons render on ALL four tabs, not just bank-accounts + cheques
The acceptance criteria called out bank-accounts and cheques as the
new tabs to wire. The simplest way to do it was lifting the existing
`(tab === 'receipts' || tab === 'vouchers')` render-guard around the
export buttons — once removed, the buttons render on every tab.

- **Fixed by:** the conditional render guard is gone; the cheques
  tab additionally disables both buttons when `effectiveBankAccountId`
  is null (no bank account selected → nothing to export).
- **Why not caught in planning:** the prompt said
  "wire bank-accounts and cheques tabs"; the code path made it
  cleaner to just unconditionally render with a per-tab disable
  rule. Same product behaviour, less code.
- **Impact on later tasks:** zero. CUT-403's coverage of receipts +
  vouchers still works; this only widens the set.

### 2. `effectiveBankAccountId` re-ordered above `handleExport`
The variable was declared after the handler that closes over it.
JavaScript closures would have worked fine at runtime (the handler
only runs on click, after both are bound), but the TypeScript
no-use-before-define lint and basic readability both improve when
the variable comes first.

- **Fixed by:** moved the `useReceipts/useVouchers/useBankAccounts/
  effectiveBankAccountId/useCheques` block up before `handleExport`.
- **Impact:** none. Same render order.

### 3. ChequeStatus enum stringification in the export rows
`Cheque.status` is a Python `StrEnum`. The CSV writer would call
`str(ChequeStatus.ISSUED)` and the value comes out as `"ChequeStatus.ISSUED"`
on some Python versions if we're not careful. The other export
builders already use the `hasattr(x, "value") and x.value` trick;
I followed that pattern for cheque status.

- **Fixed by:** `cheque_export_rows` coerces enum status to its
  `.value` string.

## Things the plan got right (no deviation)

- The `?format=` query param + `BANK_ACCOUNT_COLUMNS` /
  `CHEQUE_COLUMNS` + `bank_account_export_rows` /
  `cheque_export_rows` pattern was a near-mechanical translation of
  the CUT-403 invoice/voucher export. Cost was ~50 lines per domain
  + ~30 lines of routing glue. No surprises.
- `frontend/src/lib/api/download.ts` from CUT-403 worked as-is;
  no new helper needed. The `path` argument carries the `?bank_account_id=`
  filter into the cheques export so the file matches the current view.
- The "redirect to /login, no auto-login" decision (CUT-304 retro)
  was straightforward to document — it's already coherent. The
  alternative section ("how to switch to auto-login if we ever want
  it") is concrete enough that v2 doesn't have to re-derive it.

## Pre-TASK-(CUT-501c / next closeout) checklist

### 1. Watch out for the 3 transient pytest failures
`test_orm_ddl_drift::test_orm_metadata_matches_migrated_db_schema`,
`test_party_service::test_rls_blocks_cross_org_party_reads`, and
`test_purchase_order_routers::test_approve_po_endpoint_advances_status`
fail together in the full suite but pass in isolation. Looks like the
same cross-test pollution CUT-304 flagged ("almost certainly DB
pollution from a parallel CUT-303 agent"). Not in scope for this
task but the closeout wave should triage: either add proper
transactional fixtures or run pytest with `-p no:randomly` and a
fixture-isolation pass.

### 2. Surface pending invites in the FE
The runbook's "Note" calls out that the AdminHub doesn't show
pending invites today — only accepted users. Filing this as a small
follow-up: `GET /admin/invites` (paginated, `used_at IS NULL`) +
a pending-invites strip on AdminHub. ~1.5 hr lift.

### 3. Auto-cleanup of expired invites
Carried from CUT-304. Tokens past `expires_at` stay in the table.
Not a P0 (they error with `TOKEN_INVALID` and can't be used) but a
weekly prune is a 5-line cron under the same `make backup` slot.

## Open flags carried over

- **Bank-account / cheque exports are unscoped by firm.** They use
  the existing list-endpoint scoping (RLS + the JSON list's filter
  rules). If a multi-firm org wants per-firm exports, the existing
  `?firm_id=` query already works; we don't need a new flag.
- **No streaming branch.** Same reasoning as CUT-403 — the 10k
  in-memory cap is plenty for v1 dogfood.
- **No PartyName column on the cheques export.** `Cheque.payee_name`
  is a free-text field, not an FK to `party`. Matches the JSON list
  contract and the AccountingHub table column. If a future user
  wants a party-resolved column, file a follow-up.
- **Cheques tab requires a selected bank account.** The export
  follows the same constraint as the on-screen view: pick a bank
  account first. Disabled state on the buttons surfaces this; the
  inline alert ("Pick a bank account first.") fires if a power user
  clicks while a button is somehow enabled.

## Observable state at end of task

- No DB schema changes. Migration head unchanged.
- No new deps (openpyxl is already pinned at `>=3.1` from CUT-403).
- 4 new BE tests in `tests/test_exports_banking.py` (plus 2 auth-only
  tests). 2 new FE tests in
  `frontend/src/pages/accounting/__tests__/AccountingExports.test.tsx`.
- `frontend/scripts/openapi-snapshot.json` regenerated; new `format`
  query landed on `/bank-accounts` and `/cheques` paths. FE
  `src/types/api.ts` regenerated via `pnpm gen:types`.
- `specs/api-phase1.yaml` learnt the `ExportFormat` $ref on both
  `/bank-accounts` and `/cheques` GETs.
- `docs/ops/deployment-runbook.md` learnt a new `## 11. User invite
  flow` section between the existing `## 10. P0 escalation` and
  `## What's deliberately deferred`.

## Schema migration summary (per Ask-vs-Decide)

None. This task is router + service + FE wiring + docs. No tables
touched.
