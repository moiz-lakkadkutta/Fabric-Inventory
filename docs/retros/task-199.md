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

## CA-review correction (2026-09-26)

**What was wrong.** GSTR-1 dropped every CANCELLED invoice and had no credit-note
section. An invoice cancelled in a later month vanished from its original month's
GSTR-1 (possibly already filed) and nothing appeared in the cancel month, while the
books reduced ledger 2100 in the cancel month — books and returns disagreed in both
months. The reversal was also dated on the UTC day, not the IST day.

**Legal / accounting basis.** Once a period's GSTR-1 is filed an invoice in it cannot
be deleted; the only correction is a credit note under CGST Act §34, reported in the
return of the month the note is issued — GSTR-1 Table 9B **CDNR** (registered
recipient, original B2B), **CDNUR** (unregistered, original B2CL or export); a note
against a B2CS invoice is netted off that month's B2CS (same state + rate), and the HSN
summary (Table 12) is net of credit notes. §34(2) (as amended by Finance Act 2022): a
credit note must be declared by 30 November following the end of the financial year of
the original supply (or the annual-return date, if earlier).

**What changed.**
- `gst_service`: `gst_local_date` (fixed UTC+05:30), `is_later_gst_period`,
  `credit_note_deadline` (30-Nov after the April-March FY end).
- `sales_service.cancel_invoice`: takes an injectable `now` (default `_utcnow()`, a
  monkeypatchable seam); computes the cancel date in IST; a **cross-period** cancel
  (cancel month IST > invoice month) after the deadline raises `InvoiceStateError`
  (409) telling the user no credit note can reduce tax now and to consult their CA.
  The CREDIT_NOTE reversal, COGS reversal and stock restore are dated
  `max(cancel_date_IST, invoice_date)`. Audit payload gains `reversal_date` +
  `gst_treatment` (`SAME_PERIOD_CANCELLATION` / `CREDIT_NOTE_S34`).
- `accounting_service._post_reversal_of` / `reverse_sales_invoice_gl` /
  `reverse_cogs_sale_gl`: optional `voucher_date` (default unchanged: UTC today).
- `reports_service.compute_gstr1`: a CANCELLED invoice is still reported in its own
  month iff its CREDIT_NOTE reversal is dated in a later month (the credit note's
  `voucher_date` is the single source of truth for the period, so books and return
  always pick the same month). New `cdnr` / `cdnur` sections (per note × slab rate;
  positive amounts, `note_type` "C"; CDNR GSTIN masked like B2B; CDNUR `ur_type`
  B2CL / EXPWP / EXPWOP); B2CS originals net off `b2cs` (negative row, count 0, when no
  sales that month); `hsn` reduced by every note's lines. Original classified with
  `_bucket_for_invoice` using its own invoice date (date-dependent B2CL threshold).
- Schema/API: `Gstr1CdnrRow`, `Gstr1CdnurRow` on `Gstr1Response`; XLSX gains CDNR and
  CDNUR sheets (B2B stays sheet 0 for CSV). OpenAPI snapshot, FE types, `specs/` updated.
- FE: GSTR-1 panel shows both credit-note sections; header totals are net of notes;
  B2CS / HSN tax cells render negatives.
- Tests: `tests/test_sales_invoice_cancel_gst_period.py` (same-month, IST same-period,
  B2B→CDNR, masked CDNR GSTIN, B2CL→CDNUR, export→CDNUR EXPWOP, B2CS net-off with and
  without cancel-month sales, IST boundary, deadline allow/refuse, pure deadline + IST
  helpers, HTTP JSON + XLSX, HTTP 409). Each checks books == return per period (Σ GSTR-1
  tax, notes negative == net CR on 2100 from SALES_INVOICE + CREDIT_NOTE). Existing
  cancel + concurrency tests now pin the cancel clock to a same-period instant (they
  previously relied on the wall clock and would have become cross-period — and, after
  30-Nov-2027, refused).

**Out of scope (not built).**
- The Oct-2025 rule that a credit note to a registered recipient needs the recipient's
  ITC reversal (IMS accept/reject) before the supplier's liability reduces.
- Annual-return-date limb of the §34 deadline (no annual-return date is tracked).
- Partial credit notes / sales returns (separate backlog item) and debit notes.
- SEZ originals sit in the existing `export` bucket, so their notes go to CDNUR
  (EXPWP/EXPWOP); on the portal a SEZ recipient has a GSTIN and belongs in CDNR
  (SEZWP/SEZWOP). Pre-existing classification choice — CA to confirm.

**Flags for Moiz + CA.**
- Reversal dated `max(cancel date IST, invoice date)` — a future-dated invoice cancelled
  before its date gets a reversal on the invoice date (a reversal never predates the
  document; keeps books == return). Legacy reversals dated *before* the invoice month
  are treated as same-period (not reported).
- Credit-note amounts are positive with note type "C" (portal JSON convention); the
  header totals / books==return check subtract them.
- HSN is reduced for all credit notes (Table 12 instructions), not only B2CS ones.
