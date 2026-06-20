# Flow slice #6 — Job-work & Karigar

**Agent:** Flow-test #6 · **Date:** 2026-06-20 · **Build:** live backend `http://localhost:8000` (org "Demo Co"), read-only DB, code at `/Users/moizp/fabric`.
**Scope:** JobWorkOrder (DRAFT·SENT·PARTIAL_RECEIVED·CLOSED·CANCELLED); JW-receipt (POSTED·VOID); MO-operation karigar sub-flow (dispatch→acknowledge→receive→close); ITC-04.
**Builds on:** `00-flow-machine.md` slice #6; product-review #17 (P1 — UUID + blank GSTIN in ITC-04), #18 (no purchase→GL), `personas/06-external-karigar-supplier.md` (G1–G7, E1–E9). Cited by number; not repeated.
Severity: **P0** blocker · **P1** broken core/compliance · **P2** notable gap · **P3** polish.

---

## 1. Flows (as built)

### 1a. Standalone JWO (goods-only logistics loop) — `jobwork_service.py`
```
create_send_out ──▶ SENT ──receive_back(partial)──▶ PARTIAL_RECEIVED ──receive_back(rest)──▶ CLOSED
                     │  stock: MAIN ─OUT─▶ JOBWORK (IN_TRANSIT loc), wt-avg cost carried
                     │  receive: JOBWORK ─OUT(rcv+wst)─▶ ; rcv ─IN─▶ MAIN ; wastage vanishes
   (DRAFT enum value reserved, never used — create writes SENT directly, jobwork_service.py:240)
   (CANCELLED enum value reserved, NO code path — see Bug JW-1)
```
- Numbering: gapless `JW/<FY>/NNNN`, firm-row `with_for_update` lock (`jobwork_service.py:147-169`). Solid.
- Receipts are 1-N per JWO; each `job_work_receipt` is POSTED on insert. **VOID never implemented** (Bug JW-1).
- ITC-04 (`prepare_itc04_data`, `jobwork_service.py:690-825`): send-outs by `challan_date`, receipts by `receipt_date`, window from `YYYY-MM` or `YYYY-QN` (FY quarters). Real data, not a stub.

