# TASK-203 retro — GRN receipt posts no GL → mid-cycle BS understates inventory; ledger 1300 goes negative

**Date:** 2026-09-03
**Branch:** fix/issue-203
**Commit:** `<pending merge>` (PENDING MOIZ + CA SIGN-OFF — do not merge)
**Plan:** GitHub issue #203 comment (Option A — perpetual inventory / GRNI clearing)

## Summary

Implemented Option A (perpetual inventory with a GRN/Invoice clearing accrual).
`receive_grn` now posts a balanced `GRN_ACCRUAL` voucher (DR 1300 Inventory /
CR 2010 GRN Clearing) at goods-receipt time, so received-but-unbilled stock
reaches the Trial Balance / Balance Sheet and ledger 1300 no longer drifts to
an impossible credit balance when adjustments / COGS credit it at cost.
`post_purchase_invoice_to_gl` clears the accrual for GRN-linked PIs (DR 2010 +
DR/CR 5360 PPV / DR 1400 ITC / CR 2000 AP) instead of re-debiting 1300; direct
PIs (no `grn_id`) and legacy pre-#203 GRNs (no accrual voucher) keep the old
DR-1300 shape via a fall-through. `post_pi` rejects a second POSTED PI against
the same GRN. Migration `203_grn_accrual` (down_revision `199_invoice_cancel`)
adds the enum value, seeds ledgers 2010/5360 for existing orgs, and builds the
`uq_voucher_grn_accrual` partial-unique index. A separate operator catch-up
script backfills accruals for already-received, not-yet-invoiced GRNs.

Verification: `ruff check` + `ruff format` clean on all changed files; `mypy`
clean on the 5 changed modules; migration up/down clean on `test_203`. Tests:
new `test_grn_accrual_gl.py` 11/11 pass; regression set (test_grn_service,
test_grn_routers, test_pi_service, test_pi_routers, test_accounting_service,
test_cogs_on_sale, test_stock_adjustment_service/routers, test_reports_*,
test_purchase_order_service, test_seed_service, test_coa_service,
test_sales_invoice_cancel, test_banking_service) all green.

**GATED — accounting-model choice + money/GL + schema = PENDING MOIZ + CA
SIGN-OFF.** Fully implemented and tested on `fix/issue-203`; NOT merged.

## Deviations from plan

### 1. Migration needed an autocommit block for the enum value
Plan §4 modelled the enum ADD VALUE on `cogs_sale_voucher_type` (which only
adds the value and backfills, never uses it in the same migration). This
migration also builds an index whose predicate references `'GRN_ACCRUAL'`, so
Postgres rejected it ("New enum values must be committed before they can be
used").
- **Fixed by:** wrapping the `ALTER TYPE … ADD VALUE` in
  `op.get_context().autocommit_block()` so it commits before the index build
  (`alembic/versions/2026090300004_203_grn_accrual.py`).
- **Why not caught in planning:** the prior enum migrations never used the new
  value in the same revision, so the constraint didn't surface there.
- **Impact on later tasks:** none.

### 2. GRN service test fixture had to seed the COA
Plan §5 said "keep `test_grn_service.py` green". Because `receive_grn` now
touches the GL, its tests failed with "System ledger '1300' missing" — the
fixture never seeded the COA (previously unnecessary).
- **Fixed by:** adding `seed_service.seed_coa(...)` to the `grn_setup` fixture
  (mirrors production, where signup seeds the COA). Idempotent.
- **Why not caught in planning:** the plan noted the file must stay green but
  didn't anticipate the fixture gap.
- **Impact on later tasks:** none — any future test that receives a GRN must
  seed the COA (as production always has it).

### 3. PPV (5360) parented under COGS, not EXPENSE
Plan §3.3 gave `("5360", …, "EXPENSE", "EXPENSE", …)` with a note to parent
under `"COGS"` if #198's COGS group already exists. It does (in
`_SYSTEM_COA_GROUPS`), and 5350 Inventory Adjustment already parents under
COGS, so 5360 was parented under COGS for consistency.
- **Impact on later tasks:** coordinate with #198 only if it reorganises the
  COGS group; the P&L already buckets on group_type.

## Things the plan got right (no deviation)

- `reverse_purchase_invoice_gl` mirrors whatever lines exist, so PI-void
  reverses the new GRNI/PPV shape and reopens 2010 with zero code change —
  confirmed by `test_void_pi_reopens_grni`.
- Clearing the accrual against `voucher.total_debit` (not a recomputation)
  keeps rounding from unbalancing the PI voucher.
- The legacy fall-through (GRN-linked PI with no live accrual → old DR-1300)
  keeps in-flight pre-migration cycles closing correctly.
- Reports needed zero changes — TB/P&L/BS pick up 2010/5360 via their groups.

## Open flags carried over

- **Ask-vs-Decide gate:** the accounting-model choice, money/GL postings, and
  schema change all need Moiz + CA sign-off before merge. Do not merge
  `fix/issue-203` until recorded.
- **Catch-up for existing books:** `scripts/backfill_grn_accruals.py`
  (dry-run default) posts accruals for ACKNOWLEDGED GRNs with no posted PI.
  Moiz runs it after CA sign-off; review the dry-run and reconcile 1300 to
  stock valuation per org. Residual gaps = historical adjustment/COGS
  asymmetry → a one-time reclass JV (1300 ↔ 5350) with CA approval.
- **#190 race:** the accrual sits inside the existing GRN row lock; the
  `uq_voucher_grn_accrual` index caps any residual race at "second receive
  409s" rather than a double voucher. The stock double-post itself remains
  #190's scope.
- **#200:** this implements only the one-PI-per-GRN guard; the rest of the
  3-way match stays in #200. Cross-link in both PRs.
- **WAC cost basis unchanged (DEBT-01):** the accrual uses the GRN line rate,
  identical to what `add_stock` feeds the moving average.

## Observable state at end of task

- New ledgers per org after migration: **2010 GRN Clearing (GRNI)** (LIABILITY)
  and **5360 Purchase Price Variance** (COGS).
- New voucher type **GRN_ACCRUAL** (series "GRNI").
- Migration head on `test_203` is `203_grn_accrual`.
- New reference_type on vouchers: `"GRN"` (GRN accrual reference_id = grn_id).
