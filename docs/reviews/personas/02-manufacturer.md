# Persona Review 02 — The Textile Manufacturer / Production Owner

**Reviewer:** Claude Code (senior ERP product analyst)
**Date:** 2026-06-20
**Build:** live backend `http://localhost:8000`, org "Demo Co", read-only DB probe + full code read of `backend/app/service/{bom,mo,mo_completion,operation_progress,routing,routing_flow,qc,material_issue,jobwork,karigar_send_out}_service.py` and `models/manufacturing.py`.
**Scope:** Manufacturing only — the product's "long pole" for the upcoming customer trial.
**Relationship to the general review** (`docs/reviews/product-review-2026-06-20.md`): that review's manufacturing findings (#9 overdue badge, #11 progress mismatch, #12 QC qty handoff, #13 routing clone, #15 cost-centre UUID, #21 stock value ₹0) are **not repeated** here except where this review finds the *root cause* and goes deeper. New findings are marked **[NEW]**.

---

## 1. Persona & jobs-to-be-done

**Who:** Owner of a small/mid textile manufacturing unit making ladies' suits / sarees. Runs designs → BOM → routing → manufacturing orders (MO) → shop-floor operations (cut / stitch / embroider / QC / pack), pushes operations out to *karigars* (job-workers) on piece-rate, receives finished goods back, and lives or dies on **product costing** and **on-time delivery**.

**Jobs-to-be-done:**
1. Define a design once and reuse its recipe (BOM) + process (routing) across many production runs.
2. Release an MO, issue fabric/trims from stock, and watch units flow stage-by-stage.
3. Send embroidery/stitching to karigars, track what went out vs what came back, and pay them by piece.
4. Catch defects at QC, route rejects to rework, and know real yield.
5. Know the **true landed cost** of each finished suit (fabric + trims + **labour/job-work** + overhead) so pricing isn't guesswork.
6. Hit delivery dates — know which MOs are late and why.

---

## 2. What works well today (fair, evidenced)

Manufacturing is genuinely the most sophisticated module in the product. Several pieces are production-grade:

