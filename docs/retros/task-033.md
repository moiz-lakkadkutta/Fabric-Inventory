# TASK-033 retro — deviations from plan and pre-next checklist

**Date:** 2026-04-28
**Branch:** task/033-delivery-challan
**Commit:** TBD (open PR)
**Plan:** Delivery Challan end-to-end mirror of TASK-028 GRN

## Summary

Delivery Challan shipped end-to-end: `DeliveryChallan` + `DCLine` ORM models
appended to `app/models/sales.py`, `DCStatus` StrEnum, DC service functions
(`create_dc`, `get_dc`, `list_dcs`, `issue_dc`, `soft_delete_dc`) and
`_allocate_dc_number` / `_advance_so_status_after_dc` helpers in
`sales_service.py`, Pydantic schemas in `app/schemas/sales.py`, a
`dc_router` in `app/routers/sales.py` with 5 endpoints under
`/delivery-challans`, and two new RBAC permissions (`sales.dc.read`,
`sales.dc.approve`) granted to OWNER (via `_ALL_PERMS`), SALESPERSON (read),
and WAREHOUSE (read + approve). `issue_dc` calls
`inventory_service.remove_stock` atomically per line and advances the linked
SO to `PARTIAL_DC` / `FULLY_DISPATCHED`. 32 new tests (22 service, 10
router). ruff check, ruff format, mypy, and 425 tests all pass (395 pre-
existing + 32 new, with the 2 drift/migration tests always skipped by the
targeted run).

## Deviations from plan

### 1. DDL uses VARCHAR(50) for delivery_challan.status, not challan_status ENUM

The DDL's `delivery_challan` table uses `status VARCHAR(50) DEFAULT 'DRAFT'`
— the `challan_status` Postgres ENUM only appears on the `outward_challan` /
`inward_challan` (job-work) tables, not the customer-facing `delivery_challan`
table.

- **Fixed by:** Used the same pattern as GRN (`String(50)` column + `DCStatus` StrEnum constraint at the ORM/service level).
- **Why not caught in planning:** Task brief said "bound to `challan_status` Postgres enum (verify name in DDL)" — DDL check resolved the ambiguity.
- **Impact on later tasks:** None. TASK-034 (Sales Invoice) also uses `VARCHAR(50)` with its own StrEnum.

### 2. Router test stock-seeding needed service-layer bypass

`_seed_stock` in the router tests tried to call `POST /stock-adjustments`
with a simplified payload that didn't include the required `location_id` and
`direction` fields.

- **Fixed by:** Replaced with `_seed_stock_via_service(sync_engine, ...)` that calls `inventory_service.add_stock` directly — same pattern as GRN router tests that verify stock qty via the service layer.
- **Why not caught in planning:** Different schema from assumed payload.
- **Impact on later tasks:** TASK-034 router tests should use the same helper.

## Things the plan got right (no deviation)

- GRN mirror pattern worked perfectly — same lock-based numbering, same status constraint pattern, same soft-delete guard.
- `_advance_so_status_after_dc` cross-joins `DCLine → DeliveryChallan` rather than blindly summing all lines, correctly handling soft-deletes and DRAFT DCs.
- `issue_dc` atomicity: if `remove_stock` raises (`InsufficientStockError`), the whole transaction rolls back — no partial state.
- RBAC wiring: adding 2 new permissions (`sales.dc.read`, `sales.dc.approve`) and granting them to the right roles was clean with the existing idempotent seed pattern.

## Pre-TASK-034 checklist

### 1. DeliveryChallan ↔ SalesInvoice FK
DDL has `delivery_challan_id UUID REFERENCES delivery_challan(...)` on `sales_invoice`. TASK-034's model must declare this FK and the `SalesInvoice → DeliveryChallan` relationship.

### 2. SO status → INVOICED
`_advance_so_status_after_dc` only advances to `PARTIAL_DC` / `FULLY_DISPATCHED`. TASK-034 must add a similar `_advance_so_status_after_invoice` that moves to `INVOICED`.

### 3. Drift gate
TASK-033 added `DeliveryChallan` + `DCLine` to `Base.metadata`. The drift test will now check them. TASK-034 will add `SalesInvoice` + `SILine` — ensure they're in the Alembic migration before the drift test runs in CI.

## Open flags carried over

- `DCStatus.ACKNOWLEDGED / IN_PROCESS / RETURNED / CLOSED` transitions are not yet driven by MVP service code — reserved for customer-acknowledgement and return flows (TASK-049+).
- `qty_dispatched` denormalization on `SOLine` is updated by `_advance_so_status_after_dc` but only on issue. If a DC is ever reversed (TASK-049), the denormalized value must be decremented.

## Observable state at end of task

- 427 tests total in the repo; 425 pass when `test_orm_ddl_drift.py` and `test_migration_smoke.py` are excluded (those tests drop and recreate the schema which causes ordering-dependent failures for subsequent HTTP tests). This is a pre-existing issue, not introduced by TASK-033.
- New endpoints at `/delivery-challans` (POST, GET, GET/:id, POST/:id/issue, DELETE/:id).
- New permissions: `sales.dc.read`, `sales.dc.approve` — seeding is idempotent, existing orgs get them on next `seed_system_permissions` call.
