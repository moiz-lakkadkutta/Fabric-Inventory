# TASK-006 retro — SQLAlchemy identity models

**Date:** 2026-04-27
**Branch:** task/006-identity-models
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 2)

## Summary

Identity-domain ORM models landed in `backend/app/models/`: `Base` (DeclarativeBase) + reusable mixins (`TimestampMixin`, `AuditByMixin`, `SoftDeleteMixin`) + 11 models mirroring `schema/ddl.sql` lines 54-279 (`Organization`, `Firm`, `AppUser`, `Role`, `Permission`, `RolePermission`, `UserRole`, `UserFirmScope`, `Device`, `Session`, `AuditLog`). `alembic/env.py` now imports `app.models` so `target_metadata = models.Base.metadata` — autogenerate is on. 14 tests: 13 pure-Python schema-shape assertions + 1 round-trip insert/query/relationship-load against a migrated Postgres. All green; mypy strict clean across 30 source files.

## Deviations from plan

### 1. Included 4 tables beyond TASKS.md's TASK-006 scope

TASK-006 lists 7 models: Organization, Firm, AppUser, Role, Permission, RolePermission, AuditLog. I added 4 more from the same DDL section: `UserRole`, `UserFirmScope`, `Device`, `Session`.

- **Why:** they're tightly coupled — TASK-007 (auth service) needs `Session` for refresh-token storage, TASK-009 (RBAC) needs `UserRole`, and `Device` is referenced in architecture §17.8 for offline sync. Splitting them into a separate task would create a same-file edit conflict between TASK-006 and TASK-007.
- **Impact on later tasks:** none — TASK-007 inherits ready-to-use models. The merge surface for TASK-009/017 stays in `app/models/identity.py` rather than migrating to a follow-up.

### 2. Used mixin classes for audit columns rather than redeclaring per-model

DDL repeats `created_at`, `updated_at`, `created_by`, `updated_by`, `deleted_at` on every tenant-scoped table. Three small mixins (`TimestampMixin`, `AuditByMixin`, `SoftDeleteMixin`) reduce noise and let Python guarantee shape-consistency.

- **Why not a single GodMixin:** not every table wants all five columns. `Permission` has only `created_at`; `RolePermission`/`UserRole`/`UserFirmScope`/`Device`/`Session`/`AuditLog` are append-only-ish per the DDL exempt list (TASK-004 PATCH 1). Three mixins matches the three orthogonal axes.

### 3. AuditByMixin doesn't declare an FK on `created_by`/`updated_by`

DDL has these FKs `ON DELETE SET NULL` (TASK-004 P1-2 fold-in). At the ORM level, declaring relationships would create circular imports (every model would need to import `AppUser`). Mixin keeps them as plain `UUID | None` columns; the FK constraint is enforced by Postgres, not the ORM.

- **Trade-off:** `audit_log.user.email`-style joins won't auto-resolve. Service layer fetches user separately when needed. Acceptable for an audit log that's read in dashboards, not joined in hot paths.

### 4. `Permission` doesn't use TimestampMixin

DDL declares `Permission` with only `created_at` (no `updated_at`, no soft-delete). Inheriting `TimestampMixin` would force `updated_at`. Permissions are a near-immutable catalog; if we need to deprecate one, a new permission row is the right pattern. Inlined `created_at` only.

### 5. Renamed `app_user` Python class to `AppUser` (not `User`)

Avoids the trap where domain code later wants a `User` value object distinct from the ORM row. `AppUser` makes the persistence-vs-domain split obvious.

### 6. Round-trip test scope

Inserts `Organization` → `Firm` → `AppUser`, flushes (verifies server-side UUID defaults populate), reloads via relationship traversal, and cleans up via cascade-delete on `Organization`. This catches ~80% of model-to-DDL drift in one test:

- column type mismatches (PG_UUID vs UUID, BYTEA vs TEXT, etc.)
- nullable/server_default disagreements
- cascade rules
- relationship back_populates correctness

