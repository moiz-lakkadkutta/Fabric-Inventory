# TASK-200 retro — procure-to-pay 3-way-match guards

**Date:** 2026-09-02
**Branch:** fix/issue-200
**Commit:** `<pending>` (committed to fix/issue-200; NOT merged — see Ask-vs-Decide)
**Plan:** GitHub issue #200 (comment)

## Summary

Closed five holes in the procure-to-pay flow, all service-layer in
`backend/app/service/procurement_service.py`, no schema change:

1. **Unbounded over-receipt** — `create_grn` and `receive_grn` now enforce a
   cumulative cap (received-state GRNs + this GRN ≤ `qty_ordered`, tolerance
   `PO_OVER_RECEIPT_TOLERANCE_PCT = 0`).
2. **PO closing off a DRAFT/soft-deleted GRN** — `_advance_po_status_after_grn`
   now sums via a join to `grn`, filtered to received-state, non-deleted GRNs
   and lines, scoped by `org_id`; it also walks a PO back to CONFIRMED when the
   recomputed sum is zero.
3. **Receive against a CANCELLED PO** — `receive_grn` locks the linked PO row
   (`SELECT ... FOR UPDATE`) and re-checks its status before posting stock.
4. **Cross-PO / item-mismatch GRN lines** — a new `_validate_grn_lines_against_po`
   rejects po_line_ids not on the PO, item mismatches, and po_line_id without a PO.
5. **PI billing more than the GRN received** — `_validate_pi_lines_against_grn`
   hard-blocks quantity over-billing in `create_pi` and (defense-in-depth) in
   `post_pi`; the loose amount-drift warning is unchanged.

Verification: `ruff check` + `ruff format` clean, `mypy` clean on the service.
`pytest` green — the affected files (`test_grn_service`, `test_pi_service`,
`test_purchase_order_service`, `test_grn_routers`, `test_pi_routers`,
`test_concurrency_postings`) = 129 passed, including a real-threads concurrency
test proving the over-receipt cap holds under parallel receives.

## Interaction with #190 (concurrency)

Built ON #190's existing `receive_grn` GRN-row lock — did not remove or
duplicate it. The new PO-row `FOR UPDATE` is taken AFTER the GRN lock, so the
lock order is **GRN → PO** everywhere (documented in code + the OpenAPI receive
description). The double-receive race and the partial-unique posting index stay
#190's scope. Each receive locks its own distinct GRN row first, then contends
on the shared PO row, so no cross-lock deadlock is possible.

## Deviations from plan

### 1. PO-advance tests placed in test_grn_service.py, not test_purchase_order_service.py
Plan listed test file `test_purchase_order_service.py` for the DRAFT/soft-delete
advance tests. PO advancement is driven entirely through the GRN service, and
`test_grn_service.py` already carries the PO-advance fixtures (`_make_confirmed_po`),
so the new tests live there. No behavioural difference.

### 2. Defined the missing `UnprocessableEntity` OpenAPI response component
The spec referenced `#/components/responses/UnprocessableEntity` in 2 pre-existing
places but never defined it (latent invalid-spec bug). Added the definition next
to `Conflict` so my new 422 refs (and the old ones) resolve.

## Things the plan got right (no deviation)

- The five root causes were exact (file:line matched reality on the integration branch).
- `_sum_received_by_po_line` as a shared helper for both advance + cap kept it DRY.
- The amount-drift regression pin (qty match, 2.5x rate → still warns) confirmed
  the freight/surcharge flexibility Moiz asked for is preserved.

## Open flags carried over — Ask-vs-Decide (PENDING MOIZ SIGN-OFF)

1. **Over-receipt tolerance = 0% (hard 422).** `PO_OVER_RECEIPT_TOLERANCE_PCT`
   in `procurement_service.py`. Textile trade sometimes allows small over-supply
   ("+2% fent/rag"); flipping this one constant permits it. Money-adjacent →
   needs Moiz's call. Implemented + tested at 0; do NOT merge to main until signed off.
2. **PI qty over-billing = hard 422; amount drift stays loose.** Matches Moiz's
   recorded "flexibility for rounding/freight/surcharge" for amounts while closing
   the 10x quantity hole. Confirm this split is what he wants.
3. **Direct PIs (`grn_id IS NULL`) and direct GRN lines (`po_line_id IS NULL`)**
   remain unvalidated against a PO — PI↔PO linkage needs a new column (schema),
   explicitly out of scope. Trial-backlog item.

## Observable state at end of task

- **No migration.** All guards are over existing columns.
- **DATA-REPAIR:** `schema/patches/repair-200-po-qty-received-recompute.sql` —
  idempotent recompute of `po_line.qty_received` + `purchase_order.status` for
  QA orgs already holding corrupted POs. Run as `fabric` after the code lands;
  it does NOT rewrite append-only `stock_ledger` (legacy physical over-receipts
  stay as honest history). Detection query at the file's tail must return 0 rows.
- **#202 (lots)** also edits `receive_grn`'s add_stock loop — #200 restructured
  the top of that function (PO lock + validate); expect a trivial rebase there.
