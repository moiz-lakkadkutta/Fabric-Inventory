# TASK-197 retro — AR ageing: backdated as_of + due-date buckets

**Date:** 2026-09-02
**Branch:** fix/issue-197
**Commit:** `<pending>` (NOT merged — pending Moiz sign-off on report semantics)
**Plan:** GitHub issue #197 comment (implementation plan)

## Summary

Fixed two correctness bugs in `reports_service.compute_ageing`. (a) A backdated
`as_of` previously used the live `paid_amount`, so receipts posted *after* the
cutoff were deducted from the historical snapshot and fully-paid invoices
vanished (PAID was excluded from the lifecycle filter) — QA saw ₹525 instead of
₹110,775. Now the outstanding balance is reconstructed as-of the report date
from receipt allocations whose voucher_date ≤ as_of, and the lifecycle filter
includes PAID (a PAID-today invoice nets to 0 at as_of=today, so today's output
is unchanged). (b) Buckets aged from `invoice_date`, so credit-terms customers
looked delinquent immediately; buckets now age from days past `due_date`
(falling back to `invoice_date` when null), matching the `overdue_ar` KPI.
Service-layer only; no migration. Lint (ruff), format, and mypy pass on changed
files; 13/13 ageing tests and 40/40 across the broader reports + AR-recon +
seed-demo suites pass.

## Ask-vs-Decide gate

Report semantics on money data — **PENDING MOIZ SIGN-OFF** (no CA needed; no
posting/tax change). Implemented the plan's recommended defaults:
1. Backdated `as_of` → **reconstruct paid-as-of from receipt allocations ≤
   as_of** (option A), not reject it. Data model supports it; CAs pulling
   31-March numbers is a real use case.
2. Bucket basis → **days past due_date**, fall back to invoice_date when null,
   "current" = not yet due.
Both are the chosen semantics for Moiz to confirm before merge.

## Deviations from plan

### 1. `compute_ar_reconciliation` left untouched (as the plan instructed)
No deviation in outcome, but worth stating: the parity test
(`test_as_of_today_matches_live_paid_amount`) confirms `compute_ageing(as_of=
today).total == compute_ar_reconciliation.ageing_total`, so the two cannot
drift. Recon stays a live snapshot by design.

### 2. Widened lifecycle via a new tuple, not by editing `_AGEING_OPEN_LIFECYCLE`
Added `_AGEING_BILLED_LIFECYCLE` (adds PAID) used only by `compute_ageing`;
`compute_ar_reconciliation` keeps `_AGEING_OPEN_LIFECYCLE`. Keeps the recon's
scope explicit and avoids a spooky-action-at-a-distance shared constant.

## Things the plan got right (no deviation)

- Root cause file:line were exact (compute_ageing 863–946; the paid_amount and
  lifecycle-filter interaction).
- The paid-as-of subquery shape (RECEIPT + POSTED + not-reversed + not-deleted +
  voucher_date ≤ as_of, grouped by sales_invoice_id) was correct as written.
- Advance receipts create no `payment_allocation` row, so the join naturally
  excludes them — verified by `test_unallocated_advance_does_not_reduce_ageing`.
- AP payments stay out (they carry `sales_invoice_id NULL` + non-RECEIPT type).

## Open flags carried over

- **#199 (invoice cancel):** once a `cancelled_at` column exists, decide whether
  a CANCELLED invoice should still appear in ageing for `as_of < cancelled_at`.
  Until then a cancelled invoice disappears from all historical ageing (current
  behavior preserved). Left as a known limitation, not a TODO in code.
- **Unallocated customer advances (ledger 2500)** intentionally do not reduce
  ageing (tracked separately as P2-6).
- **OpenAPI spec drift:** `specs/api-phase1.yaml` still lists the `as_on_date`
  query param and `reports.ageing.read` permission; the live endpoint uses
  `as_of` and `accounting.report.view`. I only added the bucket-basis
  description; the param/permission drift predates this task.

## Observable state at end of task

- No migration; nothing stored (ageing is computed at request time).
- FE Ageing tab needs no change (generic bucket column labels), but the
  bucket-basis change will visibly shift customers between columns — one-time
  visual change to call out in the PR.
