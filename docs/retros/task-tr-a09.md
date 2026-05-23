# TASK-TR-A09 retro — Routing DAG flow engine

**Date:** 2026-05-23
**Branch:** task/tr-a09-dag
**Commit:** `<sha>` (PR open, awaiting team-lead review)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (TASK-TR-A09 row)

## Summary

Shipped the edge-walking routing-DAG engine in
`backend/app/service/routing_flow_service.py` and wired it into both
`operation_progress_service.start_operation` (A07) and
`karigar_send_out_service.dispatch_to_karigar` (A08), replacing the
v1 sequence-based predecessor check. The engine walks each MO
operation's incoming `routing_edge` rows and applies per-edge
semantics (FINISH_TO_START / START_TO_START / PARTIAL_FINISH_TO_START)
so diamond DAGs let parallel branches actually run in parallel.

A new GET endpoint `/manufacturing/mo-operations/{id}/can-start`
surfaces the engine verdict (`{allowed, reason}`) so the FE can
disable a "Start" button before the operator gets a 422.

`make lint`, `make test` for manufacturing-relevant suites (173
tests across `test_routing_flow`, `test_operation_progress`,
`test_karigar_send_out`, `test_routing`, `test_mo`,
`test_material_issue`, `test_manufacturing_*`, `test_bom`), `mypy .`
(226 source files) all pass. Full `pytest tests/` had one flake on
`test_invoice_pdf_routers.py::test_get_invoice_pdf_cross_org_returns_404`
that passed in isolation — pre-existing fixture-ordering issue
unrelated to A09. OpenAPI snapshot regenerated via
`dump-openapi.py`; `pnpm gen:types` ran clean.

## Traversal algorithm

**BFS over incoming edges, single-hop, no recursion.**

For `can_start_operation(op)`:

1. Load the parent MO; if no routing → `(True, None)`.
2. Eager-load the routing's edges via `selectinload`.
3. Filter to edges whose `to_operation_id == op.operation_master_id`.
   If empty → `(True, None)` (source node / base case).
4. Build `{operation_master_id: MoOperation}` map for the MO.
5. BFS with `deque` over those incoming edges. For each edge:
   - Look up the predecessor `MoOperation` via the map.
   - Apply the per-edge-type semantic.
   - On block: return `(False, reason)` immediately.
6. Safety counter caps the loop at `max(num_ops * 2, num_edges * 2, 8)`.

Single-hop is sufficient because each predecessor's own state
machine has already enforced its incoming edges by induction. A
CLOSED predecessor implies its own predecessors were CLOSED (for
F→S) or IN_PROGRESS (for S→S) at the time it closed.

## Edge-type semantics decision matrix

| Edge type                  | Upstream state requirement                                                                           | Threshold check        |
|----------------------------|-------------------------------------------------------------------------------------------------------|------------------------|
| `FINISH_TO_START`          | `state ∈ {CLOSED, SKIPPED, CANCELLED}` (terminal)                                                     | n/a                    |
| `START_TO_START`           | `state ∉ {PENDING, READY}` (IN_PROGRESS or beyond)                                                    | n/a                    |
| `PARTIAL_FINISH_TO_START`  | `state ∉ {PENDING, READY}` AND threshold met                                                          | `qty_out >= threshold_qty` OR `(qty_out/qty_in)*100 >= threshold_pct` |

Frozensets `TERMINAL_STATES` and `IN_PROGRESS_OR_BEYOND_STATES`
exported from `routing_flow_service` are the single source of truth
for these buckets — replacing the per-module `_TERMINAL_PREDECESSOR_STATES`
constants that A07 and A08 each carried.

## Deviations from plan

### 1. Used `MoOperation.qty_in` as the PF→S "planned" baseline

Plan said `qty_out / planned_qty_out × 100`. There is no
`planned_qty_out` column on `mo_operation`. The MO-create path
seeds `qty_in` from `ManufacturingOrder.planned_qty`, and `qty_in`
is the de-facto "planning figure" the existing tolerance check in
A07's `record_qty_in` uses. The engine uses `predecessor.qty_in`
as the denominator, falling back to a hard block if `qty_in <= 0`.
Documented in the code comment for the PF→S branch.

