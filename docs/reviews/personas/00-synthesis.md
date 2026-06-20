# Fabric ERP — Multi-Persona Deep-Dive Synthesis (2026-06-20)

**Method:** 6 parallel specialist agents reviewed the live system (seeded demo data, real backend + DB + source) each through one stakeholder lens, building on the 23-finding UI review (`../product-review-2026-06-20.md`). Every claim below is grounded in `file:line`, an API response, or a SQL result, and the highest-impact claims were re-verified by the orchestrator.

**Persona reports (read for detail):**
1. [`01-multi-firm-owner.md`](01-multi-firm-owner.md) — the headline persona
2. [`02-manufacturer.md`](02-manufacturer.md)
3. [`03-trader-distributor.md`](03-trader-distributor.md)
4. [`04-accountant-finance.md`](04-accountant-finance.md)
5. [`05-warehouse-sales-floor.md`](05-warehouse-sales-floor.md)
6. [`06-external-karigar-supplier.md`](06-external-karigar-supplier.md)

---

## Headline verdict

**Two genuinely strong engines sitting on a half-wired commercial spine.**

- ✅ **Sales-to-cash accounting** is exact (ties to the rupee, balanced GL, GST place-of-supply correct, finalized-invoice immutability, gapless numbering).
- ✅ **Manufacturing flow engine** is real and verified live (DAG cycle/self-loop/duplicate-edge all rejected `422`, QC 5-bucket conservation math sound, rework loop wired, completion posts balanced GL + weighted-avg FG cost).
- ⚠️ **Everything that turns those into a business** — purchase→GL, true product cost, supplier/karigar money, pricing/margin, multi-firm operation, counter-billing speed — is **schema-present, code-absent or unwired.**

For the **manufacturer customer trial**: physical flows are ready; the *numbers an owner buys an ERP for* (what a garment truly costs, what each supplier/karigar is owed, what stock is worth) are not yet trustworthy. **No P0 crashes; the gaps are completeness, not stability.**

---

## The core insight: four recurring root-cause patterns

Almost every gap across all six personas collapses into one of four patterns. Fixing by pattern is far cheaper than fixing by symptom.

### Pattern A — "Schema exists, code doesn't" (the dormant spine)
The DDL is impressively complete; large parts have **zero service/router code**. Verified-empty + no code: `price_list`, `item_uom_alt` (than/thaan units), discounts, `sales_return`/`purchase_return`, `customer_credit_profile`, `commission_scheme`, `landed_cost_entry`, `inter_firm_relationship` (`ddl.sql:1736`), and `JobWorkBill` (specced `architecture.md:433`, never built). → Trader pricing/returns/credit, multi-firm transfers, and karigar billing are all blocked on the same pattern.