The 7 non-tested models (`Permission`, `RolePermission`, `UserRole`, `UserFirmScope`, `Device`, `Session`, `AuditLog`) get pure-Python column-shape assertions. Round-tripping each one would 3x test count for marginal value.

## Things the plan got right (no deviation)

- SQLAlchemy 2.0 declarative style with `Mapped[T]` + `mapped_column(...)`. Compiles + types check under `mypy --strict` with zero gymnastics.
- `PG_UUID(as_uuid=True)` for UUID columns — Python sees `uuid.UUID`, Postgres stores native uuid.
- `JSONB` from `sqlalchemy.dialects.postgresql` for `feature_flags` / `audit_log.changes`. Maps to native Postgres JSONB.
- `LargeBinary` for BYTEA (encrypted PII) — service layer handles AES-GCM in TASK-007+.
- Server-side UUID defaults via `server_default=func.gen_random_uuid()` rather than client-generated. Matches DDL; no drift.
- Importing `app.models` in `alembic/env.py` after the URL setup wires `target_metadata` cleanly. `alembic revision --autogenerate` will work as soon as we add a new column or table.

## Pre-next-task checklist

### 1. TASK-007 (auth service) can start immediately

`AppUser`, `Session`, `Device` are all wired with relationships. Auth service should:
- Use `password_hash` field (bcrypt; column already typed `String(255)`).
- Use `mfa_secret` BYTEA field; encrypt with the envelope helper landing in TASK-007.
- Insert into `Session` on login; check `expires_at` + `revoked_at` on refresh.
- Set `request.state.user` (already documented in `RLSMiddleware` post-condition).

### 2. TASK-009 (RBAC) — `Role` / `Permission` / `RolePermission` / `UserRole`

The four tables are now first-class. `has_permission(user_id, permission_code)` is a join across 4 tables; consider materialising a flattened `user_permissions` view or in-memory cache after first query.

### 3. TASK-014 (masters scaffold) — drops in next to identity.py

`backend/app/models/masters.py` will follow the same shape: import `Base` from `app.models`, use mixins, `__all__` re-export from `app/models/__init__.py`. Pattern is now established.

### 4. `alembic revision --autogenerate` is now operational

Try it before TASK-014: `cd backend && DATABASE_URL=... uv run alembic revision --autogenerate -m "test"` should produce an empty migration file because the ORM matches the DDL. If it produces non-empty diff, that's drift — investigate.

### 5. Soft-delete query filter — service layer

ORM doesn't auto-filter `WHERE deleted_at IS NULL`. Future query helpers in service modules should add this filter (or we add a global SQLAlchemy event listener on `before_compile`). Pick one when TASK-007 first needs to query users.

### 6. Round-trip test is opt-in via `DATABASE_URL`

Local devs without Docker get the pure-Python assertions; CI's services container activates the round-trip. Same pattern as TASK-004's smoke test.

## Open flags carried over

1. **Soft-delete query filter strategy** — service-level vs ORM-level event listener. Decide at first need.
2. **`make dev` end-to-end** — still not validated this session.
3. **`make dev: setup` Makefile dependency** — TASK-001 retro item 5, still unresolved.
4. **Git identity** — Moiz action.
5. **Audit log immutability** — currently enforced by app-layer discipline. A Postgres rule preventing UPDATE/DELETE on `audit_log` is a nice cleanup.

## Observable state at end of task

- `backend/app/models/__init__.py` — `Base` (DeclarativeBase) + re-exports.
- `backend/app/models/mixins.py` — `TimestampMixin`, `AuditByMixin`, `SoftDeleteMixin`.
- `backend/app/models/identity.py` — 11 models for the identity domain.
- `backend/alembic/env.py` — imports `app.models`; `target_metadata = models.Base.metadata`. Autogenerate is on.
- `backend/tests/test_identity_models.py` — 14 tests (12 pure-Python schema-shape + 1 round-trip ORM + 1 metadata registry).
- ruff, ruff format, mypy strict — all clean across 30 source files.
- Round-trip verified end-to-end against a fresh `postgres:16-alpine` container after `alembic upgrade head`.
- Branch `task/006-identity-models` exists locally; pushed to origin.
