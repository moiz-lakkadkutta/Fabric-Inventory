# Flow Test 01 — Sales Fulfilment (Quote → SO → DC → Invoice + returns + numbering)

**Agent:** Flow-test #1 (Sales fulfilment slice of `00-flow-machine.md` §Agent-partition).
**Method:** code-read (`backend/app/{models,service,routers}/sales*.py`, `accounting_service.py`, `receipt_service.py`, `reports_service.py`, `inventory_service.py`) + live API probes against running stack (org "Demo Co", firm `7a34d2bb`) + read-only psql. Forward live tests via `ZZTEST-*` throwaway records (logged below). Builds on product-review `#4, #21, #22, #24`; persona pass cited where relevant. No seeded record mutated.

---

## 1. Flows / machines covered

| Machine | Spec states | Reachable in code | Verdict |
|---|---|---|---|
| **Sales Order** | DRAFT · CONFIRMED · PARTIAL_DC · FULLY_DISPATCHED · INVOICED · CANCELLED | DRAFT, CONFIRMED, PARTIAL_DC, FULLY_DISPATCHED, CANCELLED | **INVOICED unreachable** — no code sets it (grep: only docstrings/comments). DB: 0 SOs INVOICED across all orgs. |
| **Delivery Challan** | DRAFT · ISSUED · ACKNOWLEDGED · IN_PROCESS · RETURNED · CLOSED | DRAFT, ISSUED only | ACKNOWLEDGED / IN_PROCESS / RETURNED / CLOSED **unreachable** — no service verb or endpoint. |
| **Sales Invoice** | DRAFT · CONFIRMED · FINALIZED · POSTED · PARTIALLY_PAID · PAID · OVERDUE · CANCELLED · DISCARDED | DRAFT, FINALIZED, PARTIALLY_PAID, PAID | **CONFIRMED, POSTED, OVERDUE, CANCELLED, DISCARDED all unreachable.** `finalize` conflates spec's FINALIZED+POSTED (flips to FINALIZED *and* posts GL in one step). |
| **Quote** | (spec entity) | not modeled (`quotation_id` FK is nullable, no table) | `/sales/quotes` is a "Coming soon (TASK-038)" stub. |
| **Sales Return / Credit Note** | SALES_RETURN ← credit note ← invoice | not implemented | stub (TASK-038). No `credit_note`/`sales_return` symbol anywhere in sales code. |

Process-graph slice `QUOTE → SO → DC → INVOICE → RECEIPT` is **broken at two joints**: (a) SO↔Invoice has *no link at all* (`create_draft_invoice` has no `sales_order_id` param; invoice has `delivery_challan_id` FK but it is never populated — 11/11 invoices have NULL DC); (b) the spec's "soft-reserve on CONFIRMED" stock reservation does not exist.

---

## 2. Transition test matrix

