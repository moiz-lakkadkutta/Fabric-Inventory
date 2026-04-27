# TASK-016 retro — real auth gates

**Date:** 2026-04-27
**Branch:** task/016-permission-gates
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 2)

## Summary

`app/dependencies.py` replaces the TASK-002 stubs:

- `get_current_user(request) -> TokenPayload` — decodes the Bearer JWT, validates type=access, raises 401 on missing/invalid/refresh-token.
- `CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]` — alias for routes that just need the user.
- `require_permission(code)` — factory returning a dep that raises 403 if the user doesn't carry `code` in their JWT permissions list.

`/auth/me` lands as the canonical "what's my JWT say about me" endpoint. 9 new tests cover the full surface; **130/130 tests pass**, ruff + mypy strict clean across 44 source files.

## Deviations from plan

### 1. JWT decode lives in the dep, not in middleware

The TASK-002 retro and TASK-007 retro both said "post-TASK-007, AuthMiddleware decodes JWT and sets `request.state.user`; deps + RLSMiddleware just read state." That doesn't work cleanly — Starlette's `BaseHTTPMiddleware` has known issues propagating `request.state` mutations between middleware and the route handler. The first push tried the middleware approach and got **silent 401s** because state.user was None when the dep read it (despite middleware setting it).

Pivoted to: `get_current_user` decodes the JWT directly from `request.headers["authorization"]`. The existing `RLSMiddleware` continues to decode JWT for the `org_id → SET LOCAL` path. Two decodes per authenticated request — cheap relative to bcrypt + DB latency, and avoids the propagation footgun.

- **Trade-off:** double-decode on protected routes. Mitigation: TASK-017 layers Redis-backed session cache, eliminating one of the two decodes.
- **Long-term cleanup:** when we replace `BaseHTTPMiddleware` with raw ASGI middleware (which doesn't have the state-propagation issue), JWT decode can move back to a single middleware. Not in MVP scope.

### 2. AuthMiddleware + RLSMiddleware untouched

Both stay as-is from TASK-007. AuthMiddleware is a no-op pass-through. RLSMiddleware decodes JWT (its Wave-1 shape). The "RLSMiddleware reduces to reading state.user.org_id" cleanup the TASK-002 retro foresaw is deferred to TASK-017's broader middleware refactor.

### 3. `/auth/me` lands here, not in TASK-007

TASK-007 retro said `/auth/me` was "TASK-016+". This is that. Returns user_id, org_id, firm_id, permissions, token_expires_at — straight from the JWT payload. No DB query — JWT is the source of truth for authenticated request scope.

Frontend wants this for: rendering "Logged in as X" header, gating UI affordances by permissions[], and detecting impending token expiry to pre-emptively refresh.

### 4. Permission snapshot semantics tested explicitly

`test_token_permissions_are_snapshotted_at_issue_time` documents the intentional behavior: revoking a user's role mid-session does NOT immediately cut off access — the JWT carries the permission set as of issue time. The 15-min access TTL bounds the staleness.

If we ever need true real-time revocation (e.g. for a compromised session), TASK-017's Redis denylist lets us blacklist a `jti` mid-flight.

### 5. Forward-reference quoting broke FastAPI dep introspection

First push had `CurrentUser = Annotated["TokenPayload", Depends(get_current_user)]` (string annotation for forward ref). FastAPI's dependency analyzer can't resolve string forward-refs to a concrete type for sub-deps, so it tried to validate `current_user` as a query parameter and returned 422.

Fix: imported `TokenPayload` directly at module load (no circular — `identity_service` doesn't import from `dependencies`). String quoting removed.

### 6. Synthetic test endpoints in `test_dependencies.py`

TASKS.md's spec says "Add permission check to `POST /parties` etc." — but those routes don't exist yet (TASK-010+). To exercise `require_permission` end-to-end without inventing scaffolding for unrelated tasks, the test file builds a tiny FastAPI app at fixture time with `/tests/needs-create` and `/tests/needs-impossible`. Production routes pick up the dep when their tasks land.

### 7. `Annotated[T, Depends(...)]` is the only allowed dep syntax

FastAPI rejects `current_user: CurrentUser = Depends(require_permission(...))` with "Cannot specify Depends in Annotated and default value together". So routes that need a permission check use the explicit form:

```python
current_user: Annotated[TokenPayload, Depends(require_permission("masters.party.create"))]
```

For routes that just need authentication (any user), the alias `CurrentUser` works directly. Documented in `dependencies.py` docstring with usage examples.

## Things the plan got right (no deviation)

- Service signature already returned `TokenPayload` — no changes needed in `identity_service.verify_jwt`.
- `permissions: tuple[str, ...]` on `TokenPayload` — `in` checks are O(n) but n=38 is negligible.
- FastAPI's dependency-injection model with deps that depend on other deps works exactly as expected once the type-resolution issue was fixed.
- The hard-fail-on-CI pattern from TASK-006/007 carried over cleanly to TASK-016's tests via the shared `sync_engine` fixture.

## Pre-next-task checklist

### 1. TASK-010 (Party CRUD) wires `require_permission("masters.party.*")` on routes

Mutating endpoints get the explicit dep:
```python
@router.post("/parties")
def create_party(
    current_user: Annotated[
        TokenPayload, Depends(require_permission("masters.party.create"))
    ],
    body: PartyCreateRequest,
    db: SyncDBSession,
) -> PartyResponse: ...
```

### 2. RLSMiddleware refactor on hold until TASK-017

The "RLS reads state.user.org_id" cleanup needs a working state-propagation path. TASK-017 is the right time — alongside the Redis session-cache refactor.

### 3. Token replay protection lives in TASK-017

Today: any access token works until it expires (15 min) even if the user logged out / was suspended. Tomorrow (TASK-017): Redis denylist by `jti` lets logout / role-revocation invalidate tokens mid-flight.

### 4. /auth/me doesn't hit the DB — by design

Deliberate choice: JWT is the source of truth for the request's authenticated scope. If /me starts joining live DB state (current role assignments, current firm scope), permission-snapshot semantics break and we'd need to reconcile cache vs DB. Keep `/me` JWT-pure; if frontend needs live state, expose a separate endpoint.

### 5. /auth/enable-mfa, /auth/disable-mfa land later

Not in scope here. They'll need `current_user` + a body and re-auth confirmation. Plan for a small follow-up task or fold into TASK-019 admin panel.

## Open flags carried over

1. **Double JWT decode per protected request** — TASK-017 reduces to one via Redis cache.
2. **RLSMiddleware retains JWT-decode role** — refactor in TASK-017.
3. **Real-time permission revocation** — TASK-017.
4. **Replace BaseHTTPMiddleware with raw ASGI middleware** — Phase 2; the propagation footgun keeps biting.
5. **Git identity** — Moiz action.

## Observable state at end of task

- `backend/app/dependencies.py` — real `get_current_user`, `CurrentUser` alias, `require_permission` factory; stubs gone.
- `backend/app/routers/auth.py` — adds `GET /auth/me`.
- `backend/app/schemas/auth.py` — adds `MeResponse`.
- `backend/tests/test_dependencies.py` — 9 tests covering /auth/me happy + 4 negatives + 3 require_permission cases + snapshot semantics.
- ruff + format + mypy strict clean across **44 source files**.
- 130/130 tests pass against fresh `postgres:16-alpine` after `alembic upgrade head`.
- Branch `task/016-permission-gates` exists locally; pushed to origin.
