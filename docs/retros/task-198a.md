# TASK-198a retro — P&L COGS grouping (report fix)

**Date:** 2026-09-03
**Branch:** fix/issue-198
**Commit:** `<sha>` (NOT merged — PENDING MOIZ + CA SIGN-OFF)
**Plan:** GitHub issue #198 comment (Part 1)

## Summary

Created a dedicated `COGS` COA group and re-parented ledgers `5000 Cost of
Goods Sold` and `5350 Inventory Adjustment` into it, so `reports_service.
compute_pnl` (which already buckets by `CoaGroup.group_type` and knows a COGS
type) populates `cogs` / `gross_profit` and stops lumping 5000/5350 into
EXPENSE. A net inventory-adjustment gain (CR 5350) now reduces COGS instead of
rendering as a negative expense, so `net_profit` no longer exceeds
`total_income`. `seed_service._SYSTEM_COA_GROUPS` gains the COGS group; the two
ledgers' `parent_group_code` moves from EXPENSE to COGS; `schemas/accounting.
CoaGroupType` Literal gains `"COGS"`. A data-only Alembic migration
(`198a_cogs_coa_group`) backfills existing orgs. No `compute_pnl` code change
was needed. Lint, format, mypy, and targeted + broad tests all pass; migration
up/down/up is clean. NOT merged — money/GL + report semantics gate.

## Deviations from plan

### 1. Plan cited line numbers from `main`; worktree is based on integration
Plan referenced e.g. `post_cogs_voucher` voucher_date at line 303; in this
worktree (post #190/#192 merges) it was line 325. No behavioral impact — the
grounded design held.
- **Fixed by:** located the actual lines; logic unchanged.
- **Why not caught in planning:** plan was grounded on `main`, branch carries later merges.
- **Impact on later tasks:** none.

## Things the plan got right (no deviation)

- `compute_pnl` needed zero code change — `_PNL_GROUP_TYPES` already included COGS.
- TB is unaffected (groups by ledger, not COA group) — asserted in a test.
- `test_seed_service.py` derives its group-count assertion from
  `_SYSTEM_COA_GROUPS` dynamically, so adding the group didn't break it.

## Open flags carried over

- **Ask-vs-Decide (Moiz + CA):** (1) COGS group membership — recommended
  moving 5350 into COGS too (implemented); CA may prefer 5350 stays in EXPENSE
  (then drop '5350' from the migration + seed). (2) No historical repair of
  mis-dated legacy COGS vouchers (fix-forward). Both must be signed off before merge.
- Frontend `types/api.ts` `group_type` union is generated and still lists only
  the 5 old values; `frontend/src/lib/queries/reports.ts` already handles
  `group_type === 'COGS'` functionally. Regenerate the OpenAPI types in a
  frontend pass (out of scope for this backend fix).

## Observable state at end of task

- Migration `198a_cogs_coa_group` applied to test DB `test_198`.
- New test file `backend/tests/test_reports_pnl_cogs.py`.
