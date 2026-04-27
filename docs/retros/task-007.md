# TASK-007 retro — auth service (JWT + bcrypt + TOTP)

**Date:** 2026-04-27
**Branch:** task/007-auth-service
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 2)

## Summary

`backend/app/service/identity_service.py` implements the auth surface from TASKS.md TASK-007:

- `register_user(session, *, email, password, org_id) -> AppUser` — bcrypt-hashes (cost 12), DB-enforces email uniqueness per org
- `login(session, *, email, password, org_id, firm_id=None) -> TokenPair` — verifies credentials, snapshots permissions from `rbac_service`, issues a JWT access (15-min) + refresh (14-day) pair, persists a `session` row, updates `last_login_at`
- `refresh_token(session, *, refresh_token) -> TokenPair` — validates the refresh JWT, looks up the session row, revokes it, issues a new pair
- `verify_jwt(token) -> TokenPayload` — decodes + validates, raises `TokenInvalidError` on any failure
- `enable_mfa(session, *, user_id) -> MfaEnrollment` — pyotp TOTP secret + provisioning URI for QR
- `verify_totp(session, *, user_id, code) -> bool` — boolean check, `valid_window=1` for clock skew

3 new exceptions in `app/exceptions.py`: `InvalidCredentialsError` (401), `TokenInvalidError` (401), `MfaError` (401).

29 new tests covering hashing, registration, login (incl. wrong password / unknown email / inactive user / generic-error semantics), JWT verify (incl. bad signature, expired, malformed payload), refresh (incl. revoke-on-rotate, refusing access tokens, refusing already-revoked), MFA (TOTP enroll, valid code, wrong code, no-MFA-user). Token TTLs verified to match the spec (15-min / 14-day) within ±2s drift.

**Total suite: 81 passed against migrated Postgres; 38 passed + 43 skipped without it.** ruff + format + mypy strict clean across 36 source files.

## Deviations from plan

### 1. Refresh tokens live only in the `session` table; no Redis

TASKS.md notes "Store refresh tokens in Redis with expiry (14 days)." TASK-017 in the grand plan is "Refresh token rotation + Redis integration" — that's where Redis lands. For TASK-007 I kept refresh-token state in the DB-side `session` row (`refresh_token_hash` + `expires_at` + `revoked_at`). When TASK-017 lands, Redis becomes the fast path (denylist + per-token cache) with the DB row as durable backing.

- **Why:** spreading the persistence layer across two stores at the same time courts staleness bugs. Single-source-of-truth (`session` row) for now; layer Redis on top later.
- **Impact:** none. The public surface (`refresh_token()` API) is unchanged when Redis lands.

### 2. JWT permissions are snapshotted at issue time, not re-fetched per request

JWT payload includes `permissions[]` from `rbac_service.get_user_permissions` at issue time. Pros: stateless verify, no DB hit per request, scales linearly. Cons: stale on permission changes — a 15-minute access-token TTL bounds the staleness, which is the standard trade-off.

- **Alternative considered:** keep the JWT lean (just `user_id`, `org_id`, `firm_id`) and look up permissions per-request in `app.dependencies.get_db`. That's a DB hit on every authenticated route. We can switch to that later if the staleness ever bites; the change is one function.

### 3. Permissions in JWT are sorted

`sorted(rbac_service.get_user_permissions(...))` — guarantees stable ordering across token issues, which simplifies token comparison in tests + logs.

### 4. `is_active` / `is_suspended` checks all return the same `InvalidCredentialsError`

Wrong password, unknown email, deleted user, inactive user, suspended user — all surface as `InvalidCredentialsError("Invalid email or password")`. Tested explicitly. Per OWASP, login response messages must not leak whether an email is registered or whether an account is suspended; the only thing the response tells the attacker is "we won't let you in."

### 5. MFA secret stored as plaintext bytes in `app_user.mfa_secret` BYTEA

The DDL column is `BYTEA` and the architecture's envelope-encryption path (AES-GCM per org, §5.4) is a future task. For TASK-007 the secret is stored as UTF-8 bytes. When envelope encryption lands, the column shape doesn't change — only the encode/decode helpers do. Documented in code.

### 6. Owner permissions in JWT verified to include all 38 system perms

