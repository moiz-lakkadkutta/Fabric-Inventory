# TASK-097 retro — bank opening balance: unbalanced TB (#97) + double-booked opening balance

**Date:** 2026-09-27
**Branch:** task/097-bank-ob-regression
**Commit:** (filled at merge)

## Summary

Issue #97 (filed 2026-05-12) reported that a bank account created with an opening balance posted a one-sided Dr Bank, leaving the Trial Balance unbalanced by the opening amount. **That bug was already fixed on `main`** by #180 (Security Wave E3, 2026-06-28). Both `create_ledger` and `create_bank_account` now post a balanced JV against 3200 Opening Balance Difference. The issue was never closed.

Replaying the issue's exact UI flow as an API test turned up a **second, silent bug in the same flow.** The "New bank account" dialog sends the opening balance twice: `opening_balance` on `POST /ledgers` and `balance` on `POST /bank-accounts`. Each call booked its own opening JV. The result was that a ₹10,000 opening balance showed as **₹20,000** in the bank ledger, with 3200 credited ₹20,000, while `bank_account.balance` said ₹10,000. The TB still balanced, so no report flagged it.

**Fix** (`banking_service.create_bank_account`): the opening JV is booked only when the linked ledger has no GL balance yet.
- A balance equal to the ledger's existing balance (the dialog's case) is accepted without posting again.
- A conflicting balance is refused with an actionable 422, not silently booked as an adjustment.
- The ledger's balance is computed exactly as the TB computes it: row `opening_balance` plus POSTED, non-deleted voucher lines.

Verification: 3 new API-level tests in `tests/test_bank_opening_balance_97.py`. The double-booking and conflict tests failed before the fix (₹20,000 ≠ ₹10,000; 201 ≠ 422); the TB-balanced test passes both before and after, confirming #97 itself was already fixed. Affected suites, full-tree ruff/format/mypy and CI: see the PR.

## Deviations from plan

### 1. The reported bug was already fixed; a different one was live
The plan was to fix the unbalanced TB. It was already fixed by #180.
- **Fixed by:** a regression test for the original report, plus the double-booking fix above.
- **Why not caught earlier:** #180's tests exercised `create_ledger` and `create_bank_account` separately, and each is correct in isolation. Only the dialog's two-call sequence double-books.
- **Impact on later tasks:** API-level tests that replay the frontend's real call sequence catch integration bugs that per-service tests miss. Reuse the pattern in `tests/test_bank_opening_balance_97.py`.

### 2. Write-time balance invariant: already in place, not centralised
#97 also asked for vouchers to be refused at write time when unbalanced. Every voucher-writing path already asserts DR == CR before commit:
- `accounting_service` (all posting functions)
- `stock_service`, `payment_service`, `receipt_service`, `material_issue_service`, `bank_reconciliation_service`, `mo_completion_service`, `migration_service`

There is no single central check (e.g. a deferred DB constraint trigger), so a new service that builds `Voucher` rows directly could forget it. That is a schema change (trigger), which needs Moiz; it is flagged below, not built.

## Open flags carried over

- **Central balance guard (schema, Moiz):** a `DEFERRABLE INITIALLY DEFERRED` constraint trigger on `voucher_line` that checks each voucher sums to zero at commit. It is defence in depth for future posting code.
- **`balance` omitted while the ledger has a balance:** `bank_account.balance` stays NULL while the GL carries the ledger's opening balance, so the S1 "column in lockstep with GL" invariant isn't enforced on that path. Consider defaulting the column to the ledger balance.
- **Existing data:** accounts created through the dialog with an opening balance before this fix have their bank ledger and 3200 overstated by the opening amount. This read-only query lists them:

```sql
SELECT ba.bank_account_id, ba.bank_name, ba.balance AS account_balance, l.code,
       SUM(CASE WHEN vl.line_type = 'DR' THEN vl.amount ELSE -vl.amount END) AS gl_balance
FROM bank_account ba
JOIN ledger l ON l.ledger_id = ba.ledger_id
JOIN voucher_line vl ON vl.ledger_id = ba.ledger_id
JOIN voucher v ON v.voucher_id = vl.voucher_id
WHERE ba.deleted_at IS NULL AND v.deleted_at IS NULL AND v.status = 'POSTED'
GROUP BY ba.bank_account_id, ba.bank_name, ba.balance, l.code
HAVING ba.balance IS NOT NULL
   AND SUM(CASE WHEN vl.line_type = 'DR' THEN vl.amount ELSE -vl.amount END) <> ba.balance;
```

  Repair means soft-deleting the duplicate "Bank balance adjustment" JV per account. That is an ops step, run only with Moiz's approval. The dev DB was wiped and re-seeded on 2026-09-26 and Demo Co has no bank accounts, so dev is unaffected.

## Observable state at end of task

- The API tests need Redis on `localhost:6379` (signup rate limiter). `docker compose up -d redis` starts only Redis.
- `localhost:5432` is the Homebrew Postgres 14, not the Docker one (see the 2026-09-26 session notes); test DBs live there.
