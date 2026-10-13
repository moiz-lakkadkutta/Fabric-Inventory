# Follow-up batch 2026-10-12 retro: remaining Q01 findings, two-tab refresh race, cleanups

**Date:** 2026-10-13
**Branch:** `fixes-2026-10-12` (stacked on `fixes-2026-10-10` / PR #223)
**Commit:** `dcbac78` (HOLD, not on `main`; pending Moiz sign-off, CA for the GSTIN/firm-state items)
**Plan:** follow-ups from `docs/retros/task-batch-2026-10-10.md` and `docs/reviews/security/q01-security-review.md`

## Summary

Five work items, each built in its own worktree by a TDD implementer, checked by a fresh adversarial verifier (with a theater check: revert the source, the new tests must fail), and merged into `fixes-2026-10-12` only after a PASS:

| Item | Findings | Migration |
|---|---|---|
| Spec parity | Q01-12: `specs/api-phase1.yaml` matches all 179 operations + enforced `x-permission`; `scripts/spec_sync.py`; parity guard test; `api-phase3.yaml` fixed + marked design-only | none |
| DB hardening | Q01-06/07/09: RLS on `hsn`/`uom`; non-raising GUC policies + upgrade guard; `alembic_version` write revokes; `public` CREATE revoked from PUBLIC; seed CLI pins the org GUC | `211_db_hardening` |
| RBAC | Q01-05/08/13: outrank rule on re-role / role edit / role delete; per-org owner-guard advisory lock (no zero-Owner race); deleted roles grant nothing; `GET /admin/roles` → `identity.role.read`; receipts/payments → `accounting.voucher.*` (`bed8334`, separable) | `211_rbac_followups` (data only) |
| Cleanups | RLS refusal → 403 by SQLSTATE 42501 + source function; GST firm with no state → 422; GSTIN mod-36 check digit (BE + Vyapar import + FE hint); self-contained RLS sweeps; no-Content-Type matrix variant | none |
| Auth | Q01-03: mandatory admin MFA (enrolment-only token, backup codes, `scripts.reset_mfa` + runbook). Q01-10 + two-tab race: refresh rotation with a per-family advisory mutex, 20 s grace re-issue (peppered envelope, wiped), reuse detection revokes the family, scoped auth lock timeout → 503, FE retries once | `211_refresh_rotation` |

Migrations are linear: `210_firm_scope_rls → 211_db_hardening → 211_rbac_followups → 211_refresh_rotation` (single head).

**Integration gate on `dcbac78`** (fresh DB from `test_template`, real Redis):
- `alembic upgrade head`: three upgrades applied, single head; `spec_sync`: 0 problems; `make openapi-snapshot`: no drift.
- Frontend: tsc OK, lint OK, vitest 598/598.
- Backend: ruff, ruff format (338 files) and mypy are clean on the whole tree.
- Full pytest: **2241 passed**, 0 xfailed. The batch-1 baseline was 2079 passed + 8 xfailed. Every Q01 `xfail(strict=True)` reproduction is now a plain pass.
- Destructive `test_migration_smoke` + `test_orm_ddl_drift`: 2/2.

## Deviations from plan

### 1. Auth took four verifier rounds
Round 1 failed: the rotation had a lock-order deadlock between rotate and revoke. Round 2 failed: backup codes were not single-use under concurrency, and there was no audit row for a failed MFA. Round 3 passed with concerns: a TOTP login racing an MFA reset could survive the reset. Round 4 (`9646d5d`) closed that, and a verbatim theater check proved it: with the fix removed, the racing login gets a working token back.
- **Why not caught in planning:** the family mutex design only emerged after round 1. A row lock alone could not order the rotate and revoke paths.
- **Impact on later tasks:** any new path that mints or revokes refresh tokens must take `session_family:<id>` via `pg_advisory_xact_lock` first.

### 2. The RBAC race tests did not exercise the lock at first
The same-role demotion races passed even with the advisory lock removed: the row lock alone serialised them. Different-role variants were added (`9e8ba77`) and proven to fail without the lock.

### 3. Three migrations had to be linearised at merge
Each worktree branched from `210_firm_scope_rls`, so each merge re-pointed `down_revision`. Two worktrees edited the spec in parallel; the conflicts in `/auth/refresh` and `/auth/logout` were resolved by keeping both the auth 503 responses and the corrected `x-permission`.

### 4. The firm-state 422 message named a screen that doesn't exist
It was reworded to point at the Fabric administrator: there is no firm settings screen or endpoint yet.

## Pre-merge checklist (for Moiz)

1. Sign off #223 first: this branch is stacked on it. Then retarget this PR to `main`.
2. **Before deploying**, deploy migrations 210 + 211 ×3 together with the app. Firm-scope RLS fails closed, and admin MFA is enforced immediately, including for Moiz's own session. Enrol first, or set `MFA_REQUIRED_FOR_ADMIN=false` for the first deploy.
3. Decide on `bed8334`: keep or drop the receipts/payments permission widening. Drop it with `git revert` if not wanted.

## Open flags carried over

- **MFA:**
  - Admin-class permission set: add `admin.migrations.approve`?
  - First-enrolment risk: whoever logs in first enrols.
  - No grace period.
  - No in-app backup-code regeneration.
  - No QR code.
  - The reset CLI's identity check is manual.
- **Lock timeouts:** `AUTH_LOCK_TIMEOUT_MS` = 5 s and the 20 s refresh grace need sign-off. The audit org lock behind long imports is still unbounded (pre-existing).
- **Missing permission codes:** delete/cancel codes, `inventory.location.create`, `jobwork.order.receive`, `sales.invoice.delete`. `GET /admin/users` → `identity.user.read`?
- **Firm state:** no firm settings screen or endpoint. Derive the firm state from its GSTIN?
- **GSTIN at signup:** the firm GSTIN is not validated at signup.
- **Legacy GSTINs:** GSTINs with a bad check digit stay until edited.
- **Spec and error handling:**
  - A missing GRANT still surfaces as a 500.
  - The documented 422 error shape is wrong across the spec.
- **Migrations:** the `public` CREATE revoke is not re-granted on downgrade (deliberate).
- **Out of scope:**
  - purchase-side void numbering + debit note;
  - #216 items 3–4;
  - consolidated/partial DC billing;
  - the FE invite dialog is always org-wide;
  - `migrations.upload_migration` / `approve_migration` are async routes doing sync DB work.

## Observable state at end of task

- Docker Desktop was down for the gate. HTTP tests used a standalone `redis-server` binary instead of the usual container.
- `test_template` is still at `210_firm_scope_rls`. Bump it to `211_refresh_rotation` after merge.
