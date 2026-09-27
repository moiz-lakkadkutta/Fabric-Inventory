# TASK-198b retro — COGS voucher dating + DC-linked relief

**Date:** 2026-09-03
**Branch:** fix/issue-198
**Commit:** `<sha>` (NOT merged — PENDING MOIZ + CA SIGN-OFF)
**Plan:** GitHub issue #198 comment (Part 2)

## Summary

Two posting-timing fixes for COGS-on-sale. (1) `accounting_service.
post_cogs_voucher` gains a `voucher_date` param; `sales_service` passes
`invoice.invoice_date` so the COGS_SALE voucher lands in the same fiscal
period as the revenue (previously dated today — a backdated invoice split
revenue and COGS across FYs). (2) DC-linked invoices now post COGS at finalize:
`finalize_invoice` branches — direct invoices use the existing
`_post_cogs_for_invoice`; DC-linked invoices use a new
`_post_cogs_for_dc_invoice`, which reads the DC's outbound `stock_ledger` rows
(reference_type='DC', qty_out>0) for the cost basis and posts a single
COGS_SALE voucher referencing the invoice, WITHOUT decrementing stock again
(the DC already relieved it). A guard rejects finalizing a second invoice on a
DC already claimed by a finalized invoice (InvoiceStateError → 409). The
misleading comment in `issue_dc` and the `COGS_SALE` model docstring were
corrected. No migration (the new param defaults keep old callers valid; only
`sales_service` calls it). Lint, format, mypy, targeted + broad tests pass.
NOT merged — money/GL gate.

## Deviations from plan

### 1. "Two invoices per DC" guard: finalized, not merely existing
Plan said "409 if another non-deleted invoice already references this DC". A
naive existence check fired on the FIRST finalize because two DRAFTs coexist.
- **Fixed by:** guard checks for another invoice with `lifecycle_status != DRAFT`
  (already finalized) linked to the same DC. First to finalize wins; second is rejected.
- **Why not caught in planning:** the plan's phrasing didn't account for two DRAFTs pre-existing.
- **Impact on later tasks:** #199 (cancel) must reverse the DC-linked COGS voucher too — its plan already covers COGS reversal.

### 2. `StockLedger` has no `deleted_at`
It is append-only (no `SoftDeleteMixin`); the plan's example query included a
`deleted_at IS NULL` filter.
- **Fixed by:** dropped that clause; filter is `reference_type='DC' AND qty_out>0`.

## Things the plan got right (no deviation)

- The `post_cogs_voucher` reference-idempotency guard (one COGS_SALE per
  reference_id) makes finalize replay safe — no second locking scheme needed
  (rely on #190's finalize row-lock + partial-unique index).
- Zero-cost DC stock → `post_cogs_voucher` returns None (total <= 0) → no empty voucher.
- SERVICE items on DC-linked invoices are naturally skipped (no DC stock rows).

## Open flags carried over

- **Ask-vs-Decide (Moiz + CA):** COGS voucher dated `invoice_date` enables
  posting into prior FYs when users backdate (same exposure the sales voucher
  already has; period-close is a separate feature). Sign off before merge.
- **Out of scope (noted, unchanged):** direct-invoice lines with no stock
  position still silently skip COGS (DEBT-01 / CA conversation). DCs issued but
  never invoiced leave cost stranded in 1300 — separate product gap.
- DEBT-01 WAC basis unchanged by this work.

## Observable state at end of task

- No schema change. New behavior lives in `sales_service._post_cogs_for_dc_invoice`.
- New tests in `backend/tests/test_cogs_on_sale.py`; the old
  `test_finalize_skips_cogs_when_dc_linked` (asserted the now-removed skip) was
  replaced by `test_dc_linked_invoice_posts_cogs_at_finalize`.
