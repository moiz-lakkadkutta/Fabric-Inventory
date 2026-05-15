# TASK-TR-E06a retro — migration commit posts OB imbalance to suspense ledger

**Date:** 2026-05-14
**Branch:** task/tr-e06a-ob-suspense
**Commit:** `<sha>` (PR open, not merged — money-touching, awaiting Moiz review)
**Plan:** `docs/implementation-plan-trial.md` (Wave 0)

## Summary

Fixes the P0 blocker found by TASK-TR-E06: the migration commit step required party
opening balances to self-balance (DR == CR) and rejected anything else with a 422 —
but a Vyapar parties-only export *never* self-balances, because the firm's
capital/cash/stock live in other sheets we don't ingest in v1. Every realistic
customer migration would have hit this wall. The fix adds a seeded
`3200 Opening Balance Difference` suspense ledger; `_post_opening_balance_voucher`
now posts one balancing line to it for the DR/CR gap, so the OB voucher is always
internally balanced. The parked amount is surfaced as a `warn`-severity
`OB_DIFFERENCE_PARKED` row in the reconciliation report the FE preview pane renders;
`tb_reconciles` stays `False` (honest — the *source* didn't reconcile). Lint (ruff
+ format), typecheck (mypy), and the migration + seed + COA test suites (48 tests)
all pass. TDD: the new integration test was written first and confirmed RED (422)
before the implementation.

## Deviations from plan

### 1. Root cause was a deliberately-balanced test fixture
Plan framed E06a as "the commit refuses imbalanced input." Reality: the existing
`tests/fixtures/vyapar-sample.xlsx` fixture was hand-crafted to self-balance
(DR == CR == 23500.50), which is *why* the original tests passed and the bug never
surfaced — the fixture didn't represent a real Vyapar export.
- **Fixed by:** left the balanced fixture + its tests as-is (a balanced source is a
  valid edge case — it just adds no suspense line), and added
  `test_approve_unbalanced_obs_parks_to_suspense` which generates a *realistic*
  unbalanced export in-test with openpyxl.
- **Why not caught in planning:** the plan trusted "tests exist" without checking the
  fixture was representative.
- **Impact on later tasks:** none. Worth a general lesson — migration fixtures must
  mirror real source shapes, not idealised ones.

## Things the plan got right (no deviation)

- The suspense-ledger approach (Moiz's call in the grill-me follow-up) was exactly
  right — standard Tally/Vyapar "Difference in Opening Balances" practice, minimal code.
- `CAPITAL` ledger code `3000` was already mapped in `_LEDGER_CODE_FOR_KIND`, confirming
  the COA infrastructure was ready; adding `3200` followed the `3100` pattern verbatim.
- Seed tests derive expectations from `len(_SYSTEM_LEDGERS)` — adding a ledger didn't
  break a single hardcoded count.

## Pre-TASK-TR-E06b / next-task checklist

### 1. Existing dev/test orgs seeded before this change lack ledger `3200`
A migration commit for such an org raises a clear "System ledger '3200' missing"
error. Fresh signups (all real customers, all test orgs created via `_signup`) get it
automatically. If Moiz's dogfooding org predates this, re-seed it or use a fresh org.

### 2. The balanced fixture `vyapar-sample.xlsx` is still unrealistic
Not load-bearing for E06a, but if a future task touches migration tests, consider
replacing it with a realistic (unbalanced) fixture or in-test generation.

## Open flags carried over

- **No firm-level OB import** (cash/capital/bank from Vyapar's other sheets) — still
  out of v1 scope per CLAUDE.md #5. The suspense ledger is the deliberate stand-in;
  the accountant reclassifies post-cutover. Resurfaces if/when a "full cutover"
  migration task is scoped post-trial.

## Observable state at end of task

- New seeded ledger `3200 Opening Balance Difference` (EQUITY) — every new org gets it.
- No Alembic migration — `_SYSTEM_LEDGERS` is application-seeded at signup, not DDL.
- Branch `task/tr-e06a-ob-suspense` has the work; PR open, **not merged** (money-logic
  gate — awaiting Moiz review per the Ask-vs-Decide table).

## Follow-up: orphan-OB Major (review pass)

PR #105 review (2026-05-15) flagged a Major: the `OB_DIFFERENCE_PARKED` warn-row
that `approve()` writes into `reconciliation_json` was sized from the **pre-skip**
`_sum_ob_sides(obs_intermediate)` totals, while the suspense voucher line
`_post_opening_balance_voucher` actually posted was sized from the **post-skip**
totals (the loop drops OB rows whose `party_source_id` isn't in `party_id_by_source`).
These agree under the Vyapar adapter today (its `extract_parties` and
`extract_opening_balances` share a single iterator so parties ⊇ OB parents by
construction), but the `MigrationAdapter` Protocol allows future Tally / generic-
Excel adapters to break that invariant — and the worst-case shape is "every OB
orphaned" → no suspense line + a misleading message claiming N parked + a
zero-line voucher with no DB constraint to stop it.

### Fix

- Added a frozen dataclass `_OpeningVoucherPostResult(voucher_id, parked_amount,
  parked_side)` returned by `_post_opening_balance_voucher`. The voucher loop
  tracks the actually-posted suspense `diff` and `line_type.value` and ships them
  back to `approve()`.
- `approve()` now reads `post_result.parked_amount` / `post_result.parked_side`
  for both the conditional (`if parked_amount > 0`) and the warn-row text. The
  pre-skip `dr_total` / `cr_total` are still computed (kept on `CommitResult.tb_*`
  for the audit trail and consumed by callers) but no longer drive the warn-row.
- Corrected the misleading "(Validate flagged this.)" aside in the orphan-skip
  comment — Vyapar's `validate()` does NOT flag orphan OBs (its iterator-shared
  construction makes them impossible). Replaced with a note explaining the
  empty-name skip + the Protocol's looser future-adapter contract.

### TDD

New test `test_approve_uses_actually_posted_amount_for_parked_warn_row` in
`tests/test_migrations_router.py` constructs a `_DivergentOrphanAdapter` stub
that diverges from `extract_parties` to `extract_opening_balances` (1 valid
party + 2 balanced OBs on it + 1 orphan OB referencing PARTY-MISSING). Pre-skip
sums DR=55000 CR=5000 (gap 50000); post-skip sums DR=5000 CR=5000 (gap 0). The
test asserts no `OB_DIFFERENCE_PARKED` row is written and no `3200` line is
posted. RED before the fix (warn-row claimed "50000 CR parked" while the books
carried zero parked), GREEN after.

### Test count

- Before: 16 migration tests (8 router + 7 protocol + 1 smoke).
- After: 17 migration tests (9 router + 7 protocol + 1 smoke). Full suite 831 / 831.

### Out of scope (deferred)

- Audit field for the parked amount on `user_migration` (separate task).
- Idempotent-re-approve test for an unbalanced source (separate task).
- Replacing the hand-balanced `vyapar-sample.xlsx` fixture (still tracked above).
