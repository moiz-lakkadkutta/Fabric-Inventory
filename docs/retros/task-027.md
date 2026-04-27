# TASK-027 retro — Purchase Order model + service + router

**Date:** 2026-04-27
**Branch:** task/027-purchase-order
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md`

## Summary

Shipped Purchase Order CRUD + state machine end-to-end. New ORM models
(`PurchaseOrder`, `POLine` with `PurchaseOrderStatus` enum), Pydantic
schemas, service with state-transition methods (`approve_po`,
`confirm_po`, `cancel_po`, `soft_delete_po`), and 7 router endpoints
under `/purchase-orders`. Gapless serial allocation per `(org, firm,
series)` via row-level lock on the firm row.

36 new tests (25 service + 11 router). 282 tests green; ruff + format +
mypy strict clean across 68 source files.

## Deviations from plan

### 1. Cancel/delete use `purchase.po.approve` permission (no separate `cancel` permission in catalog)

The rbac catalog has only three PO permissions: `create`, `read`,
`approve`. Cancel and soft-delete are administrative state changes —
gating them behind `approve` keeps the permission surface minimal and
matches the policy decision in TASK-009 (deletes are a form of update,
not a separate permission).

- **Fixed by:** routers `cancel_po`, `delete_po`, `confirm_po`, `approve_po`
  all use `Depends(require_permission("purchase.po.approve"))`.
- **Why this works:** Owner role has all three; Salesperson has only
  `read`; Accountant has `read` + `post` for invoices but not PO state
  changes. The default scopes are correct.

### 2. State machine enum has 6 states; service handles 5

The DDL ENUM has `DRAFT, APPROVED, CONFIRMED, PARTIAL_GRN,
FULLY_RECEIVED, CANCELLED`. The service implements transitions for
DRAFT/APPROVED/CONFIRMED/CANCELLED. `PARTIAL_GRN` and `FULLY_RECEIVED`
are reserved for TASK-028 GRN posting, which will set them automatically
based on the cumulative `qty_received` vs `qty_ordered` per line.

- **Why not in this task:** GRN-driven state advancement requires a GRN
  service (TASK-028), so this PR scopes to documents the user creates
  manually. `cancel_po` correctly refuses on `PARTIAL_GRN`/`FULLY_RECEIVED`
  to keep that future work clean.

### 3. Sub-agent for tests, model: sonnet

Task-027 service+router was substantial enough that the test-writing
spec ran ~36 cases. Used a sonnet sub-agent (per the user's standing
"use sonnet for clear/simple tasks" instruction) — wrote both test
files, ran them, returned green. Caught zero implementation bugs;
flagged two minor type-annotation choices that I let stand.

## Things the plan got right

- DDL had `purchase_order` and `po_line` tables already with the right
  shape (status ENUM, total_amount, taxes_applicable JSONB).
- `purchase.po.{create,read,approve}` permissions already in the rbac
  catalog from TASK-009; no catalog edit needed.
- The TASK-010 / TASK-011 patterns (sync Session, kw-only signatures,
  explicit `org_id`, sub-resource ownership check) ported cleanly.
- `selectinload(PurchaseOrder.lines)` makes the get/list responses
  return lines in one query — matches the API contract without N+1.

## Pre-TASK-028 / TASK-032 checklist

### 1. TASK-028 (GRN) extends this module

GRN model + service goes in `app/models/procurement.py` and
`app/service/procurement_service.py` (extended). Reuses
`PurchaseOrderStatus` enum. The state-advance helper:

```python
def _advance_to_grn_state(session, *, po: PurchaseOrder) -> None:
    """Re-evaluate PO status based on per-line qty_received vs qty_ordered.
    Called from the GRN service after each post."""
    fully_received = all(line.qty_received >= line.qty_ordered for line in po.lines)
    po.status = PurchaseOrderStatus.FULLY_RECEIVED if fully_received else PurchaseOrderStatus.PARTIAL_GRN
```

### 2. TASK-032 (Sales Order) is the mirror task

Same shape: header + lines, state machine
(DRAFT → CONFIRMED → PARTIAL_DC → FULLY_DISPATCHED → INVOICED). Will
follow the same `procurement_service` pattern in `sales_service.py`.

### 3. Number-allocation race — same first-insert race as stock_position

`_allocate_number` does `SELECT FOR UPDATE` on the firm row, then reads
the max number. This serializes correctly for existing PO chains, but
the **first-ever PO for a (firm, series)** has no row to lock against.
Two concurrent transactions could both compute number=`0001` and both
INSERT — Postgres will unique-violate one. Same Wave-4 stress-test
follow-up as the inventory race.

## Open flags carried over

- **GRN-driven state advancement** — wired in TASK-028.
- **First-PO-in-series race** — same fix pattern as TASK-022's
  first-position race; document in Wave 4.
- **Series → FY mapping** — currently the caller passes `series`
  freely. TASK-048 (GSTR-1 prep) needs canonical FY-prefixed series
  names. Add a `series_validate(...)` helper there.

## Observable state at end of task

- New file: `backend/app/models/procurement.py` (2 models + 1 enum).
- New file: `backend/app/service/procurement_service.py` (7 public funcs).
- New file: `backend/app/schemas/procurement.py` (5 schemas).
- New file: `backend/app/routers/procurement.py` (7 endpoints under `/purchase-orders`).
- New tests: `tests/test_purchase_order_service.py` (25), `tests/test_purchase_order_routers.py` (11).
- Modified: `backend/main.py` registers the procurement router.
- Modified: `backend/app/models/__init__.py` re-exports the procurement models.
