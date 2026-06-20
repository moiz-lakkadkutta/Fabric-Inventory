# Flow slice #3 — Procurement & 3-Way Match (PO · GRN · PI)

Scope: `PurchaseOrder` (DRAFT·APPROVED·CONFIRMED·PARTIAL_GRN·FULLY_RECEIVED·CANCELLED),
`GRN` (DRAFT·ACKNOWLEDGED·IN_PROCESS·RETURNED·CLOSED), `PurchaseInvoice`
(DRAFT·CONFIRMED·MATCHING·ON_HOLD·DISPUTED·POSTED·PARTIALLY_PAID·PAID·OVERDUE·CANCELLED).
Builds on product-review #18 (purchase→GL no-op), #21 (stock valuation ₹0), personas/03-trader + 04-accountant.
Code: `backend/app/service/procurement_service.py`, `inventory_service.py`, `routers/procurement.py`, `schema/ddl.sql`.

Grounding: code-read of every transition + live DB (read-only, all orgs) + rejected API probes against
`http://localhost:8000`. No seeded records mutated.

---

## 1. Flows (as implemented)

```
PO:  create_po → DRAFT ──approve_po──→ APPROVED ──confirm_po──→ CONFIRMED
                   │  └──────confirm_po──────────────────────────┘
                   └─cancel_po→ CANCELLED   (only DRAFT/APPROVED/CONFIRMED)
     CONFIRMED ──(GRN received, auto)──→ PARTIAL_GRN ──(all lines met)──→ FULLY_RECEIVED
     advance is RECOMPUTED from Σ grn_line.qty_received vs po_line.qty_ordered

GRN: create_grn → DRAFT ──receive_grn──→ ACKNOWLEDGED   (terminal in practice)
     receive_grn side-effects: inventory_service.add_stock per line (weighted-avg),
       then _advance_po_status_after_grn(po). NO GL voucher.
     IN_PROCESS / RETURNED / CLOSED enum values are NEVER set — dead states.

PI:  create_pi → DRAFT ──post_pi──→ POSTED        (loose header amount check only)
                   │      └void_pi→ VOIDED (lifecycle CANCELLED)
                   └void_pi→ VOIDED
     CONFIRMED / MATCHING / ON_HOLD / DISPUTED / PARTIALLY_PAID / PAID / OVERDUE
       enum values are NEVER set by any code path — dead states.
     post_pi side-effects: status flip ONLY. NO GL (AP / Inventory / ITC all absent).

Cross-doc: PO──grn.purchase_order_id──GRN──pi.grn_id──PI. No PO↔PI link.
3-way "match": post_pi compares pi.invoice_amount vs grn.total_amount (header, ex-GST) only.
Purchase return / debit note: table `purchase_return` exists, 0 rows, NO service/router. Pure stub.
```

Live DB snapshot (all orgs): PI {POSTED:12 (₹367,350 + GST ₹25,159.50), DRAFT:6, VOIDED:1};
GRN {ACKNOWLEDGED:9, ₹365,850}; `voucher` reference_type ∈ {sales_invoice, receipt, material_issue,
manufacturing_order} — **zero** purchase_invoice / grn vouchers. `stock_position.current_cost` 78/79 populated.

---

## 2. Transition test matrix

