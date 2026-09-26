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

## CA-review correction (2026-09-26)

**What was wrong.** A GRN-linked PI cleared the WHOLE GRN accrual (DR 2010 =
accrual total) and booked `PI net − full accrual` to 5360 PPV. Billing fewer
units than received therefore booked the unbilled goods as a false PPV gain
(100 m received @ ₹200, bill 80 m @ ₹200 → CR 5360 ₹4,000), and the
one-POSTED-PI-per-GRN guard made the remaining 20 m unbillable forever.

**What changed.**
- A GRN-linked PI clears 2010 only for the qty it **bills**: DR 2010 =
  Σ(billed qty × GRN rate). PPV = PI net − that amount (DR if dearer, CR if
  cheaper). Unbilled qty stays accrued in 2010 for a later bill.
- Several POSTED PIs may bill one GRN. Cumulative billed qty per item across
  the GRN's live PIs may never exceed received qty: checked at `create_pi`
  (conservatively counting open DRAFTs too) and authoritatively at `post_pi`
  (POSTED/RECONCILED only; VOIDED excluded) under `SELECT … FOR UPDATE` on the
  GRN row, then the PI row (lock order GRN → PI → Firm; `void_pi` takes the
  same order). The one-PI-per-GRN guard is removed.
- **Line matching.** PI lines carry no GRN-line reference, so they match by
  item. An item on several GRN lines clears at its **weighted-average GRN
  rate** (Σ qty×rate / Σ qty). Chosen over FIFO because it is
  order-independent: void-and-rebill always clears the same value, so a void
  can never mis-allocate 2010 between GRN lines.
- **Rounding.** Each clearing is quantized to the paisa (ROUND_HALF_UP) and
  capped at the GRN's open 2010 balance read from the GL. The PI that completes
  the GRN clears the open balance exactly, so paisa residue never strands in
  2010 (e.g. 3 × ₹33.3333 accrues ₹100.00 → clears 33.33 + 33.33 + 33.34).
- **Void** mirrors every leg of the PI voucher, so it re-opens exactly what the
  PI cleared; its qty is billable again.
- The loose amount-drift warning now compares the PI against the GRN value of
  the qty it bills (a legitimate partial bill is not drift).
- Direct PIs and legacy GRNs without an accrual voucher are unchanged.
- `scripts/backfill_grn_accruals.py` needs no logic change (documented why:
  all-or-nothing per GRN; a partially-billed legacy GRN keeps the legacy
  DR-1300 path).

**Basis.** Standard GRNI / accrued-purchases practice (Ind AS 2 cost of
inventories; accrual basis under Ind AS 1 / AS 1): the GRNI liability equals
goods received but not yet invoiced, and a purchase price variance only arises
on quantity actually invoiced at a price different from the receipt cost.

**Verifier follow-ups (same day).**
- **Zero-value PI (free goods).** A ₹0 GRN-linked PI still consumes billable
  qty, so it clears that qty's accrual: DR 2010 / CR 5360 (favourable PPV),
  no AP leg. Previously it returned before posting any voucher, stranding the
  balance in 2010 while the qty cap refused every further PI. Void reverses
  it like any PI voucher. A ₹0 PI with nothing to clear (direct, or GRN
  without an accrual) still posts no voucher.
- **Same firm, same supplier.** `create_pi` (and `post_pi`, for older drafts)
  refuse a GRN from another firm or another supplier (422). Before, a PI in
  firm B could clear firm A's GRNI in firm B's books.
- **Void with a soft-deleted GRN.** `void_pi` locks the GRN without the
  soft-delete filter (still org-scoped), so a legacy PI whose GRN was later
  soft-deleted can still be voided.
- **Rounding aligned.** The GRN accrual (and the backfill preview) now round
  ROUND_HALF_UP, the same as the PI-side clearing and Postgres NUMERIC. They
  used to be HALF_EVEN vs HALF_UP; the final bill's true-up absorbed the
  difference, but they now agree.

