# Design proposal — stage-wise WIP stock on `stock_position`

**Status:** PROPOSAL, pending Moiz + CA sign-off. Nothing here is implemented yet.
**Author:** Claude Code (fix-karigar-input follow-up), 2026-10-23
**Decision already taken (Moiz):** go with the stage dimension on `stock_position`,
from architecture §5.6.4 and §5.6.7. The alternatives (per-op intermediate items, or
challan-only send-outs) are rejected.
**Replaces:** the stopgap in `karigar_send_out_service._refuse_default_finished_goods_dispatch`.

---

## 1. Problem (today's model)

| Point in the MO | Where the goods are held today |
|---|---|
| Raw fabric in godown | `stock_position(item=raw, location=MAIN)` |
| After material issue (A06) | **Nowhere in stock.** `remove_stock` drops the raw qty, and its value moves to GL `1310 WIP` (DR 1310 / CR 1300). |
| Between operations (CUT done, STITCH pending) | **Nowhere in stock.** Only `mo_operation.qty_in/qty_out` counters exist, plus the 1310 pool. |
| After MO completion (A11) | `stock_position(item=finished, location=MAIN)`, with the 1310 pool drained into it (DR 1300 / CR 1310). |

Karigar send-out (`jobwork_service.create_send_out`) is a stock move MAIN → JOBWORK.
It needs a stock row to move, and mid-routing pieces don't have one. Every op after
the first defaults to the MO's finished item, so the send-out either fails or moves
unrelated finished goods. Receive-back then adds finished goods that completion adds
again. The first op has a milder version of the same problem: it ships raw that was
already issued, so it needs twice the raw on hand, and receive-back puts it back.

## 2. Target model

From §5.6.4: `StockPosition = (item, lot, location, stage, qty)`, plus a link to the
owning MO for every WIP row.

* **Store stock** (anything not in production, which is every row that exists today)
  has `stage IS NULL` and `manufacturing_order_id IS NULL`. Its meaning is unchanged.
* **WIP stock** has `stage IS NOT NULL` and `manufacturing_order_id IS NOT NULL`.
  - In v1, **the item on a WIP row is the item physically being worked on**:
    - the issued raw item while it is still raw (`stage = RAW`);
    - the MO's finished item once the first transforming op has produced pieces
      (`stage = CUT / AT_STITCHING / STITCHED / QC_PENDING / ...`).
  - This keeps master data unchanged. No SEMI_FINISHED item per op is needed. Parts
    (dupatta, kurta body) as separate items can be added later without a schema change
    (see open question Q4).
* WIP rows are **quantity-only**. Their `current_cost` stays NULL. Value stays in the
  per-MO 1310 pool (see §5). This is what keeps GL treatment unchanged.

The `stock_stage` Postgres enum **already exists** in the baseline DDL (`RAW, CUT,
AT_DYEING … AT_FINISHING, DYED, EMBROIDERED, HANDWORKED, STITCHED, WASHED, QC_PENDING,
FINISHED, PACKED, REWORK_QUEUE, SECONDS, REJECTED, SCRAP, DISPATCHED, IN_TRANSIT`).
`stock_ledger.from_stage / to_stage` exist too, nullable and unused. We reuse both.

## 3. Schema change (one Alembic migration, needs Moiz sign-off)

