# TASK-INT-16 retro — runtime fabric_app cutover + doctor alembic fix

**Date:** 2026-05-07
**Branch:** `task/INT-16-fabric-app-runtime-cutover`
**Plan:** in-conversation — flip runtime DATABASE_URL to fabric_app and
fix the ~43 fixture migrations that surfaced.

## Summary

INT-9 created the `fabric_app` role (NOBYPASSRLS) and rewrote every RLS
policy to enforce `org_id = NULLIF(current_setting('app.current_org_id'),
'')::uuid`. But the runtime DATABASE_URL still pointed at `fabric` (the
superuser), which bypasses RLS unconditionally — making the entire RLS
layer theatre at runtime. INT-16 closes that gap.

Three deliverables:

1. **Runtime cutover**: `backend/.env.example`, `backend/.env`,
   `docker-compose.yml`, and `.github/workflows/ci.yml` now connect as
   `fabric_app:fabric_app_dev`. `MIGRATION_DATABASE_URL` stays as the
   superuser so alembic can `ALTER TABLE`/`GRANT`. CI uses
   `postgres:postgres` for migrations and `fabric_app:fabric_app_dev`
   for the test runtime.

2. **Test fixture migrations** (the real work): 11 files updated.
   Categories of fixes:
   - **`expire_on_commit=False`** on test seed sessions so the
     post-commit ORM refresh doesn't re-query without the GUC and
     surface as `ObjectDeletedError` (sales seeders, receipt seeders,
     stock seeders, switch_firm sibling-firm seeder).
   - **Set GUC before INSERT** under fabric_app's WITH CHECK clauses
     (feature_flag seeder, switch_firm cross-org seeder).
   - **Set GUC before SELECT** when reading audit_log /
     session / role rows after API calls (auth logout test, switch_firm
     audit test, dependencies snapshot test, sales create-audit test).
   - **Pass org_id explicitly** to helpers like `_enable_mfa_for` so
     they can SET GUC before SELECTing the user row.
   - **Switch RLS isolation tests to `admin_engine`** — they need
     `ALTER TABLE FORCE RLS` and `CREATE ROLE`, which fabric_app can't
     do (party + item RLS isolation tests).
   - **Migration / DDL tests use MIGRATION_DATABASE_URL** so alembic
     upgrade and `DROP SCHEMA` succeed (migration smoke + ORM DDL drift).

3. **`admin_engine` + `org_scoped_session` helpers in conftest**:
   - `admin_engine` fixture uses MIGRATION_DATABASE_URL for cross-tenant
     fixtures + DDL operations, with the same skip/fail-loud semantics
     as `sync_engine`.
   - `org_scoped_session` context manager: yields an ORM session
     pre-set with `app.current_org_id` and `expire_on_commit=False`,
     centralising the post-commit-GUC dance for any future test.

4. **Drive-by: `make doctor` alembic check** — the doctor script invoked
   `cd backend && uv run alembic current` from a fresh shell that hadn't
   sourced `backend/.env`, so alembic couldn't find DATABASE_URL and
   silently returned empty. The head-mismatch branch never fired. Fixed
   by sourcing `.env` inside the subshell that runs alembic, without
   leaking those vars into the parent doctor shell.

619 backend tests pass under the new fabric_app DATABASE_URL. ruff +
mypy clean.

## Things the plan got right (no deviation)

- **Two-URL split** (DATABASE_URL = fabric_app, MIGRATION_DATABASE_URL =
  superuser): exactly the model alembic env.py already supported as a
  fallback. No env.py change needed.
- **`admin_engine` as a sibling fixture** rather than a tag/marker on
  individual tests: tests that need DDL just declare it and get the
  superuser engine, no per-call boilerplate.
- **Migration smoke + DDL drift switched to MIGRATION_DATABASE_URL**:
  these were always implicitly admin-only — they DROP SCHEMA + run
  alembic upgrade. Pinning them explicitly makes the privilege boundary
  visible.

## Things that surprised me (and the fix)

- **`SET LOCAL app.current_org_id` is dropped on commit**, so any
  post-commit ORM attribute access auto-refreshes against an empty
  GUC and fails with `ObjectDeletedError`. The fix is
  `expire_on_commit=False` on the test session, not re-setting the
  GUC after every commit. `SET` (session-scoped, no LOCAL) would also
  work but pollutes the connection if it gets reused.
