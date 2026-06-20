# Flow slice #5 — QC / Rework / Completion / Costing

Agent 5 of the flow-machine probe (`00-flow-machine.md` rows 17-19, 22). Scope:
the 5-bucket QC verdict, the rework clone loop, scrap/by-product valuation,
`complete_mo_with_settlement`, and the WIP cost pool. Grounded in
`backend/app/service/{qc_service,mo_completion_service,material_issue_service,operation_progress_service,mo_service}.py`,
`specs/a11-rework-readback.md`, and live read/INVALID probes against the running
Demo Co instance (MO-DEMO 0001-0007, read-only — no seeded record mutated).

Builds on product-review #12 (qty propagation), #25 (WIP material-only / `cost_accrued=0`),
and personas/02-manufacturer (conservation math sound; produced_qty operator-asserted;
ALL_OR_NONE). This slice goes deeper on the **produced↔QC reconciliation hole** and the
**ALL_OR_NONE × yield-loss deadlock**, which together are the worst defect in the pipeline.

---

## 1. Flows

### 1.1 QC verdict (5-bucket) — `qc_service.record_qc_result`
```
op(PENDING) ──start_qc_inspection──▶ QC_PENDING
   guards: operation_type==QC; parent MO IN_PROGRESS; exactly ONE incoming
           routing edge; predecessor.qty_out > 0
QC_PENDING ──record_qc_result(qty_rework==0)──▶ CLOSED   (verdict PASS)
QC_PENDING ──record_qc_result(qty_rework>0) ──▶ REWORK   (clone spawned)
REWORK     ──(clone closes, re-record vs clone.qty_out)─▶ CLOSED | REWORK(deeper)
```
Conservation (load-bearing for settlement): `passed+rejected+byproduct+wastage+rework
== source.qty_out`, strict equality on NUMERIC(15,4). Source = original predecessor
(first verdict) or latest CLOSED clone (re-record). `qty_passed` lands on `op.qty_out`;
`rejected/byproduct/wastage` accumulate on columns; `qty_rework` lives ONLY on the
`QC_RESULT_RECORDED` event payload (no column — A11 reads it back via JSON path).

### 1.2 Rework loop — `_clone_for_rework`
REWORK verdict spawns a new `MoOperation` cloning the **predecessor** (the worker, not
the QC op): `qty_in = qty_rework`, `state=PENDING`, off the routing graph
(`operation_sequence=NULL`, no edge), `is_rework_paid=FALSE`, `cost_accrued=0`, no new
material issue. Operator runs the clone to CLOSED through the normal op-progress/karigar
path, then re-records QC against `clone.qty_out`. Depth capped at `_MAX_REWORK_DEPTH=5`
(`_compute_rework_depth` chain-walk) — past 5 the clone raises and the txn rolls back, so
the only escape is to scrap the units via `qty_rejected`. Bounded, not infinite.

### 1.3 Completion + settlement — `complete_mo_with_settlement`
```
guards: produced_qty>0; MO IN_PROGRESS; every op ∈ {CLOSED,SKIPPED,CANCELLED};
        policy==ALL_OR_NONE ⇒ produced_qty == planned_qty (exact);
        aggregated rework_qty==0; cost_pool>0
side effects (one txn):
  cost_pool = Σ DR-1310 voucher_line.amount from MATERIAL_ISSUE vouchers (material only)
  unit_cost = cost_pool / produced_qty
  GL voucher MANUFACTURING_COMPLETION: DR 1300 Inventory / CR 1310 WIP (= cost_pool)
  inventory_service.add_stock(finished_item, qty=produced_qty, unit_cost) → wt-avg current_cost
  mo.produced_qty/scrap_qty(=rejected+wastage)/by_product_qty written; mo.cost_pool→0
  mo_service.complete_mo IN_PROGRESS→COMPLETED; MO_COMPLETED event + audit
```
Live confirmation (MO-DEMO 0006 preview): `cost_pool=4326.40`, `unit_cost=432.64` at
produced=10 — material issues only. MO-DEMO 0007 (completed) booked produced=10 == planned,
cost_pool drained to 0, no scrap, **no QC op in its routing at all**.

---

## 2. Transition / test matrix