### Pattern B — "Computed but not wired to the UI" (the quick wins) 🎯
The hard logic exists; a screen just doesn't call it. **These are the highest ROI fixes in the whole review.**
- **Stock value ₹0 (#21):** real weighted-avg is in `stock_position.current_cost` (78/79 rows populated) but `reports_service.py:566` reads `Lot.primary_cost` (NULL). ~1-line fix → stock value becomes real everywhere.
- **Party khata / outstanding (#22):** `/reports/ageing` returns real per-party buckets **right now** (verified: Lakshmi ₹10,035.20; total ₹40,051.20) — the Parties screen just shows ₹0 because it never calls it.
- **AR ageing, GSTR-1, ITC-04 preparer** — all real backend, under-surfaced.

### Pattern C — "Hardcoded / wrong-column FE constants" (trivial)
- **FY off-by-one (#20):** backend `fiscal_year_start` is **correct**; two hardcoded FE strings are wrong — `ReportsHub.tsx:58` and `FirmSwitcher.tsx:11` = `'FY 2025-26'` (Apr 2026 ∈ FY 2026-27).
- **FK UUIDs shown raw (#15, #17):** join-for-display not done on operations/job-work grids.

### Pattern D — "Purchase & conversion never reach the GL" (the one big rock) 🪨
The single most consequential gap; everything financial downstream depends on it.
- `post_pi` (`procurement_service.py:796`) only flips DRAFT→POSTED — comment admits *"GL voucher generation lives in TASK-041."*
- `receive_grn`→`add_stock` (`inventory_service.py:277`) writes stock ledger only, **no Voucher**.
- Live DB: **12 POSTED PIs = ₹367,350 + ₹25,159.50 GST → AP should be ₹392,509.50; zero PURCHASE vouchers exist.** Inventory runs *negative* (#18) because issues credit it but receipts never debit it.
- Same shape in manufacturing: WIP cost pool is **material-only** (`mo_completion_service.py:323`), `mo_operation.cost_accrued` hardcoded `Decimal("0")` (`qc_service.py:505`), and job-work tables have **no rate/charge columns** → labour/overhead/karigar cost is financially invisible, so product cost is systematically understated and no supplier/karigar payable can be computed.

---

## Verified refinements to the original 23 findings (mostly good news)

| Orig | Was reported as | Deep-dive reality (verified) |
|------|-----------------|------------------------------|
| #21 Stock value ₹0 | "costing not flowing" | **~1-line bug** — reads wrong column; completion *does* value FG (`current_cost=2400`). |
| #22 Party khata empty | "no endpoint, core gap" | **Wiring gap** — AR ageing/balance computed & live; supplier-side genuinely absent (Pattern D). |
| #20 FY off-by-one | "report period model" | **Backend correct**; 2 hardcoded FE constants. Trivial. |
| #18 Purchase→GL | "verify if implemented" | **Confirmed not implemented** (TASK-041 deferred); AP should be ₹392,509.50. The big rock. |
| S7 Role gating untested | "couldn't test" | **Verified genuinely enforced** — Warehouse/Salesperson permissions actually restrict. ✅ |

**New issues surfaced by the deep-dive (not in the 23):**
- 🔒 **Firm-spoof authorization gap (latent security):** manufacturing routers reject `body.firm_id != JWT firm`, but **sales & procurement do not** (`sales.py:107`, `procurement.py:124`); RLS is org-level only (no `app.current_firm_id`). Harmless today (1 firm/org) but a real cross-firm write hole the moment firm #2 exists.
- ⚠️ **Oversell:** stock decrements on **DC issue**, not invoice finalize (`sales_service.issue_dc`→`remove_stock`); a counter invoice cut *without* a DC never moves stock and isn't stock-checked.
- ⚠️ **Over-receipt silently accepted:** `create_grn` has no PO-qty ceiling check.
- ⚠️ **No credit/debit note, no voucher reversal, no payment-out flow, no Balance Sheet, no period lock** — can't correct a posted error or pay a supplier at all (accountant report).

---

## Multi-firm managing owner — deep dive (headline persona)

**Verdict: architecturally multi-firm-*aware*, operationally *not* multi-firm-ready.** The bones are real (per-firm GSTIN/`has_gst`, **org-shared masters** — 147/148 parties & 223/227 items have `firm_id=NULL`, so a customer is entered once for all firms — per-firm series/flags/books, JWT firm scoping). But an owner cannot actually run 2+ firms:

1. **Can't create a 2nd firm in-app (blocker)** — `/firms` is specced but unimplemented (`GET /firms`→404 live); the only firm-create path is signup (`auth.py:195`); FirmSwitcher "Add a firm" is a dead placeholder. (DB: 226/228 orgs have exactly 1 firm.)
2. **No consolidated/group reporting (blocker)** — Reports & dashboard hard-require one active firm (`reports.py:72`, `dashboard.py:30`); no group P&L/TB/receivables/stock. That's *the* reason to put a group on one system.
3. **No inter-firm operations** — `inter_firm_relationship` table exists with branch-transfer/tax-invoice/pricing columns but is schema-only. Inter-firm stock transfer (daily in textile groups, and the usual GST-firm ↔ cash-firm split) is impossible.
4. **Firm-isolation is unevenly enforced** (the firm-spoof gap above).

**Highest-leverage multi-firm customizations:** (a) in-app firm CRUD + real firm switcher; (b) a **group/consolidated dashboard & reports** with a firm filter (incl. a **group khata** — one customer's balance across all firms); (c) inter-firm stock transfer + the GST-firm/cash-firm document split native to this trade; (d) enforce `user_firm_scope` on every write before firm #2 ships.

---

## Per-persona trial-readiness scorecard

| Persona | Verdict | The one thing blocking them |
|---------|---------|------------------------------|
| Multi-firm owner | 🟠 aware, not ready | Can't create firm #2 / no consolidated view |
| Manufacturer | 🟠 amber | Product cost is material-only (no labour/karigar/overhead) |
| Trader/distributor | 🟠 half-wired | No pricing/margin; purchase→GL; stock value reads wrong column |
| Accountant/finance | 🔴 half the ledger | Purchase-to-pay never reaches GL; no payment-out / BS / period lock |
| Warehouse + sales floor | 🟡 close | Counter billing UX is clerk-grade; oversell possible |
| Karigar + supplier | 🟠 goods yes, money no | No karigar rate/payable; no khata; no JW e-way/DC PDF |

---

## Top UX boosts (cross-persona, ranked by leverage)

1. **Searchable / barcode item picker + last-price-&-party-rate memory + keyboard-first billing** *(M)* — the single biggest daily-speed win; today it's a native `<select>` over hundreds of SKUs with rates re-typed every line. Hits every counter user, every day.
2. **Wire the Party Khata screen to the existing `/reports/ageing`** *(S)* — instantly turns the dead ₹0 party screen into the running ledger this trade lives on. Data already exists.
3. **Consolidated multi-firm dashboard + group khata** *(M/L)* — the headline owner's core reason to adopt.
4. **Fix stock value (one column) + surface low-stock/reorder** *(S then M)* — makes Inventory, Stock report, and BS inventory all real at once.
5. **Decrement & check stock on invoice finalize (oversell guard)** *(M)* — correctness the floor will hit immediately on direct sales.
6. **Resolve FK UUIDs → names on operations / job-work / GRN grids** *(S)* — cheap polish that removes "raw database" feel (and stops a UUID leaking into the ITC-04 GST return).
7. **"Soon" badges on stub nav (Quotes/Returns/Credit-control) + drop placeholder login creds** *(S)* — stops trial users hitting dead ends.

---

## Customizations necessary (textile-trade specific)

- **Size / colour variant matrix** — biggest manufacturing tax today: every SKU needs its own full BOM + routing. A design→variant matrix is essential for ladies-suit production.
- **Than/thaan ⇄ meter ⇄ piece ⇄ set UOM conversions** (`item_uom_alt` exists, no code) — fabric is bought/sold/stocked in different units constantly.
- **Karigar piece-rate payroll + karigar khata + optional karigar portal** (`architecture.md:1075` open question) — job-work is core; today the money side is invisible.
- **Dye-lot / shade tracking & matching** (lot model exists, unused) — shade consistency is a real textile constraint.
- **Make-to-order** — link MO ↔ sales order (`manufacturing_order` has no `sales_order_id`).
- **GST-firm ↔ cash/non-GST-firm document split + inter-firm transfer** — the textile-group pattern CLAUDE.md is built around.
- **Broker/commission, landed cost** (schema present) — common in the wholesale fabric chain.

---

## Prioritized roadmap for the trial

**P0 — quick wins, do first (hours–days each, mostly Pattern B/C):**
- Stock value: read `stock_position.current_cost` not `Lot.primary_cost` (`reports_service.py:566`).
- Wire Party screen to `/reports/ageing` (khata + outstanding go live).
- Drop hardcoded `'FY 2025-26'` (`ReportsHub.tsx:58`, `FirmSwitcher.tsx:11`).
- Resolve FK UUIDs→names (#15/#17); fix invoice-line AMOUNT (#4); kill placeholder login creds (#2).

**P1 — trial-blocking completeness (the big rocks):**
- **Purchase + GRN → GL posting** (TASK-041): Sundry Creditors, Inventory debit, ITC. Unblocks supplier khata, AP, true stock-on-books, margin.
- **Conversion + job-work costing:** roll `cost_accrued` (labour/overhead) + karigar charges into the WIP pool → real product cost.
- **Karigar rate/charge + payable + `JobWorkBill`** (`architecture.md:433`).
- **Routing "clone graph"** (#13) and **qty auto-propagation between ops** (#12).
- **Oversell guard** on invoice finalize; **over-receipt** ceiling on GRN.

**P2 — multi-firm & correctness depth:**
- In-app firm CRUD + real switcher; **consolidated/group reporting + group khata**; inter-firm transfer.
- Enforce `user_firm_scope` on sales/procurement writes (close firm-spoof gap) before firm #2.
- Credit/debit notes + voucher reversal + payment-out; Balance Sheet; period lock.
- Pricing/discount/margin engine; returns; than/thaan UOM; size/colour variant matrix.

**P3 — polish:** HTTP security headers at the proxy (S5), "soon" badges on stubs, breadcrumb/formatting nits, party city seed, period-picker unification across report tabs.

---

*Six persona reports + this synthesis + the 23-finding UI review + 42 screenshots are all under `docs/reviews/`. No data was mutated during the deep-dive (all live probes were reads or intentionally-rejected validation calls); the only side effect is the throwaway `ZZ Rls Probe Org` from the earlier RLS test.*