- **Routing DAG validation is real and robust.** Live-probed (all rejected, 422): a 2-cycle `A→B,B→A`, a self-loop `A→A`, and a duplicate edge `A→B,A→B`. Code: `routing_service._validate_edges` (`routing_service.py:169-207`) + iterative 3-colour DFS cycle detector (`:129-166`), run on **both** create and edge-update. Cross-firm / nonexistent operation refs are also rejected (`:199-204`). This is the strongest single feature.
- **Three real edge dependency types with threshold semantics**, not just linear chains: `FINISH_TO_START`, `START_TO_START`, `PARTIAL_FINISH_TO_START` with `threshold_qty`/`threshold_pct` and a per-executor baseline (IN_HOUSE uses predecessor `qty_in`, KARIGAR uses `MO.planned_qty`) — `routing_flow_service._check_edge` (`:260-404`). Parallel/diamond branches genuinely run concurrently because gating walks actual incoming edges, not a sequence.
- **BOM versioning is atomic and well-guarded.** New version self-promotes and demotes priors in one transaction under a `pg_advisory_xact_lock` + row `FOR UPDATE` (`bom_service.py:274-333`); delete promotes the next active (`:542-549`). MO creation requires `bom.is_active` (`mo_service.py:344-345`).
- **Deterministic operation sequencing.** MO explosion topologically sorts the routing via Kahn's algorithm with a UUID tiebreaker so two MOs off the same diamond DAG get identical `operation_sequence` (`mo_service._topological_order_operations:169-232`). BOM qty correctly scales `qty_required * planned_qty` in `Decimal` (`:419`).
- **QC 5-bucket conservation is mathematically sound.** `passed+rejected+byproduct+wastage+rework == source qty_out`, strict equality on the NUMERIC(15,4) grid, non-negativity per bucket (`qc_service.py:668-683`). Rework depth-guarded to 5 (`:378-408`).
- **Rework loop is wired end-to-end (flow side).** A REWORK verdict clones the worker op (`rework_of_mo_operation_id`), state→REWORK, and completion is **blocked** until the clone closes (`qc_service._clone_for_rework:431-515`; `mo_completion_service._assert_all_ops_closed:363-400`).
- **MO completion posts a balanced GL voucher and updates FG valuation.** `MANUFACTURING_COMPLETION` DR `1300 Inventory` / CR `1310 WIP`, DR==CR invariant asserted, then `inventory_service.add_stock(unit_cost=...)` weighted-averages FG cost (`mo_completion_service.py:519-594`). **DB-verified:** finished item `6aa9a052…` carries `current_cost = 2400.00` on 2 units — so completion *does* value FG (the review's #21 "stock value ₹0" is a **reports-layer** bug, not a completion bug).
- **Material issue validates stock and posts to GL.** Per-(item,lot) on-hand check with FOR UPDATE, duplicate-line combining, DR `1310 WIP` / CR `1300 Inventory` (`material_issue_service.py:296-368, 485-502`).
- **Good completion UX.** `completion-preview` returns `cost_pool`, `unit_cost`, policy, and explicit `blocking_reasons` (live-probed on MO-0003: 5 PENDING ops listed). State-gated MO buttons with clear tooltips (general review ✅).

---

## 3. Gaps / missing for a real manufacturer (ranked by trial impact)

### G1 — No conversion cost in product costing (material-only WIP pool) **[NEW] — most important**
The WIP cost pool is **only** material issues. `sum_wip_cost_pool` (`mo_completion_service.py:323-351`) sums *only* `voucher_line.amount` on DR-to-1310 lines posted by material issues. `mo_operation.cost_accrued` exists but is **never rolled into the pool** (only ever written as `0` on rework clones, `qc_service.py:505`). There is **no labour absorption, no overhead absorption, no cost-centre absorption** anywhere. Live evidence: MO-0003 `cost_pool = 6532.50`, `unit_cost = 653.25` = pure fabric/trim cost, zero stitching/embroidery cost.
→ For a job-work textile shop where karigar charges are a large share of cost, finished-goods cost is **systematically understated** and pricing off the system would lose money. This is the #1 costing gap.

### G2 — Job-work captures no rate/charge at all **[NEW]**
`job_work_order` / `_line` / `job_work_receipt` / `_line` (DB-verified schema) have **no rate / charge / amount / cost column** — only quantities. `dispatch_to_karigar` / `receive_from_karigar` take no rate. There is **no karigar payable, no piece-rate, no labour accrual, no GL posting** for job-work. Combined with G1, the entire conversion side of the business is financially invisible. A manufacturer cannot answer "how much do I owe Ramesh-bhai this week?"

### G3 — Single-level BOM only; no sub-assemblies **[NEW]**
`bom_line` has no `child_bom_id` / phantom / sub-assembly concept (`models/manufacturing.py:277-309`); MO explosion is a flat `for line in bom.lines` with no recursion (`mo_service.py:410-426`). A semi-finished intermediate (dyed fabric → cut panels → garment) cannot be modelled as its own BOM; everything must be hand-flattened into one level.

### G4 — No qty auto-propagation between operations; QC inbound qty not persisted **[NEW — root cause of review #12]**
No code writes a downstream op's `qty_in` when the upstream op records `qty_out`/closes — every op's `qty_in` is a **manual operator entry**. Worse, the QC op's `qty_in` is **not persisted at `start_qc_inspection`** — the arriving qty is only written into the *event payload* (`qc_service.py:594`) and the column is set later in `record_qc_result` (`:818`). So any read surface showing `mo_operation.qty_in` shows **0** between QC-start and QC-result even though upstream closed at 10. That is the exact root cause of review #12 ("Source qty arriving: 0"). For a shop floor, manual qty re-keying at every stage is slow and error-prone.

### G5 — Settlement qty (`produced_qty`) is operator-asserted, not reconciled to QC `qty_passed` **[NEW — correctness]**
`complete_mo` takes `produced_qty` as a parameter and only checks `== planned_qty` (ALL_OR_NONE, `mo_completion_service.py:469-482`). It is **never cross-checked against the terminal QC op's conserved `qty_passed`**. An operator can complete 10 into FG inventory while QC actually passed fewer (rest scrapped/reworked), and the full pool is spread over 10 units. The QC conservation invariant and the inventory settlement are decoupled.

### G6 — Scrap / wastage / by-products carry zero cost **[NEW]**
The full `cost_pool` is divided across good units only (`unit_cost = cost_pool / produced_qty`, `:506`). Scrap/wastage/by-product are recorded as **quantities only** (`mo.scrap_qty`, `by_product_qty`) — **no GL scrap write-off, no by-product inventory capitalization, no per-unit cost reallocation**. By-products (a real revenue source — fabric cut-pieces, reject fents) never hit stock and never get valued.

### G7 — No make-to-order; no sales-order ↔ MO link **[NEW]**
`manufacturing_order` has **no `sales_order_id`** column (DB-verified, 27 columns). You cannot raise an MO from a customer order, cannot trace "this production run is for Lakshmi Saree Centre's order," cannot back-flush against a sale. For a manufacturer who produces against confirmed orders, this is a workflow gap.

### G8 — No partial / over completion **[NEW]**
`completion_policy` only supports `ALL_OR_NONE`; anything else hard-rejects (`:469-482`, `_SUPPORTED_POLICIES = {"ALL_OR_NONE"}`). Real runs rarely yield exactly the planned qty — a batch of 100 suits that yields 96 good + 4 reject **cannot be completed** as-is.

### G9 — No capacity / finite scheduling **[NEW]**
`operation_master.default_duration_mins` exists but nothing consumes it. No work-centre load, no finite scheduling, no due-date derivation. `planned_start/end_date` are manual free-entry on the MO. "Which karigar is overloaded / when will this finish" is unanswerable. (Review #9's overdue badge is a downstream symptom of having no real schedule.)

### G10 — No lot / dye-lot traceability through production **[NEW — textile-critical]**
`mo_material_line.lot_id` and `material_issue_line.lot_id` exist, but lot identity is **not carried forward** to the finished good or QC result. Dye-lot/shade matching ("which finished suits came from dye-lot #47") — a core textile quality concern — is not traceable.

### G11 — Routing versioning not surfaced (unlike BOM)
`routing.version_number` exists but there is no activate/supersede workflow; a second non-deleted `(firm,code)` is rejected (`routing_service.py:339-348`) so you must soft-delete + recreate. Combined with the review's #13 ("clone graph from active version" does nothing), a routing change means **rebuilding the whole DAG by hand**.

### Lesser gaps (evidenced, lower trial impact)
- **G12** Optional operations not supported at routing level — only `bom_line.is_optional` for materials; every routed op is materialized unconditionally (`models:415-449`).
- **G13** Multi-input QC on a diamond merge explicitly unsupported — `_find_qc_predecessor` requires exactly one incoming edge (`qc_service.py:315-324`).
- **G14** `MoStatus.CANCELLED` doesn't exist; `cancel_mo` is unimplemented (`mo_service.py:772-777`). An MO cannot be cancelled.
- **G15** Single-active BOM invariant is app-code-only — no DB partial-unique index (`bom_service.py:43-44` admits this). A raw write or future bypass could leave two active versions.
- **G16** `mo_operation.outward_challan_id` / `inward_challan_id` have **no FK** (DB or ORM) — the MO↔job-work link is by convention only (`models:613-618, 672-681`); a dangling challan id wouldn't be caught.
- **G17** Material-issue valuation uses position weighted-avg even when a `lot_id` is given (not lot cost), and **NULL cost silently falls back to 0** (`material_issue_service.py:339-346`) — a plausible contributor to ₹0-cost lines (review #21).
- **G18** `completion-preview` blocking reasons print raw operation UUIDs, not names (live-probed) — same FK-display family as review #15/#17.

---

## 4. Edge cases tested (probe → actual result)

| # | Probe | Result |
|---|-------|--------|
| E1 | Routing with 2-cycle `A→B,B→A` (POST /routings, idempotency key) | **422 rejected** ✓ — cycle detector works live |
| E2 | Routing self-loop `A→A` | **422 rejected** ✓ |
| E3 | Routing duplicate edge `A→B,A→B` | **422 rejected** ✓ |
| E4 | `completion-preview` on IN_PROGRESS MO-0003 (qty 10) | 200 — `can_complete:false`, 5 PENDING ops listed as blocking reasons, `unit_cost 653.25` (material-only) |
| E5 | MO-0003 detail: header `status=IN_PROGRESS` but **all 5 ops `state=PENDING`, qty_in/out=0** | Confirms review #11 — header status and op-level progress are independent; seed set header without advancing ops |
| E6 | FG stock cost for MO output item `6aa9a052…` | `current_cost = 2400.00`, qty 2 — completion *does* value FG; review #21's ₹0 is a reports-layer bug, not completion |
| E7 | `qc_result` row count in DB | **0** — the 5-bucket QC verdict has never been exercised by seed data; untested in any seeded MO |
| E8 | MO `manufacturing_order` columns scanned for sales-order link | None — make-to-order not modelled (G7) |
| E9 | `job_work_order`/`receipt` columns scanned for rate/charge | None — piece-rate not captured (G2) |
| E10 | Raw-material `stock_position.current_cost` sample | Mostly real (50–2567); some seeded items at flat 50 — cost chain is partially populated |

---

## 5. Customizations required (textile-manufacturing specific)

1. **Karigar piece-rate & payable** (addresses G2): add rate/charge to `job_work_order_line`, accrue a karigar-payable on dispatch/receipt, post job-work charge into the MO WIP pool and GL. Highest-value textile customization.
2. **Conversion costing** (G1/G6): roll operation/labour + job-work + cost-centre overhead into `cost_pool`; value scrap write-off and by-products. Without this, "cost per suit" is fiction.
3. **Size/colour matrix** (G3-adjacent): today every size/colour is a *separate* finished item + full BOM + routing (`bom` keyed on `(design, finished_item)`). A textile maker thinks in a single design × {S/M/L/XL} × {colours} matrix — needs a variant/matrix layer so one design auto-expands into SKUs sharing a BOM template with per-variant overrides.
4. **Multi-level / sub-assembly BOM** (G3): model dyed-fabric → cut-panels → garment as nested BOMs with recursive explosion.
5. **Dye-lot / shade-lot traceability** (G10): carry `lot_id` from issued fabric through ops to FG and QC so shade-matching and lot recalls work.
6. **Make-to-order linkage** (G7): `sales_order_id` on MO + back-flush so production traces to the customer order.
7. **Partial/yield completion** (G8): allow `produced_qty < planned_qty` with the remainder booked as scrap/loss, reconciled to QC `qty_passed` (G5).
8. **Shop-floor qty auto-flow** (G4): auto-propagate good `qty_out` → next op `qty_in`; persist QC inbound qty at inspection start.

---

## 6. Top UX boosts (ranked)

| # | Boost | Why | Effort |
|---|-------|-----|--------|
| 1 | **Auto-propagate qty between consecutive ops + persist QC inbound qty at start** (G4) | Kills manual re-keying at every stage and fixes review #12's confusing "arriving: 0". Biggest day-to-day shop-floor friction. | M |
| 2 | **Show conversion/job-work cost in MO Cost tab & completion-preview** (G1/G2) | Owner's #1 question is "what does this suit cost me?" — today it silently omits all labour. Even a manual labour-cost field per op would help. | M |
| 3 | **Resolve operation/cost-centre/challan UUIDs → names** across MO ops, blocking reasons, job-work (G18, review #15/#17) | Raw UUIDs everywhere make the shop-floor screens unreadable. Pure display join. | S |
| 4 | **Unify MO progress to one definition** (review #11) + drive the overdue badge off a real date calc (review #9) | Two different "progress" numbers and a wrong "+26d" badge erode trust on the headline kanban. | S |
| 5 | **Fix routing "clone from active version" + add routing versioning** (review #13, G11) | Editing a process today means rebuilding the entire DAG by hand — a hard blocker to iterating on a design. | M |
| 6 | **Karigar piece-rate entry on dispatch + weekly payable summary** (G2) | Turns job-work from quantity-only tracking into something an owner can actually pay against. | L |
| 7 | **Size/colour variant matrix on Design** (customization #3) | A textile maker's mental model is one design × many sizes/colours; forcing a separate full BOM+routing per SKU is the biggest data-entry tax at onboarding. | L |

---

## Trial-readiness verdict (manufacturing)

**Amber — strong skeleton, not yet trustworthy for the numbers that matter.** The *flow* engine (routing DAG, gating, QC conservation, rework loop, state machines) is genuinely impressive and correct under live probing. But the module is **costing-incomplete** (material-only WIP, zero labour/job-work, no piece-rate, zero-cost scrap/by-product) and **make-to-order absent**, so the two things a production owner buys an ERP for — *true product cost* and *order-to-delivery traceability* — are not yet there. Safe to demo the shop-floor flow; not yet safe to price products or pay karigars off it.
