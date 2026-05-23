# A11 input — reading REWORK QC results column-side

**Status:** spec note for TASK-TR-A11 (#46). Captures a deliberate gap A10 left.

## The gap

A10 (`backend/app/service/qc_service.py`) persists QC verdicts to the
`production_event` log as `QC_RESULT_RECORDED` events. The PASS path
also normalises into columns: it writes `qty_passed` back to the QC
op's `mo_operation.qty_out` so the next op's predecessor check
(`qty_out` of the closed op) is a single SELECT.

The five other QC buckets — `qty_rejected`, `qty_byproduct`,
`qty_wastage`, `qty_rework`, and (for context) `qty_in` overwritten at
QC time — **do not have dedicated columns** on `mo_operation`. They
exist only on the event payload:

```jsonb
QC_RESULT_RECORDED.payload = {
  "verdict": "PASS" | "REWORK",
  "qty_passed": Decimal,
  "qty_rejected": Decimal,
  "qty_byproduct": Decimal,
  "qty_wastage": Decimal,
  "qty_rework": Decimal
}
```

The op-level conservation invariant
`qty_passed + qty_rejected + qty_byproduct + qty_wastage + qty_rework == predecessor.qty_out`
is enforced at write time inside `qc_service.record_qc_result`. After
that, the breakdown is event-only.

## Why A11 cares

A11 settles the MO's WIP cost pool back into finished-goods inventory
on `complete_mo`. The cost rolled forward by A07 (in-house operations)
and A08 (karigar send-outs) accumulates on `1310 Work-in-Process`. At
completion A11:

1. Aggregates `produced_qty` (sum of `qty_passed` over the chain — but
   only the **terminal** ops contribute finished pieces; intermediate
   passes are not finished goods).
2. Computes `unit_cost = wip_balance / produced_qty`.
3. Posts `DR 1300 Inventory / CR 1310 WIP` for the rolled-up FG batch.
4. Records scrap (`qty_rejected + qty_wastage`) and byproduct as
   secondary stock receipts where the policy says so (out of scope
   for v1 — see Phase 4 in `specs/manufacturing-pipeline.md` §16).
5. Optionally writes variance to a P&L row if `produced_qty` deviates
   from `MO.planned_qty` beyond tolerance.

The five-bucket breakdown matters for (4) and (5). Specifically:

- **Scrap value-in / total-loss accounting.** Even if v1 skips a
  separate stock receipt for rejected/wastage units, the *cost* of
  those units stays absorbed in finished-goods unit cost only if A11
  knows how many there were. Otherwise the unit cost denominator is
  wrong (we'd be using `qty_passed / yield = produced_qty`-only).
- **REWORK pieces are still WIP, not finished.** They must be excluded
  from `produced_qty` aggregation **and** from cost roll-up at the
  terminal op until rework finishes. A11-v1 (per
  `docs/retros/task-tr-a10.md` "Open flags") punts the rework-op
  creation to A10-FU. For now the terminal QC ops with `qty_rework > 0`
  block `complete_mo` (state stays `REWORK`, not `CLOSED`).
- **Variance bucket attribution.** If A11 books a variance row, it's
  useful to attribute it to the right cause (yield loss vs scrap vs
  wastage). Column-side is faster than JSONB path queries.

## Two readback options

### Option A — JOIN the event log (recommended for v1)

In `mo_completion_service.complete_mo`, aggregate by joining
`production_event` and casting `payload->>'qty_*'` to `NUMERIC`. One
query, no schema change:

```sql
SELECT
  SUM((pe.payload->>'qty_passed')::numeric)    AS total_passed,
  SUM((pe.payload->>'qty_rejected')::numeric)  AS total_rejected,
  SUM((pe.payload->>'qty_byproduct')::numeric) AS total_byproduct,
  SUM((pe.payload->>'qty_wastage')::numeric)   AS total_wastage,
  SUM((pe.payload->>'qty_rework')::numeric)    AS total_rework
FROM production_event pe
JOIN mo_operation mo_op ON mo_op.mo_operation_id = pe.entity_id
WHERE pe.event_type = 'QC_RESULT_RECORDED'
  AND mo_op.mo_id = :mo_id
  AND mo_op.operation_type = 'QC'
  AND mo_op.deleted_at IS NULL;
```

For "terminal-only" aggregation, A11 keeps the routing graph from A09
and restricts the SELECT to QC ops whose predecessor op is in the
routing's **leaf** layer (`Routing.edges` outbound is empty for that
op's parent).

**Pros:** zero migration; the event log already holds the data; if A10
ever fixes a bug or adds a bucket, A11 picks it up automatically.

**Cons:** a JSONB path query per `complete_mo` call. For a typical MO
with <20 QC ops the cost is negligible. If MOs ever grow to 1000+ ops
this becomes a perf line-item.

### Option B — Add dedicated columns + backfill migration

Add five `NUMERIC(18, 4)` columns to `mo_operation`:

```sql
ALTER TABLE mo_operation
  ADD COLUMN qty_passed_v2    numeric(18, 4),
  ADD COLUMN qty_rejected     numeric(18, 4),
  ADD COLUMN qty_byproduct    numeric(18, 4),
  ADD COLUMN qty_wastage      numeric(18, 4),
  ADD COLUMN qty_rework       numeric(18, 4);
```

Backfill from the event log in the same migration, then rewrite
`qc_service.record_qc_result` to UPDATE all five columns in addition
to writing the event.

**Pros:** column-side SQL; one extra `mo_operation` row read covers the
whole breakdown; future yield-loss reports are trivial.

**Cons:** two write paths (event + column) to keep in sync; risks
divergence if A10's invariant logic and the migration's backfill
disagree on edge cases; sunk cost if Phase 4 swaps to a different
QC model (multi-input QC, rework cloning, etc. — see A10 retro).

## Recommendation for A11

**Take Option A in A11-v1.** Reasons:

1. The cost-roll-up sums needed for the GL voucher are computable in
   one query; no per-op walk required.
2. Option B is reversible — if Phase 4 yield analytics demand
   column-side reads, the migration can land then and backfill from
   the same event log A11 reads now. Symmetric path.
3. Schema lock-in cost (Moiz-gate per CLAUDE.md "Ask vs Decide") is
   higher than the JSONB-query cost. Defer the schema decision until a
   real reporting query demands it.

If A11 implementation discovers the JOIN materially complicates the
voucher post (e.g. the variance attribution logic spirals), revisit
Option B as an A11 follow-up rather than blocking the spine.

## Cross-references

- `backend/app/service/qc_service.py:445` — payload write site for
  the five buckets.
- `docs/retros/task-tr-a10.md` §"qty_rework storage" — three-options
  analysis A10 already documented.
- `specs/manufacturing-pipeline.md` §17 (Cost) — Phase 1 vs Phase 4
  split on scrap accounting.
- TASK-TR-A11 (#46) — consumes this spec.
