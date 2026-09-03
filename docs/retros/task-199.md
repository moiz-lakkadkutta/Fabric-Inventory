# TASK-199 retro — Cancel path for finalized sales invoices (reversing voucher)

**Date:** 2026-09-03
**Branch:** fix/issue-199
**Commit:** (on `fix/issue-199`, not yet merged — PENDING MOIZ + CA SIGN-OFF)
**Plan:** GitHub issue #199 comment

## Summary

Shipped `POST /invoices/{id}/cancel` (permission `sales.invoice.cancel`, idempotent)
plus the service + accounting machinery behind it. Cancelling a FINALIZED, unpaid,
non-DC-linked invoice now posts a **reversing GL voucher** so voucher-driven reports
(TB, P&L, party statement, daybook) stay consistent with status-driven ones (GSTR-1,
ageing) that already drop CANCELLED invoices — the exact QA divergence (party statement
₹1,050 vs ageing ₹0) is closed. COGS voucher is reversed and stock restored when
present. Migration `199_invoice_cancel` (down_revision `201_bank_account_ledger_unique`)
adds `sales_invoice.cancelled_at`/`cancel_reason` and a partial-unique index. Lint
(ruff), typecheck (mypy on the 4 touched app modules), and the targeted + broad
regression tests pass. **GATED: money/GL + schema + GSTR-1-period semantics need Moiz +
CA sign-off; not merged.**

## Deviations from plan

### 1. Reversal voucher is a CREDIT_NOTE, not a second SALES_INVOICE
The plan (mirroring PI-void) proposed posting the sales reversal as a `SALES_INVOICE`
voucher with `reference_type='sales_invoice_reversal'`, and claimed "no report changes
needed".
- **Reality:** `reports_service.compute_party_statement` ties a voucher to a party by
  `voucher.party_id` OR `reference_type='sales_invoice'`, and classifies its party
  contribution BY `voucher_type` (`SALES_INVOICE` → party DEBIT). A `SALES_INVOICE`-typed
  reversal with `reference_type='sales_invoice_reversal'` and no `party_id` would be
  **neither tied to the party nor classified as a credit** — the party statement would
  still show the invoice as owed, re-creating the divergence the issue is about.
- **Fixed by:** posting the sales reversal as `VoucherType.CREDIT_NOTE` with
  `party_id=invoice.party_id` (`accounting_service.reverse_sales_invoice_gl`). CREDIT_NOTE
  is in the party-statement credit set, so the statement nets to zero. Bonus: CREDIT_NOTE
  is outside #190's `uq_voucher_one_posting_per_ref` predicate, so no collision is even
  possible. TB is `voucher_type`-agnostic (ledger-level), so the swap still nets to zero.
- **Why not caught in planning:** the plan didn't trace the party-statement tie/classify
  logic; TDD (test #1 asserting `party statement == ageing == 0`) caught it immediately.
- **Impact on later tasks:** the future credit-note *document* work can reuse these
  CREDIT_NOTE reversals or supersede them; `revises_invoice_id` remains reserved for it.

### 2. Duplicate-voucher test needs the #190 index dropped to set up
The plan's test #6 said "insert two SALES_INVOICE vouchers directly (simulating #190
damage)". With #190's index now present, a second such insert is rejected by the DB.
- **Fixed by:** the test drops `uq_voucher_one_posting_per_ref` (superuser), injects the
  duplicate, cancels, asserts BOTH are reversed and AR nets to zero, then wipes the org
  and recreates the index in a `finally`. Proves cancel is the in-app remedy for #190
  fallout while leaving the DB clean.

## Things the plan got right (no deviation)

- FOR-UPDATE lock on the invoice row before the state check → clean idempotent concurrent
  cancel (2/3-way race test: exactly one reversal).
- `reference_type='sales_invoice_reversal'` + `reference_id=<original voucher_id>` as a
  positive "already reversed" marker, backed by the new partial-unique index.
- Guards: paid → 409, DC-linked → 409, DRAFT → 409, blank reason → 422.
- Reverse-if-present for COGS; mirror-only (never reconstruct amounts); stock restore
  keyed off the `sales_invoice` outbound stock_ledger rows.
- GSTR-1/ageing/dashboard needed no code change — CANCELLED already excluded.

## How the reversal avoids the #190 unique index (the load-bearing detail)

`uq_voucher_one_posting_per_ref` = UNIQUE `(org_id, voucher_type, reference_type,
reference_id)` WHERE `voucher_type IN ('SALES_INVOICE','COGS_SALE')`.
- **Sales reversal**: `voucher_type=CREDIT_NOTE` → not covered by the predicate at all.
- **COGS reversal**: `voucher_type=COGS_SALE` (covered) BUT `reference_type=
  'sales_invoice_reversal'` (vs original's `'sales_invoice'`) and `reference_id=<cogs
  voucher_id>` (vs original's `invoice_id`) → distinct key, no collision.
- A separate index `uq_voucher_sales_invoice_reversal (org_id, reference_id) WHERE
  reference_type='sales_invoice_reversal'` guarantees ≤1 reversal per original voucher
  (concurrency backstop; loser's INSERT → 409).

## Open flags carried over (Ask-vs-Decide)

- **Moiz — schema:** two new nullable columns on `sales_invoice` + one partial index.
- **Moiz + CA — GST period:** v1 is a full cancel dated the cancel day; cancelling an
  invoice from a *prior* GSTR-1 period retroactively removes it from that period's data.
  Legally a prior-period correction belongs in a credit note. Current behavior: allow +
  audit; NO period warning is emitted yet (the plan recommended logging one — deferred).
  CA to confirm before any real GST filing depends on it.
- **Follow-up ticket:** credit-note *document* (partial amounts, GSTR-1 CDNR,
  `revises_invoice_id` linkage, DC-linked sales-returns, receipt-unwind → advance).

## Pre-next checklist

### 1. Re-run the #190 duplicate detection after merge
`SELECT reference_id FROM voucher WHERE voucher_type='SALES_INVOICE' GROUP BY 1 HAVING
count(*)>1;` — cancel+reissue any affected invoices in-app (cancel is now the remedy).

### 2. Pre-existing unrelated failure to be aware of
`tests/test_cogs_on_sale.py::test_finalize_service_item_no_cogs_no_stock` fails on the
integration branch independent of #199 (it seeds a `has_gst=False` firm with
`gst_rate=18`, which `create_draft_invoice` rejects per #194). Not touched by this task.
