# Flow Review 09 — GST Engine (place-of-supply · tax-status · invoice types · GSTR · e-invoice/e-way · RCM · rounding)

**Slice:** `00-flow-machine.md` §C "GST engine" (line 50) + Tax-status machine (line 23).
**Date:** 2026-06-20 · **Build:** live backend `localhost:8000`, org "Demo Co", read-only DB.
**Oracle:** `specs/place-of-supply-tests.md` (30 canonical scenarios).
**Builds on (not repeated):** product-review #1–#23 (GSTR-1 good; IGST for PoS=DL); personas/04-accountant §4 (e-invoice IRN + e-way NOT built despite CLAUDE.md §6; RCM boolean no posting effect; GSTR-1 decrypts GSTIN to plaintext — confirmed correct). This review root-causes the engine in `gst_service.py` + the live invoice path and grades every oracle row.

---

## 1. Flows under test (where GST is decided)

```
create_draft_invoice (sales_service.py:776-935)
  ├─ per-line gst_amount = line_amount * gst_rate/100   [gst_rate = client-supplied, line 823]
  │     ↑ computed BEFORE & INDEPENDENT of tax_type  ← decoupling bug (B3)
  ├─ _classify_buyer(party) → REGISTERED | CONSUMER ONLY  (sales_service.py:767-772)
  │     ↑ ignores party.tax_status enum entirely        ← B1 (root cause)
  └─ gst_service.determine_place_of_supply(...)  (gst_service.py:96-186)
        → (tax_type, pos_state, document_type, gstr1_section)
        ↳ lut_active NEVER passed by caller (defaults False)   ← B2
        ↳ buyer_status only ever REGISTERED/CONSUMER → SEZ/EXPORT/EOU branches DEAD live

split_tax (gst_service.py:202-215)         → CGST/SGST/IGST money split   [paise-exact ✓]
   used by: pdf_service.py:283 (per line) · reports_service compute_gstr1:1370,1490
compute_gstr1 (reports_service.py:1290-1554) → B2B/B2CL/B2CS/Export/HSN  [ties live ✓]
round_off (sales_service.py:886)           → hardcoded Decimal("0"), never computed   ← B4
e-invoice IRN / e-way                       → columns only; NO builder, NO endpoint (404)
GSTR-3B / RCM posting / credit-note         → not built (404 / boolean-only)
```

The engine is a clean pure function and is **internally correct for the goods scenarios it claims** (docstring lines 7-22). The damage is at the **boundary**: the caller never feeds it the tax_status, LUT, SEZ/export, or service-nature signals it would need to reach the rest of the matrix, so ~half the oracle is unreachable on the live path even where the branch exists in code.

---

## 2. Place-of-supply test matrix (oracle row → code/API actual → verdict)

Actual = behaviour of the **live invoice path** (`create_draft_invoice` → `_classify_buyer` → `determine_place_of_supply`). "engine-only" = the branch exists in `gst_service` but is unreachable from the API because `_classify_buyer` can't produce that `buyer_status` / `lut_active` is never passed.

