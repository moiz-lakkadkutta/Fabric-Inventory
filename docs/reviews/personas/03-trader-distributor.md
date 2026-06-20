# Persona Review 03 — Textile Trader / Distributor / Wholesaler

**Reviewer:** Senior ERP product analyst
**Date:** 2026-06-20
**Lens:** A fabric/suit **trader** — buys from mills & suppliers, sells to retailers/boutiques. **No manufacturing.** Lives on purchase→stock→sell margins, fast counter billing, negotiated pricing, and khata/credit.
**Baseline:** Builds on `docs/reviews/product-review-2026-06-20.md` (23 findings). Findings there are referenced by `#n`, not repeated. This review goes deeper on trader-specific flows with code + API + DB evidence.

---

## 1. Persona & Jobs-To-Be-Done

"Rajesh" runs a wholesale fabric/suit shop. His daily jobs:

1. **Buy smart:** raise PO to a mill, receive goods (often partial / over / short vs PO), match the supplier bill, track what he owes (creditors/khata).
2. **Know his cost:** landed cost per meter/than, weighted-avg as prices move, so he can price with a target margin.
3. **Price & discount fast:** different rates per customer/quantity, line & bill discounts, MRP vs wholesale — all negotiated at the counter.
4. **Bill in seconds:** repeat orders, convert quote→order→challan→bill, partial dispatch, barcode.
5. **Move stock:** in than/thaan & meters interchangeably, by lot/shade, across godowns.
6. **Control credit:** customer credit limits, overdue blocking, ageing, broker/dalal commission.
7. **Handle returns** both sides (sales return / purchase return) with correct GST credit/debit notes.

The manufacturing depth that dominates this build (MO/routing/QC/BOM) is **irrelevant** to him. What he needs is the *trading spine*, and that spine is where the gaps cluster.

---

## 2. What Works Well Today (evidence)

| Area | Evidence |
|------|----------|
| **PO→GRN→PI chain & partial receipt** | `procurement_service._advance_po_status_after_grn` sums cumulative `grn_line.qty_received` per `po_line` and sets `PARTIAL_GRN` / `FULLY_RECEIVED` correctly. Multiple GRNs per PO supported. |
| **Weighted-average costing actually works** | `inventory_service.add_stock` blends `new_cost = ((old_qty*old_cost)+(qty*unit_cost))/new_qty` into `stock_position.current_cost`. DB confirms real values: FAB-SILK-44 `current_cost=432.73`, FAB-COTT-44 `86.87`, etc. Cost flows from GRN line rate into the position. |
| **Stock posting on receive & dispatch** | `receive_grn` posts each line via `add_stock` (cost = GRN line rate); `sales_service.issue_dc` posts outbound via `remove_stock`. Stock ledger (184 rows) + positions are live. |
| **Negative stock is prevented** | DB CHECK `stock_position_on_hand_qty_non_negative` + `remove_stock` raises `AppValidationError("Insufficient stock: on_hand … < requested …")`. No silent overselling. |
| **Ageing report exists and is correct** | `GET /reports/ageing` returns real buckets: Lakshmi ₹10,035.20 (1-30 ₹7,168 / 31-60 ₹2,867), Mehta ₹17,920, total outstanding ₹40,051.20 — reconciles to AR. `compute_ageing` + `compute_party_statement` are wired routers. |
| **SO→DC→Invoice linkage in schema** | `delivery_challan.sales_order_id`, `sales_invoice.sales_order_id` + `delivery_challan_id` exist; DC creation validates the SO is CONFIRMED+ and advances it. Partial dispatch (many DCs per SO) is modelled. |
| **Sales→GL exact** | (Per `#✅`) Sales side reconciles to the rupee with correct IGST/CGST place-of-supply. |

**The bones of a trader system are present.** The problem is muscle: most trader-grade tables exist in `schema/ddl.sql` but have **zero service/router/UI code**.

---

## 3. Gaps / Missing for a Real Trader (ranked, evidence)

> Verified each "dormant table" by grepping `routers/` + `service/` — **NONE matched** (`price_list`, `commission`, `customer_credit_profile`, `landed_cost`, `purchase_return`, `sales_return`, `item_uom_alt` → all `NONE`). They are Phase-1 schema stubs with no behaviour.