```sql
-- stock_position
ALTER TABLE stock_position
  ADD COLUMN stage stock_stage NULL,
  ADD COLUMN manufacturing_order_id UUID NULL
      REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE RESTRICT,
  ADD CONSTRAINT stock_position_stage_mo_pairing
      CHECK ((stage IS NULL) = (manufacturing_order_id IS NULL)),
  ADD CONSTRAINT stock_position_wip_no_cost
      CHECK (stage IS NULL OR current_cost IS NULL);

-- replace the uniqueness key (built CONCURRENTLY outside the txn, then swap)
CREATE UNIQUE INDEX CONCURRENTLY uq_stock_position_org_firm_item_lot_location_stage_mo
  ON stock_position (org_id, firm_id, item_id,
                     COALESCE(lot_id, '00000000-0000-0000-0000-000000000000'::uuid),
                     location_id,
                     COALESCE(stage::text, ''),
                     COALESCE(manufacturing_order_id, '00000000-0000-0000-0000-000000000000'::uuid));
DROP INDEX uq_stock_position_org_firm_item_lot_location;

-- fast "everything AT_EMBROIDERY" / "WIP of MO X" queries
CREATE INDEX ix_stock_position_wip
  ON stock_position (org_id, firm_id, manufacturing_order_id, stage)
  WHERE stage IS NOT NULL AND deleted_at IS NULL;

-- stock_ledger: from_stage/to_stage already exist; add the MO link
ALTER TABLE stock_ledger
  ADD COLUMN manufacturing_order_id UUID NULL
      REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE RESTRICT;

-- per-MO opt-in so open MOs keep legacy behaviour (see §3.2)
ALTER TABLE manufacturing_order
  ADD COLUMN stage_tracked BOOLEAN NOT NULL DEFAULT FALSE;
```

* **RLS:** no new tables. `stock_position`, `stock_ledger` and `manufacturing_order`
  already have org and firm-scoped policies (migration 210). The new FK points at a
  table under the same policies, so a WIP row can't reference another tenant's MO.
  The CHECK constraints are tenant-agnostic. `test_rls.py` gets one new case: a WIP
  position in firm A can't be seen from firm B.
* **Audit columns:** `stock_position` already has `deleted_at` and the audit-by columns.
  Nothing new needed.
* **Feature flag:** `feature_flag.key = 'mfg.stage_stock.enabled'` per firm, default
  FALSE. `mo_service.create_mo` sets `stage_tracked = flag` on new MOs.

### 3.1 Backward compatibility

* All existing rows get `stage = NULL, manufacturing_order_id = NULL`. Their meaning
  is unchanged, and the old unique key is a strict subset of the new one.
* `inventory_service.add_stock / remove_stock / get_position / _position_predicate`
  get optional `stage=None, manufacturing_order_id=None` kwargs. The predicate matches
  `IS NULL` when they're omitted, so **every existing caller keeps touching store
  stock only** with no code change.
* The risk is in **aggregating readers** that don't go through `_position_predicate`.
  Each one must add `stage IS NULL`, or WIP qty leaks into "available" figures:
  `reports_service.compute_stock_summary`, `dashboard_service._low_stock_skus`,
  `inventory_lots_service`, `inventory_service.get_total_on_hand /
  remove_stock_fifo / list_positions`, `procurement_service`, `sales_service`
  (reserve / FIFO), `stock_service`, `material_issue_service._pick_location_for_position`,
  and `seed_demo_service`. A guard test (`test_stage_stock_readers.py`) seeds one WIP
  row and asserts that every one of these reports the same numbers as without it.
* This is an additive migration. The `CONCURRENTLY` index swap avoids long locks.
  Downgrade drops the columns only when no WIP rows exist (fail-closed pre-flight,
  per INFRA.md migration guard rules).

### 3.2 Backfill for MOs already in flight

No backfill of WIP rows. MOs created before the flag is flipped keep
`stage_tracked = FALSE` and the legacy path, including the stopgap guard, until they
complete. That avoids inventing stage quantities from op counters that were never
reconciled. A firm flips the flag once its open MOs are closed, or accepts
mixed-mode MOs. A read-only report lists `stage_tracked = FALSE` MOs that are still
open.

## 4. Stock movements per flow (only for `stage_tracked` MOs)

Notation: `item@stage[location]`, all rows scoped to the MO.

