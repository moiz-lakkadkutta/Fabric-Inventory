# Batch retro (2026-10-10): #209 + DEBT-02, #215, #216, DEBT-03, DEBT-04, TASK-TR-Q01

**Date:** 2026-10-10
**Branch:** `fixes-2026-10-10` (integration). DEBT-04 is on its own branch, `fix/debt-04`.
**Commit:** integration head `196fe15` (not merged to main; **PENDING MOIZ SIGN-OFF**, several items +CA)
**Plan:** orchestrated with the `multi-agent-fix-pipeline` skill: waved worktrees, per-agent test DBs, an Opus TDD implementer and a fresh adversarial verifier (theater check) per item.

## Summary

Every item was implemented test-first and passed a fresh verifier with a theater check: the new tests fail with the source reverted and pass with it restored. Each passed as PASS or PASS-WITH-CONCERNS, and every blocking concern was fixed and re-verified. The final integration head was verified on a **fresh** clone of `test_template` plus migration 210, with real Redis:
- backend **2079 passed / 8 xfailed / 0 failed** (the 8 are Q01 P2/P3 reproductions still open);
- whole-tree `ruff check`, `ruff format --check` and `mypy .` clean;
- `alembic heads` = one (`210_firm_scope_rls`), round-trip OK, `test_migration_smoke` + `test_orm_ddl_drift` green;
- frontend `tsc` clean, vitest 576/576;
- OpenAPI snapshot shows no drift.

Not done: no E2E stack run (CI will run it). No push or PR: GitHub publishing was denied in this session.

| Item | Result | Gate |
|---|---|---|
| DEBT-02 + #209 | `delivery_challan_id` on invoice create (API + UI "Create invoice" from a DC); DC row lock + partial unique index (migration `209_dc_invoice_link`); one invoice ↔ one DC; line-match rule | Moiz (COGS + schema); +CA for cancel-of-DC-invoice |
| Draft discard (follow-on) | `POST /invoices/{id}/discard`, DRAFT/CONFIRMED → DISCARDED, releases the DC | Moiz+CA (numbering gap) |
| #216 items 1-2 | Credit-note series `CN/<FY>/NNNN` (IST FY, gapless, per firm); Rule 53(1A) credit-note PDF; internal `CXL/<FY>` series for same-month cancels, non-GST, branch transfers and duplicate reversals | Moiz+CA |
| GSTR-1 symmetry (follow-on) | One `is_gstr1_reportable_supply` predicate for the invoice and CDN sides; branch transfers and Bills of Supply out of GSTR-1; pre-#215 ₹0 fallback reported at ₹0 | Moiz+CA |
| #215 | GSTIN state-code prefix validation (01–38, 97) with normalization; 422 on create/finalize for a GSTIN buyer resolving to ₹0 outside a branch transfer; detection SQL + script | Moiz+CA |
| DEBT-03 | `auth.forgot` limit settings-driven, with non-dev boot refusal | Moiz (auth) |
| DEBT-04 | Root cause: StrictMode double `/auth/refresh` revoked the session. Single-flight bootstrap; Playwright/CI fail-fast + log artifacts | Separate PR; merge on green |
| Q01 review | `docs/reviews/security/q01-security-review.md` + matrices + xfail repros: 0 P0 / 2 P1 / 4 P2 / 7 P3 | — |
| Q01-01/04/11 | Idempotency: SET-NX in-flight lock (409 + FE auto-retry), cache scoped to org+user+method, secrets never cached, commit before response | Moiz (security) |
| Q01-02 | Firm-level authz: firm check inside `require_permission` + RESTRICTIVE firm RLS on 60 tables (migration `210_firm_scope_rls`), fail-closed GUC; route-matrix regression test | Moiz (security + schema) |

## Deviations from plan

### 1. Cancelling a DC-linked invoice is now allowed (was a 409)
"Cancel, then the DC can be re-invoiced" required it. Cancel reverses revenue + COGS but restores no stock, because the goods left with the DC; the verifier proved GL and stock conservation.
- **Impact:** CA question on a §34 note with no goods returned. Sales returns (D01–D04) are still unbuilt, so returned goods have no path.

### 2. Invoice numbers are allocated at DRAFT time, contrary to `specs/invoice-lifecycle.md`
Discard keeps the row and its number, so the series shows the voided number rather than a silent gap.
- **Impact:** Moiz/CA decision: move allocation to finalize? This affects GSTR-1 Table 13 when it's built.

