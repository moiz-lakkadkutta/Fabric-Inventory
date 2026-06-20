# Flow Review 02 — Receivables & Invoice GL

**Slice:** finalize → post_invoice_to_gl → post_receipt → FIFO allocation → PARTIALLY_PAID/PAID/OVERDUE; AR sub-ledger vs control; immutability; idempotency; concurrency.
**Method:** code-read of `sales_service.finalize_invoice`, `accounting_service.post_invoice_to_gl`/`post_journal_voucher`, `receipt_service.post_receipt`, `middleware/idempotency.py`; live read + rejected-probe API calls; read-only `psql`. No seeded record mutated. (The pre-existing `ZZTEST-INV/0001` throwaway in firm `7a34d2bb` is from a prior agent, not this run.)
**Builds on** `product-review-2026-06-20.md` (#4 line-amount, #18 purchases-no-GL, #24 voucher#, ✅ sales→GL ties to rupee) and `personas/04-accountant-finance.md` (G1–G6). Does not repeat them; cites by number. Scope here is the **sales/receivables** half the prior review already called "genuinely solid" — and it largely is. New findings are concurrency, lifecycle dead-states, the missing void/correction path, and one seed-data invariant break.

---

## 1. Flows (as implemented)

```
DRAFT ──finalize_invoice (sales_service.py:938)──► FINALIZED
          │  guard: status==DRAFT else InvoiceStateError→409 (954-959)
          │  side-effect: post_invoice_to_gl (969) in SAME txn
          ▼
   GL voucher (VoucherType.SALES_INVOICE, status POSTED)
        DR 1200 Sundry Debtors   = invoice_amount
        CR 4000 Sales Revenue    = invoice_amount − gst_amount
        CR 2100 GST Payable      = gst_amount        (line skipped if 0)
        invariant: ΣDR==ΣCR asserted pre- AND post-flush (192-204)

FINALIZED ──post_receipt (receipt_service.py:132)──► PARTIALLY_PAID | PAID
          FIFO oldest-first (invoice_date ASC, number ASC) over
          _OPEN_AR_LIFECYCLES = {FINALIZED, POSTED, PARTIALLY_PAID, OVERDUE}
          per invoice: applied=min(remaining, outstanding); +paid_amount;
            paid>=invoice_amount ? PAID : PARTIALLY_PAID
          GL voucher (VoucherType.RECEIPT, POSTED):
            DR 1000 Cash | 1100 Bank (CASH→1000, BANK/UPI→1100)
            CR 1200 Sundry Debtors  = FULL receipt amount (not Σallocated)
```

**Reachable invoice states:** DRAFT, FINALIZED, PARTIALLY_PAID, PAID — only these four are ever assigned (`grep "lifecycle_status = "` → sales_service.py:883 DRAFT, :963 FINALIZED; receipt_service.py:237-241 PAID/PARTIALLY_PAID). **Dead states:** CONFIRMED, **POSTED**, **OVERDUE**, **CANCELLED**, **DISCARDED** — no code path assigns them (see I4). GL posting happens *inside* FINALIZED, so the invoice never carries a distinct POSTED status even though its voucher is POSTED.

**Verified-good (this slice):**
- `post_invoice_to_gl` balanced-bundle invariant asserted before+after flush (accounting_service.py:192-204). Live: every finalized invoice but one (B4) has **exactly one** SALES_INVOICE voucher (SQL `HAVING COUNT<>1` → 1 row).
- AR control = AR sub-ledger for the active firm: GL ledger-1200 balance **₹40,611.20** == Σ(invoice_amount−paid_amount) of open invoices **₹40,611.20** (SQL, firm `7a34d2bb`). TB `balanced:true`.
- Finalize state-guard is real: only DRAFT→FINALIZED (954-959); re-finalize raises InvoiceStateError→409. No `update_invoice`/`edit_invoice` exists ⇒ FINALIZED rows are immutable (confirms persona §2).
- Idempotency **is** enforced — by `IdempotencyMiddleware` (not the per-router `idempotency_key` params, which are dead). Live: receipt POST with no key → **400**, non-UUID key → **400**, valid key path works. Cache is Redis, path+key scoped, payload-hash mismatch → 409, 401/403/5xx not cached (idempotency.py:117-163).
- Receipt validation rejects: amount≤0 → 422 (`body.amount must be >0`), unknown party → 422 (`Party … not found`), bad mode → AppValidationError (receipt_service.py:157-173).
- FIFO tiebreaker is deterministic (invoice_date, number) so concurrent receipts allocate in a stable order (receipt_service.py:127).

---

## 2. Transition test matrix

| From | Event | Guard | Result | Side-effect | Verdict |
|------|-------|-------|--------|-------------|---------|
| DRAFT | finalize | status==DRAFT | FINALIZED | 1 balanced GL voucher | ✅ |
| FINALIZED/PAID/… | finalize | status!=DRAFT | InvoiceStateError→409 | none | ✅ immutable |
| FINALIZED | receipt < outstanding | amount>0, party ok | PARTIALLY_PAID | DR cash/CR AR full | ✅ |
| FINALIZED | receipt == outstanding | " | PAID | " | ✅ |
| FINALIZED | receipt > outstanding | " | PAID, **excess unallocated** | CR AR **full amount** → AR goes negative; no advance ledger, no alloc row | ⚠️ B5 / G6 |
| (party, no open invoices) | receipt | amount>0 | voucher posts (advance) | DR cash/CR AR full | ⚠️ docstring says "raises" but does **not** (B5) |
| PAID | un-pay / reverse receipt | — | **no path** | — | ❌ B-rev (no reversal) |
| any | cancel/void/discard invoice | — | **no path** | — | ❌ B6 |
| FINALIZED, due_date<today | (time passes) | — | **stays FINALIZED** | dashboard derives "overdue" but lifecycle never set OVERDUE | ⚠️ B7 |
| DRAFT | finalize ×2 concurrent (same id) | both pass guard (no row lock) | one 500 (voucher# unique) | at most 1 voucher | ⚠️ B1 |
| DRAFT,DRAFT | finalize ×2 concurrent (same firm) | — | voucher# race → one 500 | — | ⚠️ B1 |
| FINALIZED | receipt ×2 concurrent (same invoice) | no row lock | lost-update | paid_amount/Σalloc can exceed invoice_amount | ⚠️ B2 |
| n/a | receipt no Idempotency-Key | middleware | 400 | none | ✅ |
| n/a | receipt dup key same body | middleware | replay cached | none | ✅ (Redis) |
| Org B | read Demo invoice | RLS | 404 / 0 rows | none | ✅ (prior S1) |

---

## 3. Bugs

| ID | Sev | Flow | What | Location | Fix |
|----|-----|------|------|----------|-----|
| **B4** | **P2** | invariant/seed | FINALIZED invoice `RT/2526/0042` (firm `66fa5720`, ₹254,100) has **0 GL vouchers** and **no audit_log finalize entry** — it was set FINALIZED bypassing `finalize_invoice`. That firm's GL AR (ledger 1200) = **₹0** vs sub-ledger open AR = **₹254,100**: a ₹254,100 control-vs-subledger hole. Books for that firm don't reconcile (a reviewer who firm-switches sees it). | `seed_demo_service.py` (direct status insert); breaks invariant guaranteed by `sales_service.py:963-969` | Seed must finalize via `finalize_invoice` (or post the GL voucher) so every FINALIZED row has its DR-AR voucher. Add a startup/CI assert: no FINALIZED invoice with 0 vouchers. |
| **B1** | P2 | finalize concurrency | Two concurrent finalizes race on the voucher number. `get_sales_invoice` has **no `with_for_update`** (sales_service.py:633-641) so both pass the DRAFT guard; `_allocate_voucher_number` is `max(number)+1` with **no firm-row lock** (accounting_service.py:61-81) — unlike invoice-*number* creation which **does** lock the Firm row (sales_service.py:749-751). The DB unique on `(org,firm,voucher_type,series,number)` saves correctness, but `post_invoice_to_gl` does **not** catch `IntegrityError` → the loser surfaces as a **500**. `post_journal_voucher` already models the fix (catches it → clean 422, accounting_service.py:373-388). | accounting_service.py:61-81, 116-122; sales_service.py:633-641 | Lock the Firm row in `_allocate_voucher_number` (mirror :749), and/or wrap the flush in the same `IntegrityError`→422 translation as `post_journal_voucher`. Optionally `with_for_update` the invoice in finalize. |
| **B2** | P2 | receipt concurrency | `post_receipt` reads open invoices and does read-modify-write on `paid_amount` with **no row lock** on the invoice (receipt_service.py:176, 212-245). Two concurrent receipts for the same party can both see the same `outstanding`, both allocate, both overwrite `paid_amount` (lost update) → Σallocations > invoice_amount and AR over-credited. No DB constraint enforces `Σalloc ≤ invoice_amount`. (No live violation today — current data clean — but unguarded.) | receipt_service.py:108-129, 176, 235-241 | `with_for_update` the candidate invoices in `_list_open_invoices_fifo`; or a CHECK/trigger that `paid_amount ≤ invoice_amount`. |
| **B3** | P2 | receipt concurrency | Same voucher-number race as B1 on the RECEIPT series: `_allocate_voucher_number` no firm lock (receipt_service.py:85-105), and `post_receipt` does **not** catch `IntegrityError` → concurrent receipts in one firm → one **500**. | receipt_service.py:85-105, 181-207 | Firm-row lock and/or IntegrityError→422, as B1. |
| **B6** | P2 | correction | **No invoice cancel / void / discard path at all.** No `cancel_invoice`/`discard_invoice`/`void` in `sales_service`; CANCELLED & DISCARDED are unreachable. A wrong DRAFT can't be discarded; a wrong FINALIZED can't be voided. Combined with no credit note (persona G5) and no receipt reversal (B-rev), there is **zero supported way to correct a sale**. Immutability is good; the escape hatch is missing. | sales_service (absent) | Add `void_invoice` (FINALIZED→CANCELLED + reversing voucher) and `discard_invoice` (DRAFT→DISCARDED soft-delete); or ship credit notes (TASK-038). |
| B-rev | P2 | receipt correction | **No receipt reversal**, though the schema is ready: `payment_allocation.reversed_by_allocation_id` column exists (accounting.py:272) but **no service writes it** (grep → 0 producers). A wrong/duplicate receipt (different Idempotency-Key) can't be undone; paid_amount can't be walked back. | receipt_service (absent) | Add `reverse_receipt` that posts a contra voucher (DR AR / CR Cash), restores `paid_amount`, and stamps `reversed_by_allocation_id`. |
| B7 | P3 | OVERDUE | OVERDUE is **never materialized** on the invoice — no path sets `lifecycle_status=OVERDUE`. The dashboard derives overdue correctly at query time (`due_date < today` on open invoices, dashboard_service.py:165-177), but the invoice list / detail / party khata can't show an OVERDUE badge, and `_OPEN_AR_LIFECYCLES`/reports list OVERDUE for a state nothing produces. | dashboard_service.py:165-177; receipt_service.py:60-65 | Either a nightly job/derived column flips eligible invoices to OVERDUE, or drop OVERDUE from the enum and keep it purely derived (document the choice). |
| B5 | P3 | advance/docs | `post_receipt` docstring (receipt_service.py:151) says it "Raises AppValidationError if … no open invoices" — it does **not**; an advance receipt against a party with no open invoices posts DR cash / CR AR full amount (AR goes negative). Behavior is defensible (customer advance) but the doc lies and there's no advance ledger or alloc row, and the "next finalize will draw it down" claim (152-155) is unimplemented (persona G6). | receipt_service.py:151-156, 209-273 | Fix the docstring; route the unallocated remainder to an `Advance from Customers` liability ledger; implement draw-down on next finalize. |
| B8 | P3 | receipt mode | Payment mode (CASH/BANK/UPI) is persisted **only** inside the DR line's free-text description and regex-parsed back for the listing (receipt_service.py:259, 343, 378-381). UPI and BANK share ledger 1100, so they're indistinguishable at GL; a description edit or format drift silently loses the mode. | receipt_service.py:247-262, 343 | Add a `payment_mode` column on Voucher (one migration). |
| B9 | P3 | money type | `Voucher.total_debit/total_credit` and `VoucherLine.amount` are `Numeric(15,2)` (accounting.py:154-155, 209), not the CLAUDE.md-mandated **NUMERIC(18,2)** (Money §). `PaymentAllocation.amount` correctly uses 18,2 (accounting.py:259). Caps a voucher line at ~₹10 trillion — unlikely to bite, but it's an inconsistent money type vs the standard. | accounting.py:154-155, 209 | Widen to NUMERIC(18,2) for parity. |

> Dead per-router param (note, not scored): every mutating router declares `idempotency_key: str | None = Header(...)` but **none read it** (e.g. receipts.py:70, sales.py:702). Enforcement is entirely in `IdempotencyMiddleware`. Harmless but misleading — the params imply handler-level logic that doesn't exist.

---

## 4. Improvements

1. **Advance / on-account ledger** (B5/G6): over-allocation silently pushes AR negative instead of crediting an `Advance from Customers` liability; add the ledger + a manual-allocation mode (FIFO-only today, `allocation_mode='AUTO'` hardcoded at receipt_service.py:230).
2. **TDS**: `tds_amount` hardcoded `Decimal("0")` (receipt_service.py:229) — no TDS-on-receipt handling.
3. **Manual allocation UI**: receipts can only auto-FIFO; a user can't target a specific invoice (common when a customer pays a particular bill).
4. **Clean concurrency contract**: fold B1/B3 into one helper that locks the firm and translates the unique-violation race to 422 everywhere (currently only `post_journal_voucher` does it).
5. **Surface immutability to the API**: FINALIZED invoices are immutable by *absence* of an update path; an explicit 409 on any PATCH attempt would be clearer than a missing route.

---

## 5. Invariant violations

| # | Invariant | Status | Evidence |
|---|-----------|--------|----------|
| I1 | Every FINALIZED invoice ⇒ exactly one balanced SALES_INVOICE voucher | **VIOLATED** (1 row) | `RT/2526/0042`, firm `66fa5720`: 0 vouchers, 0 audit entries (B4) |
| I2 | GL AR control (ledger 1200) == Σ open-invoice outstanding (sub-ledger), per firm | Holds for active firm (₹40,611.20==₹40,611.20); **VIOLATED** for firm `66fa5720` (GL ₹0 vs subledger ₹254,100) — consequence of I1 | SQL both sides |
| I3 | `paid_amount ≤ invoice_amount` and Σallocations ≤ invoice_amount | Holds in current data (0 rows over) but **not constraint-enforced** → B2 can break it | SQL `HAVING SUM(amount)>invoice_amount` → 0 rows |
| I4 | Every enum state is reachable | **VIOLATED**: CONFIRMED, POSTED, OVERDUE, CANCELLED, DISCARDED are dead states (no assignment) | grep `lifecycle_status = ` → only DRAFT/FINALIZED/PARTIALLY_PAID/PAID |
| I5 | Receipt voucher balanced (DR cash == CR AR) | Holds (both = `amount`) | receipt_service.py:252-273 |
| I6 | Finalized invoice is immutable | Holds (no update path) | persona §2 + grep |

---

### Bottom line
The **sales→cash core is sound**: balanced GL with pre/post-flush invariants, deterministic FIFO, real immutability, working idempotency middleware, and AR control == sub-ledger for the active firm. The gaps are at the **edges of the state machine**: no correction path (cancel/void/credit-note/receipt-reversal), five **dead lifecycle states** (incl. OVERDUE never materialized), and **unguarded concurrency** (no row/firm locks in finalize or receipt → 500s and a theoretical over-allocation). One **seed-data invariant break** (B4) leaves a second firm's AR ₹254,100 out of balance. None are P0/P1 for the active-firm happy path, but the missing void/correction flow (B6) and B4 are the most trial-relevant.
