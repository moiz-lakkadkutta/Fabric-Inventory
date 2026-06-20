# Flow slice #7 — Inventory & Stock Stages

Agent 7 deep-dive. Builds on product-review **#21** (stock value ₹0) and **#18** (purchase→GL gap),
personas **03-trader** & **05-warehouse** (oversell, no reorder, no multi-UOM). Read against
`backend/app/service/{inventory_service,stock_service,inventory_lots_service,reports_service}.py`,
`routers/inventory.py`, `models/inventory.py`, `schema/ddl.sql`. All claims grounded with code refs,
live API probes, and read-only DB counts (`fabric-postgres-1 / fabric_erp`, 2026-06-20).

---

## 0. Ground-truth snapshot (read-only DB)

| Metric | Value | Meaning |
|--------|-------|---------|
| `stock_position` rows | 79 | current-state table |
| …with `current_cost > 0` | **78/79** | real weighted-avg cost IS maintained |
| …with `lot_id NOT NULL` | **1/79** | lot linkage essentially absent |
| `sum(on_hand_qty*current_cost)` | **₹2,454,424.20** | the *true* stock value |
| `/reports/stock-summary` total | **₹0.00** | what the user sees (live probe) |
| `lot` rows | **1** | lot path effectively dead |
| `stock_ledger` rows | 184 | append-only log |
| …with `from_stage`/`to_stage` set | **0** | all 23 stock stages unreachable |
| …with `this_hash` populated | **0/184** | hash-chain never written |
| `stock_position` with reserved/in-transit > 0 | **0** | reservation+transit machinery dead |
| `stock_take` rows | **0** | table modelled-out, no code |
| `item.allow_negative` distinct | `NEVER` ×227 | column never read by any code |

Ledger `reference_type` mix: MATERIAL_ISSUE 71, TEST_SEED 42, GRN 29, ADJUSTMENT 25,
JOB_WORK_SEND 8, JOB_WORK_RECEIVE 4, MANUFACTURING_COMPLETION 3, DC 2.
Locations: WAREHOUSE 230, IN_TRANSIT 2 (jobwork only).

---

## 1. Flows that actually touch stock

The **only** writers of `stock_position`/`stock_ledger` are `inventory_service.add_stock` /
`remove_stock` (+ `reserve/unreserve_for_so`, which have **no callers**). Real callers:

| Flow | Direction | Call site | lot_id passed? | cost source |
|------|-----------|-----------|----------------|-------------|
| GRN receive | IN | `procurement_service.py:569` | **No (None)** | `grn_line.rate` (0 if NULL) |
| DC issue (sales out) | OUT | `sales_service.py:565` | `line.lot_id` | position `current_cost` |
| Material issue (MO/BOM) | OUT | `material_issue_service.py:411` | — | position |
| Jobwork send | OUT@MAIN + IN@JOBWORK-loc | `jobwork_service.py:280,308` | `lot_id` | carries MAIN cost |
| Jobwork receive-back | IN | `jobwork_service.py:588` | `lot_id` | re-blend |
| MO completion (FG) | IN | `mo_completion_service.py:579` | — | computed FG cost |
| Stock adjustment | IN/OUT | `stock_service.create_adjustment` | optional | `unit_cost` param, **default 0** |

Process graph (stock view): `GRN→(+on_hand)` … `DC issue→(−on_hand)`. **Stock decrements on DC, not on
SO or invoice.** SO confirm does **not** reserve (see Bug INV-2), so there is no stock guarantee
between order and dispatch. Jobwork is the *only* inter-location movement (remove@MAIN + add@JOBWORK
location) — there is **no general godown-to-godown / firm-to-firm transfer endpoint**.

---

## 2. Stage reachability + transition matrix

`StockStage` (`models/inventory.py:62`, DDL `stock_stage` enum line 2040) has **23 values** (the
flow-machine §A says "24" — miscount; enumerate: RAW, CUT, AT_DYEING, AT_PRINTING, AT_EMBROIDERY,
AT_HANDWORK, AT_STITCHING, AT_WASHING, AT_FINISHING, DYED, EMBROIDERED, HANDWORKED, STITCHED, WASHED,
QC_PENDING, FINISHED, PACKED, REWORK_QUEUE, SECONDS, REJECTED, SCRAP, DISPATCHED, IN_TRANSIT = 23).

The enum is referenced **only** on two nullable, never-written columns:
`stock_ledger.from_stage` / `to_stage` (`models/inventory.py:235-236`). **Grep across the whole
`service/` + `routers/` tree finds zero assignments to either column and zero references to any
`StockStage.<VALUE>`.** DB: 0/184 ledger rows carry a stage.

### Stage reachability table