### 1b. MO-operation karigar sub-flow — `karigar_send_out_service.py`
```
PENDING ─dispatch─▶ DISPATCHED ─acknowledge─▶ ACKNOWLEDGED ─receive─▶ RECEIVED_PARTIAL ⇄ RECEIVED_FULL ─close─▶ CLOSED
   │ mints a fresh JWO per dispatch (delegates stock to jobwork_service.create_send_out)
   │ re-dispatch allowed from RECEIVED_FULL (split batch) → new JWO, qty_out accumulates
   receive composes jobwork_service.receive_back against op.outward_challan_id (latest JWO)
   conservation: qty_in + qty_rejected + qty_byproduct + qty_wastage ≤ qty_out (cumulative)
   close guard: accounted == qty_out (exact)
```
- Cost: `mo_operation.cost_accrued` hardcoded `0` (qc_service.py:505 per #G1) — karigar labour never costed.
- Both paths share one stock engine (`jobwork_service`), one virtual `JOBWORK` IN_TRANSIT location per firm.

---

## 2. Transition test matrix

| # | Transition / probe | Guard / expected | Result | Evidence |
|---|---|---|---|---|
| T1 | create_send_out → SENT | stock MAIN→JOBWORK, gapless number | ✅ | live `JW/2026-27/0001..0002` |
| T2 | send-out qty > MAIN on-hand | reject (`remove_stock` on_hand<qty) | ✅ blocked | `inventory_service.py:392` |
| T3 | partial receive (multiple receipts, one send-out) | many `job_work_receipt` per JWO | ✅ | live JWO 0001: 40 sent → 36 rcv + 2 wst, PARTIAL_RECEIVED |
| T4 | over-receipt (999 vs 2 open) | `recv+wst ≤ open_qty` → 422 | ✅ blocked | live probe → `422 "received (999)+wastage(0) exceeds open qty (2.0000)"` |
| T5 | receive bogus line id | line must belong to JWO → 422 | ✅ blocked | live probe → 422 |
| T6 | negative qty_received | schema `ge=0` → 422 | ✅ blocked | live probe → 422 field_error |
| T7 | receive against CLOSED / CANCELLED JWO | status∈{SENT,PARTIAL_RECEIVED} → `InvoiceStateError` | ✅ blocked | `jobwork_service.py:472-475` |
| T8 | JWO cancel | — | ❌ **no endpoint (404)** | live `POST /job-work-orders/{id}/cancel` → 404 (Bug JW-1) |
| T9 | JW-receipt void / reverse | — | ❌ **no endpoint (404)** | live `POST /job-work-receipts/{id}/void` → 404 (Bug JW-1) |
| T10 | karigar dispatch (PENDING→DISPATCHED) | MO IN_PROGRESS + predecessors terminal + is_karigar | ✅ | `karigar_send_out_service.py:308-411` |
| T11 | dispatch when MO not IN_PROGRESS | reject | ✅ | `:324-328` |
| T12 | acknowledge / receive / close: re-check MO status | — | ⚠️ **not re-checked** (only dispatch guards MO) | Bug JW-5 |
| T13 | acknowledge from non-DISPATCHED | reject | ✅ | `:471-475` |
| T14 | receive cumulative > qty_out | reject (conservation) | ✅ | `:590-598` |
| T15 | re-dispatch from RECEIVED_FULL | allowed → fresh JWO | ✅ | `_DISPATCHABLE_STATES :95-97` |
| T16 | close from non-RECEIVED_FULL | reject | ✅ | `:746-750` |
| T17 | skip / cancel a karigar op | enum has SKIPPED/CANCELLED | ❌ **no path** | Bug JW-6 |
| T18 | karigar endpoints on IN_HOUSE op | reject | ✅ | `_ensure_karigar :192-200` |
| T19 | ITC-04 `YYYY-MM` and `YYYY-QN` | both parse | ✅ | live `2026-Q1` + `_parse_period` |
| T20 | ITC-04 registered-karigar GSTIN | populate | ❌ **always null** | Bug JW-2 (live: Bharati gstin present, ITC-04 null) |
| T21 | ITC-04 nature_of_job for MO dispatch | human label | ❌ **raw UUID** | Bug JW-2 (#17) |
| T22 | idempotency (missing key) | 400 IDEMPOTENCY_KEY_REQUIRED | ✅ | live probe; middleware real (Redis + in-mem, 409 on payload mismatch) |
| T23 | RLS org isolation | org_id filter on every query | ✅ | grep — all `*.org_id == org_id` |
| T24 | firm isolation on standalone receive | session-firm check | ❌ **firm derived from data** | Bug JW-4 |

---

## 3. Bugs

| Sev | Flow | What | Where | Fix |
|---|---|---|---|---|
| **P1** | ITC-04 | **Registered-karigar GSTIN dropped + nature_of_job is a raw UUID — statutory return unfileable.** `karigar_gstin` hardcoded `None`; `nature_of_job` = `"MO operation <uuid>"`. Confirmed live: Bharati Embroidery Works is `tax_status=REGULAR, gstin=24BHARA3456Q1Z7` (party API decrypts & returns it) yet ITC-04 shows `karigar_gstin: null`; JWO 0002 shows `nature_of_job:"MO operation f0018155-…"`. Escalation of #17. | `jobwork_service.py:750-753, 759, 806-809` (gstin None); UUID label set at `karigar_send_out_service.py:392` (`operation=f"MO operation {mo_operation_id}"`) | Decrypt GSTIN at the API boundary (party endpoint already does it); resolve operation_master name instead of writing the op UUID into `JobWorkOrder.operation`. |
| **P2** | JWO / receipt | **JWO CANCELLED and JW-receipt VOID are dead enum states — no reversal anywhere.** A mistaken send-out moves stock MAIN→JOBWORK with **no way to undo**; stock is stranded at the karigar location forever (only a receive-back, implying real returned goods, can drain it). No void to reverse a bad receipt either. | `models/jobwork.py:60-71` (enum), no service/router; live `…/cancel`→404, `…/void`→404 | Implement `cancel_jwo` (SENT + zero receipts → reverse stock move, status CANCELLED) and `void_receipt` (reverse the stock pair, status VOID), both idempotent + audited. |
| **P2** | Schema integrity | **`schema/ddl.sql` is drifted from the live ORM/Alembic schema for the entire job-work area.** Base DDL defines `job_work_order(karigar_id, jwo_date, total_amount, status job_work_status)` + `outward_challan`/`inward_challan`(+lines) + **`job_work_bill(amount, gst_amount)`** — none of which the ORM uses. Live ORM/DB instead has `job_work_order(karigar_party_id, challan_date, from/to_location_id, operation)` + `job_work_receipt(+line)`. A fresh `schema/ddl.sql` apply yields a schema the app cannot run against. Also: the original design **had** `total_amount` on the JWO and a `job_work_bill` table — the CUT-305 rebuild **dropped** them, so the "no karigar charge/payable" gap (#G1) is a regression from the documented schema, not merely unbuilt. | `schema/ddl.sql:1191-1300` vs `backend/app/models/jobwork.py` | Regenerate `schema/ddl.sql` from current Alembic head (or delete it as authoritative). Decide whether to restore `job_work_bill`/charge columns (Ask-vs-Decide: schema change → Moiz). |
| **P2** | Firm isolation | **Standalone receive-back trusts the JWO's own `firm_id`, not the session firm.** Router looks up the JWO and passes `firm_id=jwo.firm_id`; the service only checks `jwo.firm_id == firm_id` (always true). With org-only RLS, any user in the org can receive-back against **any firm's** JWO. Consistent with the global firm-spoof gap (flow-machine §C). | `routers/jobwork.py:206-221`; `jobwork_service.py:470` | Scope to `current_user.firm_id` and reject when `jwo.firm_id != session firm` (mirror the karigar router's `body.firm_id != current_user.firm_id` check at `manufacturing.py:1843`). |
| **P1** | Costing | **No karigar rate / charge / payable; labour cost = ₹0.** Job-work model is goods-only (no amount column on order/line); `mo_operation.cost_accrued` hardcoded `Decimal("0")`. System cannot answer "what do I owe this karigar?" and the MO cost pool excludes labour (#G1, #25). | `models/jobwork.py:83-291`; `qc_service.py:505` | Restore charge basis (rate_basis + rate) + a `JobWorkBill` posting `Dr Job-work-charges / Cr Sundry-Creditors(karigar)`, route into `cost_accrued`. (Schema change → Moiz.) |
| **P3** | Receive (standalone) | **No wastage tolerance band.** `receive_back` accepts any wastage up to open qty — a karigar could "waste" 50% silently (#G7). MO/QC path has the 5-bucket verdict; the standalone JWO path has nothing. | `jobwork_service.py:508` | Optional per-item/operation tolerance %, flag/ block over-tolerance wastage. |
| **P3** | Value conservation | **Wastage cost written off with no expense booking + docstring contradicts code.** `receive_back` removes `rcv+wst` from JOBWORK but only credits `rcv` back to MAIN — wastage qty's cost disappears from inventory with **no GL / P&L charge** (job-work posts no GL at all). Module docstring (lines 5-7) claims wastage "leaves the wastage qty at the JOBWORK location" — code actually removes it (`:574 total_out=qty_rcv+qty_wst`). | `jobwork_service.py:5-7, 573-601` | When GL lands for inventory, book wastage to a job-work-loss expense; fix the docstring now. |
| **P3** | Audit | **Audit `before.state` is hardcoded.** `dispatch_to_karigar` logs `before.state="PENDING"` even when re-dispatching from RECEIVED_FULL; `receive_from_karigar` logs `before.state="ACKNOWLEDGED"` even from RECEIVED_PARTIAL. Audit trail misreports the true prior state. | `karigar_send_out_service.py:440-441, 705` | Capture `op.state` before mutation and log it. |
| **P3** | MO karigar | **No skip / cancel for a karigar MO operation.** `MoOperationState` has SKIPPED/CANCELLED but the karigar service offers no transition; a dispatched-by-mistake karigar op cannot be abandoned (and its JWO can't be cancelled either — compounds JW-1). | `karigar_send_out_service.py` (no path); enum `models/manufacturing.py:143-144` | Add a guarded cancel that reverses outstanding dispatch stock and closes the op. |

---

## 4. Improvements

- **ITC-04 export.** Real data but screen-only — no CSV/XLSX/JSON to file the return (#G5, Wave-5 CUT-403 not done).
- **Delivery-challan PDF + e-way payload.** Goods physically move to the karigar with no rule-55 challan to print and no e-way JSON (#G4). Even with e-way flag-gated, the challan PDF is a hard requirement.
- **Karigar khata / statement.** No `/parties/{id}/statement` for karigars (goods or money); advances unmodelled (#G2). Reuse the party-ledger infra once #22 lands.
- **Dual customer+karigar party.** Schema-ready (independent flags; send-out only checks `is_karigar`) but unusable without a unified khata (E6); 0 such parties seeded.
- **Karigar portal / role.** Open design question (#G3) — `acknowledge-karigar` is staff-operated, not karigar-operated. Decide before building.
- **`DRAFT` JWO state** is reserved but unreachable — either implement the "preview before send" flow or drop it from the enum to avoid a dead state.
- **Idempotency cache key** is `idem:{path}:{key}` (not org/user-scoped). Safe in practice with client UUIDv4 keys, but path-without-id endpoints (e.g. `POST /job-work-orders`) would collide on a shared key across tenants. Add org_id to the cache key for defense-in-depth.

---

## 5. Invariant violations

1. **Reversibility broken.** Send-out and receipt mutate stock with no inverse operation (CANCELLED/VOID are enum-only). Inventory can be permanently distorted by a mistaken JWO with no remediation path. (Bug JW-1)
2. **Value conservation.** Wastage units leave inventory (cost removed from JOBWORK position) with no offsetting expense — inventory value silently decreases, no P&L hit. (Bug JW-7)
3. **Cost completeness.** `cost_accrued ≡ 0` ⇒ MO WIP/FG cost excludes all karigar labour; a completed garment is costed at material-only. (Bug JW-5 / #25)
4. **Compliance integrity.** ITC-04 emits null GSTIN for registered karigars + UUID nature-of-job ⇒ the statutory return is incorrect. (Bug JW-2 / #17)
5. **Firm tenancy.** Standalone receive-back is org-scoped but not firm-scoped (firm taken from the target row), so cross-firm receive within an org is possible. (Bug JW-4)
6. **Schema authority drift.** Two divergent definitions of the job-work schema (`schema/ddl.sql` vs ORM/Alembic) — the checked-in base DDL cannot run the app. (Bug JW-3)

**Verified sound:** over/short-receipt guard (T4), qty conservation on the MO path (T14), receive-after-CLOSED block (T7), gapless numbering under lock, MAIN-oversell guard (T2), org-level RLS (T23), idempotency enforcement + payload-mismatch 409 (T22).
