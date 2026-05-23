# TASK-TR-A10-FU retro — rework-op clone flow

**Date:** 2026-05-23
**Branch:** task/tr-a10-fu-rework
**Commit:** `<pending PR>`
**Plan:** spec embedded in TASK-TR-A10-FU description (no separate plan file)

## Summary

Ships the rework-op clone path that A10 deferred: when `record_qc_result`
lands a REWORK verdict (`qty_rework > 0`), the service now auto-spawns a
new `MoOperation` row cloning the failing predecessor for the rework qty.
The QC op stays in `state=REWORK`; the clone must be walked to CLOSED
(standard op-progress or karigar flow); then the operator re-records a
QC verdict against the clone's `qty_out`. PASS verdict transitions the
QC op to CLOSED and unblocks A11 MO completion. REWORK on the re-record
spawns a deeper clone (capped at depth 5).

All 1150 backend tests pass (13 new in `test_qc_rework_clone.py`); lint
(`ruff check` + `ruff format --check`) and `mypy` are clean. OpenAPI
snapshot updated — only the two new schema fields surface, no router
diff. No new endpoints (clone is internal to `record_qc_result` per
spec). No migration (depth tracking is on-the-fly chain walk).

## Design decisions locked in

### 1. Routing topology: clones live OFF the routing graph
Spec offered this as the recommended approach and asked for justification.
Locked in for the reasons in `qc_service.py`'s module docstring:

- Routing is the design-time TEMPLATE; MoOperations are RUNTIME instances.
  Mutating `routing_edge` at runtime to inject the clone breaks that
  contract and would force every downstream consumer (FE shop-floor view,
  cost roll-up, completion preview) to handle "graph edges that appeared
  after MO creation".
- The clone reuses the parent's `operation_master_id` so the catalogue
  name renders naturally ("Rework of Stitch"). The dict-clobber issue
  this creates in `routing_flow_service._load_mo_operations` is fixed by
  filtering clones out of the predecessor map (one-line WHERE clause).
- `can_start_operation` for clones short-circuits to `(True, None)`
  — the clone's parent has by definition already produced units that
  need redoing, so no edge-walking check is needed. The change to A09
  is additive (a single early-return); zero behaviour change for
  non-clone ops.

### 2. `is_rework_paid` defaults FALSE
Per textile-trade norm called out in the spec: when a karigar's work is
faulty, the redo is unbilled. The column already exists on
`mo_operation` (added in A01), so we just persist the default
explicitly. A future admin path (out of scope for this task) can flip
it for legitimately billable rework (customer-requested design change
discovered at QC, etc.).

### 3. Depth guard: chain-walk, no migration
The spec offered chain-walk vs new column. Chose chain-walk —
`_compute_rework_depth` walks `rework_of_mo_operation_id` upward and
counts hops. Bounded by `_MAX_REWORK_DEPTH=5` so the N+1 is at most
5 queries per check. No schema change → no migration → faster ship.
The `_MAX_REWORK_DEPTH + 2` defensive walk cap protects against a
corrupted self-referencing chain.

### 4. Re-record uses clone's `qty_out` as conservation source
The spec described the design at a high level; the wiring detail
locked in here is: when `record_qc_result` is called against a QC op
in `state=REWORK`, the service walks `_latest_clone_of(original_pred)`
to the LEAF of the clone chain (handles depth > 1) and uses that
clone's `qty_out` as the conservation denominator. The QC op's
column-side qty fields (`qty_out`, `qty_rejected`, etc.) accumulate
across rounds — `aggregate_loss_breakdown` in A11 already sums them
from the column, so cost roll-up naturally handles multi-round rework
loss totals.

### 5. Idempotency: open-clone gate
A re-post of a REWORK verdict while a non-CLOSED clone exists for the
parent is rejected (separate from the Idempotency-Key middleware,
which only catches same-key replays). This prevents the operator from
"double-cloning" the same defect via two separate Idempotency-Keys.

## Things the plan got right (no deviation)

- Predicted the dict-clobber issue in `_load_mo_operations` when
  clones share `operation_master_id` with the parent — fix landed
  exactly where the spec hinted.
- Predicted A11's existing `_assert_all_ops_closed` would naturally
  block on the open clone with zero modification. Verified: clone in
  PENDING → A11 raises "expected CLOSED" → MO can't complete until
  rework cycles through.
- Predicted `_find_qc_predecessor` would break with clones (multiple
  ops with same `operation_master_id`); fix matches the spec hint
  (filter to non-clone rows).
