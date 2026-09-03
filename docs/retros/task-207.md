# TASK-207 retro — numeric overflow → 422 instead of 500

**Date:** 2026-09-03
**Branch:** fix/issue-207
**Commit:** (on `fix/issue-207`, not yet merged — PENDING MOIZ SIGN-OFF on money caps)
**Plan:** GitHub issue #207 comment

## Summary

Shipped a three-layer defense so no numeric overflow can 500 with UNKNOWN
again: (A) Pydantic magnitude caps on the previously-uncapped money/qty
request fields (receipt/payment `amount` → `le=1e9` + `decimal_places=2`;
PO/GRN/PI `qty*`/`rate` → `le=1e9`), mirroring the existing BL-02 SI-line
caps; (B) a service-layer guard `app/utils/money.ensure_money_in_range`
called on every derived `line_amount` / document total / gst total in
`sales_service.create_draft_invoice` and `procurement_service.create_po`
/`create_grn`/`create_pi`, plus a belt-and-suspenders `amount` re-check in
`receipt_service.post_receipt` / `payment_service.post_payment` (callable
off the HTTP path); (C) a `DataError` handler in `middleware/errors.py`
mapping SQLSTATE `22003` (numeric_value_out_of_range) to the 422
VALIDATION_ERROR envelope as a last-resort net, leaking no SQL, with all
other `DataError`s staying 500. No migration (NUMERIC columns unchanged —
they remain the authoritative hard limit). Lint (ruff check + format),
mypy, and tests all pass: the 2 new test files (15 tests) are green and a
224-test regression sweep across the touched sales/procurement/receipt/
payment suites is green.

## Deviations from plan

### 1. Payments schema already had `decimal_places=2` but no `le` cap
Plan (and the brief) said "payments/receipts already have caps per #201 —
mirror them." Reality: `PaymentCreateRequest.amount` only had
`Field(gt=0, decimal_places=2)` and `ReceiptCreateRequest.amount` only
`Field(gt=0)` — neither carried the ₹1e9 `le` cap.
- **Fixed by:** added `le=Decimal("1e9")` to both (and `decimal_places=2`
  to receipts, which lacked it).
- **Why not caught in planning:** plan was written against `main`; caps
  had not actually landed there.
- **Impact on later tasks:** none.

### 2. Added a GRN service guard the plan only listed as "latent"
Plan flagged GRN as a same-shape latent gap but its explicit service-guard
call-sites covered PO/PI/SI only. Because `create_grn` accumulates
`total_amount += qty*rate` into NUMERIC(18,2), I added
`ensure_money_in_range` per-line and on the running total there too, so the
guard layer (not just the DataError net) covers GRN.
- **Why not caught in planning:** plan leaned on schema caps for GRN, but
  `qty≤1e9 * rate≤1e9` can still reach 1e18 before the column.
- **Impact on later tasks:** none.

## Things the plan got right (no deviation)

- Root cause exact: missing `DataError` handler + unvalidated derived
  amounts; `22003` is the SQLSTATE and `exc.orig.pgcode` is duck-typed.
- The BL-02 SI-line caps were already present — no double-capping needed.
- Boundary inclusivity (`le`, exactly ₹1e9 accepted) verified end-to-end.
- The whole-transaction rollback (`get_db_sync`) means no partial rows —
  asserted directly in `test_invoice_line_product_overflow_is_422`.

## Open flags carried over

- **PENDING MOIZ SIGN-OFF:** `MAX_MONEY = ₹1e9` per-line/per-document is a
  money-policy call. It lives as one named constant in
  `app/utils/money.py`; raising it is a one-line change + test update. The
  DataError→422 mapping itself is pure error-contract hygiene, not gated.
- **JV / manual vouchers** (`accounting_service.post_journal_voucher`) were
  intentionally left uncapped per the plan — the DataError net covers them.
  Follow-up only if Moiz wants symmetric explicit caps.
- **Vyapar migration ceiling:** confirm ₹1e9 is above any real historical
  TB figure before enabling migration writes (flagged for Moiz).
- **Data repair (not in this task):** the pre-fix missing receipt cap let
  ₹1e12 junk into QA orgs' books — covered by #190's `QA %` org purge, not
  here.

## Observable state at end of task

- New module `app/utils/money.py` (`MAX_MONEY`, `ensure_money_in_range`).
- No new env vars / services / migration. Branch `fix/issue-207` holds
  three commits (red tests → implementation → spec/retro); not merged.