**G1 — No purchase→GL posting (books are half-blind).** *(extends #18)* `post_pi` only flips state DRAFT→POSTED; the docstring says "GL voucher generation lives in TASK-041." So no Sundry Creditors/AP is ever created, no purchase expense/inventory debit. A trader's #1 question — *"how much do I owe each supplier?"* — is unanswerable from the books. This is the single biggest trader blocker.

**G2 — No pricing engine; items carry no price or cost.** The `item` table has **no** `sale_rate`, `purchase_rate`, `mrp`, or `standard_cost` column (verified full DDL). Every PO/SO/invoice line price is typed by hand. The `price_list` / `price_list_line` tables (party-specific pricing, `min_qty` quantity tiers, validity dates, `selling_price`) **exist but are empty and unwired**. A trader who quotes different rates per customer/quantity gets no help — and no default price means slow, error-prone billing.

**G3 — No discounts anywhere.** `grep -i discount schema/ddl.sql` → **nothing**. `si_line` columns are only `qty, price, line_amount, gst_*`. No line discount, no bill/doc discount, neither % nor flat. Indian fabric trade is *all* negotiated discount — this is a hard blocker for real billing.

**G4 — No margin visibility.** No cost is shown against sell price on any sales screen; item has no standard cost; and the valuation report is broken (G6). A trader cannot see gross margin per line, per bill, or per customer.

**G5 — Multi-UOM / than↔meter conversion absent.** `uom_type` enum = METER/PIECE/KG/LITER/SET/GROSS/DOZEN/ROLL/BUNDLE/OTHER — **no than/thaan**. The `item_uom_alt` table (`from_uom, to_uom, conversion_factor`) exists but is **empty + no code**. Lines use only `item.primary_uom`; no per-line UOM, no conversion. He cannot stock in than and sell in meters (the textile default).

**G6 — Stock valuation reads the wrong column → ₹0.** *(root cause of #21)* The weighted-avg cost is **present** in `stock_position.current_cost`, but `reports_service.compute_stock_summary` values stock from `func.coalesce(Lot.primary_cost, 0)` instead. With only 1 `lot` row and NULL lot costs, every line valuates to ₹0. **The data exists; the query joins the wrong table.** One-line-of-logic fix (use `current_cost`) unlocks real stock value.

**G7 — No returns, either side.** `sales_return`/`sr_line` and `purchase_return` tables exist, empty, **no code**. No credit note / debit note, no GST reversal. *(extends the #stubs note — confirmed there is no backend at all, not just a UI stub.)*

**G8 — No credit control enforcement.** `customer_credit_profile` (`credit_limit, credit_days, used_credit, available_credit`) exists, empty, **no service/router**; UI is a TASK-055 stub. Nothing blocks an over-limit or overdue customer at invoice time. (Ageing *reporting* works — see §2 — but it's passive.)

**G9 — No broker/commission.** `commission_scheme` table exists, empty, no code. Dalal/broker commission is standard in fabric wholesale; nothing supports it.

**G10 — No landed cost.** `landed_cost_entry` table exists, empty, no code. Freight/octroi/coolie can't be apportioned into item cost — so even the weighted-avg cost understates true landed cost.

**G11 — No stock transfer / reorder levels.** Only `stock_adjustment` (INCREASE/DECREASE/COUNT_RESET) — no location-to-location transfer endpoint. No reorder-point field on item or position; no "what to reorder" view.

**G12 — Khata exists but is hidden.** *(refines #22)* `GET /reports/party-statement/{id}` and `/reports/ageing` return real per-party transactions & balances — but the **Party detail screen doesn't call them**, so it shows all ₹0. The khata is *computed and unsurfaced*, not missing. Cheap to wire up.

---

## 4. Edge Cases Tested (probe + result)

> Per harness rules I did **not** create/finalize records; over/short-receipt behaviour is read from the code path, valuation/ageing/negative-stock from DB + live API.

| Edge case | Probe | Actual result |
|-----------|-------|---------------|
| **Over-receipt** (GRN qty > PO qty) | `create_grn` line validation | Only checks `qty_received > 0`. **No comparison to `po_line.qty_ordered`.** Over-receipt is silently accepted; `_advance_po_status_after_grn` still marks PO `FULLY_RECEIVED` (uses `received < ordered` for "partial", so excess just reads as full). No block, no warning. |
| **Short-receipt** | same | Handled correctly → `PARTIAL_GRN`, PO stays open. |
| **Price variance** (PI rate ≠ PO/GRN rate) | `post_pi` 3-way match | **Loose, total-only:** warns when `|PI_total − GRN_total| / GRN_total > 1%`, writes `match_result={"warning":"amount_drift"}`, **never blocks**. No line-level price check, no qty match PI↔GRN at all. (Intentional per CLAUDE/Moiz, but a trader gets no variance report.) |
| **Receiving without PO** | `create_grn(purchase_order_id=None)` | Allowed; `po_line_id` optional; stock posts fine. Good for ad-hoc buys. |
| **Negative stock on sale** | DB CHECK + `remove_stock` | **Blocked.** `on_hand < qty` → `Insufficient stock` error; DB CHECK backstops. Note: `item.allow_negative` column exists (default `NEVER`) but `remove_stock` **ignores it** — even a firm that *wants* negative billing can't. Rigid. |
| **Stock valuation** | `psql` on `stock_position` vs report | `current_cost` populated (silk 432.73, value ≈ ₹87,844) but `compute_stock_summary` → ₹0 (reads `lot.primary_cost`). Confirmed root cause of #21. |
| **Khata / ageing** | `GET /reports/ageing` (live) | Returns real buckets (₹40,051.20 total). Data correct; just not on the party screen (#22/G12). |
| **Location fragmentation** | `psql location` | 228 "MAIN" rows — but across **228 distinct firms/orgs** (test-org noise), not within Demo. Within Demo a few items span up to 4 position rows/locations; inventory views must aggregate. Minor. |

---

## 5. Customizations Required (textile-trade specific)

1. **Than/thaan as a first-class UOM + conversion** — add `THAN` to `uom_type`, wire `item_uom_alt` (`1 than = N meters`, `is_fixed` for fixed-length pieces vs variable thans), and allow per-line UOM with auto-conversion to stock UOM. Without this the app can't speak the trade's language.
2. **Lot / shade-batch matching** — `lot` table exists but unused for valuation/selection. Traders sell by shade-lot ("same dye-lot only"); need lot capture on GRN, lot-wise stock, and lot pick on DC/invoice.
3. **Broker / dalal commission** — wire `commission_scheme`: commission % per broker/party, accrued on sales, payable ledger. Core to wholesale.
4. **Landed-cost apportionment** — wire `landed_cost_entry` to push freight/coolie/octroi into weighted-avg cost per GRN.
5. **Party-specific & quantity-tier price lists** — wire `price_list`/`price_list_line` (already party-specific + `min_qty`) so the counter auto-fills the right rate; add MRP + wholesale + retail tiers on the item.
6. **Bill-level & line-level discount (% and flat)** — schema change to `*_line` + header; non-optional for real billing.
7. **Cash-memo / estimate fast path** — counter sale without full invoice ceremony (aligns with CLAUDE non-GST-first-class decision).

---

## 6. Top UX Boosts (ranked)

| # | Boost | Why | Effort |
|---|-------|-----|--------|
| 1 | **Fix stock valuation to read `stock_position.current_cost`** | The value already exists; one wrong join shows ₹0 across the app. Instantly unlocks stock-value + margin reporting. | **S** |
| 2 | **Surface khata on the Party screen** (call existing `/reports/party-statement` + `/reports/ageing`) | Data is already computed; the trader's most-used screen currently lies (₹0). Pure wiring, huge perceived value. | **S** |
| 3 | **Post PI→GL (Sundry Creditors / AP)** | Without it, "what do I owe?" is unanswerable and the TB shows no creditors + negative inventory (#18). Core books integrity. | **L** |
| 4 | **Default item price + line/bill discount on invoice** | Cuts billing time and matches how every fabric bill is actually written (rate − discount). | **M** |
| 5 | **Than↔meter multi-UOM with conversion** | Lets the app handle real textile stock & billing; blocks adoption otherwise. | **M** |
| 6 | **Over/short-receipt indicator + price-variance report on GRN/PI** | Show received-vs-ordered and PI-vs-GRN deltas (don't block, just surface) so the trader catches supplier short-shipments and price creep. | **M** |
| 7 | **One-click convert Quote→SO→DC→Invoice (copy lines forward)** | Linkage columns already exist; pull prior-doc lines into the new doc instead of re-keying. Big speed win for repeat orders. | **M** |

---

## Verdict

For a **pure trader**, this build is a strong *accounting + manufacturing* engine sitting on a *trading spine that is only half-wired*. The hard parts (weighted-avg costing, RLS, GST, ageing math, doc linkage) are done correctly; the trader-facing muscle (pricing, discounts, returns, credit limits, multi-UOM, landed cost, commission, purchase→GL) is dormant schema with no code. Several high-impact fixes are nearly free because the data already exists and only the read/wiring is wrong (valuation, khata).
