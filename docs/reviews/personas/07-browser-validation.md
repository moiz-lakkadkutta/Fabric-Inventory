# Persona Findings — Live Browser Validation (2026-06-20)

Walking each persona's headline findings in the real UI (Chrome MCP, live backend + seeded data) to confirm the code/API deep-dive visually, one persona at a time. Screenshots in `validation-2026-06-20/`.

| Persona | Finding validated in browser | Result |
|---------|------------------------------|--------|
| 1 Multi-firm owner | Firm switcher lists only **one firm**; **"+ Add a firm" is a dead placeholder** (a `<div>`; clicking changes nothing — no nav, no modal); hardcoded **"FY 2025-26"** label sits in the switcher header. | ✅ Confirmed — `p1-firm-switcher.png` |
| 1 Multi-firm owner | Dashboard & all reports are scoped to a single firm ("…for Demo Firm"); no consolidated/group view. | ✅ Confirmed (dashboard header) |
| 2 Manufacturer | A **COMPLETED** MO (0007, 10 pcs incl. zardosi embroidery) shows **₹—** on the Cost tab; backend `cost_pool=0.00`, every op `cost_accrued=0.00` → finished goods costed at **₹0**. | ✅ Confirmed — `p2-mo-cost-completed.png` |
| 3 Trader | **New item** form has only code/name/type/UOM/HSN/GST% — **no sale price, cost, MRP, or purchase price.** No way to price an item or see margin. | ✅ Confirmed — `p3-new-item-form.png` |
| 3 Trader | Stock report shows RATE/VALUE ₹0.00 for all items (value lives in `stock_position.current_cost`, report reads NULL `lot.primary_cost`). | ✅ Confirmed earlier — `../screens-2026-06-20/36-stock-report.png` |
| 4 Accountant | **Khata IS built & correct** — Reports › Party statement gives Lakshmi's full running ledger (Opening ₹0 → DR 7,168 → CR 4,300.80 → DR 7,168 → **Closing ₹10,035.20**), matching the Ageing report. #22 is a *placement/wiring* gap (it's in Reports, not on the Party screen), not "missing". | ✅ Confirmed — `p4-party-statement-lakshmi.png`, `p4-ageing-report.png` |
| 4 Accountant | **NEW bug:** Party statement shows the **wrong voucher number** — Lakshmi's 2nd sale (₹7,168, 2026-05-24) is really **RT/DEMO/0006** but is labelled **RT/DEMO/0004** (amount/date/balance correct). Voucher-number mapping is off. | ⚠️ New finding — DB: firm has only 0001 & 0006 for Lakshmi |
| 4 Accountant | **No Balance Sheet** anywhere — Reports tabs are P&L/TB/GSTR-1/Stock/Daybook/Ageing/Ledger/Party-stmt/ITC-04; BS absent (specced, 404). | ✅ Confirmed (tab list) |
| 5 Warehouse/Sales | New-invoice **item picker is a native `<select>`** (DOM-verified `SELECT`, no search/typeahead/barcode input on the line row); **RATE defaults to 0.00**, typed manually every line (no price memory). | ✅ Confirmed — `p5-new-invoice.png` |
| 6 Karigar/supplier | **ITC-04 is real & works** (May 2026: 2 send-outs, 1 receipt with challan/HSN/qty/wastage). But **karigar GSTIN column is blank** (decrypt skipped → unfileable) and **`nature_of_job` shows a raw UUID** ("MO operation f0018155-…") for the MO-linked job — finding #17 leaks into a GST return. | ✅ Confirmed — `p6-itc04-may.png` |

---

### Persona 5 — Warehouse / sales floor
Opened **New invoice**. The line-item **ITEM control is a native HTML `<select>`** (DOM-verified: `tagName === SELECT`, 10 options today; no `combobox`/`type=search`/barcode input anywhere on the row). **RATE renders `0.00` and must be typed every line** — no last-price recall (and per persona 3 the item has no price to recall). For a counter with hundreds of SKUs, scrolling a native dropdown per line is the headline speed tax — exactly where UX boost #1 pays off. *(p5-new-invoice.png)*

