# TASK-TR-A01 retro — deviations from plan and pre-next checklist

**Date:** 2026-05-14
**Branch:** task/tr-a01-mfg-models
**Commit:** `<sha>` (PR open, not merged — foundational spine, needs review)
**Plan:** TASK-TR-A01 brief (Manufacturing track, wave A)

## Summary

Shipped `backend/app/models/manufacturing.py` — SQLAlchemy 2.0 ORM models for
10 of the 11 Manufacturing tables (`design`, `bom`, `bom_line`,
`operation_master`, `routing`, `routing_edge`, `manufacturing_order`,
`mo_material_line`, `mo_operation`, `production_event`) plus 5 enums
(`MoStatus`, `MoType`, `RoutingEdgeType`, `MoOperationState`, `OperationType`).
The 11th table, `cost_centre`, was already modelled in `masters.py` as
`CostCentre` — left as-is, referenced by FK string. Models registered in
`app/models/__init__.py`. Added `backend/tests/test_manufacturing_models.py`
(6 tests: import/registration parity, inspector-based column/type/nullability/PK
parity against the live migrated DB, NUMERIC-not-float spot-check, forward-ALTER
column presence, TIMESTAMPTZ check). TDD-red was verified by moving the model
file aside (test errors at collection). lint (`ruff check` + `ruff format
--check`) clean on all touched files; full backend suite **836 passed**; the
repo-wide `test_orm_ddl_drift.py` gate **passes** with the new tables in scope —
exhaustive ORM↔DDL parity confirmed.

## Deviations from plan

### 1. Task said "11 models + 4 enums" — actually 10 new models + 5 enums
`cost_centre` already had a model (`CostCentre` in `masters.py`) — redefining it
would collide in `Base.metadata`. And `operation_master` needs the
`operation_type` Postgres enum, which was not modelled anywhere, so a 5th enum
(`OperationType`) had to be defined here.
- **Fixed by:** model only the 10 unmodelled tables; reference `cost_centre` via
  FK string; add `OperationType` to `manufacturing.py`.
- **Why not caught in planning:** the brief listed `cost_centre` in the table
  set without checking it was already modelled.
- **Impact on later tasks:** none — `CostCentre` is importable from `app.models`
  as before.

### 2. The base `CREATE TABLE` DDL is NOT the real schema — the audit sweep rewrites it
`schema/ddl.sql` has a `$audit_sweep$` PL/pgSQL DO block that adds
`updated_at` / `created_by` / `updated_by` / `deleted_at` to *every*
tenant-scoped table not on an exempt list. So every Manufacturing table except
`production_event` (which IS exempt) carries the full audit-column set in the
live/migrated DB, even though its base `CREATE TABLE` only declares
`created_at`. Modelling straight from the `CREATE TABLE` text would have been
wrong on 9 tables.
- **Fixed by:** inspected the live DB's `information_schema.columns` for every
  table, then gave each model `TimestampMixin` + `SoftDeleteMixin` (+ `AuditByMixin`
  for the tables whose `created_by` is a plain UUID; the 4 tables with an inline
  `created_by` FK declare it by hand). `ProductionEvent` gets no mixins.
- **Why not caught in planning:** the brief said "mirror the DDL precisely" and
  pointed at the `CREATE TABLE` anchors; the sweep DO block is 1200 lines later.
- **Impact on later tasks:** downstream Manufacturing service tasks can rely on
  the standard audit columns being present on all MO tables except
  `production_event`.

### 3. Modelling the MO tables exposed pre-existing FK drift in `sales.py` / `inventory.py`
`sales_invoice.linked_mo_id` and `stock_ledger.mo_operation_id` were declared as
plain UUID columns (no ORM FK) *deliberately*, because their target tables
weren't modelled yet (the drift test's `include_object` skipped FKs to
unmodelled tables). Once `manufacturing_order` / `mo_operation` entered
`Base.metadata`, those FKs became in-scope and the drift test flagged them.
- **Fixed by:** added the real `ForeignKey(..., ondelete="SET NULL")` to both
  columns (`app/models/inventory.py`, `app/models/sales.py`), matching the DDL.