| Transition | How tested | Expected | Actual | Verdict |
|---|---|---|---|---|
| SO create → DRAFT | live POST `/sales-orders` (ZZTEST-SO) | 201, status DRAFT, gapless number | `0001`, DRAFT | ✅ |
| SO DRAFT → CONFIRMED | live POST `/confirm` | CONFIRMED | CONFIRMED | ✅ |
| SO confirm when not DRAFT | code `confirm_so` L260 | reject | `InvoiceStateError` | ✅ |
| SO cancel from DRAFT/CONFIRMED | live (cleanup cancel) | CANCELLED | 200 CANCELLED | ✅ |
| SO cancel from PARTIAL_DC/FULLY_DISPATCHED/INVOICED | code `cancel_so` L284 | reject | `InvoiceStateError` (→ return/CN workflow) | ✅ guard correct |
| SO cancel idempotent (already CANCELLED) | code L293 | no-op | returns SO | ✅ |
| SO → INVOICED (on invoice post) | grep + DB | SO advances to INVOICED | **never happens** | ❌ **BUG-1** |
| SO soft-delete (DRAFT/CANCELLED only) | code `soft_delete_so` L325 | reject others | guard present | ✅ |
| DC create DRAFT (no stock) | live POST `/delivery-challans` | 201 DRAFT, no stock move | DRAFT, stock untouched | ✅ |
| DC create vs SO status guard | code `create_dc` L439 | reject if SO DRAFT/CANCELLED | reject | ✅ |
| **DC over-dispatch beyond SO qty** | live: SO ordered=1, DC qty=100 | reject or clamp | **201 ACCEPTED, total_qty=100** | ❌ **BUG-2** |
| DC DRAFT → ISSUED (stock out) | code `issue_dc` + `remove_stock` | decrement, SO roll-up | decrements; negative-stock guarded (`remove_stock` L392) | ✅ (stock guard) |
| DC issue double-fire | code L556 | reject re-issue | `InvoiceStateError` (not DRAFT) | ✅ |
| DC issue → SO PARTIAL_DC/FULLY_DISPATCHED | DB: SO 0001 PARTIAL_DC (2 of 3) | correct roll-up | correct | ✅ |
| SO roll-up clamps over-dispatch | code `_advance_so_status_after_dc` L398 | clamp to ordered | sets `qty_dispatched=100>ordered`, marks FULLY_DISPATCHED | ❌ **BUG-2** companion |
| DC soft-delete after ISSUED | code `soft_delete_dc` L611 | reject | reject | ✅ |
| **Direct invoice (no DC) decrements stock** | DB: 11 invoices, 0 DC links, 0 `sales_invoice` stock-ledger rows | stock out OR ATP check | **stock NEVER moved on invoice** | ❌ **BUG-3 (#osell)** |
| Invoice create → DRAFT | live POST `/invoices` (ZZTEST-INV) | DRAFT + GST split | DRAFT | ✅ |
| Invoice DRAFT → FINALIZED + GL | live `/finalize` | FINALIZED, balanced voucher | FINALIZED, DR=CR voucher | ✅ |
| **Invoice DRAFT → CONFIRMED** | probe POST `/invoices/{id}/confirm` | transition | **404 (no endpoint)** | ❌ **BUG-4** |
| **Invoice FINALIZED → POSTED** | probe `/post` | distinct POSTED state | **404; finalize already posted** | ⚠️ states merged |
| Invoice finalize twice (double-fire) | live, new idemp key | reject | **409 INVOICE_STATE_ERROR** | ✅ |
| Edit a FINALIZED/POSTED invoice | no PATCH/PUT endpoint exists | immutable | immutable (no update route at all) | ✅ (but DRAFT also non-editable) |
| **Cancel a FINALIZED invoice** | probe `/cancel`,`/void` | reversal via credit note | **404 — no path** | ❌ **BUG-5** |
| **Discard a DRAFT invoice** | probe `/discard`, DELETE | DISCARDED / soft-delete | **404 / 405** | ❌ **BUG-5** |
| Invoice → OVERDUE past due_date | grep: nothing sets OVERDUE | flip when `due_date<today` | **never set** | ❌ **BUG-6** |
| Receipt → PARTIALLY_PAID / PAID | code `receipt_service` L237 | from FINALIZED | works (skips POSTED) | ✅ |
| Idempotency dedup (same key+body) | live: 2× create SO | same row | same SO id returned | ✅ |
| Idempotency conflict (same key, diff body) | live | 409 | 409 | ✅ |
| Missing Idempotency-Key on mutation | live | 400 | 400 | ✅ |
| RLS cross-org (firm must be in org) | code `_ensure_firm_in_org` L104 | reject foreign firm | rejects (org-scoped) | ✅ |
| Firm-scope on write (user→firm access) | code L104 only checks org, not user-firm | enforce user's firm | **not enforced** (single-firm org, can't exploit live) | ⚠️ **BUG-7** |
| Numbering gaplessness (SO/DC/SI) | code `_allocate_*_number` (`max+1` under firm row-lock) | gapless per firm/series | gapless; row-lock serializes | ✅ |
| **Party-statement voucher number** | DB join voucher↔invoice for Lakshmi | show invoice's own number | **shows GL-voucher number 0004 for invoice 0006** | ❌ **BUG-8 (#24 root-caused)** |

---

## 3. Bugs

