# TASK-TR-A10 retro — QC inspection operation (pass + rework marker)

**Date:** 2026-05-23
**Branch:** task/tr-a10-qc
**Commit:** `<sha>` (PR open, awaiting team-lead review)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (TASK-TR-A10 row)

## Summary

Shipped the QC inspection state machine
(`backend/app/service/qc_service.py`) for the textile-MO shop floor.
A QC operation is a special op whose `operation_master.operation_type
== QC` — it does NOT consume materials, it inspects the output of a
single predecessor op. The lifecycle is:

  ``PENDING → QC_PENDING → CLOSED``   (PASS verdict)
                       ``→ REWORK``   (REWORK verdict — v1 marker only)

Three new endpoints under `/manufacturing/mo-operations/{id}`:
- `POST /start-qc`          flips a PENDING QC op to QC_PENDING.
- `POST /record-qc-result`  posts the five-bucket verdict and
                            closes (PASS) or marks REWORK.
- `GET  /qc-result`         returns the latest verdict + breakdown
                            (read off the `QC_RESULT_RECORDED` event).

Strict quantity conservation at `record-qc-result`:

  ``qty_passed + qty_rejected + qty_byproduct + qty_wastage +
    qty_rework  ==  predecessor.qty_out``

This is the load-bearing invariant for A11's WIP cost settlement —
every unit dispatched upstream of QC must be accounted for in exactly
one downstream bucket.

`make lint` clean (ruff check + ruff format + mypy on 228 source
files). Full `pytest tests/` ran 1032 passed / 79 skipped / 1 flake
(`test_auth_switch_firm.py::test_switch_firm_to_other_org_returns_404`
— passes in isolation; pre-existing fixture-ordering issue
unrelated to A10). The new `test_qc_operation.py` adds 12 tests, all
green on first run.

OpenAPI snapshot regenerated via `dump-openapi.py` (116 paths now);
`pnpm gen:types` ran clean.

## Schema posture — no migration, no new column

Pre-task check via `alembic heads` showed `task_tr_a07_polish` as the
head with `MoOperationState` already carrying `QC_PENDING` and
`REWORK`, and `OperationType.QC` already declared. So A10 ships zero
schema work — the enum substrate was laid down in A01.

The interesting design choice was where `qty_rework` lands. Three
options:

1. **Bolt on a `mo_operation.qty_rework` column.** Cheap migration,
   but the rework qty's natural home is on the *cloned* rework op
   that A10-FU will create (its `qty_in` ≡ how many units came in
   for rework). A transitional column on the QC op is then re-derived
   from events anyway — dead weight.
2. **Persist on the `ProductionEvent.payload`.** The event log is
   already the audit trail for QC verdicts; a single
   `QC_RESULT_RECORDED.payload.qty_rework` lookup is unambiguous. A
   future migration that adds a column (if A11 cost-roll-up demands
   one column-side) can backfill from events.
3. **Carry on a sidecar `qc_result` table.** Overkill for v1; event
   log already does it.

Went with option 2. `GET /qc-result` is the single API surface for
the rework qty pre-A10-FU. Service docstring records the trade-off
so the future maintainer (probably me) knows why a column they might
want to add isn't there yet.

## Predecessor lookup — strict single-input

The conservation rule needs to know `predecessor.qty_out`. We walk
`routing_edge` for edges with `to_operation_id == qc_op.operation_master_id`
and require **exactly one** incoming edge. A multi-input QC inspecting
the merged output of a diamond DAG is a real shop-floor pattern but
the bucket-sum invariant gets fiddly (whose qty_out do you sum
against?). v1 ships single-input only; multi-input goes to A10-FU
alongside rework-op creation.

The QC op's own `qty_in` (seeded to `MO.planned_qty` at MO-create)
is rewritten at `record_qc_result` to equal `predecessor.qty_out` so
that the standard A07 conservation read
(`qty_in == qty_out + scrap + byproduct + wastage`) stays meaningful
column-side too — without this rewrite the column reads
`qty_in = planned_qty` and a downstream cost-roll-up reader would
get confused.

## RBAC catalog

Added two slugs to `_SYSTEM_PERMISSIONS`:

  - `manufacturing.qc.write` → start + record verdict.
  - `manufacturing.qc.read`  → view state + latest verdict.

Granted to:
  - OWNER (via `_ALL_PERMS`).
  - PRODUCTION_MANAGER (both slugs — they run the QC inspection).
  - ACCOUNTANT (read only — QC verdict feeds A11 WIP settlement).

