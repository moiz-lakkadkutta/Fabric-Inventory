# TASK-066 retro — Sentry SDK wiring + /live + /ready uptime endpoints

**Date:** 2026-04-27
**Branch:** task/066-sentry-uptime
**Plan:** TASKS.md §TASK-066

## Summary

Completed wiring of the Sentry SDK stub introduced in TASK-002. Added `StarletteIntegration` and `FastApiIntegration` to `init_sentry` so unhandled exceptions are captured automatically. Added `tests/test_sentry_real_init.py` (4 tests) that monkeypatch `sentry_sdk.init` to assert correct call kwargs and integration list. Added `docs/OPERATIONS.md` with Hetzner deploy DSN instructions, `/live`/`/ready` endpoint documentation, and UptimeRobot/BetterUptime free-tier config guidance. All 399 tests pass; ruff, format, and mypy all clean.

## Deviations from plan

### 1. StarletteIntegration added alongside FastApiIntegration

Plan mentioned only `FastApiIntegration`. The Sentry FastAPI docs require `StarletteIntegration` as a prerequisite — FastAPI is built on Starlette and the integrations are layered. Added both. No impact on other tasks.

### 2. No-op tests duplicated in new file (regression guard)

The task spec asked only for "real DSN" tests in `test_sentry_real_init.py`. Two additional no-op regression guard tests (`test_sentry_real_init_no_op_for_none`, `test_sentry_real_init_no_op_for_empty_string`) were added to `test_sentry_real_init.py` — they overlap with `test_sentry_no_op.py` intentionally. This makes the new file a self-contained contract for `init_sentry` behaviour under all four inputs (None, empty, fake DSN, fake DSN + env).

## Things the plan got right (no deviation)

- `sentry-sdk[fastapi]>=2.0` was already in `pyproject.toml` — no dep change needed.
- `init_sentry` was already called in `main.py` lifespan startup — no `main.py` change needed.
- `/live` and `/ready` were already fully implemented — TASK-066 is purely verification + tests + docs.

## Pre-TASK-067 checklist

### 1. OPERATIONS.md section on Sentry is complete
`docs/OPERATIONS.md` exists and covers DSN setup, log level rotation, and secret rotation. TASK-067 adds `docs/DEPLOYMENT.md`; it can reference OPERATIONS.md rather than duplicate it.

### 2. TASK-065 still blocks TASK-067
TASK-067 is now only blocked by TASK-065 (backup runbook). Confirm TASK-065 status before starting TASK-067.

## Open flags carried over

- `/sentry-debug` dev route — deliberately excluded from production code (documented in OPERATIONS.md as a manual Phase-2 verification step). If a future task adds a dev-only router, this is the natural place for it.

## Observable state at end of task

- `docs/OPERATIONS.md` is a new file (not in any prior task).
- No new env vars required; `SENTRY_DSN` was already declared in `app/config.py` and `.env.example` (if it exists).
- All tests continue to run without a real Sentry DSN — `sentry_sdk.init` is always monkeypatched in new tests.
