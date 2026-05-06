# TASK-INT-7 retro — dev-stack stabilization (P0-1, P0-2)

**Date:** 2026-05-06
**Branch:** `task/INT-7-dev-stack`
**Plan:** in-conversation `/grill-me` master plan, INT-7 section.

## Summary

Closed both halves of the 2026-05-06 QA outage:

1. **P0-1 (env pollution).** Added `make doctor` which probes `/live`, `/ready`, compose health, alembic head, env-file presence, and prints the redacted effective `DATABASE_URL`. It exits 0 on healthy, 1 with a named diagnostic on failure. Added `make dev-native` which scrubs the shell env (`env -i`) and sources `backend/.env` before launching uvicorn — making the parent-shell-pollution mode of failure structurally impossible.
2. **P0-2 (empty schema).** Wired `alembic upgrade head` into both paths: `backend/entrypoint.dev.sh` runs migrations before uvicorn in the compose `api` service, and `scripts/dev-native.sh` does the same before launching native processes.

`backend/.env.example` now also defines `MIGRATION_DATABASE_URL` so INT-9 (RLS role split) lands cleanly without changing the template again. `alembic/env.py` reads it (falling back to `DATABASE_URL`).

Test/lint state: `pytest` 92 passed, 481 skipped (skipped are integration tests that need DB-backed auth fixtures, unchanged); `ruff check` clean; `mypy` clean; `scripts/test_doctor.sh` green against both healthy (`:8001`) and unreachable (`:1`) APIs.

## Deviations from plan

### 1. `test_config.py` regression surfaced and fixed

Plan said "no refactor expected" for INT-7. Reality: the moment `make setup` started writing `backend/.env`, the existing `test_cors_origins_non_dev_empty_raises` started passing values from disk into Settings and the "fail-fast" assertion stopped firing.

- **Fixed by:** `_build_settings()` now passes `_env_file=None` so unit tests load only the env vars they explicitly set.
- **Why not caught in planning:** the test passed historically only because `backend/.env` happened to be absent; my QA pass already created it, so the regression was on tomorrow's clock anyway.
- **Impact on later tasks:** zero — this is a one-line, isolated fix.

## Things the plan got right (no deviation)

- Compose-only as `make dev`, native as `make dev-native`, both auto-migrate, both pre-flight `/ready`. The split is exactly what was needed.
- `MIGRATION_DATABASE_URL` in `.env.example` keyed up INT-9 cleanly.
- Static-analysis tests for `dev-native.sh` / entrypoint were the right call — booting them in tests is heavy and the assertions read like documentation.

## Pre-INT-8 checklist

### 1. Stop and re-launch the user's broken `:8000` uvicorn (or kill it)

The QA-pass clean uvicorn on `:8001` still serves; the user's original `:8000` process is still polluted with docker-internal hostnames. Once they restart it from a clean shell it'll pick up the new `backend/.env` (now with `MIGRATION_DATABASE_URL`) and `make doctor` will report green at `:8000`. Until then, integration tests targeting the API should use `FABRIC_API_URL=http://localhost:8001`.

### 2. INT-8 will need the request-context middleware before any other handler

The envelope handler reads `request.state.request_id`. Add the request-context middleware first (registers `request.state.request_id = uuid4()` and stamps the `x-request-id` header), then write the failing test for the validation envelope.

### 3. INT-8 should not run `migrate-create` — no schema changes

INT-8 is pure middleware + handler work; `make migrate-create` not needed. Save the schema-change discipline for INT-9 and INT-11.

## Open flags carried over

- **Compose entrypoint not booted in this session.** I changed `Dockerfile.dev` and added `entrypoint.dev.sh`, but didn't run `make dev` to validate the image rebuilds and `alembic upgrade head` actually executes inside the container. The static tests assert the wiring; first real exercise is whoever next runs `make dev` from clean.
- **`scripts/dev-native.sh` not booted in this session.** Same reason — booting it forks long-lived processes. First exercise is the next dev who needs hot-reload.

## Observable state at end of task

- New executable scripts: `scripts/doctor.sh`, `scripts/dev-native.sh`, `scripts/test_doctor.sh`, `backend/entrypoint.dev.sh`.
- New tests: `backend/tests/test_setup.py` (4 cases).
- Modified: `Makefile` (new `dev-native`, `doctor` targets; `setup` writes `backend/.env`), `backend/.env.example` (now includes `MIGRATION_DATABASE_URL` + comments), `backend/.env` (mirrored), `backend/Dockerfile.dev` (entrypoint), `backend/alembic/env.py` (reads `MIGRATION_DATABASE_URL` first), `backend/tests/test_config.py` (`_env_file=None` in `_build_settings`).
- A clean uvicorn QA process is still running on `127.0.0.1:8001` (PID was `69831`; the process inherits no shell env). Safe to leave running through INT-8.
- The user's original uvicorn on `:8000` is still running but still broken. Doesn't block INT-8 since INT-8 is pure code change verifiable against `:8001`.