### BUG-8 — P2 — Party statement shows the wrong invoice number (root cause of product-review #24)
- **Flow:** Invoice → GL voucher → party statement.
- **What:** `compute_party_statement` emits `number = Voucher.number` (`reports_service.py:1124-1126`, query L1017/1030). For a SALES_INVOICE voucher the **voucher number is allocated independently** (`accounting_service._allocate_voucher_number` L116, `max(Voucher.number)+1`) from the **invoice number** (`sales_service._allocate_si_number` L739). They diverge whenever some invoices are created but never finalized (a DRAFT consumes an invoice number but no voucher number).
- **Evidence (DB, firm `7a34d2bb`):** invoices `0004` & `0005` are DRAFT; the 6 FINALIZED invoices (`0001,0002,0003,0006,0007,0008`) get vouchers `0001..0006`. So Lakshmi's invoice **0006 ↔ voucher 0004** — the statement prints "RT/DEMO/0004". Amount/date/balance all correct, only the document number is wrong.
- **Fix:** for `reference_type='sales_invoice'` vouchers, display the linked `SalesInvoice.series/number` (join on `reference_id`), not `Voucher.number`. Same latent bug in `compute_ledger_statement` (L752/770).

### BUG-1 — P2 — SO never advances to INVOICED (dead state + no SO↔invoice link)
- **What:** No code sets `SalesOrderStatus.INVOICED`; `create_draft_invoice` accepts no `sales_order_id` and the invoice's `delivery_challan_id` FK is never populated either. SOs remain PARTIAL_DC/FULLY_DISPATCHED forever after billing.
- **Evidence:** grep — only docstrings reference INVOICED (`sales_service.py:17` "TODO TASK-034"). DB: `SELECT status,count(*) FROM sales_order` → 0 INVOICED; 11/11 invoices have NULL `delivery_challan_id`.
- **Fix:** thread `sales_order_id`/`delivery_challan_id` into invoice create; on finalize, roll fully-billed SO → INVOICED.

### BUG-2 — P2 — DC can over-dispatch beyond SO ordered qty (no remaining-qty guard)
- **What:** `create_dc` (L407) validates SO *status* but never compares cumulative `qty_dispatched` against `qty_ordered`. `_advance_so_status_after_dc` (L398) writes the inflated dispatched qty onto the SO line and happily marks FULLY_DISPATCHED.
- **Evidence (live ZZTEST):** SO ordered=1 → DC `qty_dispatched=100` accepted (201, `total_qty=100`). Only `remove_stock` (negative-stock guard, `inventory_service.py:392`) limits issue, and that's a stock check, not an order check.
- **Fix:** in `create_dc`/`issue_dc`, reject `Σ dispatched > qty_ordered` per SO line (allow a configurable tolerance).

### BUG-3 — P2/P1 — Direct invoices never decrement stock (#osell oversell)
- **What:** `finalize_invoice` posts GL only; neither create nor finalize calls `inventory_service.remove_stock`. Stock leaves only on DC issue — but in practice invoices are raised directly (no DC). Inventory is therefore overstated by every direct sale and nothing prevents invoicing goods you don't hold (no ATP check).
- **Evidence (DB):** 11 invoices, **0** linked to a DC; `stock_ledger` has **no** `sales_invoice` reference rows (only 1 `DC` OUT total). Ties to product-review #21 (stock value) — sold goods never leave stock.
- **Fix:** decide the canonical stock-out point. If invoice-direct is the norm, post stock-out on finalize for invoices without a DC (and guard against negative/ATP), mirroring `issue_dc`.

### BUG-5 — P2 — No reversal path for a finalized invoice (CANCELLED/DISCARDED unreachable)
- **What:** Invoice router exposes only create/finalize/list/get/pdf. No cancel, discard, void, or credit-note endpoint; no DELETE. A mistakenly-finalized invoice (wrong party/amount) **cannot be corrected** — and sales-returns/credit-notes are a stub (TASK-038).
- **Evidence (live):** `POST /invoices/{id}/{cancel,discard,void,post,confirm}` → all **404**; `DELETE /invoices/{id}` → **405**. My ZZTEST-INV/0001 FINALIZED invoice is now **unremovable** (see cleanup note).
- **Fix:** implement credit-note reversal (POSTED/PARTIALLY_PAID → CANCELLED) and DRAFT → DISCARDED, per `specs/invoice-lifecycle.md` §7.

