# TASK-022 retro — Stock ledger + position service (deep-focus single-author)

**Date:** 2026-04-27
**Branch:** task/015-seed-data → continued on same branch
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` §8 (deep-focus tasks)

## Summary

Shipped the inventory invariant pair end-to-end: append-only `stock_ledger`
(one INSERT per move, never UPDATE/DELETE) + denormalized `stock_position`
kept in sync inside the same transaction. Weighted-average cost on every
inbound move; SO reservation gate via `atp_qty`; explicit cross-org
defense-in-depth filter on every public function.

New ORM models for `Lot`, `Location`, `StockLedger`, `StockPosition` (in
`app/models/inventory.py`) — `mo_operation_id` declared without an FK
target (Phase-3 not yet modeled); drift gate updated to skip FKs whose
referred table isn't in `Base.metadata`. `StockPosition.atp_qty` mapped
as a SQLAlchemy `Computed` column matching the DDL's STORED generated
column.

18 new tests + 1 drift-gate filter tweak. 246 tests green; ruff +
format + mypy strict clean across 62 source files.

## Deviations from plan

### 1. Did this on the TASK-015 branch instead of a fresh branch

Plan said one branch per task. After TASK-015 merged, the user asked to
"do everything not blocked by frontend" with separate reviews. I'd
already cut a fresh branch off main and was about to start TASK-022 on
it; the actual git history shows TASK-015 was merged via PR #15, then
this work continued on the same checkout. The PR for TASK-022 is fresh
off main with a clean diff.

- **Fixed by:** the actual TASK-022 PR is on `task/022-stock-ledger`,
  cut from latest main after the TASK-015 squash-merge. (Pre-PR self-
  check confirms diff is TASK-022 only.)
- **Why this matters:** branch-per-task is the rule for atomic review +
  rollback. A wide branch combining 015+022 would have been hard to
  review and harder to revert.

### 2. `mo_operation` FK is not declared on the ORM (Phase-3 isolation)

The DDL adds `stock_ledger.mo_operation_id` with an FK to `mo_operation`
in a later DDL section (manufacturing schema). `mo_operation` itself
isn't modeled in ORM until Phase-3 manufacturing wave (TASK-073). If we
declare the FK on the ORM, SQLAlchemy raises `NoReferencedTableError`
at metadata-compile because the target table isn't in `Base.metadata`.

- **Fixed by:** column declared on ORM without FK (`Mapped[uuid.UUID |
  None]` only); DB still enforces the FK from DDL. Drift gate updated
  to skip foreign-key constraints whose referred table isn't modeled
  (`tests/test_orm_ddl_drift.py:_include_only_modeled`).
- **Impact on later tasks:** when TASK-073 (manufacturing MOs) lands,
  the `mo_operation` model will appear in `Base.metadata` and the drift
  gate will require the FK declaration on `StockLedger`. One-line fix
  at that time.

### 3. `StockPosition` doesn't have `created_at` (DDL omits it)

The DDL declares `stock_position.updated_at` inline but not `created_at`
— the row is upsert-style, so a creation timestamp is misleading. My
ORM model uses `AuditByMixin + SoftDeleteMixin` but **not** `TimestampMixin`
(which would force a `created_at` column the DB doesn't have); `updated_at`
is declared manually.

- **Why this matters:** future "give every model the full audit-mixin
  set" refactors should respect this exception. There's a comment in the
  model body explaining it.

### 4. FIFO costing scope was reduced to weighted-average

The plan said "FIFO cost calculation: avg_cost = sum(total_value) / sum(qty)
from all in ledger entries." That formula is moving-average, not strictly
FIFO. True FIFO costing requires layer-tracking (each inbound creates a
"layer" with its own cost; outbound consumes layers oldest-first). For
MVP the moving-average is correct for `current_cost` and matches Vyapar
behavior. Real FIFO is a Phase-3 enhancement when lot-level cost basis
becomes important.

- **Fixed by:** documented in the service module docstring.
- **Impact on later tasks:** TASK-061b (Vyapar adapter) imports moving-
  average opening cost from .vyp — matches our model. TB reconcilation
  gate (TASK-062) is unaffected. If real FIFO is ever needed, it's a
  service-layer rewrite, no schema change.

## Things the plan got right

- The DDL already had `stock_ledger`, `stock_position`, `lot`, `location`
  with the right shape (including the `atp_qty` STORED generated column).
  Zero schema work in this task.
- Append-only invariant + position-equals-running-sum invariant ported
  cleanly via one transaction holding both writes + a `SELECT … FOR
  UPDATE` row lock on the position row to serialize concurrent moves.
- The "DEEP-FOCUS, no T3 split" call (plan §8) was correct — the
  weighted-average cost math, the position-lock-then-update flow, and
  the validation guards (`_ensure_*_in_*`) all touch the same module
  and would have raced if split across sub-agents.

## Pre-TASK-023 / TASK-027 / TASK-032 checklist

### 1. TASK-023 (stock adjustment) is the natural next pick

It calls `add_stock` and `remove_stock` directly with `reference_type='ADJUSTMENT'`
and a JV reference. Re-uses everything here.

### 2. TASK-027 (PO) and TASK-032 (SO) are independent of inventory state

PO/SO are documents that don't move stock; the GRN (TASK-028) and DC
(TASK-033) layers do. So both can run in parallel after this lands.

### 3. Note the cross-org test pattern is now reusable

`test_get_position_does_not_leak_across_orgs` and
`test_list_positions_filters_by_org` are templates: probe with a
foreign org_id, expect empty / None. Every future tenant-scoped service
should mirror this.

## Open flags carried over

- **True FIFO costing** (Phase-3): currently moving-average. Not a bug,
  intentional MVP scope.
- **Lot consumption order** (Phase-3): no FIFO-by-lot logic in
  `remove_stock`. Today, `lot_id` is just a partition key for the
  position row.
- **Concurrency stress test**: only the unit-level FOR UPDATE assertion
  is present. A genuine concurrent-writer test (two threads racing
  add_stock for the same key) would round out the invariant. Slot when
  Wave 4 procurement starts running stress tests against multiple GRNs.

## Observable state at end of task

- New file: `backend/app/models/inventory.py` (4 models + 2 enums).
- New file: `backend/app/service/inventory_service.py` (7 public funcs).
- New file: `backend/tests/test_inventory_service.py` (18 tests).
- Modified: `backend/app/models/__init__.py` — re-exports the new models.
- Modified: `backend/tests/test_orm_ddl_drift.py` — filter skips FKs to
  unmodeled tables.
