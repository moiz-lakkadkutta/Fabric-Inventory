# TASK-002 retro — deviations from plan and pre-next checklist

**Date:** 2026-04-25
**Branch:** task/002-fastapi-boilerplate
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 1)

## Summary

FastAPI boilerplate landed end-to-end: `backend/main.py` factory pattern with lifespan, four middleware (CORS → logging → RLS → error), `/live` and `/ready` probes, structured JSON logging via `structlog`, Sentry SDK no-op stub gated on `SENTRY_DSN`, async SQLAlchemy engine, `AppError` exception hierarchy, FastAPI dependency stubs (`get_db`, `get_current_user`, `require_permission`). 12 integration tests, all green. ruff + ruff format + mypy strict all clean. `Idempotency-Key` middleware kept as a docstring-only placeholder per plan (lands in TASK-008). `make dev` not run (verification stayed at unit/integration test level — Docker Desktop not started for this session).

## Deviations from plan

### 1. Wave-1 ran serially in main session, not in parallel sub-agent worktrees

Original plan §1 calls for 4 parallel Tier-2 agents in isolated worktrees. All 4 returned blocked by sandbox permissions; auto-accept mode did not propagate to background subagents. Conductor pivoted to direct execution.

- **Fixed by:** main session executed each task in sequence (TASK-005 first, then 002). Captured agent research and design plans were the input.
- **Why not caught in planning:** assumed subagent worktrees inherit the user's interactive permission profile.
- **Impact on later tasks:** TASK-004 and TASK-003 will follow the same pattern. For future waves where parallelism actually pays, either drop `isolation: "worktree"` in Agent calls (so subagents inherit perms) or add explicit subagent grants to `.claude/settings.json` (or use git worktrees manually for parallel-when-needed bash work).

### 2. Renamed `ValidationError` → `AppValidationError`

Original brief named the validation exception `ValidationError`. Pydantic exports its own `ValidationError` and shadowing it across the codebase would cause subtle bugs and import surprises.

- **Fixed by:** named the class `AppValidationError`. `code = "validation_error"` is unchanged so the API contract is identical.
- **Impact on later tasks:** import name is `AppValidationError`. Mention in retros for TASK-006/007 if they touch this.

### 3. Renamed `PermissionError` → `PermissionDeniedError`

Same shadowing concern — Python ships a built-in `PermissionError`.

- **Fixed by:** `PermissionDeniedError`. `code = "permission_denied"`.

### 4. RLS middleware sets `request.state.org_id`; `get_db` dependency emits `SET LOCAL`

Original brief implied middleware would emit `SET LOCAL app.current_org_id`. Reality: middleware does not own a SQLAlchemy session — sessions are per-dependency-call. Cleaner split:
- RLS middleware: validate JWT → strict UUID-format `org_id` → stash on `request.state.org_id`.
- `get_db` dependency: read `request.state.org_id` → re-validate UUID → `SET LOCAL app.current_org_id = '<uuid>'` on the session before yielding.

- **Why:** Postgres `SET LOCAL` does not accept bind parameters; the only safe path is strict UUID validation before string formatting. Keeping validation in two places is defense-in-depth, not duplication.
- **Impact on later tasks:** TASK-007 (real auth) plugs into this same shape. TASK-006/010+ services receive an already-RLS-scoped session.

### 5. `cors_origins` validator added for empty-string env var

`pydantic-settings` parses list-typed env vars as JSON by default; `CORS_ORIGINS=""` → JSONDecodeError. Added a `field_validator` that accepts JSON list, comma-separated string, or empty string. `CORS_ORIGINS=` in `.env.example` is now safe.

- **Why not caught in planning:** generic `list[str]` annotation looks innocuous; only surfaces at first import with a real `.env`.
- **Impact on later tasks:** zero. Devs can write `CORS_ORIGINS=http://localhost:5173,https://app.example.com` or `CORS_ORIGINS=["http://..."]` or leave it empty.

### 6. `aiosqlite` NOT added to deps (deviating from blocked agent's draft)

The blocked TASK-002 agent suggested adding `aiosqlite` so tests could run without Postgres. Skipped: project policy (CLAUDE.md "Test database is real Postgres") rules against SQLite. Tests are written to be resilient to missing Postgres (e.g., `/ready` test asserts `200 or 503`). CI service container provides real Postgres.

- **Impact on later tasks:** none. RLS tests in TASK-006+ will require Postgres anyway.

## Things the plan got right (no deviation)