### 3. CXL series goes beyond the locked "one CN series per firm"
A same-month cancel is a true cancellation, with no §34 note. Giving it a CN number would leave gaps in the series GSTR-1 reports. Internal `CXL/<FY>` keeps CN gapless.

### 4. #216's §34 predicate made GSTR-1 asymmetric for branch transfers
The invoice side still reported them, so a later-month cancel was never reversed. Fixed by the GSTR-1 symmetry follow-on. #216 and that fix **must ship together.**

### 5. Q01 fixes went beyond P1
Q01-04 and Q01-11 (both P2) were fixed with Q01-01 because they're the same code path and the same correctness problem.

### 6. Q01-02 implemented as DB-layer RLS, not only app checks
The 91 by-id routes needed a can't-forget chokepoint. The verifier proved the RLS, not the app layer, protects by-id routes.

## Things the plan got right (no deviation)
- Wave order by function-conflict (DEBT-02 before #215 on `create_draft_invoice`). The conflicts that did occur were additive and resolved mechanically.
- Verifying the *merged* candidate for Q01-02, not the branch alone. That caught that the new discard route needed coverage, and it was covered.
- Fresh-DB full runs in verification. They caught a CI-only break (Q01-02 B1) that pre-populated DBs had hidden.

## Pre-next checklist

### 1. Get Moiz/CA sign-off, then push
Push `fixes-2026-10-10` and `fix/debt-04` and open PRs; the PR text is in the session scratchpad. Expect first-push CI to exercise E2E for the first time with DEBT-04's fail-fast settings.

### 2. Deploy order for migration 210
App and schema ship together. Rolling the app back without `alembic downgrade` fails closed: users see no firm data.

### 3. Data checks before trial
- `schema/patches/detect-215-invalid-gstin-prefix.sql` and `backend/scripts/detect_invalid_gstin_prefix.py`: parties and invoices hit by #215.
- `docs/retros/task-097.md`: OB double-booking detection.

## Open flags carried over
- **CA (#217):**
  - §34 note for cancel of a DC-linked invoice;
  - CXL series;
  - numbering at draft;
  - #215 prefix rules;
  - branch transfers absent from all GSTR-1 tables (Table 8?);
  - pre-registration Bills of Supply;
  - Cash Memo / Estimate exclusion;
  - pre-#215 ₹0 fallback reported at a 5% rate with ₹0 tax, firm state as PoS (amend instead?).
- **Moiz:**
  - discard gated on `sales.invoice.cancel` (salespeople can't discard; the button still shows);
  - Q01-02 L2 (idempotency replay ≤15 min after revocation), L3 (org-shared masters editable by firm-scoped users), L4 (FE invites always org-wide);
  - Q01-04 limitation (replay skips suspended/permissions-version checks);
  - backend refresh-rotation race (two tabs can log one out; the DEBT-04 follow-up);
  - non-GST firm pre-#194 invoices could still take a CN number.
- **Remaining Q01 findings:**
  - P2: Q01-03 (MFA not mandatory for Owner), Q01-05 (demote an Owner);
  - P3: Q01-06…Q01-10, Q01-12, Q01-13.
  - All are in the review doc; xfail reproductions are in `backend/tests/security/`.
- **Follow-ups:**
  - consolidated / partial DC billing;
  - purchase-side void numbering + debit note (#216 report);
  - GST firm with no state → ₹0 B2C;
  - GSTIN checksum not validated;
  - #216 items 3 (SEZ in B2B/CDNR, waiting on #217) and 4 (snapshot buyer GSTIN at finalize);
  - M2 matcher is English-text based (`app/middleware/errors.py:188`);
  - the matrix walk lacks a missing-Content-Type variant.

## Observable state at end of task
- **Local Redis:** none. HTTP tests need a real Redis (the idempotency middleware connects for real), so run `docker run -d --rm -p 63xx:6379 redis:7` and point `REDIS_URL` at it. conftest's default `localhost:6379` has nothing listening on this machine.
- **`test_template`** is migrated to `210_firm_scope_rls`. `test_integ` is a scratch DB.
- **Worktrees:** `~/fabric-worktrees/integ` (`fixes-2026-10-10`) and `~/fabric-worktrees/debt-04`.
- **Verifier probe scripts** are in the session scratchpad only; nothing is committed.
