# TASK-028 retro — GRN model + service + router + stock posting

**Date:** 2026-04-27
**Branch:** task/028-grn

## Summary

Shipped GRN end-to-end: 2 ORM models + `GRNStatus` StrEnum, schemas,
service in `procurement_service.py` (`create_grn`, `get_grn`, `list_grns`,
`receive_grn`, `soft_delete_grn`, `_advance_po_status_after_grn`,
`_allocate_grn_number`), 5 router endpoints under `/grns`. `receive_grn`
posts to the stock ledger via `inventory_service.add_stock` and advances
the linked PO's status to `PARTIAL_GRN` / `FULLY_RECEIVED` based on
cumulative `qty_received` per po_line.

New Alembic migration `task_028_grn_line_po_line_fk` adds nullable
`grn_line.po_line_id` FK so GRN lines map to specific PO lines (not by
item-id heuristic).

35 new tests (25 service + 10 router). 318 tests green; ruff + format +
mypy strict clean across 71 source files.

## Deviations from plan

### 1. Added `grn_line.po_line_id` via forward migration

DDL had no `po_line_id` column on `grn_line` — the original schema
matched lines to PO lines by `item_id`. That's lossy when a PO has
duplicate items per line. Added a nullable FK so the GRN service can
target a specific po_line; null when the GRN isn't tied to a PO.

- **Why this matters:** `_advance_po_status_after_grn` walks po_lines
  and sums `GRNLine.qty_received WHERE po_line_id = X`. Without the FK,
  the sum would over-count if two po_lines share the same item.

### 2. `purchase.grn` permissions expanded

Catalog had only `purchase.grn.create`. Added `purchase.grn.read` and
`purchase.grn.approve`. Owner gets all (via `_ALL_PERMS`); Warehouse
role gets `read` and `approve` (it's the operational warehouse-side
state change).

### 3. Test smoke head revision bumped

`tests/test_migration_smoke.py` asserts the alembic head is the latest
migration. Bumped from `task_015_uom_hsn_per_org` to
`task_028_grn_line_po_line_fk`.

## Things the plan got right

- Service-layer state advancement (`_advance_po_status_after_grn`)
  cleanly delegated to procurement_service from receive_grn — keeps
  the PO state machine the single owner of `PurchaseOrder.status`.
- `GRNStatus` StrEnum at the ORM level even though DDL stores VARCHAR —
  prevents typos at the application boundary.
- `inventory_service.add_stock` already had the right shape
  (`reference_type`, `reference_id`, `unit_cost`, `lot_id?`, `txn_date`)
  — drop-in callable.

## Pre-TASK-029 checklist

### 1. PI (Purchase Invoice) extends procurement_service

Same module, similar pattern: `create_pi`, `post_pi`, ... `post_pi`
will trigger the GL voucher autoposting (TASK-041) when that lands.

### 2. GRN-without-PO is a real path

Direct stock receipts (no PO; e.g. opening balance import in TASK-025
or a supplier sample drop) call `create_grn(purchase_order_id=None)`.
TASK-061b (Vyapar adapter) will use this for opening-stock seeding.

## Open flags

- **Negative GRN qty (returns)**: not implemented. Returns to supplier
  go through the `RETURNED` GRN status — service flow lands when
  TASK-049 (credit note) needs it.
- **Lot creation on GRN**: today, `lot_number` is just text on grn_line.
  Creating a `Lot` row from a GRN line is a Phase-3 enhancement when
  expiry-tracked items become important.
- **Concurrency on `_advance_po_status_after_grn`**: two GRNs racing
  to receive against the same PO could both compute "FULLY_RECEIVED"
  consistently (same cumulative sum), but the PO update isn't locked.
  Same Wave-4 stress-test concern as the inventory service.

## Observable state at end of task

- New migration: `2026042700002_task_028_grn_line_po_line_fk.py`
- Modified: `app/models/procurement.py` (+ `GRN`, `GRNLine`, `GRNStatus`)
- Modified: `app/service/procurement_service.py` (+5 GRN funcs + helpers)
- Modified: `app/schemas/procurement.py` (+5 GRN schemas)
- Modified: `app/routers/procurement.py` (+5 GRN endpoints under `/grns`)
- Modified: `app/service/rbac_service.py` (+`purchase.grn.read`, `+approve`)
- Modified: `main.py` (+grn_router)
- Modified: `tests/test_migration_smoke.py` (head bump)
- New tests: `tests/test_grn_service.py` (25), `tests/test_grn_routers.py` (10).
