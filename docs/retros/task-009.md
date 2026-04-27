# TASK-009 retro — RBAC service

**Date:** 2026-04-27
**Branch:** task/009-rbac-service
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 2)

## Summary

`backend/app/service/rbac_service.py` ships with the system permission catalog (38 codes), the 5 system role definitions (Owner, Accountant, Salesperson, Warehouse, Production Manager), idempotent seeding helpers, role-assignment + permission-check primitives, and `create_custom_role`. Service-only — routers (TASK-008/016) wire it. 16 tests; total suite is 54/54 green against migrated Postgres; ruff + mypy strict clean across 34 source files.

## Deviations from plan

### 1. Defined a 38-permission catalog inline rather than referencing architecture.md

TASK-009's brief says "preset bundle of permissions (from docs/architecture.md)". The architecture doc describes the role concept but doesn't enumerate every permission code — and I'd rather fail-loud than guess. The catalog in `_SYSTEM_PERMISSIONS` covers the surface every TASKS.md row will need (sales, purchase, inventory, accounting, masters, identity, admin) at the granularity Phase-1 actually uses (`sales.invoice.finalize` separate from `sales.invoice.create`, etc.).

- **Why this scope:** the seed is idempotent; future tasks (TASK-034, 047, …) will append rows to `_SYSTEM_PERMISSIONS` and the next signup-path call picks them up. Existing orgs need a separate one-shot reseed migration once they exist; documented in code.
- **Impact:** the routers in TASK-016 reference these exact permission codes. Drift between this catalog and what routers check is caught at `has_permission` call time (returns False) rather than at startup, so services should consult `rbac_service.SYSTEM_ROLE_CODES` / the catalog when wiring `require_permission`.

### 2. Service is sync (not async) despite the rest of the runtime being async

`app/db.py` exposes async engine + sessions, FastAPI handlers are async, but the RBAC service operates on `sqlalchemy.orm.Session` (sync). Two reasons:

- Test ergonomics: the existing `db_session` fixture (transactional rollback over a sync `Connection`) is the cleanest path for inserting + querying without flaky cross-test pollution. Going async would require an `AsyncSession`-equivalent fixture and `pytest-asyncio` parametrization on every test.
- Performance: RBAC checks are cheap reads on join tables. When TASK-016 routers need them from async handlers, they'll wrap with `asyncio.to_thread(...)` (or just call from a sync subdependency) — this is a normal SQLAlchemy 2.0 pattern.

If/when we need to push tens of thousands of permission checks per request, we revisit. Until then, sync is the right tool.

### 3. Hoisted `sync_engine`, `db_session`, `fresh_org_id` fixtures into `tests/conftest.py`

TASK-006's `test_identity_models.py` had local copies of these fixtures. Moved to conftest.py so `test_rbac_service.py` (this task) and any future DB-bound test file can share. `test_identity_models.py` lost its duplicates and now imports from conftest. Also added `fresh_org_id` for the common "spin up an org + set RLS GUC" pattern. Net: -47 lines of duplication.

### 4. `update_system_role` is a clear-error stub, not a real implementation

TASKS.md doesn't strictly require it but the architecture's "system roles are immutable for MVP" is the natural decision point. Rather than silently allowing system-role mutations, the function raises `PermissionDeniedError`. Makes the immutability invariant call-site-checkable.

### 5. Production Manager role has only 4 permissions for MVP

The role's real surface (manufacturing orders, dispatch, receive, QC) is Phase-3. Without Phase-3 permissions in the catalog, the role would be empty. I gave it `inventory.stock.read`, `inventory.lot.read`, `masters.item.read`, `masters.party.read` so a dogfooding production manager has something useful before Phase-3 lands. Documented in the role's description.

## Things the plan got right (no deviation)