| Stage | Reachable by any flow? | By which flow |
|-------|:--:|--|
| RAW, CUT | **No** | — (item_type=RAW exists but is `ItemType`, a *different* enum) |
| AT_DYEING / AT_PRINTING / AT_EMBROIDERY / AT_HANDWORK / AT_STITCHING / AT_WASHING / AT_FINISHING | **No** | — (MO operations track state on `mo_operation`, never on stock stage) |
| DYED / EMBROIDERED / HANDWORKED / STITCHED / WASHED | **No** | — |
| QC_PENDING / FINISHED / PACKED | **No** | — (QC verdict lives on `mo_operation`/QC tables, not stock) |
| REWORK_QUEUE / SECONDS / REJECTED / SCRAP | **No** | — (rework/scrap recorded as qty buckets in MO settlement, not stage) |
| DISPATCHED / IN_TRANSIT | **No** | — (jobwork uses a *Location* of `location_type=IN_TRANSIT`, not the stage enum) |

**Verdict: 23/23 stages are dead/unreachable.** The stock layer is single-stage (a flat on-hand pool
per item×lot×location). All manufacturing "stage" semantics live on `mo_operation` and are never
projected onto inventory. The `stock_stage` enum + two ledger columns are pure schema scaffolding
(Phase-3 placeholder per the model docstring) — honest, but should not be mistaken for a working
WIP-by-stage inventory.

### Transition test matrix (what the engine *does* enforce)

| Transition | Guard | Tested result |
|------------|-------|---------------|
| 0 → +qty (first inbound) | qty>0 | ✓ creates position, cost=unit_cost |
| +qty inbound (existing) | qty>0 | ✓ weighted-avg blend (`inventory_service.py:320`) |
| outbound, on_hand ≥ qty | — | ✓ on_hand−qty, cost unchanged |
| outbound, on_hand < qty | `on_hand < qty` → 422 | ✓ **live probe: 422 "Insufficient stock"** (ignores `allow_negative`, Bug INV-3) |
| outbound, no position row | row None → 422 | ✓ |
| qty ≤ 0 on add/remove | `_validate_qty` → 422 | ✓ |
| reserve, atp < qty | manual atp calc → 422 | ✓ logic correct **but never invoked** (Bug INV-2) |
| stage transition | n/a | **no code path exists** |

---

## 3. Bugs

| # | Sev | Flow | What | Where | Fix |
|---|-----|------|------|-------|-----|
| **INV-1** | **P1** | Valuation | **Stock value reports ₹0 while true value is ₹2.45M.** `compute_stock_summary` weights qty by `Lot.primary_cost` via `outerjoin(Lot, Lot.lot_id==StockPosition.lot_id)`. But **no flow mints lots** — GRN calls `add_stock` with **no `lot_id`** (`procurement_service.py:569`), so 78/79 positions have `lot_id IS NULL` → lot join yields NULL → `coalesce(...,0)` → ₹0. The real weighted-avg is in `stock_position.current_cost` (78/79 populated). Deepens product-review **#21**: it is *structural*, not "1-column" — the report reads a table (`lot`) that the write path never fills. | `reports_service.py:566-567,583` (read) ↔ `procurement_service.py:569` (write) | Drop the Lot join; `weighted_value = sum(StockPosition.on_hand_qty * coalesce(StockPosition.current_cost,0))`. Live: report ₹0.00 vs DB ₹2,454,424.20. |
| **INV-2** | **P1** | SO→DC oversell | **No stock reservation; oversell window open.** `reserve_for_so`/`unreserve_for_so` exist (`inventory_service.py:477,515`) but have **zero callers** — SO confirm never reserves. `reserved_qty_so`/`reserved_qty_mo`/`in_transit_qty` are always 0 (DB: 0 rows non-zero), so `atp_qty == on_hand_qty` always. Stock only drops at **DC issue** (`sales_service.py:565`), not SO/invoice. ⇒ N concurrent SOs for the same on-hand all "succeed"; the clash surfaces only when the 2nd DC fails. Confirms persona 05 oversell. | `inventory_service.py:477` (dead) ; `sales_service` SO-confirm (no reserve call) | Call `reserve_for_so` on SO confirm; release on DC/cancel. Surface ATP (not on_hand) as "available". |
| **INV-3** | P2 | Outbound | **`item.allow_negative` is a dead column.** `remove_stock` hard-blocks `on_hand < qty` (422) with no override path; `allow_negative` (DDL `item:408`, model `masters.py:363`) is never read anywhere (grep: 1 hit, the definition). A trader who legitimately sells ahead of GRN entry (common in textile) cannot, even if configured. Corrects persona 05's "blocked by DB CHECK": **there is no DB CHECK on `on_hand_qty`** (DDL `stock_position:654` is plain `NOT NULL DEFAULT 0`) — the guard is purely app-layer in `remove_stock`. | `inventory_service.py:392`; `allow_negative` unread | Branch on `item.allow_negative` (NEVER/WARN/ALWAYS) before the 422. |
| **INV-4** | P2 | Audit integrity | **`stock_ledger` hash-chain never written.** `prev_hash`/`this_hash` columns exist (`models/inventory.py:247-248`) but `add_stock`/`remove_stock` construct `StockLedger()` without them (`inventory_service.py:326-340, 402-416`). DB: 0/184 rows hashed. The "append-only + hash-chain" tamper-evidence the model docstring promises is absent for inventory. | `inventory_service.py:326,402` | Populate hash-chain like the audit_log path, or drop the columns + docstring claim. |
| **INV-5** | P2 | Adjustment costing | **"Found stock" adjustments dilute weighted-avg to 0.** INCREASE / COUNT_RESET→up default `unit_cost=0` (`stock_service.py:42, 90`). Adjusting +qty at ₹0 blends a 0 cost into `current_cost`, silently writing down the item's average cost. 25 ADJUSTMENT ledger rows exist. | `stock_service.py:90,182` | Default to current position `current_cost` (like DECREASE/jobwork do), not 0; only use 0 when caller explicitly says cost-unknown. |
| **INV-6** | P3 | Lots | **Lot path is dead but advertised as live.** Router comment "lot creation already happens inside GRN / Receive-Back" (`routers/inventory.py:250`) is false — no `Lot()` is constructed in any service (grep: 0). `/lots` returns ~empty; `grn_line.lot_number` is captured (`procurement_service.py:492`) then dropped (not passed to `add_stock`). FEFO/expiry, supplier-lot traceability all non-functional. | `procurement_service.py:492,569` | Mint a `Lot` from `grn_line.lot_number` and pass `lot_id` into `add_stock`. |
| **INV-7** | P3 | Adjustment | COUNT_RESET no-op path synthesizes a ledger row with `txn_type="IN"` for a zero-movement (`stock_service.py:160`) — mislabels a reset as an inbound. Cosmetic but pollutes ledger filters. | `stock_service.py:160` | Use a `txn_type="RESET"`/`"ADJUST"` label. |

