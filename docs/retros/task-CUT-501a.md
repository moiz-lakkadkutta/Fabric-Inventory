# TASK-CUT-501a retro — Rate-limit /auth/forgot + token cleanup

**Date:** 2026-05-11
**Branch:** task/CUT-501a-auth-security-closeout
**Plan:** Wave-6 W6-A slice of CUT-501 closeout (cutover-plan-2026-05-10.md), closing CUT-303 retro follow-ups #1 and #3.

## Summary

Shipped two CUT-303 retro follow-ups end-to-end on a single branch:

- **Rate-limit `/auth/forgot`**: new `app/middleware/rate_limit.py` exposes a small Redis sliding-window helper (`ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` → `EXPIRE`) as a FastAPI dependency. Applied to `POST /auth/forgot` with a 5 reqs / 60s / per-IP policy. 6th hit returns 429 with the standard error envelope + `Retry-After` seconds. `X-Forwarded-For` left-most entry is honoured so per-IP works behind Caddy. New `RateLimitedError` AppError + new `RATE_LIMIT_EXCEEDED` code; the existing AppError handler grew an `extra_headers` hook so the 429 carries `Retry-After` without forking the envelope path. Falls back to no-op when `REDIS_URL` is unset (dev sans docker-compose still works).
- **Cleanup of stale `password_reset_token` rows**: new `password_reset_service.cleanup_expired_tokens(session, *, now)` deletes rows where `(used_at IS NOT NULL AND used_at < now - 7d) OR (expires_at < now - 1d)` in a single statement; returns the deleted row count. New `app/cli/cleanup_tokens.py` entrypoint (`uv run python -m app.cli.cleanup_tokens`) connects via `MIGRATION_DATABASE_URL` (BYPASSRLS — this is a cross-tenant chore). New `make cleanup` Makefile target wraps it; deployment runbook §9a documents the crontab line `30 4 * * * cd /opt/fabric && make cleanup >> /var/log/fabric-cleanup.log 2>&1`. No Celery, no scheduler library — per CLAUDE.md Phase-1 sync stance.

Verification: backend `uv run pytest -q` ran 814 passed (was 805) — the 9 new tests live in `tests/test_auth_forgot_rate_limit.py` (3) and `tests/test_password_reset_cleanup.py` (6). Backend `ruff check .` + `ruff format --check .` + `mypy .` all clean. Frontend `pnpm tsc --noEmit`, `eslint`, `prettier --check`, `check:types` (OpenAPI snapshot drift gate) all clean. OpenAPI snapshot regenerated + spec updated with the 429 response on `/auth/forgot`.

## Deviations from plan

### 1. New rate-limit tests contaminated the existing `/auth/forgot` integration suite

Plan: ship 3 rate-limit tests + 3 cleanup tests, both files self-contained. Reality: introducing a global rate limit on `/auth/forgot` meant `tests/test_password_reset.py`'s 7 sequential forgot calls (all from the same `testclient` peer) cumulatively tripped the 5/min ceiling. The first 5 tests passed; tests 6–8 returned 429.

- **Fixed by:** added an autouse `_reset_forgot_rate_limit` fixture to `test_password_reset.py` that clears `ratelimit:auth.forgot:*` keys around each test. Reads the URL from `get_settings().redis_url` (not `os.environ`) because pydantic-settings loads `.env` without re-exporting to the process env.
- **Why not caught in planning:** the brief read as "rate-limit forgot" without flagging the suite-level coupling. Should have grepped `tests/test_password_reset.py` for the forgot-call count before deciding the policy was orthogonal.
- **Impact on later tasks:** zero. The fixture is local to that one file.

### 2. Module-level Redis client cached across pytest event loops

First impl cached the lazily-built `aioredis.Redis` at module scope. Worked for one test, then broke every subsequent test with `Event loop is closed` because pytest-asyncio creates a fresh loop per test and the cached client was bound to the loop from test 1.

