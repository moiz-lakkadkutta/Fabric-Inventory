# TASK-040 retro — deviations from plan and pre-next checklist

**Date:** 2026-04-28
**Branch:** task/040-coa-endpoints
**Plan:** inline in TASKS.md

## Summary

Shipped COA admin endpoints on top of the seeded data from TASK-015. New files: `coa_service.py`, `schemas/accounting.py`, `routers/accounting.py`. Added `accounting.coa.{read,update}` permissions to `rbac_service.py` and granted them to Accountant. Registered the router in `main.py`. 24 new tests (14 service, 10 router). All 419 tests pass; ruff/format/mypy clean.

## Deviations from plan

### 1. Permissions: `accounting.coa.*` instead of `masters.coa.manage`

Plan said add `accounting.coa.read` and `accounting.coa.update`. There was already a `masters.coa.manage` in `_SYSTEM_PERMISSIONS` (and the Accountant role had it). Added the new finer-grained `accounting.coa.*` perms alongside the existing `masters.coa.manage` rather than replacing it — removing a perm risks breaking the Accountant role for callers already using `masters.coa.manage`.

- **Fixed by:** Adding two new rows to `_SYSTEM_PERMISSIONS` + granting both to Accountant. `masters.coa.manage` left untouched.
- **Impact on later tasks:** TASK-041 (Voucher) may want to consolidate these perms; defer to that task.

### 2. System ledger detection: `created_by IS NULL` heuristic

`Ledger` model has no `is_system_ledger` column (unlike `CoaGroup.is_system_group`). The `seed_coa` function creates ledgers with `created_by=None`. Using `created_by IS NULL` as the system-row guard works for MVP, but any user-created ledger that doesn't supply `created_by` would also become read-only.

- **Fixed by:** Documenting in `coa_service._is_system_ledger` docstring and in this retro.
- **Schema debt:** Add `is_system_ledger BOOLEAN DEFAULT false` column to `ledger` table in a future migration (surface in TASK-041 or a dedicated patch).

### 3. `Ledger.created_by` has FK to `app_user.user_id`

Service tests that tried to pass `uuid.uuid4()` as `created_by` hit a FK violation. Fixed by adding a `real_user_id` fixture that creates an actual `AppUser` row in the seeded org.

- **Impact on later tasks:** Any future service test that creates a `Ledger` with a non-null `created_by` must use a real AppUser UUID.

## Things the plan got right

- Party CRUD pattern mirrored cleanly: service → schemas → router → tests.
- Sync `Session`, kw-only, explicit `org_id` convention held throughout.
- Idempotency-Key accepted on all mutations (validated as UUID v4 if present).
- `AppValidationError` on 422, `PermissionDeniedError` on 403 — error mapping worked first try.

## Pre-TASK-041 checklist

### 1. Schema debt: `is_system_ledger` column
Create an Alembic migration that adds `is_system_ledger BOOLEAN DEFAULT false NOT NULL` to the `ledger` table. Backfill with `UPDATE ledger SET is_system_ledger = true WHERE created_by IS NULL`. Update `coa_service._is_system_ledger` to use the column instead of the `created_by IS NULL` heuristic.

### 2. Confirm `masters.coa.manage` permission is still used
Search for any existing callers of `masters.coa.manage` before deprecating it. If no other code references it, remove in TASK-041 cleanup.

### 3. TASK-041 Voucher model needs `coa_group_id`
The Voucher / JournalLine will reference `ledger.ledger_id`; the `coa_service.get_ledger` helper is ready to use.

## Open flags carried over

- `masters.coa.manage` perm is now redundant alongside `accounting.coa.*` — consolidation deferred to TASK-041.
- `is_system_ledger` column missing from `Ledger` model — schema debt, tracked above.

## Observable state at end of task

- 7 new endpoints under `/coa/groups` and `/ledgers`.
- New permissions seeded per-org at signup: `accounting.coa.read`, `accounting.coa.update` — Accountant role gets both.
- 419 tests total (395 pre-existing + 24 new).
- Pre-existing flaky test (`test_item_routers::test_delete_item_returns_204_and_hides_from_list`, `test_orm_ddl_drift`) intermittently fails under full parallel run due to `organization.name` unique constraint collisions; passes in isolation. Not introduced by TASK-040.
