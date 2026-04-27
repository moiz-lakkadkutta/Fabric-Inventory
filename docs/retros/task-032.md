# TASK-032 retro — deviations from plan and pre-next checklist

**Date:** 2026-04-27
**Branch:** task/032-sales-order
**Commit:** (pending merge to main)
**Plan:** TASK-032 spec in task prompt

## Summary

Shipped Sales Order CRUD + state machine end-to-end. New ORM (`SalesOrder`, `SOLine`), service (`sales_service`), schemas (`SOCreateRequest`, `SOResponse`, etc.), and router (7 endpoints under `/sales-orders`). Added `sales.order.read` and `sales.order.approve` permissions to `rbac_service`. 37 new tests (26 service + 11 router). All 320 total tests pass; `ruff check`, `ruff format --check`, and `mypy` are clean. Drift gate (`test_orm_ddl_drift`) passes with zero diff.

## Deviations from plan

### 1. `SalesOrder` had two extra DDL columns not in the spec: `quotation_id` and `salesperson_id`

Plan said to mirror `schema/ddl.sql` lines 1350-1391. The DDL has `quotation_id UUID REFERENCES quotation(...)` and `salesperson_id UUID REFERENCES app_user(...)` that were not mentioned in the task spec.
- **Fixed by:** Added both columns to `SalesOrder` ORM model. `quotation_id` declared without a FK constraint (quotation table not yet modeled — same FK-skip pattern used by procurement). `salesperson_id` declared with FK to `app_user.user_id`.
- **Why not caught in planning:** Task spec focused on the functional columns; the drift gate caught it after the first full test run.
- **Impact on later tasks:** Zero — columns are nullable and not exposed in current service/schema.

### 2. `so_line` column name is `price` not `rate`

The DDL uses `price NUMERIC(15,4)` (not `rate` like `po_line`). Task spec said "mirror PO" but the DDL diverges on this field name.
- **Fixed by:** Named the ORM column `price`, and used `price` throughout service/schema. Service helper uses `line["price"]` dict key.
- **Why not caught in planning:** Reading the DDL directly revealed this; procurement used `rate` but sales uses `price`.
- **Impact on later tasks:** TASK-033 (DC) and TASK-034 (SI) should expect `price` not `rate` on `so_line`.

## Things the plan got right (no deviation)

- `sales_order_status` enum values matched exactly (`DRAFT`, `CONFIRMED`, `PARTIAL_DC`, `FULLY_DISPATCHED`, `INVOICED`, `CANCELLED`).
- `is_customer` check (not `is_supplier`) correctly gates party validation.
- Soft-delete strict allow-list (DRAFT or CANCELLED only) enforced.
- Gapless serial via SELECT FOR UPDATE on firm row works identically to PO pattern.
- `_ALL_PERMS` computed from `_SYSTEM_PERMISSIONS` automatically gives Owner all new permissions — no manual update needed for Owner role.

## Pre-TASK-033 checklist

### 1. DC model extends `sales.py` — don't create a new file
TASK-033 (Delivery Challan) should add `DeliveryChallan` and `DCLine` to `backend/app/models/sales.py`, not a new file, consistent with the repo structure comment.

### 2. `so_line.price` not `rate`
DC lines link to `so_line` — make sure any join or copy logic uses `price` (not `rate`).

### 3. `sales.order.read` permission needed for DC router
DC creation will need to read SO state. Use `sales.dc.create` permission gate (already in catalog) for the DC endpoint.

### 4. Drift gate will fire on new tables
`DeliveryChallan` and `DCLine` must include the full audit-sweep column set (`updated_at`, `created_by`, `updated_by`, `deleted_at`) to pass drift gate.

## Open flags carried over

- `quotation_id` and `salesperson_id` on `SalesOrder` are nullable and unused in this task. TASK-035+ (Quotation) will wire up the quotation FK when it models the `quotation` table.
- `PARTIAL_DC`, `FULLY_DISPATCHED`, `INVOICED` SO status transitions are TODOs in `sales_service.py` docstring — TASK-033 and TASK-034 will add `_advance_to_dc_state` / `_advance_to_invoice_state` helpers.

## Observable state at end of task

- 320 tests total (37 new). All green.
- `ruff check`, `ruff format --check`, `mypy` all clean across 74 source files.
- Drift gate passes: 0 ORM↔DDL diffs on modeled tables.
- New endpoints live at `/sales-orders` (prefix), authenticated + permission-gated.
- `sales.order.read` added to ACCOUNTANT and SALESPERSON roles in `rbac_service.py`.