- **Why not caught in planning:** the brief scoped the task to "create the
  models" — it didn't anticipate that the drift gate would surface latent FK
  gaps in sibling domains.
- **Impact on later tasks:** none — this is strictly more correct.

### 4. `mo_operation` carries a large forward `ALTER TABLE`
Beyond its base `CREATE TABLE`, `mo_operation` has a "state machine + karigar +
event-sourcing hooks" `ALTER TABLE` adding 15 columns (`firm_id`, typed `state`,
`karigar_party_id`, `executor`, challan links, qty/cost columns, rework self-FK,
optimistic-lock `version`, …). The legacy free-text `status` column is kept in
parallel with the typed `state`.
- **Fixed by:** all 15 forward-ALTER columns declared on `MoOperation`; a test
  asserts their presence.
- **Why not caught in planning:** expected; the brief mentioned the
  ~959-1092 range only — the ALTER lives at ~2171.
- **Impact on later tasks:** the MO-lifecycle service should drive
  `mo_operation.state` (the typed enum), not the legacy `status` string.

## Things the plan got right (no deviation)

- TDD-first worked cleanly: the parity test fails at collection without the
  models, passes once they exist.
- Following `jobwork.py` / `procurement.py` style (PG_ENUM with
  `create_type=False`, `_UUID_DEFAULT`, mixins, `Mapped[...]`) made the models
  drop in without friction.
- The existing `test_orm_ddl_drift.py` auto-scopes to `Base.metadata.tables` —
  registering the new tables put them under the exhaustive gate for free.

## Pre-TASK-TR-A02 checklist

### 1. The worktree had pre-existing conflict-marker cruft — verify it's clean
Six unrelated files (`backend/app/{routers,schemas,service}/inventory*.py`,
`docs/ops/cutover-plan-2026-05-10.md`, `frontend/scripts/openapi-snapshot.json`,
`frontend/src/types/api.ts`) ended up with Git conflict markers during this
session (a stray `git stash pop` of a pre-existing `stash@{0}` "wave-3 worktree
leftovers"). They were re-stashed aside (`git stash` entry: "TR-A01 cleanup:
wave-3 stash@{0} leftovers re-stashed"). They are NOT part of this task and were
NOT committed. Before the next task, confirm `git status` in the worktree is
clean and decide what to do with that stash.

### 2. Run the full suite with the env file sourced
The worktree's `backend/.env` is gitignored and must be copied from the main
repo. The DB-bound tests (`sync_engine`, drift test) read `DATABASE_URL` /
`MIGRATION_DATABASE_URL` from the process env — `set -a && . ./.env && set +a`
before `uv run pytest`, or they skip.

## Open flags carried over

- `outward_challan` / `inward_challan` are still unmodelled. `mo_operation`'s
  `outward_challan_id` / `inward_challan_id` are plain UUID columns (no ORM FK) —
  the DB enforces the constraint. When a future task models the challan tables,
  add the ORM FKs and the drift test will start checking them.
- `qc_plan`, `qc_result`, `labour_slip` and other Phase-3 manufacturing tables
  exist in the DDL but were out of scope here — they reference `mo_operation` /
  `operation_master` and will model cleanly once their owning task lands.

## Observable state at end of task

- New file: `backend/app/models/manufacturing.py`, `backend/tests/test_manufacturing_models.py`.
- Modified: `backend/app/models/__init__.py` (exports), `backend/app/models/inventory.py`
  + `backend/app/models/sales.py` (FK fixes per deviation 3).
- Untracked files left on disk, NOT committed, not mine: `docs/ops/qa-run-2026-05-07.md`,
  `docs/ops/testing-cookbook.md` (pre-existing worktree cruft).
- Git stash entry created this session: "TR-A01 cleanup: wave-3 stash@{0}
  leftovers re-stashed" — holds the six conflict-marker files. Pre-existing
  stashes (`wip-scheduled-tasks-lock`, etc.) are untouched.
- No new dev-env requirements. No Alembic migration created — the 11 tables
  already exist in the migrated DB; this is a parity task.