Not granted to:
  - SALESPERSON (locked in by `test_salesperson_403_on_start_qc`).
  - WAREHOUSE (they don't run QC; A11-time we can reconsider for
    "warehouse acknowledges QC pass before put-away").

The task spec mentioned "QC Inspector if it exists" — no such role
in the system catalog today. Future expansion can add it without
schema work (just append to `_SYSTEM_ROLES`).

## Test coverage (12 tests, all green first run)

- `test_qc_pass_path_happy` — full PASS lifecycle: upstream
  qty_out=100, QC records 95+5 → state=CLOSED, qty_out=95.
- `test_qc_rework_marker_path` — 80 passed + 15 rework + 5
  rejected → state=REWORK (NOT CLOSED), end_date unset, payload
  carries qty_rework=15.
- `test_start_qc_rejects_non_qc_operation` — /start-qc against a
  STITCHING op returns 422.
- `test_record_qc_result_rejects_non_qc_operation` — same on the
  result endpoint (defense in depth).
- `test_record_qc_result_rejects_mismatched_sum` — buckets sum=90
  vs predecessor.qty_out=100 → 422 conservation error.
- `test_start_qc_rejects_when_mo_is_draft` — MO must be
  IN_PROGRESS.
- `test_start_qc_rejects_when_predecessor_has_no_output` —
  upstream qty_out=0 means nothing to inspect.
- `test_salesperson_403_on_start_qc` — real RBAC stack, 403 with
  `code=PERMISSION_DENIED`.
- `test_record_qc_result_idempotency_replay` — same Idempotency-Key
  returns cached body, version doesn't double-bump.
- `test_cross_org_cannot_start_qc` — RLS opacity, 422 not-found
  rather than 403.
- `test_qc_emits_production_events` — `QC_INSPECTION_STARTED` +
  `QC_RESULT_RECORDED` both emitted; result payload carries
  verdict + buckets + predecessor link.
- `test_accountant_can_read_qc_but_not_start` — A10 RBAC mirror of
  the A07 polish accountant test.

## Deviations from plan

- **Plan said "OperationMaster — verify enum has QC, document gap
  if not"** — verified; no gap; no migration needed.
- **Plan said "list_qc_operations / get_qc_operation in service".**
  Shipped both (`list_qc_operations` filters by
  `operation_master.operation_type == QC` via a JOIN); the GET
  endpoint surfaced is `/qc-result` per the task spec, which uses
  `get_latest_qc_result` rather than `get_qc_operation`. The
  `get_qc_operation` helper is in the public API surface for future
  endpoints (e.g. a dedicated GET if the FE needs op metadata
  separate from the verdict).
- **Plan asked for "Salesperson + a QC Inspector role if exists"**;
  no QC Inspector in the catalog so we granted to OWNER + PM only,
  with ACCOUNTANT read. Locked in the SALESPERSON-deny test.
- **`MoOperation.qty_in` rewrite at QC time.** Not explicitly
  called out in the plan but necessary for column-side
  conservation reads (see "Predecessor lookup" above). Documented
  in the service docstring.

## Open flags for the next task (A10-FU or A11)

- **Multi-input QC.** Rejected with "not supported in v1" for now;
  A10-FU should design the multi-input conservation rule
  (sum-of-predecessor-qty_outs?  pick the latest?  pick the
  smallest qty_out and demand the rest match?).
- **Rework-op creation.** A10-FU clones the failing predecessor as
  a new `MoOperation` with `rework_of_mo_operation_id` set to the
  parent, `qty_in = qty_rework`. The clone's `executor` should
  inherit from the parent. The `is_rework_paid` flag (already in
  the column inventory) suggests rework can be free OR billable;
  A10-FU should pick a default.
- **A11 cost settlement.** The five buckets on
  `QC_RESULT_RECORDED.payload` are the authoritative input for WIP
  settlement. If A11 needs them column-side (for SQL aggregations
  rather than JSON path queries), add a migration to copy them
  forward — see the "qty_rework storage" trade-off above.

## Pre-A11 checklist

- [ ] Verify the QC op's `qty_out` column carries the
      `qty_passed` figure (column-side reader for cost roll-up).
- [ ] Decide where `qty_rework` lives long-term (event payload vs
      column) before A10-FU creates the rework clone.
- [ ] Confirm `manufacturing.qc.read` is enough for the A11
      Accountant flow; bump if A11 needs new slugs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