- **Fixed by:** in `app/middleware/rate_limit.py`, dropped the prod-side module cache — `_get_redis` now returns `aioredis.from_url(...)` fresh per request. The `aioredis` connection pool is keyed per-URL inside the library, so the per-call overhead is one pool-lookup, not a TCP handshake. Test-injection path (`set_redis_client_for_testing`) is still module-global on purpose: tests want a single fakeredis instance.
- **Why not caught in planning:** matched the `IdempotencyMiddleware` pattern (which DOES cache per-instance), but missed that this caches at module scope rather than middleware-instance scope. The middleware version is fine because each `TestClient` builds a new app + new instance.
- **Impact on later tasks:** zero. Documented inline in the module so a future "let's cache for perf" PR can read why caching is intentionally absent.

### 3. `Result.rowcount` doesn't show up on the generic `Result` type

`session.execute(delete(...))` returns a `CursorResult` at runtime but a `Result` in the type stubs; `Result` doesn't expose `rowcount`. mypy red.

- **Fixed by:** `int(getattr(result, "rowcount", 0) or 0)` with a short comment. Avoids a cast + keeps the runtime contract explicit.
- **Why not caught in planning:** SQLAlchemy 2.x type stubs are stricter than the 1.4 ones; first time this codebase has done a bulk DELETE returning rowcount.
- **Impact on later tasks:** zero. If we add more bulk-DML services, factor into a small helper.

## Things the plan got right (no deviation)

- Per-IP keying (not per-(IP, email)) is the right grain. The follow-up retro flagged email-pump as the threat; that's exactly the per-IP shape.
- `Retry-After` derived from the OLDEST surviving entry — when that ages out, the caller has at least one slot back. Polite-client SLA holds without over-engineering.
- `make cleanup` + crontab is sufficient. No Celery scaffold needed; the cleanup is a single SQL DELETE, runs in O(seconds), and is idempotent.
- `extra_headers` on `AppError` is a clean extension point — easy to reuse for future codes (e.g. `WWW-Authenticate` on a future 401-with-challenge).
- 5 req / 60 s threshold is comfortable for legitimate use (a user fat-fingering their own email + retrying lands well under 5/min) but tight against the email-pump abuse vector.

## Pre-TASK-(NNN+1) checklist

### 1. Broader rate-limit follow-up

Apply the same helper to `/auth/login` (brute-force throttle) + `/auth/signup` (sign-up flood). Out of scope here per the brief's Ask-vs-Decide note. The helper is generic — `rate_limit(bucket="auth.login", max_requests=10, window_seconds=60)` is the literal line. File as `TASK-CUT-501b` (or whichever post-Wave-6 slot Moiz prefers).

### 2. Wire the crontab on the prod box

Adding the crontab line is a one-time manual step on `app.taana.in`. The deployment runbook has the line; the operator needs to run `crontab -e` and paste it. Until then, `password_reset_token` will grow unbounded (slowly — a few rows / month for a one-org dogfood). Not urgent; flag in the next prod deploy walk.

### 3. Acceptance run for the rate-limit path on the dev stack

`make dev` → `for i in $(seq 1 6); do curl -X POST http://localhost:8000/auth/forgot -H 'Content-Type: application/json' -d '{"email":"a@b.c","org_name":"x"}'; done` should print 5×200 then 1×429 with `Retry-After`. Not a regression suite worth — it's covered by `test_auth_forgot_rate_limit.py` — but a useful smoke check before the next cutover demo.

## Observable state at end of task

- `make cleanup` is the new operator-facing entry point. Running it in dev is a safe no-op (empty table); first prod run will probably delete 0 rows because dogfood hasn't accumulated any used+7d-old or expired+1d-old rows yet.
- New env-var dependency: none. The CLI reuses `MIGRATION_DATABASE_URL` (already required for `alembic upgrade head`).
- No schema changes. No new tables. The `password_reset_token` table is the same as TASK-CUT-303 left it.
- OpenAPI snapshot file (`frontend/scripts/openapi-snapshot.json`) + generated types (`frontend/src/types/api.ts`) were regenerated to surface the new 429 response on `/auth/forgot`. CI's `check:types` drift gate is green.
- `specs/api-phase1.yaml` updated for `/auth/forgot` with the 429 response + `Retry-After` header.
- New `RATE_LIMIT_EXCEEDED` enum value in `app/exceptions.ErrorCode`. The frontend's `lib/api/client.ts` envelope-handler doesn't special-case 429 yet — it'll surface as a generic toast. If we add an "auto-retry after `Retry-After`" path in the FE, that's a future task.