- **Fixed by:** `_check_edge` PF→S branch using `Decimal(predecessor.qty_in or 0)`.
- **Why not caught in planning:** plan inferred a column that doesn't exist.
- **Impact on later tasks:** A10 (QC) may want to revisit if QC ops
  carry their own planning figures distinct from MO planned_qty;
  filed as A09-FU2.

### 2. Shipped the `/can-start` endpoint (was "if time" in the spec)

Spec said "If you have time, add a GET endpoint." Did so — only
~30 lines of router + schema + 1 integration test, and it's a real
FE win (disable buttons before the operator gets a 422). Same
permission as the other read endpoints (`manufacturing.operation.read`).

## Things the plan got right (no deviation)

- BFS over edges with single-hop traversal — transitive walking is
  unnecessary by induction on each predecessor's state machine.
- Keeping the engine's behaviour identical for the legacy "no
  edges → allowed" base case meant no fallback wiring was needed.
- The PF→S "upstream must be IN_PROGRESS regardless of threshold"
  rule — without it a `threshold_qty=0` or `qty_out=0` corner case
  would let downstream start before upstream had begun.
- KARIGAR predecessor handling came for free — adding the karigar
  in-flight states (DISPATCHED, ACKNOWLEDGED, RECEIVED_*) to the
  `IN_PROGRESS_OR_BEYOND_STATES` set covered it.

## Pre-TASK-TR-A10 (QC) checklist

### 1. Decide where QC ops sit in the DAG

QC operations (operation_type=QC) typically gate the next op — a
F→S edge from "STITCHING" to "QC" to "PACKING" today. A10 may
introduce a richer "QC_PENDING → QC_PASS / QC_FAIL → REWORK" loop
that the current state enum already partially supports
(`QC_PENDING`, `REWORK` are members of `MoOperationState`). The
engine already treats both as `IN_PROGRESS_OR_BEYOND` for S→S /
PF→S edges; verify that's the desired semantic for A10's QC
gates.

### 2. PF→S baseline gap for rework ops

`MoOperation.qty_in` is seeded from `MO.planned_qty` for all ops,
including rework ops (created with `rework_of_mo_operation_id`).
For a rework op that has its own (smaller) target qty, the PF→S
percentage check would compute against the wrong baseline. A07's
docstring already flagged this; A09 inherits the same gap. A10 or
A11 should either:
- store a per-op `planned_qty_out` column, OR
- derive the rework baseline from `parent_op.qty_rejected`.

### 3. Optional: surface `can-start` reasons by upstream id

The reason string today names the blocking predecessor by
`operation_master_id` (UUID). The FE might want a parsed
`{blocked_by_op_master_id, edge_type, current_state, threshold}`
payload for richer UI. Filed as A09-FU3 if Moiz asks.

## Open flags carried over

- **A09-FU2** (rework baseline): PF→S threshold_pct against
  `planned_qty` is loose for rework ops — surfaces at A10/A11.
- **A09-FU3** (structured can-start reason): if the FE wants more
  than a string, add a typed reason DTO. Defer until the FE asks.
- **Pre-existing test flake**:
  `tests/test_invoice_pdf_routers.py::test_get_invoice_pdf_cross_org_returns_404`
  fails when the full suite runs serially after some other test
  drops the `organization` table — passes in isolation. Not an A09
  regression; track separately if it bites in CI.

## Observable state at end of task

- Dedicated test DB: `fabric_erp_tra09_test` (gitignored `.env`
  points runtime + migration URLs there).
- New file: `backend/app/service/routing_flow_service.py` (~340 LOC).
- New test file: `backend/tests/test_routing_flow.py` (13 tests).
- New endpoint: `GET /manufacturing/mo-operations/{id}/can-start`.
- New schema: `CanStartOperationResponse`.
- Removed: `_predecessors_closed` helpers from both
  `operation_progress_service` and `karigar_send_out_service` (now
  superseded; comments left as breadcrumbs).
- OpenAPI snapshot + frontend `src/types/api.ts` regenerated.
