# TASK-INT-12 retro — dashboard KPIs + QA doc rewrite (P1-8 + cross-cutting)

**Date:** 2026-05-06
**Branch:** `task/INT-12-activity-kpis-docs`
**Plan:** in-conversation `/grill-me` master plan, INT-12 section.

## Summary

Last branch in the post-QA stabilization sweep. Two visible deliverables:

1. **Dashboard KPI rewrite** (P1-8). Drop `low_stock_skus` and
   `supplier_ap` (mock-only — always ₹0 in live mode). Add
   `gst_collected_mtd` — what textile firms actually watch for GSTR-3B
   liability planning. Net 5 cards instead of 6 with two zeros.

2. **QA doc rewrite** (cross-cutting). `qa-manual-test.md` updated to
   reflect every INT-7…INT-12 contract change: unversioned API paths,
   canonical envelope on validation 422s, per-org email model, inter-
   state always IGST, 5-card dashboard, fabric_app runtime role.
   Section headers explain the WHY of each change so future testers
   don't re-discover the same bugs.

3 new tests in `test_int12_dashboard_kpis.py` + an updated existing
`test_get_kpis_zero_state` to assert the new key set. 586 backend
tests pass; ruff + mypy clean.

## Deliberately deferred (recorded per /grill-me Q8)

### P1-7 — Audit emits across mutating service methods

Plan called for an `audit_service.emit(...)` helper called from every
mutating service (signup, login, logout, invoice.create/finalize/cancel,
receipt.post, party.create, item.create). Each emit writes to
`audit_log` and the activity feed projects from there.

That's a 10-15 service-touch task. Each call site needs a thin
`emit()` wrapper, and each mutation needs a `kind` constant nailed
down. Worth its own branch with proper test coverage per emitter.

Tracked as **TASK-INT-15** (next-up follow-up). Today the activity
feed shows only `auth.session.switch_firm` events — that was
yesterday's QA finding; it stays as-is until INT-15.

### Other cross-cutting docs already landed

- `/v1/*` → unversioned: done in this branch.
- `tax_status: REGISTERED` → `REGULAR`: actually never landed because
  the QA guide didn't have that exact phrase; the enum docstring
  inside `gst_service.py` already documents the right names.
- Cookie name `fabric_refresh_token` → `fabric_refresh`: done
  (sed replace, single occurrence).

## Things the plan got right (no deviation)

- Pure-type-alias test for KPI key set — fastest possible test, fails
  loudly on any future drift, no DB needed.
- `gst_collected_mtd` is a one-function addition that mirrors
  `_sales_in_range` — pattern from existing code, no architectural
  decisions required.
- The QA doc rewrite as a documentation-only landing avoids the
  "documentation drifts" pattern we've seen on past tasks.

## Pre-INT-15 / next-task checklist

### 1. INT-15 (audit emits + activity feed) is the natural next step

Follow-up tasks queued by the stabilization sweep, ordered:
- **TASK-INT-13** — GL split into `2110/2120/2130` ledgers (P2-2,
  GST correctness scope #2).
- **TASK-INT-14** — Bill of Supply trigger for COMPOSITION /
  NIL-rated lines (P2-3, GST correctness scope #3).
- **TASK-INT-15** — Audit emits + activity feed projection (P1-7).
- **TASK-INT-16** — Switch runtime DATABASE_URL to fabric_app
  (deferred from INT-9; ~43 fixture migrations).

### 2. Schedule the CA call before INT-13/INT-14

Per INT-11 retro, GST correctness scope #2 and #3 each touch real
accounting ledgers and document-type rules. CA should validate
before either lands. Comment `# CA-VALIDATED-PENDING: 2026-05-06`
in `gst_service.py` is the breadcrumb.

### 3. Re-run the QA manual top-to-bottom

The whole point of this 5-branch sweep was to make the QA guide
green. Now's the time to actually run the pass and confirm. Open
issues for any remaining FAILs.

## Open flags carried over

- **`fabric_app` runtime cutover (TASK-INT-16)**: still on `fabric`
  (superuser, BYPASSRLS) at runtime. RLS is enforced in tests via
  `test_rls_force.py`, but production still bypasses. Cutover is
  deferred because flipping `DATABASE_URL` surfaces ~43 fixture
  migrations.

- **Activity feed staleness**: until INT-15 lands, the feed shows
  only `auth.session.switch_firm`. Note in the dashboard UI when
  available_firms == 1 to not surface an empty feed.

- **TASK-INT-13 / INT-14**: required before any customer with a
  composition firm OR before the first GSTR-3B filing. Both are
  flagged in `gst_service.py` and called out in INT-11 retro.

## Observable state at end of task

- Modified: `app/service/dashboard_service.py` — drops
  `low_stock_skus`/`supplier_ap` from `KpiKey`, adds
  `gst_collected_mtd` builder + `_gst_collected_in_range` helper.
- Modified: `tests/test_dashboard_service.py` — `test_get_kpis_zero_state`
  asserts the new key set.
- New tests: `tests/test_int12_dashboard_kpis.py` (3 cases).
- Updated: `docs/ops/qa-manual-test.md` — every section's spec/code
  drift fixed; new explanatory header lists which INT-N branch
  produced each change so the doc and the code stay coupled.

## Bringing it home — what the 6-branch sweep delivered

For the record, since this is the last retro:

| Branch | Issues closed | New tests |
|---|---|---|
| INT-7 dev-stack | P0-1, P0-2 | 4 |
| INT-8 envelope | P1-2, P1-9 | 7 |
| INT-9 RLS force | P0-3 | 4 |
| INT-10 auth shape | P1-3, P1-4, P1-5, P3 refresh-key | 6 |
| INT-11 GST correctness | P2-1 (P2-2/P2-3 deferred) | 9 |
| INT-12 KPIs + docs | P1-8, P1-1, P1-6 | 3 |
| **Total** | **15 of 17 QA findings** | **33 new tests** |

Two issues deferred and tracked: P2-2 → INT-13, P2-3 → INT-14, P1-7
→ INT-15. Plus the runtime fabric_app cutover → INT-16.