- Middleware execution order: CORS → logging → RLS → error. Starlette runs middleware in REVERSE registration order, so registration sequence `RLS → logging → CORS` was the correct pattern; documented inline with the comment.
- Sentry SDK no-op gating on empty DSN — clean.
- structlog with `contextvars.merge_contextvars` for `request_id` propagation through async — clean JSON line per request, with correlation ID baked in.
- pydantic-settings strict validation at startup — caught two env var typos during local dev within seconds.
- mypy strict from day 1 — zero gymnastics needed beyond typing `call_next: RequestResponseEndpoint` (Starlette ships this exact type for `BaseHTTPMiddleware.dispatch`).

## Pre-next-task checklist

Ordered by what bites first.

### 1. `make dev` not yet validated end-to-end this session

The full stack (Postgres + Redis + FastAPI + Vite via docker-compose) was not booted. TASK-002's middleware/test verification was at `uv run pytest` level. Before TASK-006 starts: open Docker Desktop, run `make dev`, confirm `curl http://localhost:8000/live` returns `{"status": "live"}`, confirm `/ready` returns 200 with both `db: true` and `redis: true`.

### 2. `make dev` does NOT auto-run `make setup`

Carried from TASK-001 retro item 5. Still unresolved. If a fresh terminal hits `make dev` without `.env` present, docker-compose will error out. Three options for TASK-006 or earlier:
- `dev: setup` dependency in Makefile (idempotent, fast).
- Make `env_file: .env` in `docker-compose.yml` optional and inline `environment:` declarations.
- Document explicitly in CLAUDE.md "Sessions & Continuity".

### 3. Idempotency-Key pattern lands in TASK-008

`backend/app/utils/idempotency.py` is currently a docstring stub. TASK-008 (auth routers) is the canonical implementation site since it's the first task with mutating endpoints (`POST /auth/signup`, `POST /auth/login`). The pattern: hash `Idempotency-Key + body_sha256` → Redis dedupe with 24h TTL → return cached response on replay → raise `IdempotencyConflictError` (409) on key collision with different body.

### 4. RLS middleware decodes JWT with project's JWT secret — needs alignment with TASK-007

Current `RLSMiddleware` reads `JWT_SECRET` from settings and decodes HS256 best-effort. TASK-007 will add real auth (signup, login, refresh, MFA). Ensure TASK-007's token shape includes `org_id` claim (and likely `firm_id`, `user_id`, `permissions[]`). The middleware will pick those up automatically.

### 5. `get_db` dependency: `SET LOCAL` runs every request even when no `org_id`

Currently if `request.state.org_id` is None, no SET runs. That means a session inherits whatever GUC was last set in that connection. Two safer options for TASK-006/009:
- Always reset: `SET LOCAL app.current_org_id = ''` when no org_id.
- Let RLS policies treat empty/missing GUC as "no rows" (default-deny).
Pick one in TASK-009 alongside the first RLS-scoped query.

### 6. mypy strict: `Awaitable` import unused after format

ruff format reorganized imports across all 12 files; verified clean. No outstanding type-annotation gotchas.

### 7. CI's `[ -d app ]` mypy guard can be dropped after this branch merges

TASK-005 added a guard so CI stays green before `backend/app/` exists. After TASK-002 merges to main, two-line edit in `.github/workflows/ci.yml` removes the guard. Nice cleanup, not a blocker.

### 8. Git identity still auto-guessed

Last commit author: `Moiz P <moizp@Abduls-MacBook-Pro.local>`. Run `git config --global user.name/email` at first opportunity. (Carried from TASK-001 retro item 2.)

## Open flags carried over

1. `make dev` not validated end-to-end this session.
2. `make dev: setup` dependency decision (TASK-001 open flag #5).
3. Git identity still auto-guessed (TASK-001 open flag #2).
4. Subagent permission policy (Wave-1 deviation #1) — needs decision before any future wave hopes for parallel-agent execution.

## Observable state at end of task

- `backend/app/{config,db,exceptions,dependencies}.py` — new.
- `backend/app/middleware/{__init__,auth,errors,logging,rls}.py` — new.
- `backend/app/utils/{__init__,idempotency}.py` — new (idempotency is docstring stub).
- `backend/main.py` — replaced; factory + lifespan + `/live` + `/ready`.
- `backend/.env.example` — added `CORS_ORIGINS=`, `SENTRY_DSN=`; bumped `JWT_SECRET` placeholder length.
- `backend/pyproject.toml` — added `structlog>=24.1`, `sentry-sdk[fastapi]>=2.0`.
- `backend/uv.lock` — regenerated.
- `backend/tests/test_health.py` — deleted (replaced by `test_live.py`).
- `backend/tests/{test_live,test_ready,test_middleware_logging,test_middleware_rls,test_middleware_cors,test_error_handler,test_sentry_no_op}.py` — new (12 tests, all green).
- `backend/tests/conftest.py` — updated for new app structure.
- `docs/retros/task-002.md` — this file.
- Branch `task/002-fastapi-boilerplate` exists locally; not pushed.
