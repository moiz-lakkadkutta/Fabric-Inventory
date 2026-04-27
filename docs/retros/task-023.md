# TASK-023 retro — Stock adjustment service + router

**Date:** 2026-04-27
**Branch:** task/023-stock-adjustment
**Plan:** TASK-023 spec in TASKS.md + agent briefing

## Summary

Shipped `StockAdjustment` ORM model, `stock_service.py` (create_adjustment / list_adjustments / get_adjustment), `app/schemas/inventory.py` (request/response), and `app/routers/inventory.py` (POST + GET /stock-adjustments + GET /{id}). Registered the router in `main.py`. 11 service tests + 8 router tests added. All 302 tests pass; ruff check/format and mypy are clean.

**Design choice:** Used the existing `stock_adjustment` DDL table (present in the baseline migration from TASK-004) as a header row. The actual qty movement is recorded in `stock_ledger` with `reference_type='ADJUSTMENT'` and `reference_id=stock_adjustment_id`. This gives a clean audit trail — the header captures reason + approval metadata while the ledger is the authoritative append-only record.

## Deviations from plan

### 1. DDL audit_sweep adds columns the ORM must declare

**Plan said:** `stock_adjustment` has only the columns listed in DDL lines 716-728 (`qty_change`, `reason`, `requires_approval`, `approved_by`, `approved_at`, `created_by`, `created_at`).

**Reality:** The DDL's `$audit_sweep$` DO block (lines 2279-2347) adds `updated_at`, `updated_by`, and `deleted_at` to every non-exempt table. `stock_adjustment` is not in the exempt list, so all three get added. Additionally, the explicit FK constraints on `approved_by` → `app_user(user_id)` and `created_by` → `app_user(user_id)` in the base DDL (rewritten to `ON DELETE SET NULL` by the P1-2 DO block) needed to be declared in the ORM — unlike `AuditByMixin` columns on other tables, which don't have FK constraints in the DDL.

**Fixed by:** Added `SoftDeleteMixin` to `StockAdjustment`, plus explicit `updated_at`, `updated_by` columns, and `ForeignKey("app_user.user_id", ondelete="SET NULL")` on `approved_by` and `created_by`.

**Why not caught in planning:** The audit_sweep DO block runs at migration time and isn't visible in the CREATE TABLE statement itself. Requires reading the full DDL end-to-end to notice.

**Impact on later tasks:** Any future model for a non-exempt table must declare audit_sweep columns. Established pattern here for future reference.

### 2. Router tests need out-of-band location setup

**Plan said:** HTTP-only router tests sufficient.

**Reality:** `POST /stock-adjustments` requires a `location_id` that references a row in the `location` table. No location API endpoint exists yet. Router tests had to set up locations via a direct DB call using the `sync_engine` fixture, then commit so the app's session sees it.

**Fixed by:** `_create_location_and_add_stock()` helper in the router test file uses `sync_engine` from conftest, calls `inventory_service.get_or_create_default_location()` + `add_stock()`, then commits.

**Why not caught in planning:** Location API endpoints are in a future task. The dependency wasn't explicit in the scope.

**Impact on later tasks:** When the location management API lands (TASK-025+), the router tests can be simplified to use HTTP calls end-to-end.

## Things the plan got right (no deviation)

- `stock_adjustment` table was present in the DDL from TASK-004 baseline — no new migration needed.
- The `inventory.adjustment.create` and `inventory.stock.read` permissions already seeded in `rbac_service.py`.
- INCREASE/DECREASE/COUNT_RESET direction model worked cleanly by wrapping `inventory_service.add_stock`/`remove_stock`.
- COUNT_RESET no-op case (delta = 0) correctly writes a stub audit ledger row.
- ruff/mypy were clean with minimal back-and-forth.

## Pre-TASK-024 checklist

### 1. Verify test DB migration status before starting
Run `make migrate` if the schema has drifted; the drift gate (`test_orm_ddl_drift.py`) catches this immediately.

### 2. Location API
If TASK-024 or any nearby task needs location creation via HTTP, that endpoint must be built first. The current workaround (direct DB calls in tests) is fine for this task only.

## Open flags carried over

- No approval workflow implemented: `requires_approval` and `approved_by`/`approved_at` fields exist on the header but are never set by the service. A future approval-flow task will surface these. Currently all adjustments are posted immediately.
- No `unit_cost` enforcement for DECREASE/COUNT_RESET→decrease paths: the cost basis stays as the current position cost (standard WACC behavior). Flagged in service docstring.

## Observable state at end of task

- New files: `backend/app/service/stock_service.py`, `backend/app/schemas/inventory.py`, `backend/app/routers/inventory.py`, `backend/tests/test_stock_adjustment_service.py`, `backend/tests/test_stock_adjustment_routers.py`
- Modified: `backend/app/models/inventory.py` (added `StockAdjustment`), `backend/app/models/__init__.py` (re-export), `backend/main.py` (router registration), `TASKS.md` (TASK-023 → Done)
- Test count: 302 total (283 pre-task + 19 new)
- All gates green: pytest ✓, ruff check ✓, ruff format ✓, mypy ✓