| # | Scenario | Probe | Result | Verdict |
|---|----------|-------|--------|---------|
| T1 | QC conservation sum 9≠10 | live POST record-qc-result MO-DEMO-0006 | 422 "QC bucket sum 9 ≠ source qty_out 10" | PASS (guard works) |
| T2 | negative bucket | live | 422 pydantic field validation | PASS |
| T3 | all-zero buckets | live | 422 "requires at least one non-zero qty" | PASS |
| T4 | wrong firm_id | live | 422 "firm_id must match current session firm" | PASS (router defense) |
| T5 | double-complete (COMPLETED MO) | live POST complete MO-DEMO-0007 | 422 "status is COMPLETED, expected IN_PROGRESS" | PASS |
| T6 | complete with open ops | live POST complete MO-DEMO-0006 | 422 lists PENDING + QC_PENDING ops | PASS |
| T7 | no material issued → cost_pool 0 | code `complete…:500` | 422 "WIP cost pool is zero" | PASS (#25) |
| T8 | rework infinite loop | code `_MAX_REWORK_DEPTH=5` | bounded; raises at cap | PASS |
| T9 | preview policy mismatch produced=9999 | live preview | can_complete=false, ALL_OR_NONE reason | PASS |
| **T10** | **produced_qty vs terminal QC qty_passed** | **code `complete…:447-482`** | **NO check — produced reconciled only to planned_qty** | **FAIL (B1)** |
| **T11** | **yield loss < planned, ALL_OR_NONE** | **code `complete…:471-477`** | **MO uncompletable unless operator lies produced=planned** | **FAIL (B1/B2)** |
| T12 | conversion/overhead in WIP | code `cost_accrued` only ever written 0 | unit_cost = material only | FAIL (B3, =#25) |
| T13 | by-product valuation | code — no add_stock for byproduct | by-product qty recorded, value=0, no stock/GL | FAIL (B4) |
| T14 | scrap stock receipt | code — single add_stock (FG only) | scrap cost absorbed into FG, no scrap stock | KNOWN (A11 v1 scope) |
| **T15** | **concurrent complete, distinct Idempotency-Keys** | **code `complete…` + `mo_service._transition`** | **no MO-row lock; double settle plausible** | **FAIL (B5)** |
| T16 | idempotency-key replay | middleware cache | dedup OK for identical retry | PASS |

---

## 3. Bugs

| Sev | Flow | What | Where | Fix |
|-----|------|------|-------|-----|
| **HIGH** | completion / conservation | **`produced_qty` is operator-asserted and reconciled ONLY to `planned_qty`, never to actual good output (terminal QC `qty_passed` / terminal op `qty_out`).** An operator can — and under ALL_OR_NONE *must* — enter produced=10 when QC passed only 6. The system then mints 10 FG units + posts full WIP→FG, although only 6 good units exist. Units dispatched into QC's `rejected` bucket evaporate; FG qty is fabricated. Conservation (the very invariant QC enforces upstream) is broken at the settlement beat. | `mo_completion_service.complete_mo_with_settlement` L447-482 (body), `routers/manufacturing.py:1316-1337` (passthrough) | Compute `producible = Σ qty_out` of the routing's **terminal** ops (or terminal QC `qty_passed`) and require `produced_qty <= producible`; ideally derive `produced_qty` from the chain instead of trusting the body. |
| **HIGH** | completion policy | **ALL_OR_NONE × any yield loss = deadlock.** `produced_qty` must *exactly* equal `planned_qty` (L471-477) and it's the only policy in v1. Textile cutting/stitching always loses units to scrap/wastage/rework, so a truthful MO (produced < planned) can **never** be completed — forcing operators to either not record losses or to lie produced=planned (which then trips B1). No partial-yield completion path exists. | `mo_completion_service.complete_mo_with_settlement` L469-482; only `ALL_OR_NONE` in `_SUPPORTED_POLICIES` | Ship a `YIELD` / `PARTIAL` policy that accepts `produced_qty = terminal good output` and books variance vs planned to a P&L yield-loss ledger (A11 spec §5 punted this). |
| **MED** | costing | **WIP = material only; conversion + overhead never costed.** `mo_operation.cost_accrued` is written `0` at the single write-site (`qc_service.py:505`) and is never incremented by `operation_progress_service.complete_operation` nor posted to GL; `sum_wip_cost_pool` reads only DR-1310 material-issue lines. In-house labour, machine, and karigar conversion add ₹0 to FG cost. | `cost_accrued` never set ≠0; `sum_wip_cost_pool` L323-351 | Accrue conversion at `complete_operation` (cost-centre rate × time/qty) → DR 1310 / CR conversion-applied, and include in the pool. (= product-review #25.) |
| **MED** | by-product valuation | **By-product recognised in qty, valued at ₹0, never stocked.** `by_product_qty` is summed and written to `mo.by_product_qty` but there is no `add_stock` for it and no GL credit — a saleable co-product (offcuts, seconds) is invisible to inventory and never reduces FG cost. | `complete_mo_with_settlement` L608 (write-only); single `add_stock` L579 (FG only) | Receive by-product to a SECONDS/by-product item at a policy NRV and CR WIP for its value so FG unit cost nets down. |
| **MED** | concurrency | **No MO-row lock during settlement → double-settle window.** `complete_mo_with_settlement` advisory-locks only the voucher-number partition; `get_mo`/`_transition` use no `FOR UPDATE` / version check. Two concurrent completes with *different* Idempotency-Keys both read IN_PROGRESS, both recompute the same `cost_pool` (completion never voids the material-issue vouchers `sum_wip_cost_pool` re-reads), and both post a full WIP→FG voucher + FG receipt → FG double-booked, 1310 over-credited (negative WIP). Idempotency-Key protects identical retries, not genuinely concurrent distinct requests. | `mo_completion_service` (no row lock); `mo_service._transition` L655-667, `get_mo` L548 | `SELECT … FOR UPDATE` the MO row (or advisory-lock on `mo_id`) at the top of `complete_mo_with_settlement`, before the status read. |
| LOW | costing accuracy | **Scrap/wastage material cost fully absorbed into FG via `unit_cost = cost_pool/produced_qty`** with `produced=planned`. Defensible per A11 v1 (scrap stays in FG), but combined with B1/B2 the denominator is the *fabricated* planned qty, so per-unit cost is understated whenever real yield < planned. | `complete…` L506 | Resolve via B1/B2 (correct denominator). |
| LOW | rework cost | Rework clone carries `cost_accrued=0`, no material re-issue, `is_rework_paid=FALSE` → rework is free in the cost model even when it consumes real labour/material. Acceptable for unpaid karigar redo; wrong for in-house/material-consuming rework. | `qc_service._clone_for_rework` L494-505 | Allow material re-issue against the clone + accrue conversion (depends on B3). |

---

## 4. Improvements

1. **Derive, don't ask.** `produced_qty` should be computed from the routing's terminal
   good-output, with the request value (if any) used only as an operator confirmation that
   must match — eliminates B1 by construction.
2. **Yield variance ledger.** Even before a full PARTIAL policy, book `(planned-produced)`
   value to a yield-loss P&L row so management sees real conversion efficiency.
3. **Scrap & by-product as first-class stock receipts** (A11 spec §4) — SECONDS/SCRAP items
   at policy valuation; today they vanish.
4. **Surface conversion cost** (B3) so FG cost reflects more than fabric — the manufacturer's
   margin math is wrong without it.
5. **Completion-preview should flag the produced↔output gap.** `preview_completion`
   currently mirrors the same blind spot (only checks `target==planned`), so the FE shows a
   green "can_complete" even when the asserted qty exceeds what QC passed. Add a
   `producible_qty` field + blocking reason.

---

## 5. Invariant violations (cost & conservation)

- **V1 (conservation, HIGH):** "every unit dispatched upstream of QC is accounted for in one
  bucket downstream" holds *at the QC op* but is **abandoned at completion** — FG qty =
  operator-asserted `planned_qty`, decoupled from `Σ qty_passed`. Units in the `rejected`
  bucket are double-lost (not stocked as scrap, yet replaced by phantom FG). (B1)
- **V2 (cost completeness, MED):** FG unit cost ≠ true cost of production. WIP pool excludes
  ALL conversion/overhead (`cost_accrued≡0`) and by-product recovery, and absorbs scrap
  material against an inflated denominator. (B3, B4, B5-row LOW)
- **V3 (GL balance, OK):** the completion voucher itself is balanced DR 1300 = CR 1310 =
  cost_pool (post-flush invariant L636-639 verified; live preview shows symmetric codes).
  The integrity failure is in the *amount basis* (V2) and *FG quantity* (V1), not the
  double-entry balance.
- **V4 (idempotent settlement, MED):** "settle once" relies on the IN_PROGRESS state guard
  with no row lock → concurrent distinct-key completes can settle twice. (B5)