- **fabric_app can't `ALTER TABLE`** even on tables it has CRUD on —
  that's an owner-only privilege. Tests that need `FORCE ROW LEVEL
  SECURITY` had to migrate from sync_engine → admin_engine. Caught
  immediately with a useful "must be owner of table party" error.
- **`make doctor` alembic check was silently failing** before INT-16.
  This was always a bug — the validation report flagged the `cd`
  pattern but the actual root cause was the missing `.env` source.
  Fixed in this branch as a drive-by since INT-16 was already touching
  doctor's surrounding context.

## Deliberate non-goals (NOT done in this branch)

- **Refactor every "post-API DB inspection" test** — only the ones that
  actually broke. Some tests don't read after the API call so they
  don't need GUC. Adding it preemptively would be cargo-culting.
- **Drop the superuser fallback in conftest's `admin_engine`** — local
  single-role setups still work via the DATABASE_URL fallback. We can
  tighten this later when CI definitely has both URLs and dev docs are
  updated.
- **`api_idempotency` and other audit-style tables** — these are
  org-scoped via RLS, but nothing in this branch uncovered a fixture
  that breaks under fabric_app. If something surfaces in INT-13/14,
  fix it then with the same playbook.

## Pre-INT-13 / next-task checklist

### 1. CA call still gates INT-13 / INT-14

Per INT-12 retro and confirmed today: GL split (INT-13) and Bill of
Supply trigger (INT-14) both need CA validation before they land. The
`# CA-VALIDATED-PENDING: 2026-05-06` marker in `gst_service.py` is the
breadcrumb. INT-15 + INT-16 were sequenced first because they had no
external blockers.

### 2. Verify production cutover after merge

In production:
- `backend/.env` should already use `fabric_app:fabric_app_dev` for
  DATABASE_URL.
- A `psql ... -c "SELECT current_user"` against the running app's
  connection should return `fabric_app`, not `fabric`.
- An RLS test in prod (e.g. trying to bypass via direct DB query)
  should fail — RLS is now actually enforced.

### 3. The `make doctor` alembic check actually works now

Test it locally: `make doctor` (or `bash scripts/doctor.sh`). The
`alembic at head (...)` line should appear. Pre-INT-16 it was an
empty/yellow warning every time.

## Open flags carried over

- **TASK-INT-13 / INT-14**: required before any composition firm
  onboards or before the first GSTR-3B filing. Both still gated on
  the CA call.
- **Test conftest still uses `db_session` (rolling-back transaction)
  for many tests** — these work fine because the rollback never
  commits, so the post-commit-GUC issue doesn't apply. Don't try to
  refactor every test to org_scoped_session; it's not needed.

## Observable state at end of task

- Modified: `backend/.env.example`, `backend/.env`, `docker-compose.yml`,
  `.github/workflows/ci.yml` — runtime URL flipped to fabric_app.
- Modified: `backend/tests/conftest.py` — added `admin_engine` fixture
  + `org_scoped_session` context manager.
- Modified: 11 test files — fixture migrations under fabric_app (sales
  router seeder, receipt seeder, stock adjustment seeder, switch_firm
  seeders, auth router MFA + logout, dependencies, feature_flag, party
  + item RLS isolation, migration smoke, ORM DDL drift).
- Modified: `scripts/doctor.sh` — alembic check now sources
  `backend/.env` so `alembic current` can find DATABASE_URL.

## Bringing it home — INT-16 closes the runtime RLS gap

| Concern | Pre-INT-16 | Post-INT-16 |
|---|---|---|
| Runtime role | `fabric` (superuser, BYPASSRLS) | `fabric_app` (NOBYPASSRLS) |
| RLS at runtime | Theatre — every SELECT bypasses | Enforced — `app.current_org_id` is mandatory |
| Test runtime | `fabric` (or postgres:postgres in CI) | `fabric_app` |
| `make doctor` alembic check | Silent yellow warning | Actually verifies head matches |

Next on the deferred list: **INT-13 (GL split)** and **INT-14 (Bill of
Supply)**. Both still gated on the CA call. The audit emit pattern
from INT-15 will be reused for the GL split in INT-13.