### Persona 6 — Karigar / supplier (external)
**ITC-04** (Reports › ITC-04, period → May 2026) populates correctly: 2 send-outs (Bharati 40m floral / Rafiq 5m plain) + 1 receive-back (36m received, 2m wastage) — the job-work goods loop and the GST-return preparer are genuinely built. Two defects make it unfileable as-is: the **karigar GSTIN column is blank** for both (PII decrypt skipped at the API boundary), and **`nature_of_job` prints a raw UUID** (`MO operation f0018155-…`) for the MO-linked job while the standalone JWO correctly reads "STITCHING" — i.e. bug #17 escapes into a statutory return. *(p6-itc04-may.png)*

---

## Browser-validation outcome

All six personas' headline findings were reproduced live in the UI. Net refinements to act on:
- **#22 downgraded in effort, upgraded in clarity:** the running khata is fully built and correct (Reports › Party statement / Ageing) — it just isn't on the Party screen. **Embed-the-existing-view (S)**, not build-from-scratch (L). The ₹0-vs-₹10,035.20 split between two screens is the single most quotable demo bug.
- **Manufacturing costing is visibly ₹0** end-to-end (a *completed* MO shows ₹— / `cost_pool=0`), confirming product cost is untrustworthy for pricing.
- **Two new bugs found while validating:** (a) party statement shows the **wrong voucher number** (0004 for what is really 0006); (b) the **#17 UUID leak reaches the ITC-04 GST return** + blank karigar GSTIN — elevate #17 from "cosmetic" to "compliance".
- **Trader pricing gap is absolute:** the item form has no price field at all.
- **Counter speed:** native-select item picker + manual rate = the clearest UX-boost target.

---

### Persona 4 — Accountant (the khata wiring gap, visualised)
The single clearest result of the whole session: **the same balance is ₹0 on one screen and ₹10,035.20 on another.**
- **Masters › Party › Lakshmi Saree Centre** → TOTAL BILLED / OUTSTANDING **₹0.00**, "No transactions for this party yet" (`../screens-2026-06-20/39-party-detail.png`).
- **Reports › Ageing** → Lakshmi **₹10,035.20** with 1-30/31-60 buckets; total ₹40,051.20 (`p4-ageing-report.png`).
- **Reports › Party statement › Lakshmi** → full voucher-level khata, Opening ₹0 → Closing **₹10,035.20** (`p4-party-statement-lakshmi.png`).
So the running khata — *the* core ledger for this trade — is fully implemented and correct; it's simply not surfaced where the owner looks for it (the party screen). That reframes #22 from "build the khata" (L) to "embed the existing party-statement on the party page" (S). While here I also caught a **voucher-number mislabel** in the statement (0004 shown for 0006) and confirmed **no Balance Sheet** exists.

> Data-hygiene aside (not a product bug): the dev DB holds multiple stale firms coded `DEMOFIRM` from repeated seeding; a `code='DEMOFIRM'` join double-counts. The *logged-in* firm `7a34d2bb` is clean: exactly 10 invoices, 10 distinct numbers, unique constraint on `(org,firm,series,number)` intact.

---

### Persona 1 — Multi-firm managing owner
Opened the **Demo Firm** switcher (top-left). The "Switch firm" menu contains exactly one entry (Demo Firm, checked) and a muted **"+ Add a firm — Owner only"** row. I'm logged in as the Owner, yet clicking it does nothing: a script-level click on the `<div>` left the URL at `/` with no dialog (matches agent finding — `/firms` is a 404, no firm router). The dropdown header also literally shows **"FY 2025-26"** — the hardcoded FE constant (`FirmSwitcher.tsx:11`) that drives report finding #20. Net: a managing owner cannot create or operate a second firm from the UI today. *(p1-firm-switcher.png)*