| # | Machine | From → verb | Expected | Actual | Result |
|---|---------|-------------|----------|--------|--------|
| 1 | PO | DRAFT → approve | APPROVED | APPROVED | PASS |
| 2 | PO | APPROVED → approve | reject | InvoiceStateError | PASS |
| 3 | PO | DRAFT/APPROVED → confirm | CONFIRMED | CONFIRMED | PASS |
| 4 | PO | CONFIRMED → confirm | reject | InvoiceStateError | PASS |
| 5 | PO | FULLY_RECEIVED → cancel | reject | 409 "requires return/credit-note" (live) | PASS |
| 6 | PO | PARTIAL_GRN → cancel | reject | refused | PASS |
| 7 | PO | CANCELLED → cancel | no-op | returns po (idempotent) | PASS |
| 8 | PO | **CANCELLED + DRAFT GRN → receive_grn** | stay CANCELLED / reject | **PO flips to FULLY_RECEIVED (un-cancel)** | **FAIL — BUG P1-A** |
| 9 | GRN | create vs DRAFT PO | reject | InvoiceStateError (create only) | PASS |
| 10 | GRN | create vs CANCELLED PO | reject | InvoiceStateError (create only) | PASS |
| 11 | GRN | DRAFT → receive | ACKNOWLEDGED + stock + PO advance | works | PASS |
| 12 | GRN | ACKNOWLEDGED → receive | reject (no double-post) | InvoiceStateError | PASS |
| 13 | GRN | **qty_received > po_line.qty_ordered** | reject / cap | **accepted, stock over-posted, PO→FULLY_RECEIVED** | **FAIL — BUG P1-B** |
| 14 | GRN | short receipt < ordered | PARTIAL_GRN | PARTIAL_GRN | PASS |
| 15 | GRN | line rate = NULL → receive | cost not corrupted | **unit_cost=0 blended into wt-avg** | **FAIL — BUG P2-C** |
| 16 | GRN | line lot_number set → receive | stock lot-tracked | **lot_id=None; lot_number dropped** | **FAIL — BUG P3-D** |
| 17 | PI | create vs DRAFT GRN | reject | InvoiceStateError | PASS |
| 18 | PI | DRAFT → post | POSTED **+ GL** | POSTED, **NO GL** | **FAIL — BUG P1-E (#18)** |
| 19 | PI | POSTED → post | reject | InvoiceStateError (409 in-org) | PASS |
| 20 | PI | post without Idempotency-Key | 400 | 400 (live) | PASS |
| 21 | PI | post, PI qty > GRN/PO qty | block/flag | **no qty match at all** | **FAIL — BUG P2-F** |
| 22 | PI | post, amount drift >1% | warn (no block, by design) | match_result warning, no block | PASS (by design, but see Imp-2) |
| 23 | PI | post, GRN.total_amount NULL | match runs | **match silently skipped** | **FAIL — BUG P2-G** |
| 24 | PI | POSTED → void | VOIDED + GL reversal | VOIDED, no GL (none existed) | PASS-ish (no GL to reverse) |
| 25 | PI | RECONCILED → void | reject | InvoiceStateError | PASS |
| 26 | PI | VOIDED → void | no-op | returns pi | PASS |
| 27 | RLS | cross-org PI read/post | 404/not-found | 422 "not found" (live) | PASS (org RLS works) |
| 28 | Firm | act on other firm's PO within org | reject | **allowed (firm not enforced)** | **FAIL — BUG P2-H** |

---

## 3. Bugs

| Sev | Flow | What | Evidence (file:line / API / SQL) | Fix |
|-----|------|------|----------------------------------|-----|
| **P1-A** | PO cancel ↔ GRN | **Cancelled PO silently un-cancelled by receiving a pre-existing DRAFT GRN.** `receive_grn` only checks `grn.status == DRAFT`; it never re-validates the parent PO. `_advance_po_status_after_grn` unconditionally sets PARTIAL_GRN/FULLY_RECEIVED. Sequence: create GRN (DRAFT) while PO CONFIRMED → cancel PO → receive GRN → PO resurrects to FULLY_RECEIVED, stock posts. Cancel guard (line 306) is thus bypassable. | `procurement_service.py:558-562` (GRN-only guard), `:412-415` (unconditional advance), `:385-417` | In `receive_grn`, re-fetch PO and reject if status ∈ {CANCELLED} (and ideally require CONFIRMED/PARTIAL_GRN). |
| **P1-B** | GRN over-receipt | **No ceiling check anywhere.** `create_grn` validates only `qty>0` (line 479-480); `receive_grn` never compares to `po_line.qty_ordered`. `_advance_po_status_after_grn` uses `received < ordered` → over-receipt (received>ordered) satisfies "fully received", PO→FULLY_RECEIVED with `qty_received > qty_ordered`, and the surplus is posted to stock. No DB CHECK constraint either (ddl `po_line`/`grn_line`). Persona-03 (trader) flagged silent over-receipt. | `procurement_service.py:475-501`, `:402-415`; `schema/ddl.sql:782,826` (no CHECK) | Add per-line cumulative check: Σ received + new ≤ qty_ordered × (1+tolerance); reject or require explicit over-receipt flag. |
| **P1-E** | PI post → GL | **post_pi posts nothing to the GL** (confirms #18, root-caused deeper). Service comment "GL voucher generation lives in TASK-041; this stage just advances the state" (`:803-804`). Live: 12 PIs POSTED yet `voucher` has **0** rows of purchase_invoice/grn type. Missing postings: **Dr Inventory/Purchases ₹367,350, Dr ITC (input GST) ₹25,159.50, Cr Sundry Creditors/AP ₹392,509.50** (DB-wide). GRN receipt likewise books no Dr Inventory / Cr GRN-clearing → TB Inventory goes negative (#18). Books have no creditors and no input-tax credit. | `procurement_service.py:796-836`; `receive_grn :544-592` (stock only, no voucher); SQL `voucher` reference_type set | Implement TASK-041: GRN → Dr Inventory / Cr GR-IR; PI post → Dr GR-IR + Dr ITC / Cr AP. Balanced bundle per CLAUDE.md. |
| **P2-C** | GRN cost | **Null-rate GRN line corrupts weighted-average cost.** `receive_grn` sets `unit_cost = rate or Decimal("0")` (line 568) and `add_stock` blends 0 into `current_cost` (`inventory_service.py:320`). A receipt without a rate silently drags item valuation toward 0. | `procurement_service.py:567-580`; `inventory_service.py:317-322` | Reject GRN receive when any line rate is NULL (or fall back to PO line rate / last cost) instead of 0. |
| **P2-F** | PI 3-way match | **No quantity match.** `post_pi` only compares header amounts; PI line qty is never reconciled against GRN received qty or PO ordered qty. A PI can bill more units (or different items) than were ever received — overbilling passes. `create_pi` also does no item/qty cross-check vs the linked GRN. | `procurement_service.py:816-829` (amount only); `create_pi :648-746` | Match per line: PI.qty vs Σ GRN.qty_received and PI.rate vs PO.rate; set ON_HOLD/DISPUTED on breach. |
| **P2-G** | PI match skip | **Match silently no-ops when `grn.total_amount` is NULL** — which happens whenever GRN lines carry no rate (common). Guard `grn.total_amount is not None and > 0` (line 818) falls through with zero warning, so the only existing check is defeated by the same null-rate path as P2-C. | `procurement_service.py:816-822` | Fall back to PO line amounts for the match basis; warn when GRN has no cost. |
| **P2-H** | RLS / firm | **Firm-level scope not enforced on procurement writes.** `firm_id` is taken from request body (`create_po/grn/pi`) and only checked to belong to the org (`_ensure_firm_in_org`). State-change endpoints (approve/confirm/cancel/receive/post/void) look up by `org_id` only — a user can drive any firm's documents within their org. Matches flow-machine §C firm-spoof gap (`app.current_firm_id` never set). | `procurement_service.py:103-108`; routers approve/confirm/receive/post (org_id only) | Enforce caller's firm membership; set + filter on `app.current_firm_id`. |
| **P3-D** | GRN lot | **Lot tracking dropped on receipt.** `grn_line.lot_number` (string) is captured but `receive_grn` calls `add_stock(... lot_id=None)` (line 569-580) and never creates a `Lot`. Stock is single-pool; lot-level traceability/FIFO (#21 future layer) impossible despite the captured data. | `procurement_service.py:567-580` | Resolve/create `Lot` from `lot_number` and pass `lot_id` to `add_stock`. |
| **P3-I** | PI lifecycle | **6 of 10 PI states are dead.** CONFIRMED/MATCHING/ON_HOLD/DISPUTED/PARTIALLY_PAID/PAID/OVERDUE never set; `held_by`/`hold_reason` columns (ddl 2169-2170) unused; `match_result` schema expects per-line `{po_variance_pct, grn_variance_pct, decision}` (ddl 2166) but code writes header `{warning, drift_pct}`. PARTIALLY_PAID/PAID never set means PI payment never advances lifecycle. | `models/procurement.py` enum vs `procurement_service.py:830-831`; `schema/ddl.sql:2164-2170` | Wire match→MATCHING/ON_HOLD/DISPUTED and payment→PARTIALLY_PAID/PAID, or prune unused states. |
| **P3-J** | Purchase return | **Debit-note / purchase-return flow is a bare table.** `purchase_return` exists (0 rows) with no service, router, or schema. Cancel/void guards repeatedly defer to "TASK-049 credit-note workflow" that doesn't exist — so a received-then-wrong PO/GRN has no correction path except DB surgery. | `schema/ddl.sql:887`; no `service/routers` refs; `procurement_service.py:312` | Build purchase-return → debit note → stock-out + Dr AP / Cr Inventory+ITC reversal. |

---

## 4. Improvements

1. **GRN return / quality-reject path.** GRN has RETURNED/IN_PROCESS/CLOSED states but no transition to them — no way to reject/return part of a receipt. Pairs with P3-J.
2. **Make the amount-drift check configurable, not log-only.** Current >1% header drift only writes `match_result` and never blocks (by design per CLAUDE.md flexibility), but there is no UI surfacing and no threshold to *hold*. Accountant-04 persona wants a hold queue (ON_HOLD) for material variance.
3. **Idempotency replay not verified for dedup.** Middleware enforces key *presence* (400 confirmed live) but actual response-cache dedup on retry was not exercised (would mutate seeded data). Add an integration test that double-fires `post`/`receive` with the same key and asserts single side-effect.
4. **GRN posts everything to the firm's `MAIN` default location**, ignoring any multi-warehouse intent — no location selector on receive.
5. **`create_pi` accepts items not on the linked GRN/PO** — should restrict line items to received items.
6. **PO cancel after DRAFT GRN exists** should at minimum warn/cascade-void the dangling DRAFT GRN (ties to P1-A).

---

## 5. Invariant violations

- **GL conservation broken (P1-E):** goods received (₹365,850) and PIs posted (₹392,509.50 incl GST) produce **no** AP, ITC, or Inventory-debit postings → Trial Balance has no Sundry Creditors and Inventory runs negative (#18). Double-entry incomplete for the entire purchase cycle.
- **State-machine monotonicity broken (P1-A):** a terminal CANCELLED PO can transition back to FULLY_RECEIVED. Cancel is not actually terminal/guarded against the GRN path.
- **Qty conservation broken (P1-B):** Σ received may exceed Σ ordered with no ceiling; PO marked FULLY_RECEIVED while over-received. No PO↔GRN↔PI quantity reconciliation exists (P2-F).
- **Valuation integrity (P2-C):** weighted-average cost can be silently pulled toward 0 by null-rate receipts; `current_cost` is otherwise correct (78/79 rows) — the report-layer ₹0 is the separate #21 column-read bug, but this path can corrupt the source pool.
- **Tenancy (P2-H):** org RLS holds (cross-org PI invisible, verified live) but firm isolation is unenforced on every procurement write.
