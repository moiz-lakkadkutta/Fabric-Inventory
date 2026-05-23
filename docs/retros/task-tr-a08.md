# TASK-TR-A08 retro — Per-operation karigar (job-work) send-out

**Date:** 2026-05-23
**Branch:** task/tr-a08-karigar
**Commit:** TBD (PR open against `main`)
**Plan:** `docs/implementation-plan-trial.md` § TASK-TR-A08

## Summary

Shipped the karigar / job-work per-MO-operation lifecycle on top of the
existing in-house A07 state machine and the older CUT-305 job-work
service. New module `backend/app/service/karigar_send_out_service.py`
implements the lifecycle

    PENDING → DISPATCHED → ACKNOWLEDGED → RECEIVED_PARTIAL ⇄ RECEIVED_FULL → CLOSED

with four POST endpoints under `/manufacturing/mo-operations/{id}/…`
(dispatch-karigar, acknowledge-karigar, receive-karigar, close-karigar)
plus a fifth re-dispatch path (the lifecycle also permits
`RECEIVED_FULL → DISPATCHED` for operators who split a planned batch
across multiple physical shipments). Each transition emits a
`ProductionEvent`; dispatch and close also emit `audit_log` rows. Stock
posting + outward/inward challan minting are delegated to the existing
`jobwork_service.create_send_out` / `receive_back` helpers — A08 just
wires the MO-operation row to the resulting `JobWorkOrder` and
`JobWorkReceipt` ids via the (FK-less) `outward_challan_id` /
`inward_challan_id` columns.

RBAC: added two new fine-grained slugs (`manufacturing.karigar.dispatch`
+ `manufacturing.karigar.receive`) granted to OWNER, Production Manager,
and Warehouse (Warehouse already owns `jobwork.order.create` for the
same physical workflow). Salesperson 403 is locked in by an integration
test.

Test coverage: 13 new integration tests covering happy path, re-dispatch,
all state-machine guards, over-receive rejection, cross-org RLS
opacity, idempotency replay, RBAC 403 + Warehouse positive, and
production_event emission ordering. Full BE suite is green
(1080 / 1080), ruff clean, mypy clean across all 223 source files,
frontend `pnpm test` green (306 / 306) post-`gen:types` snapshot
refresh.

## Deviations from plan

### 1. `MoOperation` has no `item_id` — dispatch needed an item to ship

The plan implicitly assumed the operation knew what physical item to
send. The schema reality is that `mo_operation` doesn't carry an
`item_id` (operations transform inputs into outputs; the input-item
varies per op — raw at op1, dyed at op2, etc.). The existing
`jobwork_service.create_send_out` insists on item + uom + qty per line.

- **Fixed by:** added `item_id`, `uom`, `lot_id` as optional fields on
  `KarigarDispatchRequest`. When omitted, the service defaults to the
  MO's `finished_item_id` and the item's `primary_uom` — works for
  single-op routings where the operation's input genuinely is the
  finished item. Operators with multi-op routings should pass
  `item_id` explicitly. Tests rely on the default (stocking both raw
  and finished item to satisfy `jobwork_service.create_send_out`'s
  on-hand check).
- **Why not caught in planning:** the A01 schema notes were skimmed,
  not deeply read.
- **Impact on later tasks:** A09 / A10 (rework + finer-grained ops)
  may want to model in-process intermediate items as first-class
  Items. Flagged for the planning loop.

### 2. `mo_operation.qty_in` is seeded to `planned_qty` at MO create — wrong default for karigar

A05 seeds `qty_in = planned_qty` so the in-house path has a "planned
in" figure to ceiling-check against (5% tolerance). For karigar ops,
`qty_in` should track the cumulative ACTUAL receive-back qty — it
starts at zero. With the seed left in place, the first receive on a
100-unit-dispatch tried to register `qty_in = 100 (seed) + 60 (receive)
= 160`, blowing past the dispatched 100.

- **Fixed by:** `dispatch_to_karigar` resets `qty_in = 0` on the FIRST
  dispatch (detected by absence of any prior `OPERATION_DISPATCHED`
  event for the op). Subsequent dispatches don't touch `qty_in`.
- **Why not caught in planning:** the A05 seed behaviour was only
  documented in the `operation_progress_service` module docstring;
  reading order matters.
- **Impact on later tasks:** none — this is a karigar-only book-keeping
  detail.

## Things the plan got right (no deviation)

- The "reuse `operation_progress_service.py` patterns" steer was on the
  money: advisory lock, predecessor check, event-emit helper, and audit
  emission were copy-and-tweak.
- Delegating stock posting to `jobwork_service.create_send_out` /
  `receive_back` avoided every stock-conservation edge case A06 had to
  solve from scratch.
- Splitting the RBAC slug into `.dispatch` + `.receive` (rather than
  reusing `manufacturing.operation.progress`) is the right grain — it
  lets Warehouse staff run dispatch/receive without inheriting the
  in-house qty-record permission.

## Pre-TASK-TR-A09 checklist

### 1. Decide intermediate-item modelling

A09 (rework / split / merge) needs operations to track WHAT they're
producing, not just qty. Today A08 hard-codes "ship the finished
item" as the default. Pick: (a) add `mo_operation.input_item_id` /
`output_item_id`; (b) introduce a `wip_item` first-class entity; (c)
let the routing edge carry the intermediate-item link. See
`MoOperation` model + `backend/app/service/karigar_send_out_service.py
::_resolve_dispatch_item`.

### 2. Decide whether re-dispatch should reset `qty_in`

Today a re-dispatch (RECEIVED_FULL → DISPATCHED) leaves the cumulative
`qty_in` from the prior wave intact. That's the right behaviour for a
"keep tracking total receipts across waves" semantic. If A09 wants
per-wave accounting, the receive-side ceiling check needs revisiting.
Search `_advisory_lock_operation` callers for context.

### 3. ITC-04 reporter should surface karigar-MO linkage

`jobwork_service.prepare_itc04_data` doesn't know about MO operations
today. When A11 (Period-Close / GST reports) lands, it'll want to filter
ITC-04 by MO — wire `JobWorkOrder.job_work_order_id` back to
`MoOperation.outward_challan_id` for that drill-down.

## Open flags carried over

- **No FK on `outward_challan_id` / `inward_challan_id`.** Per the
  `MoOperation` model docstring, CUT-305 dropped the original challan
  tables CASCADE so the DB-level FK doesn't exist. We store the new
  `JobWorkOrder.job_work_order_id` / `JobWorkReceipt.job_work_receipt_id`
  ids there as plain UUIDs. A future migration should re-add the FKs
  pointing at the new target tables.
- **Default `item_id = finished_item` is a v1 simplification.** See
  Deviation 1; flagged for A09 planning.

## Observable state at end of task

- New test DB: `fabric_erp_tra08_test` (created via `CREATE DATABASE`,
  Alembic migrated). `.env` in worktree points at it.
- New ProductionEvent types in flight in this org: `OPERATION_DISPATCHED`,
  `OPERATION_ACKNOWLEDGED`, `OPERATION_RECEIVED_PARTIAL`,
  `OPERATION_RECEIVED_FULL`, `OPERATION_CLOSED`. Free-text column so no
  schema change required.
- New permission slugs `manufacturing.karigar.dispatch` /
  `manufacturing.karigar.receive` need to be seeded into every existing
  org on deploy — the idempotent `seed_system_permissions` path handles
  this on the first request, but the deploy runbook should note it for
  observability.