| # | Scenario | Expected (oracle) | Code/API actual | Verdict |
|---|----------|-------------------|-----------------|---------|
| 1 | Intra B2B MH→MH | CGST+SGST / MH / Tax Inv | REGISTERED→CGST_SGST/MH/B2B | ✅ PASS |
| 2 | Inter B2B MH→KA | IGST / KA | IGST/KA/B2B | ✅ PASS |
| 3 | Intra B2C MH | CGST+SGST / MH | CONSUMER→CGST_SGST/MH/B2CS | ✅ PASS |
| 4 | Inter B2C ≤₹2.5L MH→KA | **CGST+SGST / MH** (§10(1)(d)) | **IGST/KA**/B2CS | ⚠️ DEVIATES — code does IGST (INT-11 "always IGST"); ₹2.5L used only as B2CL/B2CS bucket. **Code is arguably more legally correct than the oracle row** (delivery-to-KA = inter-state); flag for CA sign-off (gst_service.py:67,162-179) |
| 5 | Inter B2C >₹2.5L MH→KA | IGST / KA | IGST/KA/B2CL | ✅ PASS |
| 6 | Intra unregistered biz MH | CGST+SGST / MH | CONSUMER→CGST_SGST/MH | ✅ PASS |
| 7 | Sale to composition **buyer** (GSTIN) KA | IGST / KA / Tax Inv | REGISTERED→IGST/KA/B2B | ✅ PASS (composition buyer = normal B2B, correct) |
| 8 | Composition **seller** TN→TN | NIL_NOT_A_SUPPLY / **Bill of Supply** | seller regime never checked → CGST_SGST/TN, **tax charged** | ❌ FAIL — not handled (docstring line 18 "out of scope"); no `firm.regime`/BoS forcing |
| 9 | Bill-to-ship MH→KA, ship GJ | IGST / **GJ** | pos=ship_to → IGST/GJ **iff ship_to passed**; else IGST/KA | 🟡 PARTIAL — correct only when caller sends ship_to_state |
| 10 | Bill-to-ship MH→MH, ship KA | IGST / KA | ship_to=KA→IGST/KA; **ship_to omitted→CGST_SGST/MH (wrong)** | 🟡 PARTIAL — silent intra-state if ship_to omitted |
| 11 | Bill-to-ship MH→KA, ship KA | IGST / KA | IGST/KA | ✅ PASS |
| 12 | SEZ **+ LUT** | NIL_LUT (zero-rated) | engine has branch (line 126), but `_classify_buyer` never returns SEZ & `lut_active` never passed → taxed as normal sale | ❌ FAIL live (engine-only) |
| 13 | SEZ no LUT | IGST / SEZ | engine-only (line 126); live taxes via buyer_state not "SEZ" | ❌ FAIL live |
| 14 | Export **+ LUT** | NIL_LUT (zero-rated) | party.is_export ignored by `_classify_buyer` → CONSUMER, **taxed** | ❌ FAIL live (engine-only, line 134) |
| 15 | Export no LUT | IGST | engine-only; live taxes via buyer_state | ❌ FAIL live |
| 16 | Deemed export EOU + LUT | NIL_LUT | engine-only (line 142); unreachable live | ❌ FAIL live |
| 17 | Services inter-state | IGST / KA (§12) | no service-nature input; treated as goods → IGST/KA (tax_type coincidentally right) | 🟡 PARTIAL — no §12 logic |
| 18 | Immovable-property service | **CGST+SGST / MH** (property loc, §12(3)) | treated as goods → if buyer KA → **IGST/KA** | ❌ FAIL — no §12(3) override |
| 19 | RCM service, unregistered supplier | Self-Invoice IGST (buyer self-assess) | not handled; no self-invoice | ❌ FAIL (not built) |
| 20 | OIDAR cross-border | NIL (zero-rated) | not handled | ❌ FAIL (not built) |
| 21 | Inter-firm transfer, diff GSTIN | IGST / Tax Inv (+auto SI/PI pair) | diff GSTIN → normal goods → IGST/KA ✓ tax_type; **no auto SI+PI pair** | 🟡 PARTIAL |
| 22 | Branch transfer, same GSTIN | NIL_NOT_A_SUPPLY / Delivery Challan | same-GSTIN branch → NIL_NOT_A_SUPPLY/DELIVERY_CHALLAN ✓ (relies on B1-fix decrypt, sales_service.py:842-856) | ✅ PASS |
| 23 | Sales return, same period | Credit Note / reverse | no credit-note service (persona-04 G5; "TASK-038") | ❌ FAIL (not built) |
| 24 | Sales return, diff period | Credit Note / reverse | same | ❌ FAIL (not built) |
| 25 | Job-work dispatch | NIL_NOT_A_SUPPLY / DC | handled in job-work module as DC (not via GST engine) | 🟡 N/A-engine (elsewhere) |
| 26 | Consignment dispatch | NIL_NOT_A_SUPPLY / DC | no consignment model | ❌ FAIL (not built) |
| 27 | Consignment settlement | IGST / Tax Inv | no consignment model | ❌ FAIL (not built) |
| 28 | RCM purchase, notified HSN | Self-Invoice IGST | `rcm_applicable`/`is_rcm_applicable` boolean only, **no posting, no self-invoice** | ❌ FAIL (stub) |
| 29 | RCM GTA | Self-Invoice CGST+SGST/IGST | not handled | ❌ FAIL (not built) |
| 30 | Import → onward sale | Onward IGST / KA | onward sale → normal inter → IGST/KA ✓ tax_type; no import/BCD/ITC | 🟡 PARTIAL |

