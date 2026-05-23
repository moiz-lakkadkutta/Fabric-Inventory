# TASK-TR-A11 retro — MO completion with WIP settlement + GL

**Date:** 2026-05-23
**Branch:** task/tr-a11-mo-complete
**Commit:** `<sha>` (DRAFT PR open, awaiting team-lead review)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (TASK-TR-A11)

## Summary

Shipped the terminal money-touching step in the Manufacturing
pipeline: a fresh `mo_completion_service.complete_mo_with_settlement`
that drains an MO's WIP cost pool into finished-goods inventory and
posts a balanced GL voucher (DR 1300 Inventory / CR 1310
Work-in-Process). The router endpoint
`POST /manufacturing/mo/{id}/complete` was rewritten — it now requires
a `MoCompleteRequest` body (`firm_id`, `produced_qty`, optional
`narration` / `series`) and is no longer the skinny state-machine flip
A05 shipped.

A06's WIP debit (`material_issue` → DR WIP) is exactly mirrored: the
completion voucher CRs WIP for the full pool. Net effect: the firm's
1310 net balance returns to its pre-issue value (locked in by
`test_wip_balance_zero_outs_after_completion`). The finished item
lands at the firm's MAIN warehouse with `unit_cost = cost_pool /
produced_qty`, flowing through the same
`inventory_service.add_stock` weighted-average path A06 uses for raw
receipts.

15 new tests in `tests/test_mo_completion.py`. All green first run. 7
pre-existing tests in `test_mo.py` / `test_material_issue.py` needed
narrow updates because they drove the old skinny `/complete` — the
state-machine ones now stop at IN_PROGRESS (the money-touching
transitions are covered in the A11 module).

OpenAPI snapshot regenerated (116 paths unchanged — the `MoCompleteRequest`
schema is in-place additive); `pnpm gen:types` ran clean.

## Cost roll-up algorithm

Per-unit cost on finished goods is computed at completion time:

  ```
  cost_pool      = sum(voucher_line.amount) over POSTED material_issue
                   vouchers' DR WIP lines for this MO
  unit_cost      = cost_pool / produced_qty       (NUMERIC(15,6))
  voucher_post   = DR 1300 Inventory  cost_pool
                 = CR 1310 WIP        cost_pool
  fg_stock_add   = add_stock(item=finished, qty=produced_qty,
                             unit_cost=unit_cost, ref=MO)
  mo.cost_pool   = 0          # drained
  ```

`unit_cost` is on the `NUMERIC(15,6)` grid (same precision as
`stock_ledger.unit_cost`), so a `1000 / 95 = 10.526316`-style figure
keeps 6 d.p. of precision. The GL voucher itself stays on the
`NUMERIC(18,2)` grid — money rounding happens only at the voucher
layer, never on the per-unit cost.

## REWORK readback gap — A10 carry-over

The plan explicitly flagged this: A10 stores `qty_rework` on the
`QC_RESULT_RECORDED.payload` (no column). For the loss-breakdown
aggregator in `_aggregate_loss_breakdown` this means a two-step read:

  1. SQL aggregate `qty_rejected / qty_byproduct / qty_wastage`
     across all (column-side) ops in one query.
  2. For each QC op on the MO, walk to the latest
     `QC_RESULT_RECORDED` event (sorted by `occurred_at DESC,
     created_at DESC`) and pull `payload["qty_rework"]` (stored as a
     string per A10). Sum across QC ops.

Critically, A11's actual MO-state gate refuses completion if ANY op is
in REWORK state (not just non-CLOSED) — so in the happy path the
`rework_qty` aggregate is always 0 when settlement runs. The
event-payload walk is therefore defensive: if a future code path
somehow records `qty_rework > 0` and lets the op transition to
CLOSED, the aggregator surfaces it and the settlement refuses with a
422 ("aggregated rework_qty=... must be fully cycled before
completion"). That belt-and-braces matters because the cost-pool
denominator is `produced_qty`; unrecorded rework would silently
inflate the per-unit cost.

If A10-FU ever migrates rework to a column (the followup the A10
retro flagged), this service drops the event-walk loop for a
column-side `SUM(MoOperation.qty_rework)` — the call site stays the
same.

## completion_policy decision — v1 = ALL_OR_NONE only

The schema column carries `completion_policy VARCHAR(50) DEFAULT
'ALL_OR_NONE'` so future PARTIAL / OVER_PRODUCTION values fit
without migration. v1 ships **only** ALL_OR_NONE:

  - `produced_qty MUST equal planned_qty` to the `NUMERIC(15,4)`
    grid (`Decimal.quantize(0.0001)`).
  - Anything else rejects with a 422 that names both quantities.

Why not PARTIAL in v1? Two reasons:

  1. **WIP-side correctness is harder under PARTIAL.** If the MO
     planned 100 units, issued ₹1000 of WIP, but only produced 95
     and abandoned the rest, the remaining ₹50 of WIP is either
     written off (DR Scrap / CR WIP) or carried (rework MO). v1 has
     no UI for either decision; ALL_OR_NONE sidesteps it.
  2. **FE complexity.** The FE A12 "complete MO" dialog already has
     to surface produced_qty + loss breakdown + voucher preview. A
     PARTIAL policy adds "what do we do with the residual?" toggles
     that aren't worth the v1 scope.

ALL_OR_NONE means in practice the operator plans for QC loss
**before** creating the MO (planned_qty = realistic-yield). The
`test_cost_rollup_with_qc_scrap` test demonstrates this: planned_qty
= 95 (not 100), upstream produces 95, QC passes 95 cleanly,
produced_qty = 95.

A future A11-FU can add PARTIAL behind a feature flag without changing
this service's signature — `completion_policy` is already on the MO
header.

## New ledger code? No — reuse existing 1310 / 1300

The plan asked me to confirm we're reusing `1310 Work-in-Process`
correctly and whether new ledger codes are needed for production
variance. Decision: **no new ledger codes in v1**.

  - **1310 Work-in-Process** is exactly the same ledger A06 debits.
    The completion CR is the mirror leg; net balance returns to zero
    per MO. Verified by `test_wip_balance_zero_outs_after_completion`.
  - **1300 Inventory** is the same ledger A06 credits on issue.
    Posting finished-goods DR to it is the same convention every
    accounting textbook uses — FG and raw both live under 1300, and
    the `item.item_type` column (`RAW` vs `FINISHED`) is the lens
    that splits them for valuation reports.
  - **Variance ledger** (the "actual cost ≠ standard cost" residual)
    is **not in v1** because v1 has no standard-cost model. Cost is
    purely roll-up — every rupee of WIP becomes a rupee of FG cost.
    Once a "standard cost" model arrives (likely B-something), a
    `5310 Production Variance` ledger will be needed. Out of scope.

A new `VoucherType.MANUFACTURING_COMPLETION` value was added to the
Postgres enum (forward-only `ALTER TYPE ADD VALUE` in migration
`task_tr_a11_mo_completion`) so the trial-balance drill-down stays
legible (one voucher_type per source doc) and the voucher-number
partition (`(org_id, firm_id, voucher_type, series, number)`) keeps
MO completions cleanly separated from material issues, JVs, sales
invoices etc.

## What broke in pre-existing tests (and why)

7 tests in `test_mo.py` / `test_material_issue.py` previously drove
the skinny `/complete` (no body required). My new endpoint requires
`MoCompleteRequest`, so the no-body POSTs started 422-ing on
Pydantic validation rather than on the state machine. Updates:

  - `test_state_machine_draft_to_closed_happy_path` — was DRAFT →
    RELEASED → IN_PROGRESS → COMPLETED → CLOSED in one shot.
    Trimmed to DRAFT → RELEASED → IN_PROGRESS; the money-touching
    chain lives in `test_mo_completion.py::test_complete_mo_happy_path`.
  - `test_release_required_before_other_transitions` — parametrize
    list trimmed to `[start, close]` (dropped `complete`).
  - `test_cannot_complete_when_not_in_progress` — sends the new body
    so the state-guard fires (not the Pydantic shape guard).
  - `test_create_mo_emits_audit_log_on_each_state_transition` —
    chain trimmed to release + start; the complete/close audit emit
    is locked in by `test_complete_mo_emits_audit_row` in the A11
    module.
  - `test_transition_records_narration_in_audit_log` — parametrize
    list trimmed to release + start; complete's narration pipe-through
    is locked in by `test_complete_mo_happy_path` (we pass narration
    and assert the voucher narration uses it).
  - `test_cannot_issue_against_completed_or_closed_mo` — now drives a
    full issue → ops-close → complete cycle to legitimately land the
    MO in COMPLETED, then runs the original re-issue refusal check.

This is a deliberate contract break, not a deprecation: the A05
skinny `/complete` was a placeholder for the A11 money work; that
work has now arrived.

## A12-FE input (what the FE complete-MO dialog needs)

When A12-FE picks up the FE flow, the dialog needs:

  1. **Operator-claimed produced_qty input** (Decimal, defaults to
     `mo.planned_qty`). FE validates against ALL_OR_NONE locally
     (warns if `produced_qty != planned_qty`).
  2. **Pre-flight loss preview**: hit a new
     `GET /manufacturing/mo/{id}/completion-preview` (not built yet,
     A11-FU) that runs `_aggregate_loss_breakdown` + `_sum_wip_cost_pool`
     read-only and returns:
       - scrap_qty / wastage_qty / byproduct_qty (totals).
       - rework_qty (aggregate from QC events).
       - cost_pool (current WIP debit balance for this MO).
       - estimated_unit_cost (cost_pool / claimed produced_qty).
     Dialog shows this so operator sees the voucher preview before
     committing. **Flagged in A12-FE: this preview endpoint is the
     A11 followup most likely to be next.**
  3. **Hard blockers surfaced inline**, not in the failure toast:
       - any non-CLOSED op (link to per-op state).
       - REWORK QC (link to the rework workflow).
       - cost_pool == 0 (link to "issue materials first").
  4. **Idempotency-Key auto-generation** per dialog open. Replay-safe
     by router contract.

## Deviations from plan

  - **Plan said "Replace or augment ``POST /manufacturing/mo/{mo_id}/complete``"**
    — chose to REPLACE outright (with backwards-incompatible body
    shape). Rationale: making it body-optional would hide the
    money-touching nature of the new endpoint and let stale callers
    silently 422 with a Pydantic shape error rather than the
    state-machine reason. A deliberate break beats a soft deprecation
    for a money-touching surface.
  - **Plan said "RBAC: reuse `manufacturing.mo.write` if it exists, OR add
    `manufacturing.mo.complete` if a finer split makes sense"**.
    Decision: reuse `manufacturing.mo.write` — the existing slug
    already covers create / release / start / complete / close per
    its description string. A `manufacturing.mo.complete` split would
    only matter if an org wanted to separate "factory operator can
    drive ops + complete" from "factory manager can release / close"
    — that's a workflow split not warranting a new permission today.
    Flagged for review.
  - **Plan asked for "OperationMaster — verify enum has QC, document gap
    if not"** — verified (A10 already shipped it). Used in the
    loss-breakdown query.

## Open flags for Moiz / team-lead review (DRAFT PR)

  1. **VoucherType enum extension is forward-only.** The new
     `MANUFACTURING_COMPLETION` value cannot be removed via downgrade
     (Postgres restriction). Harmless if A11 is rolled back: no rows
     would reference the value post-rollback. Same caveat as A06's
     `MATERIAL_ISSUE`.
  2. **`mo.scrap_qty` semantics.** The schema column reads as
     "scrap quantity". A11 writes `rejected + wastage` to it,
     keeping byproduct on its own column. If the schema docs intend
     scrap = rejected only and wastage separately, this needs a
     second column (`mo.wastage_qty`) and a migration. The
     loss-breakdown helper already keeps them separate internally so
     either decision is one-line in the writer.
  3. **Finished-goods location.** v1 lands FG at the firm's MAIN
     warehouse (same `get_or_create_default_location` A06 uses for
     outbound issue). A future multi-warehouse setup needs a per-MO
     "where do FG land" field — could be on the MO header (new
     column) or default at firm-level via a feature flag. Not v1.
  4. **`completion_policy` PARTIAL.** v1 ALL_OR_NONE only (see
     decision above). Confirm Moiz is OK with the operator-plans-
     for-loss model.
  5. **Production variance ledger.** No `5310 Production Variance`
     today; cost rolls through 1:1. Variance only matters with a
     standard-cost model, which we don't have. Confirm OK.
  6. **Migration is co-existing with A08-FU on a sibling head.** The
     DB I tested against is per-task (`fabric_erp_tra11_test`);
     A08-FU's `task_tr_a08_fu_itemids` migration shares my
     `task_tr_a07_polish` parent. On merge, alembic will see two
     heads — the team-lead will need to either land A08-FU first
     (and rebase A11 to depend on it) or land A11 first and rebase
     A08-FU. The migrations don't touch overlapping tables so
     ordering is interchangeable.

## Pre-A12-FE checklist

  - [ ] Decide whether `manufacturing.mo.complete` deserves its own
        permission slug (currently `manufacturing.mo.write` covers it).
  - [ ] Build the `GET /manufacturing/mo/{id}/completion-preview`
        endpoint (A11-FU) so the FE dialog can surface the cost +
        loss preview before committing.
  - [ ] Sign off on `mo.scrap_qty` carrying rejected + wastage vs.
        adding a separate `wastage_qty` column.
  - [ ] Decide PARTIAL completion policy scope (now / next-task /
        post-MVP).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
