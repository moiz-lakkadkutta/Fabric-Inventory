# T-INT-5 hard review (2026-05-04)

3 commits, +1158/-12, 9 files on `task/int-5-receipts-post` branched off main at `3c752d2`. CI green at HEAD on the third try (one no-firm-context test fix, one mypy any-return fix). Closes the daily loop the integration arc was built for.

## Behavior coverage vs the plan's 6-row table

| # | Behavior | Status |
|---|---|---|
| 1 | `POST /v1/receipts` records cash receipt against an invoice (FIFO allocation) | **✅ shipped.** `receipt_service.post_receipt` allocates oldest-first across the party's open invoices; explicit allocation list lands in a follow-up if needed. |
| 2 | Receipt creates audit + ledger postings; invoice transitions DRAFT/FINALIZED → PARTIAL_PAID/PAID | **✅ shipped.** Voucher (DR Cash/Bank, CR AR), `payment_allocation` rows, audit log, `paid_amount` bump, lifecycle transition. |
| 3 | `GET /v1/receipts` lists receipts for current firm | **✅ shipped.** Reads RECEIPT vouchers newest-first. |
| 4 | RLS isolation | **✅ shipped (inherited).** Voucher table has RLS policy from DDL; service filters by `org_id` + `firm_id`. Same posture as T-INT-3 / T-INT-4. |
| 5 | Frontend: AccountingHub Receipts tab shows real receipts | **✅ shipped.** `lib/queries/accounts.ts` swaps `useReceipts` to dual-branch; existing `AccountingHub` table renders the live data unchanged. |
| 6 | (Smoke) Playwright: from invoice detail → "Record payment" → fill amount → see invoice status update | **⚠️ UI shipped, Playwright deferred.** The `Record payment` button + inline form are there; `usePostReceipt` invalidates the invoice cache so the lifecycle pill updates. Playwright config is the same gap as every prior task. |

**5 of 6 shipped functionally; the deferred row is the cross-task Playwright config gap, not a missing capability.**

## What landed

### Backend

- **`PaymentAllocation` ORM** mirroring DDL (line 2208) — `voucher_id`,
  `sales_invoice_id`/`purchase_invoice_id` (CHECK: exactly one),
  `amount`, `tds_amount`, `allocation_mode`, `reversed_by_allocation_id`,
  full audit-sweep tail.
- **`receipt_service.post_receipt`** — single entry-point that:
  - Validates amount > 0 and mode in `{CASH, BANK}`.
  - Allocates FIFO across the party's open invoices (oldest first by
    `invoice_date` then `number`); creates `payment_allocation` rows;
    bumps `sales_invoice.paid_amount`; transitions lifecycle to
    `PARTIALLY_PAID` or `PAID`.
  - Builds a balanced GL voucher (DR 1000 Cash-on-Hand or 1100 Bank
    Accounts / CR 1200 Sundry Debtors).
  - Audit log + `dashboard_service.invalidate_firm`.
  - Over-allocation is allowed; the unallocated remainder shows up in
    the audit log + response body.
- **`receipt_service.list_receipts`** filters `voucher_type=RECEIPT`,
  newest-first.
- **`POST /v1/receipts`** + **`GET /v1/receipts`** under
  `receipts_router`. Permission gates `banking.bank.create` and
  `banking.bank.read` (already on Owner / Accountant in the rbac
  seed). `_require_active_firm` mirrors the dashboard's posture.

### Frontend

- **`lib/queries/accounts.ts`**: `useReceipts` swapped to dual-branch
  (Q6); new `usePostReceipt` mutation. Live branch maps the wire
  shape (rupees-as-string + UUID allocations) into the existing
  `Receipt` type. On success, invalidates `['invoices']` and
  `['dashboard']` so the InvoiceDetail pill flips and the dashboard
  KPI strip catches up.
- **`InvoiceDetail.tsx`** grows a `Record payment` toggle visible
  when the invoice is `FINALIZED` / `PARTIALLY_PAID` / `OVERDUE`.
  Inline form (amount + mode + reference) submits via
  `usePostReceipt` with a fresh idempotency key; on success the
  invoice cache invalidates and the pill flips automatically.

### Tests

- 4 router tests (FIFO allocation across two invoices with right
  lifecycle transitions, no-open-invoices unallocated path,
  newest-first list ordering, balanced-voucher round-trip).

## Critical findings

### CRIT-1: Receipts list doesn't surface party / mode / allocation strings

**Where:** `GET /v1/receipts` returns voucher headers only — no
`party_name`, no `mode`, no allocation invoice numbers. The frontend
mapper papers over this by stuffing empty strings into
`Receipt.party_id` / `party_name` / `allocated_to`. Live mode
AccountingHub Receipts tab therefore shows "—" / blank cells where
the click-dummy showed real names.

**Why:** Receipts ride the generic `voucher` table. Joining to
`payment_allocation` + `party` would need a multi-table read. Out of
scope for the slice — the goal was making the daily loop close on
real data, not parity with the click-dummy fixture richness.

