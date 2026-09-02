# TASK-190 retro — concurrency: state-check-then-write double-posting

**Date:** 2026-09-02
**Branch:** fix/issue-190
**Commit:** `<sha>` (NOT merged — PENDING MOIZ SIGN-OFF)
**Plan:** GitHub issue #190 comment (implementation plan)

## Summary

Fixed the state-check-then-write race that let two overlapping transactions
both observe an aggregate's pre-state and each post GL / stock / AR, across all
four cited loci: sales invoice finalize, GRN receive, receipt FIFO allocation,
and the latent payment (AP) FIFO allocation. The fix is one coherent strategy —
`SELECT ... FOR UPDATE` on the aggregate row with a re-check of state under the
lock, plus a partial-unique index on `voucher(org_id, voucher_type,
reference_type, reference_id) WHERE deleted_at IS NULL AND reference_id IS NOT
NULL AND voucher_type IN ('SALES_INVOICE','COGS_SALE')` as a DB backstop, whose
`IntegrityError` is translated to `InvoiceStateError` (409) mirroring the JV
voucher-number-race pattern. Real-threading tests prove exactly-one-posting for
finalize (n=2, n=3), 8-way GRN receive, and 2-way full receipts; each was
verified to FAIL on the unfixed code (index dropped + fix stashed) — the receipt
test reproduced the exact ₹20000-vs-₹10000 over-allocation from the issue.
Lint (ruff check + format), types (mypy), and the broad affected suite (155
tests across sales/procurement/receipt/payment/JV/idempotency/PI) all pass.
Migration round-trips cleanly (index absent after downgrade, present after
upgrade). NOT merged: gated on Moiz for the schema index, the GL loser-outcome
change (200→409), and the destructive data repair.

## Deviations from plan

### 1. Migration file naming + pre-flight query execution
Plan said `make migrate-create` with name `190_voucher_posting_unique`. Reality:
this repo names migration files with a date-serial prefix and a slug revision id
(e.g. `2026070500002_f2_ap_payment_schema.py`), so I hand-wrote
`alembic/versions/2026090200001_190_voucher_posting_unique.py` (revision
`190_voucher_posting_unique`, down_revision `f2_ap_payment_schema` = current
head). The pre-flight duplicate-detection query needed `conn.execute(sa.text(...))`,
not `exec_driver_sql` (the latter raised `immutabledict is not a sequence` under
the psycopg2 sync driver alembic uses).
- **Why not caught in planning:** the plan assumed autogen naming and a driver
  detail not exercised until run.
- **Impact on later tasks:** none.

### 2. Test teardown could not rely on ON DELETE CASCADE
Plan's test skeleton implied deleting the org would cascade. Reality: no schema
carries an org-level ON DELETE CASCADE (`firm_org_id_fkey` blocked the delete).
`_drop_org` now runs as the superuser with `session_replication_role = replica`
(FK enforcement off) and sweeps every table with an `org_id` column, then the
organization row.
- **Why not caught in planning:** the QA cookbook `DELETE FROM organization
  WHERE name LIKE 'QA %'` was assumed to cascade; it does not in this schema.
- **Impact on later tasks:** reusable committed-fixture teardown pattern for
  future concurrency tests.

## Things the plan got right (no deviation)

- Root cause + all four loci exactly as described; the JV pattern
  (`_allocate_voucher_number` firm-row lock + IntegrityError→clean-error) was the
  correct in-repo reference to copy.
- Index predicate correctly EXCLUDES PURCHASE_INVOICE — PI void posts a second
  voucher with the same reference_id and must stay insertable (guarded by
  `test_pi_service.py::test_void_pi_reversal_not_blocked_by_190_posting_index`).
- Receipt loser semantics: second full receipt books surplus to Customer
  Advances (2500), both receipts return 200; only the allocation is once.
- `get_sales_invoice` / `get_grn` left lock-free (GET/PDF paths); locked reads
  inlined only in the mutating service methods.

## Open flags carried over

- **DATA REPAIR IS NOT DONE (ops step).** Corrupt demo/QA rows still exist in the
  live local `fabric_erp` DB (6 dup GL groups, 3 doubled GRNs, 6 over-allocated
  invoices per the issue). The migration's pre-flight guard will REFUSE to apply
  on `fabric_erp` until they are cleaned. Repair SQL is documented at
  `schema/patches/190-dedupe-postings.sql` (fallback) with the recommended path
  being QA-org wipe + Demo Co re-seed. Requires Moiz approval before running.
- **Ask-vs-Decide gate:** schema index + GL loser-outcome change (200→409) +
  destructive repair all need Moiz sign-off before merge.

## Observable state at end of task

- New migration head on this branch: `190_voucher_posting_unique`. Test DB
  `test_190` is migrated to it.
- No OpenAPI change (409 already documented for finalize; no new endpoints).
- Untracked-but-committed artifact: `schema/patches/190-dedupe-postings.sql` is an
  ops script, not run by any code.