**Legacy data: GRNs short-billed under the earlier #203 code.** That code
cleared the FULL accrual on the first PI and booked the unbilled value as a
false CR 5360 gain. Such a GRN can now take a second PI for the unbilled qty.
It finds 2010 already at 0, so it clears ₹0 and books its full net as DR 5360,
which reverses the earlier false gain. The CA should see these GRNs. This
read-only query lists them (checked against a simulated case):

```sql
-- Read-only. GRNs with a live #203 accrual that are still short-billed
-- (live POSTED/RECONCILED PIs bill less than received) yet whose GRN Clearing
-- (2010) is already 0 — i.e. short-billed under the pre-correction #203 code,
-- which cleared the FULL accrual and booked the unbilled value as a false
-- PPV (5360) gain. Run with a role that bypasses RLS, or per org with
-- app.current_org_id set.
WITH recv AS (
    SELECT g.org_id, g.firm_id, g.grn_id, g.series, g.number, g.grn_date,
           SUM(gl.qty_received) AS received_qty,
           SUM(gl.qty_received * COALESCE(gl.rate, 0)) AS received_value
    FROM grn g
    JOIN grn_line gl ON gl.grn_id = g.grn_id AND gl.deleted_at IS NULL
    WHERE g.deleted_at IS NULL AND g.status = 'ACKNOWLEDGED'
    GROUP BY g.org_id, g.firm_id, g.grn_id, g.series, g.number, g.grn_date
),
billed AS (
    SELECT p.grn_id, SUM(pl.qty) AS billed_qty
    FROM purchase_invoice p
    JOIN pi_line pl ON pl.purchase_invoice_id = p.purchase_invoice_id
                   AND pl.deleted_at IS NULL
    WHERE p.grn_id IS NOT NULL AND p.deleted_at IS NULL
      AND p.status IN ('POSTED', 'RECONCILED')
    GROUP BY p.grn_id
),
grni AS (
    SELECT r.grn_id,
           SUM(CASE WHEN vl.line_type = 'CR' THEN vl.amount ELSE -vl.amount END)
               AS open_2010
    FROM recv r
    JOIN voucher v
      ON v.org_id = r.org_id AND v.deleted_at IS NULL
     AND (   (v.voucher_type = 'GRN_ACCRUAL' AND v.reference_id = r.grn_id)
          OR (v.voucher_type = 'PURCHASE_INVOICE' AND v.reference_id IN (
                SELECT p.purchase_invoice_id FROM purchase_invoice p
                WHERE p.grn_id = r.grn_id)))
    JOIN voucher_line vl ON vl.voucher_id = v.voucher_id
    JOIN ledger l ON l.ledger_id = vl.ledger_id AND l.code = '2010'
    GROUP BY r.grn_id
)
SELECT r.org_id, r.firm_id, r.grn_id, r.series || '/' || r.number AS grn_no,
       r.grn_date, r.received_qty, COALESCE(b.billed_qty, 0) AS billed_qty,
       r.received_qty - COALESCE(b.billed_qty, 0) AS unbilled_qty,
       r.received_value, g.open_2010
FROM recv r
JOIN grni g ON g.grn_id = r.grn_id
LEFT JOIN billed b ON b.grn_id = r.grn_id
WHERE EXISTS (SELECT 1 FROM voucher v
              WHERE v.org_id = r.org_id AND v.voucher_type = 'GRN_ACCRUAL'
                AND v.reference_id = r.grn_id AND v.deleted_at IS NULL)
  AND COALESCE(b.billed_qty, 0) < r.received_qty
  AND g.open_2010 = 0
ORDER BY r.org_id, r.grn_date, grn_no;
```

**Open CA question (unchanged here).** PIs carry no separate freight / other
charges fields; any freight billed inside line rates lands in 5360 PPV as price
variance, as before.

PENDING MOIZ + CA SIGN-OFF.
