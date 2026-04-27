# TASK-053 retro — deviations from plan and pre-next checklist

**Date:** 2026-04-27
**Branch:** task/053-bank-accounts
**Plan:** TASK-053 spec in TASKS.md + implementation brief from session prompt

## Summary

Shipped `BankAccount` + `Cheque` ORM models, service (CRUD for BankAccount; create+list for Cheque), Pydantic schemas, and a FastAPI router under `/bank-accounts` and `/cheques`. Added `banking.bank.{create,read,update}` permissions to the RBAC catalog; Owner gets all three, Accountant gets read+create. All 304 tests pass (21 new), ruff/format/mypy clean.

## Deviations from plan

### 1. Audit-sweep adds columns not in the DDL CREATE TABLE

Plan expected `bank_account` and `cheque` to only have `created_at`/`updated_at` (as declared in the DDL `CREATE TABLE`). Reality: the DDL audit-sweep DO block adds `deleted_at`, `created_by`, `updated_by` to ALL non-exempt tables — including `bank_account` and `cheque`. The ORM drift gate (`test_orm_ddl_drift.py`) caught this immediately.

- **Fixed by:** Added `AuditByMixin` + `SoftDeleteMixin` to both `BankAccount` and `Cheque` in `backend/app/models/banking.py`. `TimestampMixin` was intentionally NOT used because `created_at`/`updated_at` are already in the DDL CREATE TABLE (audit-sweep skips them if they exist).
- **Why not caught in planning:** The brief mentioned checking the drift gate but didn't pre-read the audit-sweep's exempt table list.
- **Impact on later tasks:** None — columns now match.

### 2. `voucher_id` FK to unmodeled `voucher` table causes NoReferencedTableError

`cheque.voucher_id` has a DB-level FK to `voucher.voucher_id`. Declaring it as `ForeignKey("voucher.voucher_id", ...)` in the ORM raised `NoReferencedTableError` at test startup because `voucher` is not yet modeled.

- **Fixed by:** Dropped the ORM-level FK, keeping only the UUID column — same pattern as `firm.primary_godown_id` in `identity.py`. DB-level constraint still enforced.
- **Why not caught in planning:** Pattern was established by an earlier task but not highlighted in the brief.
- **Impact on later tasks:** TASK-055 (Voucher model) will need to model `voucher` and may optionally re-add the ORM-level FK at that point.

### 3. `soft_delete_bank_account` raises rather than deletes

`bank_account` now has `deleted_at` (added by audit-sweep), so soft-delete IS technically possible. The service raises `AppValidationError` instead to block accidental deletion until the business flow is designed (TASK-056 cheque clear/bounce flow).

- **Fixed by:** Documented in service docstring. The router endpoint exists (DELETE 204) but always returns 422.
- **Why not caught in planning:** The audit-sweep adding `deleted_at` was discovered during implementation.
- **Impact on later tasks:** TASK-056 can either (a) enable soft-delete by removing the guard, or (b) keep the guard and route deactivation through a different mechanism.

### 4. `_make_firm_and_ledger` in service tests needed ORM model objects, not raw SQL

The initial `_make_firm_and_ledger` helper used raw `INSERT INTO firm ... registered_address ...` SQL which failed because `registered_address` is not a `firm` column. Other test files use `Firm(org_id=..., code=..., name=..., has_gst=...)` via the ORM.

- **Fixed by:** Rewrote helper to use `Firm`, `CoaGroup`, `Ledger` ORM models directly.
- **Why not caught in planning:** Wrote raw SQL without checking existing patterns in the test suite.
- **Impact on later tasks:** Zero — the helper is local to `test_banking_service.py`.

## Things the plan got right (no deviation)

- PII encryption via `encrypt_pii`/`decrypt_pii` stubs worked first time.
- Cross-org defense-in-depth: `org_id` filter on every service func + explicit cross-org checks in `create_cheque`.
- Permission gate pattern (same as Party router) worked without issues.
- Idempotency-Key header accepted on all mutating endpoints.
- `ChequeStatus` enum declared with `create_type=False` (DDL owns DDL).

## Pre-TASK-054 checklist

### 1. Verify TASK-056 picks up the soft-delete guard decision

`soft_delete_bank_account` always raises. TASK-056 (cheque clear/bounce) should decide whether to enable it or route deactivation differently.

### 2. rbac_service.py merge conflict risk

`_SYSTEM_PERMISSIONS` and `_SYSTEM_ROLES` are hot spots. Any parallel branch that adds new permissions will conflict here.

### 3. `voucher` FK will need ORM modeling in TASK-055

When `voucher` ships as an ORM model, re-evaluate whether to add `ForeignKey("voucher.voucher_id", ondelete="SET NULL")` back to `Cheque.voucher_id`.

## Open flags carried over

- `soft_delete_bank_account` guard (surfaces in TASK-056).
- `voucher_id` FK without ORM relationship (surfaces in TASK-055).
- No PATCH `/cheques/{id}` endpoint — cheque status transitions land in TASK-056.

## Observable state at end of task

- 304 tests pass, 133 skipped (skipped = no Postgres in that test runner).
- New endpoints: `POST /bank-accounts`, `GET /bank-accounts`, `GET /bank-accounts/{id}`, `PATCH /bank-accounts/{id}`, `DELETE /bank-accounts/{id}` (always 422), `POST /cheques`, `GET /cheques`.
- New permissions seeded at org signup: `banking.bank.create`, `banking.bank.read`, `banking.bank.update`.
