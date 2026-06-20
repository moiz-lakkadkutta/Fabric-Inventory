# Persona Review 04 — Accountant / Finance Controller

**Reviewer lens:** the person who closes the books monthly, files GST, reconciles bank + party khata, and signs the balance sheet. Money correctness is non-negotiable: a ₹1 hole is a bug, not a rounding nit.
**Date:** 2026-06-20 · **Build:** live backend `localhost:8000`, demo org "Demo Co", read-only DB.
**Builds on** `docs/reviews/product-review-2026-06-20.md` (findings referenced as #1–#23; not repeated). This review root-causes the accounting cluster in the service code and quantifies it.

---

## 1. Persona & jobs-to-be-done

| JTBD | Needs | Status |
|------|-------|--------|
| Close the month | Balanced TB, P&L, **Balance Sheet**, period lock | TB + P&L only; **no BS, no period lock** |
| File GSTR-1 | B2B/B2CL/B2CS/Export + HSN, correct IGST vs CGST+SGST | **Works, ties to the rupee** |
| File GSTR-3B / claim ITC | Output GST − Input GST (ITC) | **No ITC** (purchases never post) |
| Run the khata | Per-party AR **and AP** ledger + ageing | AR side works; **AP side empty** |
| Pay suppliers | Payment voucher → Creditors | **No payment-out flow at all** |
| Reconcile to Vyapar | OB import within ±₹1 | Import balances internally; **not compared to Vyapar's TB** |
| Correct a mistake | Reverse / contra / credit-note | **No reversal, no credit/debit note** |

---

## 2. What's correct today (evidence)

- **Sales → GL is exact.** `accounting_service.post_invoice_to_gl` (accounting_service.py:84-206) posts DR Sundry Debtors / CR Sales / CR GST Payable with a balanced-bundle invariant asserted before *and* after flush (lines 192-204). Live TB: Sundry Debtors ₹40,051.20, Sales ₹39,600.00, GST Payable ₹4,752.00, DR=CR=₹70,890.90, `balanced:true`.
- **Receipts tie.** `receipt_service.post_receipt` (receipt_service.py:132-301) does FIFO allocation oldest-first (deterministic tiebreaker on number), bumps `paid_amount`, transitions PARTIALLY_PAID/PAID, posts DR Cash/Bank / CR Sundry Debtors. AR after receipt = ₹40,051.20 reconciles to ageing total exactly.
- **Double-entry is enforced.** Both auto and manual posting paths assert Σ DR == Σ CR and re-query persisted lines (accounting_service.py:404-423). Manual JV (`post_journal_voucher`) hardens against direct posts to **control accounts** (lines 310-314) and **inactive ledgers** (301-305), and translates the voucher-number race into a clean 422 (lines 373-388). This is genuinely good accounting hygiene.
- **GST place-of-supply is correct.** `gst_service.determine_place_of_supply` (gst_service.py:96-186): inter-state is **always IGST regardless of value** (INT-11 fix, lines 162-179) — the ₹2.5L threshold is correctly used only as a GSTR-1 B2CL/B2CS bucket, not a tax flip. `split_tax` puts the odd-paise remainder on SGST so CGST+SGST == total (lines 210-214). Same-GSTIN branch transfer → NIL_NOT_A_SUPPLY + Delivery Challan (lines 116-123).
- **GSTR-1 is real.** `reports_service.compute_gstr1` (reports_service.py:1290-1554): B2B/B2CL/B2CS/Export/HSN buckets, **decrypts the real plaintext GSTIN** for the filing (lines 1330, 1416-1420) rather than leaking ciphertext, HSN summary grouped by hsn+uom+tax_type.
- **Migration OB import balances.** `migration_service.upload_and_reconcile` (migration_service.py:195-204) computes `tb_diff = debits − credits` and gates on `tb_diff == 0` (exact, stricter than the ±₹1 target). Opening-balance voucher is posted on approve (`_post_opening_balance_voucher`).
- **AR ageing + party statement endpoints exist** (`GET /reports/ageing`, `GET /reports/party-statement/{id}`, `GET /reports/ledger-statement`) — partially closes #22 on the *sales* side.
- **Immutability holds.** No `update_invoice`/`edit_invoice` in `sales_service`; `finalize_invoice` only allows DRAFT→FINALIZED (sales_service.py:954-963). Finalized invoices cannot be edited or hard-deleted.

---

## 3. Accounting integrity gaps (ranked, root-caused)

### G1 — Purchases never post to the GL (confirms & root-causes #18). **P1 for a trial.**
Two independent breaks in the chain:
- **GRN receipt does not touch the GL.** `procurement_service.receive_grn` (procurement_service.py:567-580) calls `inventory_service.add_stock`, which (inventory_service.py:277-343) writes **only** `stock_ledger` + `stock_position` — there is **no Voucher/VoucherLine** anywhere in that function. So a received GRN never debits GL **Inventory** nor credits a **GRNI / Goods-Received-Not-Invoiced** account. (There is no GRNI account in the COA at all.)
- **PI posting only flips a status flag.** `procurement_service.post_pi` (procurement_service.py:796-836) literally documents it: *"GL voucher generation lives in TASK-041; this stage just advances the state."* DRAFT→POSTED with zero journal lines. No credit to **Sundry Creditors (AP)**, no debit to **Input GST (ITC)**.

Meanwhile `material_issue_service` **does** post DR 1310 WIP / CR 1300 Inventory (material_issue_service.py:20-21, 61-62). So Inventory gets credited (issues) but never debited (receipts) → the ledger runs **negative**.

**Quantified (live):** 12 POSTED purchase invoices = net ₹367,350.00 + GST ₹25,159.50. Posted voucher types: `RECEIPT, MANUFACTURING_COMPLETION, SALES_INVOICE, MATERIAL_ISSUE` — **zero PURCHASE vouchers**.
**What the books *should* show:** DR Inventory ₹367,350 (or DR Purchases), DR Input-GST/ITC ₹25,159.50, **CR Sundry Creditors ₹392,509.50**. Today: Creditors absent, Inventory shows **CR ₹26,538.90** (the orphaned material-issue credit). Net effect: **payables, COGS, ITC, and true stock value are all missing from the GL.**
**Fix:** add a `post_pi_to_gl` (DR Inventory/Purchases + DR Input GST / CR Sundry Creditors), and post GRN→GL (DR Inventory / CR GRNI) with PI clearing GRNI; seed GRNI + Input-GST ledgers in the COA.

### G2 — No supplier khata / no payable side of the party ledger. **P1.**
`reports_service.compute_party_statement` only classifies `SALES_INVOICE/DEBIT_NOTE` (DR) and `RECEIPT/CREDIT_NOTE` (CR) voucher types (reports_service.py:955-958). There are **no purchase-invoice or payment vouchers**, so a supplier's statement is permanently empty regardless of #18. Compounding: **there is no payment-out flow at all** — `receipt_service` is customer-only; no `VoucherType.PAYMENT`. A supplier balance can never be created *or* settled. For a textile firm that lives on supplier khata, this is a core hole.
**Also:** masters `get_party` (masters_service.py:158) returns the Party row with no balance computation, so the party-detail page still shows ₹0 (#22 symptom persists) — the khata lives under `/reports`, never wired into `/parties/{id}`.

### G3 — Stock valuation reads the wrong column (root-causes #21). **P2.**
The cost **is** captured: `add_stock` maintains weighted-average `stock_position.current_cost` (inventory_service.py:317-322). But `compute_stock_summary` values stock off `lot.primary_cost` (reports_service.py:566-567), and lots are created without `primary_cost` (DB: 1 of N lots has a cost). So valuation joins to NULL→₹0. This is a **column mismatch**, not missing data.
**Fix:** value off `stock_position.current_cost` (already weighted-avg per receipt), or backfill `lot.primary_cost` on receipt. Note this still won't reconcile to a GL Inventory figure until G1 is fixed.

### G4 — No Balance Sheet; no period lock/close. **P2.**
`/reports/balance-sheet` is specced (api-phase1.yaml:4436) but **not implemented** — returns 404 live. Only TB exists. P&L groups already tag ASSET/LIABILITY/EQUITY (reports_service.py:80), so a BS is a short grouping job on top of `compute_tb`. **No period-lock table or close mechanism anywhere** (grep: none) — nothing stops a back-dated voucher into a filed month. A controller cannot "close" April.

### G5 — No reversal / credit note / debit note. **P2.**
`CREDIT_NOTE`/`DEBIT_NOTE` exist as enum values and are *read* by the party statement, but **no service creates them** (grep for `VoucherType.CREDIT_NOTE` producers = 0; sales returns = "Coming soon TASK-038"). Combined with control-account JV blocking (correctly) at accounting_service.py:310-314, there is **no supported way to correct a wrong receipt or post a sales/purchase return**. Immutability is good; the *escape hatch* (contra/reversal) is missing.

### G6 — Advances and TDS not really handled. **P3.**
`post_receipt` over-allocation credits the **full** AR (receipt_service.py:263-273) — pushing AR negative as a de-facto customer advance — but the unallocated remainder gets **no allocation row**, and the docstring's claim that "the next finalize will draw it down" (lines 152-155) is **not implemented**. There's no advance/on-account ledger and no manual allocation (FIFO only). `tds_amount` is hardcoded `Decimal("0")` (line 229).

---

## 4. GST compliance status (built / stubbed / flag-gated)

| Capability | State | Evidence |
|-----------|-------|----------|
| Place-of-supply engine (goods) | **Built & correct** | gst_service.py:96-186; inter-state always IGST |
| CGST/SGST/IGST split | **Built**, paise-exact | gst_service.py:202-215 |
| GSTR-1 (B2B/B2CL/B2CS/Export/HSN) | **Built**, plaintext GSTIN | reports_service.py:1290-1554 |
| **GSTR-3B** | **Missing** | no service |
| **ITC on purchases** | **Missing** (blocked by G1) | no Input-GST ledger movement |
| **e-invoice IRN JSON payload** | **NOT built** | grep `irn/einvoice` in services = 0 hits. CLAUDE.md §6 claims this ships in Phase 1 behind a flag — only the flag *key* exists (`gst.einvoice.enabled`), not the payload builder |
| **e-way bill** | **NOT built** | grep = 0 |
| Reverse charge (RCM) | **Stub** | `rcm_applicable` stored on PI (procurement_service.py:658) with **no posting effect**; gst_service docstring lists RCM (scn 28) out of scope |
| Job-work ITC-04 | **Not built** | — |
| Services PoS, bill-to-ship-to, composition seller, return GST | **Out of scope** | gst_service.py:15-22 |

**Bottom line:** output-GST machinery (PoS, split, GSTR-1) is real and trustworthy. Everything input-side (ITC, 3B) and the e-invoice/e-way "drop-in" promised in CLAUDE.md are **not yet built**.

---

## 5. Edge cases tested (probe → result)

| Probe | Result |
|-------|--------|
| `GET /reports/tb` balances? | ✅ DR=CR=₹70,890.90, `balanced:true` |
| `GET /reports/balance-sheet` | ❌ **404** (not implemented) |
| Posted voucher types in DB | RECEIPT, MANUFACTURING_COMPLETION, SALES_INVOICE, MATERIAL_ISSUE — **no PURCHASE** |
| 12 POSTED PIs → AP in TB? | ❌ no Sundry Creditors row; ₹392,509.50 missing |
| Inventory ledger sign | ❌ **CR ₹26,538.90** (negative asset) |
| Lots with cost | 1 lot has `primary_cost`; valuation report → ₹0 |
| Supplier party statement | empty (no purchase/payment vouchers) |
| FY label source | hardcoded FE string `ReportsHub.tsx:58 = 'Apr 2026 · FY 2025-26'` + `FirmSwitcher.tsx:11` — backend `fiscal_year_start` (reports_service.py:60-72) is **correct**; the off-by-one (#20) is **purely a hardcoded, wrong FE constant** (Apr 2026 ∈ FY 2026-27) |
| Finalized invoice editable? | ✅ No — no update path; DRAFT→FINALIZED only |
| Migration OB reconcile gate | `tb_diff == 0` exact (migration_service.py:201) — but compares import internal DR/CR, **not** against Vyapar's reported TB |

---

## 6. Customizations & must-fixes for a trial (ranked)

1. **G1 — Post purchases to the GL** (PI → DR Inventory/Purchases + DR Input GST / CR Creditors; GRN → DR Inventory / CR GRNI). Seed GRNI + Input-GST ledgers. Without this the books are structurally incomplete: no payables, no COGS, no ITC, negative stock. **Largest single fix.**
2. **G2 — Supplier payment-out flow + AP in party khata.** Add `VoucherType.PAYMENT` + payable classification in `compute_party_statement`. A textile trial without supplier khata won't survive week 1.
3. **G3 — Fix stock valuation column** (`stock_position.current_cost`) — small, high-visibility.
4. **#20 FY label** — delete the two hardcoded FE constants, derive from backend `fiscal_year_start`; unify the period control across report tabs. Trivial but the wrong-FY label erodes trust instantly.
5. **G4 — Balance Sheet report** (grouping on `compute_tb`) + a **period-lock** table before a real close.
6. **G5 — Credit/Debit note + voucher reversal** so mistakes are correctable.
7. **Vyapar reconcile** — compare imported OB TB against the *Vyapar-reported* TB total (not just internal DR=CR) to actually meet the ±₹1 target.

## 7. Top UX/correctness boosts (ranked, with effort)

1. **Purchase→GL posting (G1)** — why: the #1 correctness hole; books are unusable for close without it. **L**
2. **Supplier payment + AP khata (G2)** — why: core daily textile workflow. **M**
3. **Stock valuation column fix (G3)** — why: one-line query change turns ₹0 into real numbers. **S**
4. **FY label + unified period picker (#20)** — why: hardcoded wrong constant visible on every report. **S**
5. **Balance Sheet + period lock (G4)** — why: a controller cannot "close" without them. **M**
6. **Credit/Debit notes + reversal (G5)** — why: no legal way to fix a posted error today. **M**
7. **Wire party khata into `/parties/{id}` + ITC/GSTR-3B once G1 lands** — why: surfaces the already-built `/reports/party-statement` on the screen accountants actually open, and unblocks input-GST. **M**

---

### Bottom line (can the books be trusted for a trial?)

**Half the ledger is trustworthy, half is missing.** The **sales-to-cash side is genuinely solid** — sales→GL, receipts, AR ageing, GSTR-1, and place-of-supply all reconcile to the rupee with real double-entry discipline and good invariants. But the **entire purchase-to-pay side never reaches the GL**: 12 posted purchase invoices (₹392,509.50) produce **zero** vouchers, so there are **no payables, no COGS, no ITC, and a negative Inventory balance** — the TB "balances" only because the missing entries are absent on both sides. A trial customer could invoice and collect honestly, but **could not close a month, file GSTR-3B, claim ITC, or run a supplier khata**.

**Top 5 must-fix:** (1) post purchase invoices + GRN to the GL [G1, the big one], (2) supplier payment-out flow + AP party khata [G2], (3) fix stock valuation to read `stock_position.current_cost` not `lot.primary_cost` [G3/#21], (4) drop the hardcoded wrong FY label and unify report periods [#20], (5) ship Balance Sheet + a period-lock before any real close [G4]. e-invoice IRN/e-way are *not built* despite CLAUDE.md implying Phase-1 readiness — fine while under ₹5 Cr, but don't represent them as done.
