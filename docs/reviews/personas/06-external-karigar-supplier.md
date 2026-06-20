# Persona Review 06 — External Stakeholders: the Karigar & the Supplier

**Reviewer:** Senior ERP product analyst (job-work / external-party lens)
**Date:** 2026-06-20
**Build:** live backend `http://localhost:8000` (org "Demo Co"), read-only DB `fabric-postgres-1`, code at `/Users/moizp/fabric`
**Companion doc:** `docs/reviews/product-review-2026-06-20.md` (23 findings). This review references those by number (e.g. #17, #22) and does **not** repeat them.

Severity legend: **P0** blocker · **P1** broken core flow · **P2** notable gap · **P3** polish.

---

## 1. Persona & jobs-to-be-done

### The Karigar (job-worker / embroiderer / tailor / washer)
External contractor. Receives our fabric/parts, does one operation (embroidery, stitching, lace, washing), returns finished pieces. In the Indian ladies-suit trade this is the **core production mechanism**, not an edge case (architecture.md:421-457).

JTBD (from the firm's side — the karigar is tracked *by our staff*):
1. **Send goods out** on a delivery challan (rule 55), know what's at each karigar right now.
2. **Receive pieces back**, in multiple partial lots, capturing good qty + wastage/shortage + rejects.
3. **Know what I owe** the karigar: piece-rate × pieces, or per-meter × meters, net of advances.
4. **Maintain the karigar's khata** (running balance: issued / received / rejected / charges payable / paid).
5. **File ITC-04** quarterly (goods sent for job-work, regardless of karigar GST registration).
6. **Move goods legally** (delivery challan PDF; e-way bill when value/distance thresholds hit).
7. (Maybe) let the karigar **see/accept jobs** himself — the open "karigar portal" question.

### The Supplier (mill / grey trader / trim vendor)
External party we buy from. JTBD: receive our PO, we GRN their goods, we owe them money (payables), we track their ledger and performance (on-time, quality). Mostly handled by the Purchase module already reviewed; this doc covers the **external-party ledger/payable** angle only, which is blocked by the same root cause as the karigar payable.

---

## 2. What works today (evidence)

The **physical goods loop is genuinely well-built** — this is the strongest part of the external-party story.

| Capability | Evidence | Verdict |
|---|---|---|
| **Send-out challan + stock move** | `jobwork_service.create_send_out` (`backend/app/service/jobwork_service.py:190-339`) mints a gapless `JW/<FY>/NNNN` JWO, moves stock MAIN→JOBWORK virtual location carrying weighted-avg cost across. Live: `JW/2026-27/0001`. | ✅ Solid |
| **Receive-back, partial + multiple receipts** | `receive_back` (`jobwork_service.py:428-635`) supports many `job_work_receipt` rows per JWO; per-line invariant `received + wastage ≤ open_qty` (line 508); header auto-promotes `SENT → PARTIAL_RECEIVED → CLOSED`. Live JWO 0001 = `PARTIAL_RECEIVED`, sent 40 / recv 36 / wastage 2. | ✅ Solid |
| **Wastage / shortage capture** | `qty_wastage` on both order-line and receipt-line; wastage leaves JOBWORK and is **not** credited back to MAIN (`jobwork_service.py:587-601`). | ✅ Correct model |
| **Two send-out paths, one engine** | Standalone `/job-work-orders` **and** MO-operation karigar dispatch (`karigar_send_out_service.py`) with a full state machine `PENDING→DISPATCHED→ACKNOWLEDGED→RECEIVED_PARTIAL⇄RECEIVED_FULL→CLOSED`. Endpoints `POST /manufacturing/mo-operations/{id}/{dispatch,acknowledge,receive,close}-karigar` (`routers/manufacturing.py:1829-1900`). The MO path delegates stock to the same `jobwork_service`, minting a fresh JWO per dispatch (re-dispatch supported). | ✅ Deep, well-factored |
| **ITC-04 data preparer is REAL (not a stub)** | `prepare_itc04_data` (`jobwork_service.py:690-825`); `GET /reports/itc04?firm_id=…&period=2026-Q1` returns live send-outs + receipts with challan no/date, karigar name, HSN, qty, UOM, nature-of-job. Accepts `YYYY-MM` and `YYYY-QN` (FY-quarter mapping). FE tab `ReportsHub.tsx:301` (`Itc04Panel`) renders it. | ✅ Real, with caveats (§3) |
| **Conservation / over-receipt guard (MO path)** | `receive_from_karigar` enforces cumulative `received+scrap+byproduct+wastage ≤ qty_out` (`karigar_send_out_service.py:584-598`); shrinkage in transit tolerated, receive-side balances by construction. | ✅ Thoughtful |
| **Karigar party as first-class flag** | `party.is_karigar` (`models/masters.py:158`); send-out rejects non-karigar parties (`jobwork_service.py:82-86`). 5 karigars, 41 suppliers in seed. | ✅ |
| **Audit + RLS** | Every send/receive emits `audit_log` + `production_event`; all queries org-scoped. Tenant isolation verified in companion review (S1). | ✅ |

**Bottom line on §2:** the *operational* (qty/stock) half of job-work is trial-grade. The *commercial* (money/ledger/payment) half is essentially absent — see §3.

---

## 3. Gaps for job-work & external parties (ranked, evidence)

### G1 — **No karigar charges, rate, or payable. The system cannot answer "what do I owe this karigar?"** — P1
This is the single biggest gap. The entire job-work data model is **goods-only**:
- `job_work_order` / `job_work_order_line` have **no** rate/charge/amount column (`models/jobwork.py:83-291`; DB: only the 4 `job_work_*` tables exist, none for labour/bill).
- `party` has `is_karigar` but **no piece-rate / per-meter rate** field (`models/masters.py`; grep for rate/charge/piece → none).
- `operation_master` has no rate column (only `cost_centre_id`).
- `mo_operation.cost_accrued` exists **but is hardcoded `Decimal("0")`** (`qc_service.py:505`) — karigar labour never enters the MO cost pool. The praised "Cost tab" (companion #65 positive) is **material-issue WIP only**; karigar labour is invisible to product costing.
- There is **no `JobWorkBill` entity** despite architecture.md:433 explicitly specifying `JobWorkBill (karigar's bill for labour) → Payment`, and architecture.md:450 / 888 specifying a karigar ledger and payout report.

Consequence: a shop owner using this for real cannot compute karigar dues, cannot cost a garment correctly, and the "Cost tab" understates true cost. **For a textile job-work business this is a must-have, not nice-to-have.**

### G2 — **No karigar khata / running balance** — P1 (compounds companion #22)
`GET /parties/{id}/{transactions,khata,ledger,statement}` all → **404** (probed live, karigar `cdc6a3e8…`). Even the *goods* ledger the architecture promises ("issued / received / rejected qty per karigar", architecture.md:450) has no endpoint — `KarigarCards.tsx` rolls up only open-JWO qty client-side. There is no per-karigar statement combining goods movement + charges + advances + payments. Advances to karigars (architecture.md:451 — "₹5,000 advance before they start") are entirely unmodelled.

### G3 — **No "Karigar" role; no portal; the open design question is unresolved** — P2 (design decision needed)
architecture.md:1075 (§13 Open questions) still reads: *"Karigar login. Do karigars log in to see/accept jobs, or is everything tracked by your staff on their behalf?"* — **undecided.** Evidence it's unbuilt:
- The role table seeds **no Karigar role** (DB: only Accountant/Owner/Production Manager/Salesperson/Warehouse). architecture.md:201 lists "Karigar (if portal enabled)" with a parenthetical — aspirational.
- The `acknowledge-karigar` endpoint exists but is operated by **internal staff** on the karigar's behalf, not by the karigar (`require_permission("manufacturing.karigar.dispatch")`).
- No external/limited-access concept, no scoped-to-own-jobs query path, no WhatsApp-first UX.

This is a **high-value, well-scoped customization** for a manufacturer customer (§5).

### G4 — **No delivery-challan PDF and no e-way bill for goods sent to karigar** — P2
Goods physically move to the karigar but there is **no challan document to print** (jobwork router has no PDF endpoint; `JobWorkOverview.tsx` has no print affordance) and **no e-way-bill payload** (grep `eway` in jobwork code → nothing). architecture.md:445-449 requires a rule-55 delivery challan in *all* GST/non-GST combinations and notes the e-way trigger on goods movement. A karigar dispatch over the value/distance threshold currently has no compliant paperwork. (Consistent with CLAUDE.md: e-way is flag-gated for Phase-later, but even the *challan PDF* is missing.)

### G5 — **ITC-04 caveats: GSTIN never populated, raw-UUID nature-of-job, no export** — P2
The preparer works but:
- `karigar_gstin` is **always `null`** — decryption deliberately skipped at the service layer (`jobwork_service.py:750-753`) and **not re-added at the API boundary**, so the actual return field is blank for registered karigars.
- `nature_of_job` shows **`"MO operation f0018155-…"` (raw UUID)** for MO-linked dispatches (live ITC-04 output) — companion bug #17 leaks straight into the GST return.
- No CSV/XLSX/JSON export (`ReportsHub.tsx:78-79` confirms ITC-04 has no `format=` path; Wave-5 CUT-403 not done). It's a screen, not a fileable artifact.

### G6 — **Supplier payable / ledger absent** — P2 (root cause = companion #18)
`is_supplier` exists (41 suppliers) but purchases don't post to GL (no Sundry Creditors — companion #18), and the same missing `/parties/{id}/khata` (#22) means **no supplier ledger or outstanding-payable view**. Supplier performance (on-time %, reject %) — architecture.md:888 — is unbuilt. Supplier communication (PO share/WhatsApp) is explicitly Phase 4 per CLAUDE.md, so out of scope for trial.

### G7 — **No wastage tolerance band on standalone JWO** — P3
`receive_back` accepts any wastage up to open qty (`jobwork_service.py:508`) with **no tolerance flag** — a karigar could "waste" 50% and nothing flags it. architecture.md:557 specifies a tolerance band for operations; the standalone JWO path has none. (The MO/QC path has the 5-bucket verdict, which is better.)

---

## 4. Edge cases tested (probe → result)

| # | Edge case | Probe | Result |
|---|---|---|---|
| E1 | Partial + multiple receipts vs one send-out | Code + live JWO 0001 (40 sent → 36 recv + 2 wastage, `PARTIAL_RECEIVED`) | ✅ Supported; `job_work_receipt` is 1-N per JWO |
| E2 | Over-receipt (return more than sent) | `receive_back` line 508 invariant `recv+wastage ≤ open_qty` → `AppValidationError` 422 | ✅ Blocked |
| E3 | Karigar loses/damages material beyond tolerance | Wastage capped only at open qty; **no tolerance band** | ⚠️ Accepted silently (G7) |
| E4 | Reworking returned-from-karigar goods | MO/QC path: `rework_of_mo_operation_id` clone exists (`test_qc_rework_clone.py`). Standalone JWO: **no rework concept** | ◑ Partial — MO only |
| E5 | Paying a karigar across multiple jobs | **Impossible** — no payment/bill entity at all (G1) | ❌ Unsupported |
| E6 | Party who is BOTH customer and karigar | Model supports via independent flags; **0 such parties in seed**; but with no unified khata (G2) the dual balance can't be viewed anyway | ◑ Schema-ready, unusable |
| E7 | Send to non-karigar party | `_ensure_karigar` rejects (`jobwork_service.py:82`) | ✅ Blocked with actionable msg |
| E8 | ITC-04 for a quarter with mixed monthly/quarter period strings | `GET /reports/itc04?period=2026-Q1` and `2026-05` both parse (`_parse_period`) | ✅ Both work |
| E9 | Registered karigar GSTIN on ITC-04 | Live output `karigar_gstin: null` always | ❌ Blank (G5) |

---

## 5. Customizations required (concrete)

Ranked by trial value for a **manufacturer customer**:

1. **Karigar charges + payable + khata (G1+G2).** Add `rate_basis` (PER_PIECE / PER_METER / LUMP_SUM) + `rate` to either the JWO line or a karigar-operation-rate master; introduce a **`JobWorkBill`** entity (challan-linked, charge = rate × accounted qty, minus rejects) that posts `Dr Job-work-charges / Cr Sundry-Creditors(karigar)` and feeds a **karigar khata** (`GET /parties/{id}/statement` unifying goods + charges + advances + payments). Route `cost_accrued` from this so the MO cost pool finally includes labour. **Effort: L.** Highest impact — this is what makes the module a *business* tool, not a logistics tracker.
2. **Karigar khata/statement endpoint (G2).** Even before charges, ship the *goods* khata (issued/received/rejected per karigar) and the financial statement once #22's party-ledger lands. Reuse the same `/parties/{id}/statement` infra as customers/suppliers. **Effort: M.**
3. **Delivery-challan PDF + e-way payload for JW dispatch (G4).** Rule-55 challan template (auto GST/non-GST switch per architecture.md:449), e-way JSON behind the existing `gst.eway.enabled` flag. **Effort: M.**
4. **ITC-04 hardening + export (G5).** Decrypt `karigar_gstin` at the API boundary, resolve `nature_of_job` to the operation name (fixes #17 in the return too), add JSON/Excel export matching the GST-portal ITC-04 offline-tool schema. **Effort: M.**
5. **Karigar portal (G3) — resolve the open question first, then build.** Minimal scope: a separate **Karigar role** (own-jobs-only RLS scope, zero financial data), a WhatsApp-first/mobile "my jobs" view with accept + mark-progress, mapping a `party_id` to a lightweight login. Decide with Moiz before building (Ask-vs-Decide: new role + auth surface). **Effort: L** (but high differentiation).
6. **Supplier payables + performance (G6).** Falls out of fixing #18 (purchase→GL) + #22 (party ledger); add on-time/reject KPIs per architecture.md:888. **Effort: M** (mostly unblocked by other fixes).

---

## 6. Top UX boosts (ranked 1–6)

| # | Boost | Why | Effort |
|---|---|---|---|
| 1 | **"You owe" column on the karigar overview & cards** | The #1 question a shop owner asks; today `JobWorkOverview.tsx` shows only qty. Needs G1 backend. | L (blocked on G1) |
| 2 | **Resolve raw-UUID `nature_of_job` / operation labels** (FE #17 + ITC-04 G5) | A UUID in the ITC-04 return and Active-jobs table reads as broken to any user. | S |
| 3 | **"Print challan" button on each JWO row** | Goods leave the building with no paper today; karigars expect a slip. | M (G4) |
| 4 | **Per-karigar khata drill-down** (click a KarigarCard → statement) | Turns the rollup tiles into the khata every textile owner lives by. | M (G2) |
| 5 | **Wastage-over-tolerance flag on receive-back** | Surfaces a karigar quietly wasting/pilfering material; cheap trust signal. | S (G7) |
| 6 | **ITC-04 "Download for portal" + period label fix** | Makes the tab a fileable artifact, not just a screen (compounds companion #20 period model). | M (G5) |

---

## Summary (≤12 lines)

The **physical goods loop is trial-ready and genuinely strong**: send-out challans, partial/multiple receive-backs, wastage capture, a clean MO-operation karigar state machine, real RLS/audit, and a *working* ITC-04 data preparer. But the **commercial half of job-work is absent**, so the external-party story is **NOT trial-ready** for a real manufacturer.

**Top 5:**
1. **No karigar charges/rate/payable anywhere** (P1) — `cost_accrued` is hardcoded 0, no `JobWorkBill`, system can't answer "what do I owe this karigar?" or cost a garment with labour.
2. **No karigar (or supplier) khata/statement** (P1) — `/parties/{id}/{khata,ledger,statement}` all 404; advances unmodelled (compounds #22).
3. **ITC-04 caveats** (P2) — GSTIN always null, `nature_of_job` shows a raw UUID (#17), no fileable export.
4. **No delivery-challan PDF and no e-way bill** for goods sent to a karigar (P2) — goods move with no compliant paper.
5. **Karigar portal undecided** (P2) — open question architecture.md:1075 unresolved; no Karigar role, no external access; high-value, well-scoped customization once Moiz decides.