---

## 4. Improvements

1. **General stock transfer.** No godown↔godown or firm↔firm transfer endpoint exists; only jobwork
   moves across locations (remove+add). A first-class `transfer_stock` (atomic OUT+IN, optional
   in-transit) is needed for multi-warehouse traders.
2. **Reorder / low-stock is a proxy only.** `item.min_qty` exists (DDL `:548`, `masters.py:659`) but
   `dashboard_service._low_stock_skus` counts `on_hand <= 0`, ignoring `min_qty` entirely
   (`dashboard_service.py:235`). Wire reorder thresholds to `min_qty`.
3. **Multi-UOM / than–thaan absent.** `add_stock`/`remove_stock` assume a single primary UOM; no
   meter↔piece↔set conversion, `item_uom_alt` empty. Textile "thaan" (roll) vs meter is unsupported.
4. **`stock_take` table is orphaned** (0 rows, no model/service/router) — physical-count workflow
   unbuilt; adjustments are the only correction path.
5. **`reserved_qty_mo` / `in_transit_qty` unused** — MO release and jobwork dispatch should populate
   these so ATP reflects committed-but-not-consumed stock.
6. **Valuation cannot do "as-of past date"** — `compute_stock_summary` reads current `stock_position`
   only; `as_of` param accepted but ignored (`reports_service.py:527`). Historical valuation needs a
   ledger walk.

---

## 5. Invariant checks

| Invariant | Status |
|-----------|--------|
| `on_hand_qty == Σ(qty_in − qty_out)` over ledger key | **Holds** — both atoms written in one txn under `SELECT…FOR UPDATE` (`inventory_service.py:249,385`). |
| `atp_qty == on_hand − reserved_mo − reserved_so − in_transit` | Holds trivially (generated col `stock_position:658`) but **vacuous** — reserved/transit always 0 (INV-2). |
| Weighted-avg cost monotonic/correct | Math correct (`:320`); **violated economically** by INV-5 (₹0 dilution). |
| Append-only ledger, no UPDATE/DELETE | Holds for qty; **hash-chain integrity broken** (INV-4). |
| No negative on-hand | Holds via app-layer 422 (no DB CHECK — INV-3); but oversell deferred to DC, not prevented at SO (INV-2). |
| Idempotency on mutating stock endpoints | **Holds** — global `middleware/idempotency.py` enforces; live probe: missing key → **400**, valid dup deduped. |
| RLS / org isolation | Holds — `stock_ledger`/`stock_position` have `org_id` RLS policies (DDL `:645,677`); services filter `org_id` explicitly. **Firm-level** isolation relies on caller-passed `firm_id` (flow-machine §C firm-spoof caveat applies). |
| Money = NUMERIC/Decimal | Holds — `Numeric(15,4)` qty, `Numeric(15,6)` cost, `Decimal` throughout. |

---

### Live/DB evidence log (non-destructive)
- `GET /reports/stock-summary` → `total_value: 0.00`, 12 rows all `avg_cost 0.0000` (INV-1).
- DB `sum(on_hand_qty*current_cost)` = ₹2,454,424.20; 78/79 `current_cost>0`; 1/79 with lot.
- `POST /stock-adjustments` DECREASE 9999 on on_hand=5 → **422** "Insufficient stock" (no record created).
- `POST /stock-adjustments` without `Idempotency-Key` → **400** (middleware enforced).
- No `ZZTEST-*` records committed; all forward probes were rejected by design.