`test_verify_jwt_decodes_payload` asserts the Owner login produces a JWT whose `permissions` field contains every code from the system catalog (38 entries). This is the integration check that auth + RBAC + JWT issue all line up — caught nothing in initial run, but it's the test that'll catch drift the next time someone changes the permission catalog or the role bundle.

### 7. Redis dependency unchanged

`redis` was already in deps from TASK-001. We don't import it here; TASK-017 will. No churn.

## Things the plan got right (no deviation)

- Service signature `(session, *, kw-only org_id, firm_id, ...)` — matches CLAUDE.md §"Authentication & RLS".
- Bcrypt cost factor 12 — industry standard, covered by tests.
- HS256 + `settings.jwt_secret` — the existing config field is sized at min 16 chars, so signing key strength is enforced at config-load time (TASK-002 model_validator).
- pyotp.TOTP with `valid_window=1` — accepts the previous + next 30s slot.
- Service is sync (sqlalchemy `Session`); router-side will wrap with `asyncio.to_thread` per the TASK-009 retro pattern. Same call-site convention as `rbac_service`.

## Pre-next-task checklist

### 1. TASK-008 (auth routers) wires this end-to-end

Routes:
- `POST /auth/signup` — orchestrates org creation, `rbac_service.seed_system_roles`, `register_user`, `assign_role(OWNER, firm_id=None)`.
- `POST /auth/login` — calls `login()` and returns `{access_token, refresh_token, expires_at}`.
- `POST /auth/refresh` — calls `refresh_token()` against the request body.
- `POST /auth/mfa/enable` — calls `enable_mfa(user_id=current_user.user_id)`.
- `POST /auth/mfa/verify` — calls `verify_totp`. Returns 401 on mismatch (router converts boolean → exception).

All five are mutating endpoints → `Idempotency-Key` header required (P0-4 fold-in for TASK-008).

### 2. TASK-016 replaces `require_permission` stub with `verify_jwt` + `has_permission`

In `app/dependencies.py`:
- Read `Authorization: Bearer …` from request.
- `payload = verify_jwt(token)` (raise 401 on failure).
- Set `request.state.user = payload`.
- `require_permission("...")` checks `permission_code in payload.permissions`.

### 3. RLSMiddleware reduces to "read state.user.org_id"

Per the TASK-002 retro (and the TASK-006 PR review), once a real auth middleware exists, `RLSMiddleware` should stop decoding JWTs and just read `request.state.user.org_id` set by the auth middleware. TASK-008/016 should land this refactor.

### 4. Redis-backed rotation lands in TASK-017

When TASK-017 wires Redis: replace the `session.refresh_token_hash` lookup with a Redis GET (with DB fallback for cold cache). Old session rows become an audit trail; revocation is `redis DEL` + `UPDATE session SET revoked_at = NOW()`.

### 5. Password reset flow not in scope

TASKS.md doesn't list it for Phase 1. When a paying customer needs it, plan + add. Until then, dev resets via DB are fine.

### 6. Async-wrap pattern — same as RBAC

When TASK-008 routers call into this service from async context, wrap with `asyncio.to_thread(identity_service.login, ...)`. If 5+ call sites need wrapping, switch the service interior to async. Don't refactor preemptively.

## Open flags carried over

1. **Redis-backed refresh rotation** — TASK-017.
2. **Real RBAC permission gate in routers** — TASK-016.
3. **Envelope encryption for `mfa_secret`** — Phase-2 follow-up; column shape unchanged.
4. **Password reset flow** — out of MVP scope; revisit when customer asks.
5. **Async-wrap pattern** — first router call site decides.
6. **Git identity** — Moiz action.

## Observable state at end of task

- `backend/app/exceptions.py` — added `InvalidCredentialsError`, `TokenInvalidError`, `MfaError` (all 401).
- `backend/app/service/identity_service.py` — full auth service.
- `backend/tests/test_identity_service.py` — 29 tests (4 always-run, 25 DB-bound).
- `docs/retros/task-007.md` — this file.
- ruff + format + mypy strict clean across 36 source files.
- 81/81 tests pass against fresh `postgres:16-alpine` after `alembic upgrade head` (4 + 16 + 12 always-run pure-Python, 49 DB-bound). Without Postgres: 38 pass + 43 skip.
- Branch `task/007-auth-service` exists locally; pushed to origin.