**Tally:** ✅ PASS 7 · ⚠️ deviates(oracle-vs-law) 1 · 🟡 PARTIAL/elsewhere 6 · ❌ FAIL 16. Of the 16 FAILs, 5 (#12–16) are *engine-implemented-but-unreachable-live* (dead code behind `_classify_buyer`), the rest are genuinely not built. This matches the engine docstring's own self-declared scope (lines 7-22) — the engine is honest about what it does; the gap is that the **declared scope is ~7 of 30 scenarios** and nothing guards the unhandled ones.

### Tax-status behaviour table (DDL `tax_status` enum vs actual handling)

| `party.tax_status` | Spec behaviour | Actual (`_classify_buyer` sales_service.py:767-772) | Verdict |
|--------------------|----------------|------------------------------------------------------|---------|
| REGULAR | normal Tax Invoice, full GST | mapped via GSTIN presence → REGISTERED/B2B | ✅ if GSTIN set; ⚠️ REGULAR-but-no-GSTIN → CONSUMER |
| COMPOSITION | **buyer**: normal Tax Invoice (sc 7); **seller**: BoS no tax (sc 8) | buyer→REGISTERED ✓; **seller regime never checked** ✗ | 🟡 buyer-side only |
| UNREGISTERED | CGST+SGST (geography), B2CS reporting | collapsed to CONSUMER | ✅ tax_type ok (no biz/consumer distinction) |
| CONSUMER | CGST+SGST / B2CS | CONSUMER | ✅ |
| OVERSEAS | export / zero-rated | **`_classify_buyer` returns CONSUMER (no GSTIN) → domestic GST charged** | ❌ over-taxed; not export |

**Root cause:** the rich `tax_status` enum (`schema/ddl.sql:21`, 5 values, `NOT NULL`) is **dead in the PoS path** — `_classify_buyer` reads only `party.gstin`. Live parties carry `REGULAR`/`UNREGISTERED` (probed: 14/4) but the engine can't see it.

### Invoice-type behaviour (which suppress GST?)

| Doc type | Engine can emit? | GST suppressed? | Notes |
|----------|------------------|-----------------|-------|
| Tax Invoice | yes (default) | no | standard |
| Bill of Supply | only via NIL_LUT/NIL_NOT_A_SUPPLY or same-GSTIN | display-only (pdf_service.py:218-227) | engine never sets `invoice_type=BILL_OF_SUPPLY` directly for composition |
| Cash Memo | **no** — engine `DocumentType` has no CASH_MEMO (gst_service.py:46-50) | pdf can render (pdf_service.py:220) but nothing sets it | dangling: template supports, engine never produces |
| Estimate | **no** — not in `DocumentType` | pdf renders (line 222), never set | same |
| Delivery Challan | yes (same-GSTIN / non-supply) | yes | ✓ |
| Credit Note | enum exists, **no producer** | — | sales returns not built (persona-04 G5) |

CLAUDE.md §7 promises Bill of Supply / Cash Memo / Estimate as "native first-class document types". **Cash Memo & Estimate are unreachable** — the PDF layer knows the strings but no service ever writes them to `sales_invoice.invoice_type`.

### Split & rounding

- `split_tax` (gst_service.py:202-215): IGST→all on igst; CGST_SGST→halves with the odd-paise remainder pushed onto SGST so `cgst+sgst == gst_amount` exactly. ✅ paise-exact, verified live (GSTR-1 B2B row: cgst 384.00 / sgst 384.00 / total 768.00 on ₹6400 @12%).
- **`round_off` is never computed** — hardcoded `Decimal("0")` at sales_service.py:886; DDL column exists (`ddl.sql:2154`) and the PDF prints it (pdf_service.py:364) but no nearest-rupee logic anywhere (grep: zero hits). Invoices carry exact paise; no rounding adjustment line. ❌ B4.

---

## 3. Bugs

| Sev | Flow | What | Evidence | Fix |
|-----|------|------|----------|-----|
| **High** | tax-status → PoS | **`_classify_buyer` ignores `party.tax_status` entirely** — returns only REGISTERED (has GSTIN) / CONSUMER (no GSTIN). OVERSEAS/export parties get domestic GST; SEZ/EXPORT/EOU branches in the engine are dead code; composition-seller unhandled. The authoritative 5-value enum is unused in tax determination. | sales_service.py:767-772; ddl.sql:21; live parties REGULAR/UNREGISTERED | Map `tax_status`+`is_export`/`is_sez`/`is_exporter`+GSTIN → full `BuyerStatus`; pass it to the engine |
| **High** | e-invoice / e-way | **Not built.** Only nullable columns `irn_id`,`eway_bill_id` (sales.py:407-408; ddl.sql:1456) + `eway_bill` table + `eway_status` enum. No IRN JSON payload builder, no NIC/GSP call, no endpoint (all 404). CLAUDE.md §6 claims the **payload builder + GSTR-1 IRN JSON ship in Phase 1 behind a flag** — even the flag is not seeded; only a docstring mentions the key namespace. | grep `irn/einvoice/eway` services = 0; `/sales/...//einvoice|irn|eway` → 404; feature_flag.py:3 (key only) | Build IRN payload builder now (flag-gated, no live call) to match §6; or correct §6 to "schema only" |
| **Med-High** | invoice create | **gst_amount decoupled from tax_type.** Per-line `gst_amount = line_amount*gst_rate/100` is computed (sales_service.py:823-825) *before and independent of* `pos_decision.tax_type`. A NIL_NOT_A_SUPPLY branch-transfer (sc 22) or NIL_LUT export carrying any `gst_rate>0` line still adds GST to `invoice_total`/`gst_amount` — **tax charged on a zero-rated / non-supply document.** No validation zeroes it. | sales_service.py:817-840 vs 857-865 (no feedback) | After PoS decision, force per-line GST to 0 when tax_type ∈ {NIL_LUT, NIL_NOT_A_SUPPLY, NIL}; reject otherwise |
| **Med** | rounding | `round_off` always 0; never computed despite DDL column + PDF field. No nearest-rupee invoice rounding. | sales_service.py:886; ddl.sql:2154; grep=0 | Compute `round_off = round(total) - total`; post the diff to a Round-Off ledger on finalize |
| **Med** | rate source | **GST rate is client-supplied per line, not HSN/item-driven**, default 0. `item.gst_rate` (ddl.sql:405) + `item.hsn_code` exist but are not used to derive/validate the line rate → a wrong or omitted rate silently yields ₹0 tax with no warning. | sales_service.py:823; routers/sales.py:68,394 (`gst_rate=line.gst_rate`) | Default line rate from item HSN master; validate request rate against it; warn on mismatch |
| **Med** | export reporting | **Engine vs GSTR-1 export inconsistency.** Live path never sets `pos_state` to SEZ/EXPORT/EOU (sc 12-16 dead), so an export-party invoice is **taxed** (IGST via buyer_state) — yet `_bucket_for_invoice` buckets it as **export** off `party.is_export`/`is_sez` (reports_service.py:1263-1266). Return shows a zero-rated export bucket containing a tax-charged invoice. | gst_service `_classify_buyer` vs reports_service.py:1263-1272 | Single source of truth: feed is_export/is_sez into the engine so charged-tax and return bucket agree |
| **Med** | RCM | **RCM is a boolean stub with no effect.** `rcm_applicable`(PI)/`is_rcm_applicable`(item) stored; `rcm_status` enum (PROPOSED/CONFIRMED/REVERSED, ddl.sql:37) unused; no self-invoice, no GL posting (sc 19/28/29). Confirms persona-04 §4. | procurement_service.py:658; ddl.sql:37,475,855 | Self-invoice generator + RCM GL (Dr Expense, Cr IGST Payable, Cr Supplier) on PI post when flagged |
| **Low** | GSTR-3B | **Not built** — `/reports/gstr3b` → 404; no service. CLAUDE.md §6 lists 3B/ITC machinery. | live 404; grep = 0 | Build 3B (output from GSTR-1 + input from PI ITC once purchases post — blocked by persona-04 G1) |
| **Low** | doc types | Cash Memo / Estimate unreachable — `DocumentType` enum lacks them (gst_service.py:46-50) though pdf_service.py:220-223 + CLAUDE.md §7 expect them. | — | Add CASH_MEMO/ESTIMATE to `DocumentType`; let UI/series pick them |
| **Low** | bill-to-ship | §10(1)(b) not modelled; relies on caller passing `ship_to_state`. If omitted, sc 9/10 silently fall to buyer-state → wrong intra/inter. | sales_service.py:863; gst_service.py:150-151 | Require ship_to for 3-party; warn when buyer≠ship-to |

---

## 4. Improvements

1. **Promote `tax_status` to the engine's primary input** (not GSTIN presence). One mapping function `party → BuyerStatus` covering COMPOSITION/OVERSEAS/SEZ/EXPORT/EOU. Unblocks sc 8,12-16,20 in one move and kills the dead-branch problem.
2. **Validate tax_type ⇄ gst_amount as an invariant** at finalize (a NIL_* invoice must have Σgst = 0; a Tax Invoice must have non-zero unless explicitly exempt-HSN). Cheap guard, closes B3.
3. **HSN-rate master + per-line validation** — derive default rate, warn on override, store `is_rcm_applicable` from HSN notified list (feeds sc 28).
4. **Composition-seller onboarding** — `firm.regime` field + auto-force Bill of Supply, suppress rate entry (sc 8).
5. **Round-off ledger** on finalize so the printed total and the GL agree to the rupee.
6. **Build the IRN payload builder now** (pure JSON, flag-gated, no NIC call) — this is the part CLAUDE.md §6 says is the de-risking 80%; today it's 0%. Same for e-way payload.

## 5. Invariant / compliance gaps

- **INV-1 (tax_type ⇄ tax_amount):** no enforcement that NIL_* ⇒ 0 GST, or Tax Invoice ⇒ rate present. Decoupled computation (B3).
- **INV-2 (single source for inter/intra):** engine uses `pos != seller_state`; GSTR-1 re-derives from `place_of_supply_state != seller_state` and separately buckets export off party flags → two code paths that can disagree (B6).
- **INV-3 (round-the-rupee):** invoice total not rounded; `round_off` dead.
- **COMP-1:** e-invoice IRN + e-way payload builders absent — CLAUDE.md §6 represents these as Phase-1-built-behind-a-flag; reality is schema + flag-key only. Acceptable while < ₹5 Cr, **but not the "1-week drop-in" §6 claims** until the payload builder exists.
- **COMP-2:** GSTR-3B + ITC absent (3B blocked on purchase→GL, persona-04 G1).
- **COMP-3:** RCM has no posting/self-invoice effect; `rcm_status` workflow enum unused.
- **COMP-4:** Services PoS (§12), immovable-property override (§12(3)), OIDAR, consignment, credit-note all unmodelled — 11 oracle rows with no code path.
- **POSITIVE:** output-side core (PoS for goods sc 1-3,5-7,11,22; split_tax; GSTR-1 B2B/B2CL/B2CS/Export/HSN with plaintext-GSTIN decrypt) is correct and ties to the rupee live. The engine is honest about its declared scope; the risk is the **undeclared, unguarded gap** around it.

---

### Oracle caveat worth escalating
Scenario 4 (inter-state B2C ≤₹2.5L → "CGST+SGST / supplier state") in the oracle conflicts with the code's INT-11 fix (always-IGST inter-state, ₹2.5L = reporting bucket only). **The code is more aligned with actual GST law than the oracle row** — the ₹2.5L threshold governs B2CL vs B2CS *reporting* and capturing buyer state, not the IGST-vs-CGST flip. Recommend correcting the oracle, not the code. Needs CA sign-off (already flagged `CA-VALIDATED-PENDING` gst_service.py:70).