| Flow | Stock move | GL |
|---|---|---|
| **Material issue (A06)** | store `raw[MAIN]` → `raw@RAW[MAIN]` (OUT of store row, IN to WIP row; same lot carried) | unchanged: DR 1310 / CR 1300 at weighted-average cost |
| **In-house op start + qty-in (A07)** | consume predecessor output rows (`raw@RAW` for op #1, else predecessor's `finished@<done-stage>`) → `finished@AT_<op>[MAIN]`. Op #1 converts raw qty → piece qty using the BOM ratio (`qty_in` pieces ⇐ `qty_in × bom_qty_per_unit` of raw; see Q3) | none |
| **In-house qty-out / complete** | `finished@AT_<op>` → `finished@<done-stage>` for good qty; scrap → `finished@SCRAP`; wastage is removed (no row) | none (wastage value stays in the 1310 pool and lands in the finished item's cost at completion, as today) |
| **Karigar dispatch (A08)** | `<input>@<pred-stage>[MAIN]` → `<input>@AT_<op>[JOBWORK]`. JWO line carries `item_id`, `lot_id`, and new `stage` + `manufacturing_order_id`, so `create_send_out` gets stage-aware lines instead of store-stock lines | none |
| **Karigar receive (A08)** | `@AT_<op>[JOBWORK]` → good qty `finished@<done-stage>[MAIN]`, scrap → `@SCRAP`, by-product → store row of the by-product item if one is configured (else `@SCRAP`), wastage removed at JOBWORK | none. The karigar labour bill → MO cost pool is a separate, not-yet-built flow (§5.5 step 5); out of scope |
| **QC (A10)** | predecessor output → `@QC_PENDING`; pass → `@FINISHED` (still WIP, MO-scoped); reject → `@REJECTED`; rework → `@REWORK_QUEUE`, consumed by the rework clone op | none |
| **MO completion (A11)** | consume the final op's `finished@FINISHED` (or `@<done-stage>` of the sink op) WIP rows for `produced_qty`; then the **existing** `add_stock(finished, MAIN)` store receipt. Leftover WIP rows (scrap/rejected) are zeroed with `SCRAP` ledger rows | unchanged: DR 1300 / CR 1310 for the whole pool |

Rules:

* **Stage mapping:** `operation_master.operation_type` → (`AT_` stage, done stage):
  DYEING→(AT_DYEING, DYED), EMBROIDERY→(AT_EMBROIDERY, EMBROIDERED),
  STITCHING→(AT_STITCHING, STITCHED), QC→(QC_PENDING, FINISHED), PACKING→(—, PACKED).
  WEAVING / OTHER (cutting, handwork, printing, washing) have no unambiguous mapping
  today. See Q2.
  The mapping lives in one function, `stage_service.stages_for(op_type)`.
* **Conservation invariant**, tested per flow: for a stage-tracked MO, Σ WIP qty across
  stages + produced + scrap + wastage = Σ qty entered, at every point.
* **DAG joins (§5.6.6 Batch 2):** STITCH after parallel EMBROIDERY and HANDWORK
  consumes from *both* predecessors' done-stage rows. In v1 all parts are the same
  finished item, so the join consumes `min()` of the predecessor outputs. See Q4.
* `routing_flow_service.can_start_operation` stays the gate. Stage rows give it a
  second, physical check ("is there WIP qty at the predecessor's done stage?").

## 5. WIP valuation and GL

* **Proposal: no GL change.** WIP stage rows carry no cost. The 1310 pool per MO
  (`mo_completion_service.sum_wip_cost_pool`) stays the only source of WIP value, and
  completion still drains it into the finished item at `pool / produced_qty`. The
  `stock_position_wip_no_cost` CHECK enforces that WIP rows can't double-count value.
* **Inventory valuation report** (`compute_stock_summary`) keeps valuing store rows
  only, and shows WIP as a separate memo block: qty by stage from stage rows, value =
  the MO's 1310 balance. Total stock + WIP then ties to GL 1300 + 1310.
* **Things that WOULD change GL treatment (CA questions, not in scope):**
  - Per-stage WIP valuation (cost attached as goods move stage to stage, e.g. adding
    karigar labour at receive). This needs value on WIP rows and per-stage GL
    sub-ledgers.
  - Expensing wastage/scrap at op close to "Material wastage" (architecture §5.6.3
    says so). Today it stays in the pool and inflates finished-item cost.
  - Booking karigar labour into 1310 (§5.6.7 step 5).

## 6. ITC-04 / delivery challan

* The rule-55 challan and ITC-04 Table 4 (goods sent) / Table 5 (goods received back)
  read JWO lines. With stage rows, a mid-routing JWO line becomes
  `finished item @ CUT` instead of a wrong store item.
* `prepare_itc04_data` gains `stage` and `manufacturing_order_id` columns, which also
  closes A08 retro item 3 (MO linkage).
* **CA questions:**
  - Description and HSN for semi-finished goods: the finished item's HSN, or the
    input fabric's HSN?
  - The **taxable value** ITC-04 requires for goods sent. WIP rows have no unit cost.
    Proposal: the MO's 1310 balance ÷ pieces in WIP, at dispatch time, stored on the
    JWO line.
  - Whether the scrap/wastage left at the karigar needs reporting in Table 5.

## 7. Reports and screens affected

Stock summary and valuation (WIP memo block), low-stock dashboard tile (store only),
lot "where is my lot" (§5.6.4, new: lot split by stage and location), MO detail (WIP
by stage panel), karigar cards / job-work overview (qty AT_<op> per karigar), ITC-04
export, and stock ledger (stage columns shown).

## 8. Task breakdown (estimates for Claude Code + Moiz review)

| # | Task | Est. | Gate |
|---|---|---|---|
| S1 | Migration + ORM + `inventory_service` stage/MO kwargs + reader filters + guard test + RLS test | 2 d | **Moiz (schema)** |
| S2 | `stage_service` (op_type → stages, conservation helpers) + feature flag + `mo.stage_tracked` | 1 d | — |
| S3 | Material issue → `raw@RAW` (after the concurrent lot-handling fix lands in `material_issue_service.py`) | 1 d | Moiz (stock move) |
| S4 | In-house op progress stage moves (A07), incl. raw → piece conversion at op #1 | 2 d | Moiz |
| S5 | Karigar dispatch/receive stage moves; stage-aware `jobwork_service` lines; remove the stopgap for stage-tracked MOs | 2 d | Moiz |
| S6 | QC + rework stage moves (A10) | 1.5 d | — |
| S7 | MO completion consumes WIP rows; leftover → SCRAP; conservation test end to end (CUT in-house → STITCH karigar → QC → complete) | 1.5 d | Moiz (touches A11) |
| S8 | Stock summary WIP memo + tie-out test (store + WIP = GL 1300 + 1310) | 1 d | CA review |
| S9 | ITC-04 stage/MO columns + value per Q-CA | 1 d | **CA** |
| S10 | FE: MO detail WIP-by-stage, karigar cards qty AT_<op>, lot split view | 2 d | — |
| | **Total** | **~15 dev-days** (≈3 weeks with review) | |

## 9. Open questions

**For Moiz**

1. Is a per-MO opt-in (`stage_tracked`) acceptable, rather than backfilling in-flight
   MOs? (Recommended: yes.)
2. Op types that the stage enum doesn't cover (WEAVING, OTHER, handwork, printing,
   washing have stages but no `operation_type`). Should we extend `operation_type`
   (an enum `ADD VALUE`), or add a `stage_in/stage_out` override on
   `operation_master` (another schema change)?
3. Raw → piece conversion at op #1. Should the BOM ratio drive it (4.2 m → 1 piece),
   or should the operator enter actual pieces cut, with the remainder posted as
   wastage?
4. Parts as separate items (dupatta / kurta body sent to different karigars, §2 and
   §5.5 Day-2). Is "finished item @ stage" enough for the trial, or do parts need to
   be first-class now?
5. Should WIP rows be lot-tracked (carry the raw lot through every stage, for "where
   is lot L-17")? The proposal carries `lot_id`; confirm.

**For the CA**

6. ITC-04 HSN/description and taxable value for semi-finished goods sent (§6).
7. Should wastage/scrap be expensed at op close instead of absorbed into
   finished-goods cost (§5)?
8. Karigar labour, when billed: capitalise into WIP 1310, or expense it?