### BUG-6 — P3 — OVERDUE is never computed
- **What:** `receipt_service._OPEN_AR_LIFECYCLES` includes OVERDUE, but no job/transition ever sets it. An invoice past `due_date` stays FINALIZED. (Related to product-review #9 overdue-badge miscalc on the FE side.)
- **Fix:** scheduled flip `due_date < today AND unpaid → OVERDUE`, or compute it as a derived view.

### BUG-4 — P3 — CONFIRMED / POSTED invoice states are dead
- **What:** Enum + spec define DRAFT→CONFIRMED→FINALIZED→POSTED, but `confirm`/`post` endpoints don't exist and `finalize` jumps DRAFT→FINALIZED while also doing the GL post. Harmless today (finalize is atomic) but the state model is a lie vs `specs/invoice-lifecycle.md`; a reader expecting CONFIRMED-edit or a separate POSTED audit step is misled.
- **Fix:** either implement the intermediate states or prune them from the enum + spec so the machine matches reality.

### BUG-7 — P3 — Firm-scope not enforced on sales writes (firm-spoof, low live impact)
- **What:** `_ensure_firm_in_org` (L104) checks the firm belongs to the caller's org but **not** that the user has access to that specific firm; `app.current_firm_id` is never set (per `00-flow-machine.md` §C). In a multi-firm org, a user could write SO/DC/invoice into a sibling firm by passing its `firm_id`.
- **Evidence:** Demo org has a single firm, so not live-exploitable here; code-level gap confirmed. Cross-**org** is correctly blocked.
- **Fix:** validate `firm_id ∈ user's accessible firms` in the service guard.

---

## 4. Improvements
- **Editable DRAFT:** spec says DRAFT is "edit any field", but there is no update/PATCH endpoint — a wrong DRAFT can only be… not fixed (no discard either). Add DRAFT edit + discard.
- **Stock reservation on CONFIRMED:** spec promises "soft-reserved" stock at CONFIRMED; nothing reserves. Add ATP/reservation so over-commit is visible before dispatch.
- **DC `total_amount` is NULL when lines omit price** (`create_dc` L489) — DCs are often non-priced, fine, but the FE "source DC/PO literal label" (#6) and missing money formatting compound it.
- **Unify numbering:** SO/DC/SI and GL-voucher each re-implement `max+1` allocators; fold into one helper and (critically) make sales-invoice vouchers reuse the invoice's number to kill BUG-8 class entirely.
- **Quotes:** the documented entry point of this flow (QUOTE) is unmodeled — Quote→SO conversion is the natural top of the funnel for the trial.

## 5. Invariant violations
- **Process-graph linkage broken:** SO ⇎ Invoice (no FK populated), so "convert SO to invoice", SO INVOICED, and per-SO billed-qty are all unenforceable (BUG-1).
- **Inventory conservation broken:** goods can be sold (invoiced) without ever leaving stock (BUG-3); on-hand ≠ purchased − sold.
- **Order ≥ dispatch invariant broken:** Σ DC qty can exceed SO ordered qty (BUG-2).
- **Document-number identity broken:** the number shown on the party ledger ≠ the actual invoice number (BUG-8).
- **State-machine fidelity:** 9 declared states across the three machines are unreachable (SO INVOICED; DC ACKNOWLEDGED/IN_PROCESS/RETURNED/CLOSED; SI CONFIRMED/POSTED/OVERDUE/CANCELLED/DISCARDED).
- **Holds correctly:** GL voucher balanced DR=CR (verified post-finalize); numbering gapless under firm row-lock; idempotency dedup/conflict/required all enforced; double-finalize & double-issue rejected; negative-stock guard on DC issue; cross-org RLS.

---

### ZZTEST cleanup log
Created + removed via API: ZZTEST-SO/0001 (SO, cancel+delete ✅), ZZTEST-DC/0001 (DC, delete ✅), ZZTEST-IDEM/0001 (SO, delete ✅).
**Residue requiring manual cleanup:** `sales_invoice` series `ZZTEST-INV` number `0001` (id `b042a154-b73d-4233-b247-880c9d713c04`), **FINALIZED**, + its posted GL voucher — **could not be removed via API** (no cancel/discard endpoint; DB is read-only for this agent). This residue is itself live proof of BUG-5.
