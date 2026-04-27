# TASK-008 retro — auth routers

**Date:** 2026-04-27
**Branch:** task/008-auth-routers
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 2)

## Summary

Five HTTP endpoints under `/auth/*` wire TASK-007's auth service + TASK-009's RBAC service end-to-end:

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /auth/signup | email, password, org_name, firm_name | user_id, org_id, firm_id, token pair |
| POST | /auth/login | email, password, org_name | requires_mfa OR token pair |
| POST | /auth/mfa-verify | email, password, org_name, totp_code | token pair |
| POST | /auth/refresh | refresh_token | token pair (old session revoked) |
| POST | /auth/logout | refresh_token | revoked: bool (idempotent) |

Sync handlers (FastAPI threadpool) match the sync service layer — no `asyncio.to_thread` wrapping needed. Sync DB session via new `get_db_sync` dep + `app/db.py` sync engine helpers. Pydantic schemas in `app/schemas/auth.py`. Idempotency-Key header validated as UUID-shape; real dedupe lands in TASK-017. **17 router integration tests + 101 total**, all green against migrated Postgres. ruff + mypy strict clean across 41 source files.

## Deviations from plan

### 1. Login takes `org_name` (not `org_id`)

Spec literally says `{email, password}` for login. Reality: emails are unique per-org (DDL `app_user_org_id_email_key`), so login MUST disambiguate which org. UUID `org_id` is the wrong UX (user doesn't know it). Switched to `org_name` with internal lookup. Frontend will show an org-name field on the login form.

- Same change applied to `/auth/mfa-verify` for consistency.
- `/auth/signup` returns `org_id` so the frontend can stash it for later session restoration.

### 2. `/auth/mfa-verify` re-presents `email + password + totp_code` (not just `{user_id, totp_code}`)

The spec wording — `{user_id, totp_code}` — accepts a known user_id and only the TOTP. That lets anyone with a leaked user_id brute-force the 6-digit code (10⁶ guesses; pyotp accepts a 30s window with `valid_window=1`, so a determined attacker has 60s × 6.6 RPS to brute force per code). Demanding the password again forces two real factors.

- Spec form is also kept reachable: the `LoginResponse.user_id` is returned alongside `requires_mfa=true` so the frontend can pre-fill the email if it didn't cache it.
- A proper "MFA challenge token" (short-lived JWT issued by login, single-use, exchanged via mfa-verify) is the production-grade fix and lands when we layer Redis denylist in TASK-017.

### 3. Idempotency-Key is validated, not deduped

Per the grand plan, TASK-008 introduces the pattern. The full implementation needs Redis (TASK-017) + the `api_idempotency` table. For TASK-008 we accept the header, validate UUID shape, and document the deferred dedupe in code + retro. Clients that send a key today get no replay protection but won't be rejected.

- A malformed Idempotency-Key surfaces a clean 422 here rather than a confusing 500 later. Tested.

### 4. `/auth/logout` is idempotent + accepts unknown tokens

Spec says "invalidate refresh token." A logout call with an unknown / malformed / already-expired / already-revoked token returns 200 + `{revoked: false}` rather than 401. Reasoning: clients retrying logout (network blip, double-tap) should always succeed; a 401 there confuses UX (looks like "you weren't logged in") and trains users to ignore auth errors. The "true 401" case is reserved for `/auth/refresh` and protected endpoints.

The one exception: a logout call with an **access token** (wrong type) returns 400 — that's a programmer error (frontend bug), not a network blip.

### 5. Sync handlers (def, not async def)

FastAPI runs `def` handlers in a threadpool, which lets sync service calls execute without stalling the event loop. Matches the sync `rbac_service` + `identity_service` from TASK-007/009. The alternative — async handlers with `asyncio.to_thread(service_func, ...)` — adds wrapping noise everywhere with no benefit until concurrency-bound.

### 6. New sync engine + sync session machinery in `app/db.py`

Existing `app/db.py` had async-only. Added parallel sync engine, sync sessionmaker, `get_sync_session()`. URL is rewritten asyncpg → psycopg2 (same trick as `alembic/env.py`). Both engines share the same `DATABASE_URL` config. `dispose_engine()` tears down both.

- `app/dependencies.py:get_db_sync` is the FastAPI dep; sets `app.current_org_id` GUC just like its async counterpart, commits on success, rolls back on exception.

### 7. Signup orchestration is in the router, not a service

`signup` creates: org → firm → seeds RBAC permissions + roles → registers user → assigns Owner role → issues tokens. That's 6 service calls. Could be a `signup_org_owner` service method, but routers ARE supposed to orchestrate — services own atomic operations, routers compose them. Keeps the service-layer contract clean.

### 8. Test integration uses `TestClient` against shared Postgres, not transactional rollback

The router tests open their own connection through `get_db_sync` — they don't share a connection with a savepoint-rollback fixture. So I gave each test unique org/email names (UUID-suffixed) and skipped row cleanup. Test DB is ephemeral (transient Postgres container) so persistence between tests is fine.

- The unit-test-style transactional fixture (`db_session` from conftest) still gives the service-level tests their isolation. Two test patterns side-by-side; pick the one that fits.

### 9. Pydantic schemas use `pydantic[email]` extras (added to deps)

`EmailStr` needs `email-validator`. Added `pydantic[email]>=2.0` to `pyproject.toml`. Consequence: `pydantic` no longer pulls bare; CI re-resolves the lock file.

## Things the plan got right (no deviation)

- 5 endpoints match the spec signatures (request/response field names) modulo the org-name change above.
- Generic `InvalidCredentialsError` everywhere — wrong password / unknown email / unknown org / inactive user / suspended user / wrong TOTP all return the same 401 with the same message. No info leak.
- `/auth/refresh` rotates session rows: the old refresh token's session row is marked `revoked_at = now()`, a new pair is issued. Replay of the old token → 401.
- All 5 are mutating endpoints → all accept Idempotency-Key.
- Token TTLs (15-min access / 14-day refresh) come from `identity_service` constants — single source of truth.

## Pre-next-task checklist

### 1. TASK-016 replaces `app/dependencies.py:require_permission` stub

- Read `Authorization: Bearer …` header in a new `get_current_user` dep
- Call `identity_service.verify_jwt(token)` → `TokenPayload`
- Set `request.state.user = payload`
- `require_permission(code)` returns a dep that asserts `code in payload.permissions`, raises `PermissionDeniedError` otherwise

### 2. TASK-017 makes Idempotency-Key real

- Add `app/utils/idempotency.py` middleware/decorator that:
  - On request entry: hash `(idempotency_key, body_sha256)` → cache key
  - Look up in Redis (and `api_idempotency` table for cold cache)
  - On hit: return cached response (status, headers, body)
  - On miss: call handler, cache the response with 24h TTL
- Same task wires Redis-backed refresh-token rotation.

### 3. RLSMiddleware should retire its JWT decoder

Once TASK-016's `get_current_user` lands and sets `request.state.user`, RLSMiddleware should reduce to:
```python
request.state.org_id = (
    str(getattr(request.state, "user", None).org_id)
    if getattr(request.state, "user", None) else None
)
```
Documented in TASK-002 retro; TASK-008 doesn't touch this.

### 4. Email-validator dep matters for offline installs

Adding `pydantic[email]` pulls `email-validator` + `dnspython`. If a deploy env lacks PyPI access, we now need both wheels cached. Note in TASK-067 (deploy runbook).

### 5. The deprecated `HTTP_422_UNPROCESSABLE_ENTITY` constant

Starlette deprecated it in favor of `HTTP_422_UNPROCESSABLE_CONTENT`. We're still using it transitively via `status` import patterns elsewhere; replaced the one router instance with the literal `422`. When Starlette fully removes the alias, a single grep + replace clears it.

### 6. /auth/me, /auth/enable-mfa, /auth/disable-mfa are NOT in this PR

The spec listed five endpoints; "enable MFA" lives behind a JWT-protected endpoint that I'd add once TASK-016 brings real auth gates. Tests use the service directly. `/auth/me` (current-user info) is also TASK-016+.

## Open flags carried over

1. **MFA brute-force surface** — currently 10⁶ codes, 60s window. Layered defense (re-present password) reduces to brute-forcing both factors. Production-grade fix is MFA challenge tokens (Redis-backed) — TASK-017.
2. **Idempotency-Key dedupe** — TASK-017.
3. **Redis-backed refresh-token denylist** — TASK-017.
4. **/auth/me + /auth/enable-mfa + /auth/disable-mfa** — TASK-016 (need real auth dep).
5. **Removing the deprecated 422 alias** — passive; no action needed.
6. **Git identity** — Moiz action.

## Observable state at end of task

- `backend/app/routers/__init__.py` + `backend/app/routers/auth.py` — 5 endpoints.
- `backend/app/schemas/__init__.py` + `backend/app/schemas/auth.py` — Pydantic models.
- `backend/app/db.py` — adds sync engine + sync sessionmaker + `get_sync_session`.
- `backend/app/dependencies.py` — adds `get_db_sync` + `SyncDBSession` Annotated alias.
- `backend/main.py` — `app.include_router(auth_router.router)`.
- `backend/pyproject.toml` — `pydantic` → `pydantic[email]`.
- `backend/uv.lock` — regenerated.
- `backend/tests/test_auth_routers.py` — 17 router integration tests.
- `docs/retros/task-008.md` — this file.
- ruff + format + mypy strict clean across 41 source files.
- 101/101 tests pass against fresh `postgres:16-alpine` after `alembic upgrade head`.
- Branch `task/008-auth-routers` exists locally; pushed to origin.