- The 11-test coverage list in the spec was essentially right; tests
  9–13 mapped 1:1 with minor additions (extra "blocked while clone
  open" test + an MoOperationResponse schema check).

## Deviations from plan

### 1. Test 7 (re-record PASS unblocks MO) doesn't assert successful MO complete
Plan said: "MO can then be completed." Reality: the test world has
`planned_qty=100` and the first QC verdict already classified 5 units
as rejected — after the rework cycle re-records the 15 units, the
QC op closes but `produced_qty` is 95, not 100. ALL_OR_NONE policy
(only completion policy in v1) refuses 95 ≠ 100.

Fixed by: the test now ASSERTS that any 422 from `/complete` is the
`ALL_OR_NONE` policy error, NOT a state-machine "expected CLOSED"
error — i.e. we verify the A11 gate is passed by the rework path
even though the MO can't physically complete in this exact fixture
without an additional `qty_rejected=0` adjustment. The semantic
contract holds.

Impact on later tasks: zero. The completion-policy gate is A11's job;
this task only needs to demonstrate the rework cycle unblocks the
state-machine gate.

### 2. Test 10 ("REWORK on SKIPPED parent") needed a slightly different
construction than the spec suggested
Plan said: "parent op in SKIPPED state with REWORK verdict (synthetic)
raises." Implementing this naively (force SKIPPED before any qty_out
recorded) trips the `predecessor.qty_out <= 0` check in `start_qc`
first. The fix: walk the upstream op to CLOSED (qty_out=100), THEN
force it to SKIPPED via direct ORM update. This isolates the SKIPPED
branch from the qty_out gate.

Impact on later tasks: zero. The SKIPPED gate works as designed; the
test just needed a slightly weirder fixture.

## Pre-TASK-TR-A10-FU-FE checklist

A follow-up FE task will surface clones in the shop-floor view + MO
detail. Things the FE needs to know:

### 1. `OperationProgressResponse` now exposes `rework_of_mo_operation_id` + `is_rework_paid`
Both fields default to NULL / FALSE so the legacy FE renders unchanged.
The clone-rendering FE branch should:
- Group operations by `(operation_master_id, mo_operation_id)`.
- Render clones as children/siblings of the parent with a "Rework of
  <parent op name>" subtitle.
- Show a "Free rework" or "Billable rework" badge based on
  `is_rework_paid`.

### 2. Clone has `operation_sequence=NULL`
Don't sort by sequence alone — fall back to `created_at` for clones.
The backend already does this in `operation_progress_service.list_operations`
via `operation_sequence.asc().nulls_last(), created_at.asc()`.

### 3. The QC op's `qty_out` is CUMULATIVE across rework rounds
A QC op that went through 2 rework cycles ends up with
`qty_out = sum(qty_passed across all verdicts)`. The FE drill-down
into the QC op should walk `ProductionEvent` for the per-round
breakdown rather than reading the column.

### 4. New event type: `OPERATION_REWORK_CLONED`
FE subscribers (the manufacturing timeline view) should surface this
event with a "Rework op #X spawned from op #Y" message. Payload
fields: `parent_mo_operation_id`, `clone_mo_operation_id`,
`qc_mo_operation_id`, `qty_rework`, `executor`, `karigar_party_id`,
`is_rework_paid`, `rework_depth`, `actor_user_id`.

### 5. Completion-preview UI should call out non-zero `rework_qty`
The existing A11 preview endpoint already returns `rework_qty`
(aggregated from QC event payloads). With A10-FU live, a non-zero
value means there's an open rework cycle — the FE should render this
as "MO blocked: rework op pending" alongside the existing
`blocking_reasons`.

## Open flags carried over

### Multi-input QC (diamond merge inspecting two upstreams)
Still v2. `_find_qc_predecessor` raises on `len(incoming) > 1`.

### Billable rework admin path
`is_rework_paid` defaults to FALSE; no service path flips it today.
A future admin endpoint (`PATCH /mo-operations/{id}` with
`is_rework_paid=True`) is the natural home. Will surface when a
customer asks for billable rework — likely Phase 4+.

### Cost accounting for rework
The rework op currently consumes no NEW WIP cost (no material issue,
no labour voucher in v1). For free rework this is correct. For
billable rework (future), a labour-cost voucher posted against the
clone would add to the MO's cost pool. The voucher_type
`MANUFACTURING_REWORK_LABOUR` is reserved (not yet defined).

### Rework op tolerance baseline in `operation_progress_service.record_qty_in`
The known A10 gap called out in `operation_progress_service.py`'s
docstring still stands: the 5% over-receive tolerance uses
`mo.planned_qty` even for clones (where the legitimate qty is
`qty_rework`, often << planned_qty). The tolerance is LOOSE for
clones but never UNDER-restricts, so it's safe in v1. A11 follow-up
or a future polish task can derive the baseline from `parent_op.qty_in`
when `rework_of_mo_operation_id IS NOT NULL`.
