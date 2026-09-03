# TASK-196 retro — Dashboard sales/GST KPIs count DRAFT invoices

**Date:** 2026-09-03
**Branch:** fix/issue-196
**Commit:** `<this task's commit on fix/issue-196>` (not merged; orchestrator integrates)
**Plan:** GitHub issue #196 comment (agent-ready plan)

## Summary

`sales_today`, `sales_mtd` and `gst_collected_mtd` were computed over
`_NON_CANCELLED_LIFECYCLES`, a tuple that included DRAFT and CONFIRMED —
invoices that never post to the general ledger. A draft dated today
therefore inflated all three dashboard numbers by its full amount.
Replaced that tuple with `_BILLED_LIFECYCLES`
(FINALIZED/POSTED/PARTIALLY_PAID/PAID/OVERDUE), mirroring
`reports_service._GSTR1_LIFECYCLE` and consistent with the already-correct
`_OPEN_AR_LIFECYCLES` used for outstanding_ar/overdue_ar. Six integration
tests added (real Postgres + RLS). Lint (ruff check + format), types
(mypy), and the impacted test set (43 tests across dashboard, reports,
receipt, activity-title suites) all pass. No schema/API/OpenAPI change, no
migration.

## Deviations from plan

### 1. Test placement
Plan suggested extending `test_int12_dashboard_kpis.py` and/or
`test_dashboard_service.py`. Put all six DB-backed tests in
`test_dashboard_service.py` because that file already has the
`_seed_org_firm` / `_add_invoice` ORM helpers; `test_int12` is a
type-alias-only file with no DB fixtures.
- **Fixed by:** added tests to `backend/tests/test_dashboard_service.py`;
  extended `_add_invoice` with a `gst_amount` param (default 0) so GST KPIs
  can be asserted.
- **Why not caught in planning:** minor; the plan left the choice open.
- **Impact on later tasks:** none.

### 2. "finalize moves KPIs" test uses a direct ORM status flip
Plan suggested driving `sales_service.finalize_invoice`. Used a direct ORM
update DRAFT→FINALIZED instead to keep the test a focused unit of the KPI
filter without coupling to the full finalize/posting flow (which other
suites already cover).
- **Fixed by:** `test_finalized_invoice_moves_sales_kpis` flips status +
  `clear_cache()`.
- **Impact on later tasks:** none.

## Things the plan got right (no deviation)

- Root cause file:line was exact (`_NON_CANCELLED_LIFECYCLES`, lines 144–148).
- `_BILLED_LIFECYCLES` must include PAID (unlike `_OPEN_AR_LIFECYCLES`) — the
  PAID/PARTIALLY_PAID regression guard confirms it.
- No other users of `_NON_CANCELLED_LIFECYCLES` (grep-verified before removal).
- No migration; KPIs are computed live so no data repair needed.

## Open flags carried over

- Semantics note (Ask-vs-Decide): "sales" is now defined as FINALIZED+ .
  If Moiz ever wants a "pipeline incl. drafts" figure, that is a *new* KPI,
  not a change to these three. This is a pure bugfix — no gate blocks merge.
- FE "+0.0% vs prev" hardcoded delta is out of scope (separate cosmetic issue).

## Observable state at end of task

- Nothing new in the dev env. Test DB `test_196` already at head; no migration applied.
