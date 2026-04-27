# TASK-010 retro — Party CRUD

**Date:** 2026-04-27
**Branch:** task/010-party-crud
**Commit:** `<sha>` (pre-merge)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md`

## Summary

Shipped Party CRUD end-to-end: service (`masters_service`), router (`/parties` —
POST/GET-list/GET-by-id/PATCH/DELETE), schemas (Pydantic v2), PII encryption
stubs (`app/utils/crypto.py`), and 33 new tests (20 service + 13 router HTTP).
All 163 tests pass against a migrated Postgres 16 in Docker; `ruff check`,
`ruff format --check`, and `mypy --strict` clean across 50 source files.

## Deviations from plan

### 1. `list_parties` / `get_party` / `update_party` / `soft_delete_party` now take `org_id` explicitly

Plan implied RLS alone would scope reads. CLAUDE.md's invariant — "Every
service method receives `org_id: UUID` ... explicitly. Never infer from user." —
required defense-in-depth: app-layer org_id filter on top of RLS.

- **Fixed by:** added `org_id: uuid.UUID` to all four service signatures
  (`backend/app/service/masters_service.py`); routers pass `current_user.org_id`.
- **Why not caught in planning:** the original sketch leaned on RLS as the only
  filter. The first run of `test_list_parties_filters_by_type` exposed that
  superuser DB connections (CI default) bypass RLS entirely, so the test saw
  cross-org rows. App-layer filter is mandatory.
- **Impact on later tasks:** every future service method touching tenant data
  must follow this pattern. Already consistent with `create_party`'s shape.

### 2. RLS isolation test required a non-superuser test role

Plan: write an RLS isolation test for the security boundary. Reality: Postgres
superusers bypass RLS unconditionally even with `FORCE ROW LEVEL SECURITY`.
Both the dev container and CI's postgres service use a superuser, so a naive
RLS test would have green-passed for the wrong reason (filtering happening at
the app layer, not the policy).

- **Fixed by:** `test_rls_blocks_cross_org_party_reads` creates a
  `rls_isolation_test_role` (NOLOGIN, NOBYPASSRLS), grants minimal SELECT/
  INSERT, runs each org's read inside `SET LOCAL ROLE` + `SET LOCAL
  app.current_org_id`. Test toggles `FORCE RLS` on `party` and reverts in a
  `finally` block.
- **Why not caught in planning:** the architecture spec assumes a non-superuser
  app role in prod; CI/dev doesn't. Bridging that gap belongs in test setup,
  not in production schema.
- **Impact on later tasks:** every future RLS test should use the same role
  pattern (or we should establish a shared `rls_test_app` fixture). Slot for
  TASK-015 (seed data) or a small refactor next time we add RLS-bounded tests.

### 3. GSTIN regex fix (16 → 15 chars)

The initial regex `^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]Z[A-Z\d]$` matched 16
characters; GSTIN is 15. Caught by `test_create_party_happy_path` rejecting a
valid `27ABCDE1234F1Z5`.

- **Fixed by:** `^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[A-Z\d]$` — the entity-code
  position (13th char) merges with the next slot.
- **Why not caught in planning:** copy-paste of the pattern without character-
  counting. Test caught it on first run.
- **Impact on later tasks:** TASK-047 GST engine owns the full validator
  (state-code lookup + checksum digit). This regex is a syntactic gate only.

## Things the plan got right (no deviation)

- Sync `Session` + sync route handlers; consistent with the auth router.
- PII encryption stub pattern (`bytes` columns, `encrypt_pii`/`decrypt_pii`
  helpers): zero changes needed when real AES-GCM lands in Phase 2.
- Permission catalog already had `masters.party.{create,update,read}` — no
  catalog edit needed.
- Idempotency-Key validation reused via `_validate_idempotency_key` import
  from `auth` router.

## Pre-TASK-011 checklist

### 1. Item / SKU CRUD will need the same `org_id`-explicit pattern

Mirror the four-service-method shape established here (create / get / list /
update / soft-delete) and pass `org_id` explicitly. The router-side test for
cross-org isolation should use the same `_signup_owner` helper pattern from
`tests/test_party_routers.py:38-51`.

### 2. Decide whether `firm_id` is a hard requirement on Item

Party can be org-level (`firm_id IS NULL`). Items in textile trade are
typically org-level too (one HSN catalog), but SKU pricing can vary per firm.
Confirm with Moiz before writing the schema migration.

### 3. The PII regex pattern is now in `masters_service`

If TASK-011 also needs PAN validation (it might for the manufacturer party
linkage on items), import the regex from `masters_service` rather than
re-defining. We have a soft DRY rule against premature abstraction, but two
copies of the same regex is the threshold to extract.

## Open flags carried over

- **Real PII encryption** (Phase 2): swap `app/utils/crypto.py` to AES-GCM with
  per-org DEK. Service layer needs no edit by design.
- **GSTIN full validation** (TASK-047): state-code lookup + checksum digit.
  Current regex is format-only.
- **Shared `rls_test_app` role fixture**: the test creates the role inline
  today. When the second RLS-bounded test arrives, lift it into a session-
  scoped conftest fixture.

## Observable state at end of task

- New file: `backend/app/utils/crypto.py` (PII encryption stubs).
- New file: `backend/app/service/masters_service.py` (Party CRUD).
- New file: `backend/app/schemas/masters.py` (request/response models).
- New file: `backend/app/routers/masters.py` (5 endpoints).
- `backend/main.py` registers the masters router.
- New tests: `tests/test_party_service.py` (20), `tests/test_party_routers.py` (13).
- Postgres role `rls_isolation_test_role` (NOLOGIN, NOBYPASSRLS) is left in
  the test DB after first run — idempotent, reusable. CI creates it fresh.
- Docker test container `fabric-task010-pg` on `localhost:5499` was used for
  local verification. Not a project artifact — restart with the standard
  docker-compose for normal dev.
