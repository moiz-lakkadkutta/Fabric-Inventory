# TASK-029 retro — Purchase Invoice + state machine + 3-way match

**Date:** 2026-04-28
**Branch:** task/029-purchase-invoice

## Summary

Shipped Purchase Invoice end-to-end. New ORM (`PurchaseInvoice`, `PILine`,
`VoucherStatus` enum, `PurchaseInvoiceLifecycleStatus` enum), schemas,
6 endpoints under `/purchase-invoices` gated by `purchase.invoice.{create,
post,read,void}` (catalog expanded). Service: `create_pi`, `get_pi`,
`list_pis`, `post_pi`, `void_pi`, `soft_delete_pi`, `_allocate_pi_number`.

`post_pi` runs a **loose 3-way match**: if PI is GRN-linked and the PI
total drifts > 1% from GRN total, the warning is recorded in
`match_result` JSONB but the post is NOT blocked (Moiz wants flexibility
for rounding / freight / surcharge differences). Within 1%, no warning.

39 new tests (28 service + 11 router). 434 tests green; ruff + format +
mypy strict clean across 88 source files.

## Deviations from plan

### 1. Two parallel status enums per the DDL

The DDL keeps both `voucher_status` (basic, shared with all voucher
docs) AND `purchase_invoice_status` (richer, PI-specific lifecycle). I
exposed both: `status` for the basic voucher state machine, and
`lifecycle_status` for the PARTIALLY_PAID / OVERDUE / etc. richer state
that lands when payments allocate (TASK-052). My service writes to both
columns in lockstep.

### 2. Permission catalog grew by 2 codes

Added `purchase.invoice.create` and `purchase.invoice.void` —
`purchase.invoice.post` and `read` already existed. Owner gets all (auto
via `_ALL_PERMS`). Accountant doesn't get `void` (administrative —
Owner only).

### 3. GL voucher autoposting deferred to TASK-041

The spec called for `post_pi` to "create a GL voucher (Debit Inventory,
Credit AP)". That's TASK-041's domain (voucher_service + auto-posting
rules). For now, `post_pi` only advances state; when TASK-041 lands,
it'll register a posting hook on the PI status transition.

## Things the plan got right

- `voucher_status` enum already in DDL; reused without schema work.
- `purchase_invoice` table had all the columns needed (invoice_amount,
  gst_amount, rcm_applicable, grn_id, due_date, paid_amount, etc.).
- The TASK-027/028 patterns (gapless serial, sync Session, kw-only,
  state-machine methods, soft-delete strict allow-list) ported cleanly.
- 3-way match scope decision (loose, log-but-don't-block) matches Moiz's
  flexibility requirement and avoids over-engineering for MVP.

## Pre-TASK-030 checklist

### 1. TASK-030 (Supplier Ledger) — depends on TASK-029

Reads PIs + Payments and produces a per-supplier statement (opening
balance, PI debits, payment credits, closing balance). TASK-051
(Payment voucher) blocks the credit side; if TASK-030 starts before
TASK-051, scope it to "PI-only ledger view" and add payments later.

### 2. TASK-041 voucher autoposting picks up the post_pi hook

When PI is POSTED, voucher_service should auto-post:
- `Debit Inventory @ invoice_amount + gst_amount`
- `Credit AP (party-specific sub-ledger) @ same`
- `Debit GST Input @ gst_amount` (if rcm_applicable=False)
- `Credit RCM Liability @ gst_amount` (if rcm_applicable=True; TASK-050)

Add a service hook in `procurement_service.post_pi` that calls
`voucher_service.autopost_pi(pi)` once that exists.

## Open flags

- **Concurrency on `_allocate_pi_number`** — same first-row race as PO
  / GRN. Wave-4 stress test follow-up.
- **`match_result` audit trail** — `match_result` is JSONB; not
  versioned. If multiple post attempts modify it (re-post after un-void),
  history is lost. Acceptable for MVP since `void_pi` lands you in a
  terminal state.
- **`due_date` not enforced** — passed through but no scheduled
  `OVERDUE` transition. The DDL has `lifecycle_status` for OVERDUE; a
  Celery task in TASK-066+ would set it.

## Observable state at end of task

- Modified: `app/models/procurement.py` (+ `PurchaseInvoice`, `PILine`,
  `VoucherStatus`, `PurchaseInvoiceLifecycleStatus`)
- Modified: `app/service/procurement_service.py` (+6 PI funcs + helpers)
- Modified: `app/schemas/procurement.py` (+4 PI schemas)
- Modified: `app/routers/procurement.py` (+6 PI endpoints under `/purchase-invoices`)
- Modified: `app/service/rbac_service.py` (+`purchase.invoice.create` and `+void`)
- Modified: `main.py` (+pi_router)
- Modified: `app/models/__init__.py` re-exports
- New tests: `tests/test_pi_service.py` (28), `tests/test_pi_routers.py` (11)