**Resolution path:** small follow-up `task/post-int-5-receipt-list-rich`:
extend `list_receipts` to LEFT JOIN `payment_allocation` →
`sales_invoice` (for the allocation series/number) and the receipt's
party_id from the first allocation. ~40 LOC.

### CRIT-2: Signup defaults users to no firm context — every consumer needs `/auth/switch-firm`

**Where:** Receipts test had to call `/auth/switch-firm` after signup
because the access token's `firm_id` is `None`. Same on dashboard
(T-INT-2 surfaced this) and now on receipts. The Owner role is
org-wide so the JWT carries no firm; users have to pick one.

**Trade-off chosen:** consistent with Q3 (firm switch is an explicit
event with audit trail). For dogfood-with-one-firm, asking the user
to switch immediately on first login is friction. The frontend
useAuthBootstrap could auto-switch when there's exactly one firm.

**Resolution path:** in `useAuthBootstrap`, after `/auth/me` succeeds,
if `me.firm_id is null` and the user has access to exactly one
firm, auto-call `/auth/switch-firm` with that firm. ~20 LOC; tracked
as a small follow-up. **Worth doing before friendly-customer.**

### CRIT-3: Mode field is CASH/BANK only — no UPI / Cheque

**Where:** Frontend Record-payment dropdown + backend `mode` validation
list `CASH | BANK`. Click-dummy's Receipt type allows `UPI | CHEQUE`
too.

**Trade-off:** added scope. UPI is technically Bank under the hood;
Cheque needs a separate flow (deposit, clearance, bounce — more
state machine). For T-INT-5 dogfood, CASH and BANK cover Moiz's
common cases.

**Resolution path:** UPI: trivial — add `UPI` to the enum and book
to the same `1100 Bank Accounts` ledger (or a separate
`1101 UPI Suspense` if the bookkeeping wants it separate). Cheque
is its own arc — touch when banking module gets the cheque-clearance
flow.

## Other observations

- **One ledger for all banks (control account, single row).** Real
  per-bank tracking needs `bank_account_id` flowing through
  `voucher_line` (the DDL has `bank_account` table; not in the ORM
  yet). Trade-off documented in the receipt_service docstring; revisit
  when banking module ships.
- **Allocations are AUTO only.** No manual override yet. `allocation_mode`
  defaults to `'AUTO'` in DDL; service hardcodes it. When the user
  needs to allocate to a specific invoice (rare for dogfood), a
  manual allocation modal is a small frontend addition + a
  `target_invoice_ids: list[UUID]` param on the service.
- **Over-allocation books an unallocated balance** in the audit log
  but doesn't create an "advance from customer" credit ledger
  entry. The voucher still balances (DR Cash > CR AR by the
  unallocated amount would be unbalanced — no, wait: voucher CR is
  the receipt amount, allocations are derivative). Re-checking:
  voucher is DR Cash `amount` / CR AR `amount` (both equal). The
  unallocated remainder shows up as the difference between voucher
  CR AR and the sum of payment_allocation rows. AR ends up
  over-credited by the unallocated amount, which means an "advance
  from customer" credit on AR for that party. Acceptable for
  dogfood; needs a sub-ledger reconciler eventually.
- **`InvoiceDetail` Record-payment form** is inline rather than a
  modal — saves the modal scaffolding and matches the existing
  staleError affordance pattern. Could be modal-ized later if a
  designer prefers.
- **`useInvoice` cache invalidation** triggers a refetch; the lifecycle
  pill flips automatically. The dashboard cache invalidation is
  per-firm; in mock mode the `invalidateQueries(['dashboard'])` is a
  noop because the dashboard isn't on screen.

## Recommended close-out

- **Merge.** No CRIT blocks the merge.
- **Before friendly-customer:**
  - CRIT-2 auto-switch-on-single-firm in `useAuthBootstrap` (~20 LOC).
  - CRIT-1 receipt list join with party + allocation series (~40 LOC).
- **In the wider banking arc:**
  - CRIT-3 UPI mode + cheque flow.
  - Per-bank-account postings (DR `bank_account_id`-keyed) with a
    real `bank_account` ORM.
  - Manual allocation override for receipts with multiple open
    invoices when FIFO isn't what the user wants.

## Summary

T-INT-5 closes the daily loop. Moiz can now log into staging.taana.in
(or `localhost:5173` per local-dev-mode), see the dashboard, create a
sales invoice for a customer, finalize it (which posts a balanced GL
voucher), and record a receipt that FIFO-allocates against open
invoices and flips the lifecycle pill. The trial balance reads from
`voucher_line` and now reflects every step in the flow.

The integration arc (T-INT-1 through T-INT-5) is functionally
complete. The remaining items in the plan are the explicit deferrals
(Playwright across all five tasks, OpenAPI in-sync test) and the
small UX polish CRITs from this task. From here, the next move is the
24-hour soak + dogfood switch-day per the plan's Q12 trigger.