- Service signature: `(session, *, kw-only org_id, firm_id, …)` — matches CLAUDE.md §"Authentication & RLS" rule that every service method takes explicit `org_id`/`firm_id`.
- `firm_id=None` for org-level role assignments — the partial unique index from TASK-006 (`uq_user_role_user_role_firm` with `COALESCE(firm_id, sentinel)`) does the de-duplication at the DB layer; service-level `assign_role` is just an idempotent upsert wrapper.
- `get_user_permissions` UNIONs firm-scoped + org-level UserRole rows — the natural semantics ("Owner at org level applies in every firm").
- Custom-role validations: empty code/name → `AppValidationError`; system-role-code collision → `AppValidationError`; unknown permission codes → `AppValidationError`. All HTTP 422 via the error handler.

## Pre-next-task checklist

### 1. TASK-007 (auth service) wires this on signup

Once a user signs up + creates an org, the signup service should call `rbac_service.seed_system_roles(session, org_id=...)` then `assign_role(..., role_id=roles["OWNER"].role_id, firm_id=None)`. The service is idempotent so re-running is safe; document the call site in TASK-007's retro.

### 2. TASK-016 (router permission checks) replaces stubs

`app/dependencies.py:require_permission(perm)` is currently a no-op factory (per TASK-002). TASK-016 should replace its body with `rbac_service.has_permission(...)`-backed logic, plumbing through `request.state.user.user_id` + `request.state.user.firm_id` (when TASK-007 sets those).

### 3. Permission catalog grows with each domain task

When TASK-034 lands sales-invoice routers, append the relevant codes to `_SYSTEM_PERMISSIONS` and add them to the role definitions that should grant them. The seed function picks them up on the next call. Document the pattern in TASK-034's retro.

### 4. Async wrap pattern when first router calls this

When TASK-008/016 first calls a sync `rbac_service.has_permission` from an async handler, use:
```python
allowed = await asyncio.to_thread(
    rbac_service.has_permission,
    session, user_id=..., firm_id=..., permission_code=...,
)
```
or expose an async wrapper in the same module if the call sites are abundant. Don't refactor the underlying service to async until the wrap pattern shows up in 5+ routers.

### 5. Existing-org reseed strategy for new permissions

When `_SYSTEM_PERMISSIONS` grows in a future task, `seed_system_permissions` only fills in for orgs whose signup re-runs the helper. Existing orgs get the new perm rows + role grants when the function is re-called (idempotent). For Phase-2 we'll want a backfill migration that walks all orgs; until then, dev-only `make seed` (TASK-015) can re-call the helper for the test org.

### 6. Custom-role ownership check is in the router, not here

`create_custom_role` doesn't gate on `has_permission(..., "identity.role.create")` — that's the router's job. Documented in the docstring; TASK-016 must add the gate.

## Open flags carried over

1. **Phase-3 permissions** (mfg.mo.create, mfg.operation.dispatch, etc.) — append to catalog when TASK-073 lands.
2. **Async-wrapping** is the next refactor — once TASK-016 lands, decide whether to wrap or rewrite.
3. **Reseed migration for existing orgs** — Phase-2 when first paying customer arrives.
4. **Audit log integration** — role assignments and custom-role creation should write to `audit_log`. Not part of TASK-009; lands with TASK-007 sign-up audit + TASK-016 router audit.
5. **Git identity** — Moiz action.

## Observable state at end of task

- `backend/app/service/__init__.py` — package marker.
- `backend/app/service/rbac_service.py` — full RBAC service (38 perms, 5 roles, idempotent seed, `assign_role`, `get_user_permissions`, `has_permission`, `create_custom_role`, `update_system_role` stub).
- `backend/tests/conftest.py` — added `sync_engine`, `db_session`, `fresh_org_id` fixtures (hoisted from `test_identity_models.py`).
- `backend/tests/test_identity_models.py` — local duplicates removed; imports the conftest fixtures.
- `backend/tests/test_rbac_service.py` — 16 tests covering seeding idempotency, role-permission assignments, per-firm scoping, org-level role inheritance, custom-role validations, system-role immutability.
- `docs/retros/task-009.md` — this file.
- ruff + format + mypy strict clean across 34 source files.
- 54/54 tests pass against fresh `postgres:16-alpine` after `alembic upgrade head`.
- Branch `task/009-rbac-service` exists locally; pushed to origin.
