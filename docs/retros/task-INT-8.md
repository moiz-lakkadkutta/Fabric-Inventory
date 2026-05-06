# TASK-INT-8 retro — error envelope completion (P1-2, P1-9)

**Date:** 2026-05-06
**Branch:** `task/INT-8-error-envelope`
**Plan:** in-conversation `/grill-me` master plan, INT-8 section.

## Summary

Every 4xx/5xx response now returns the canonical Q8a envelope —
`{code, title, detail, status, field_errors, request_id}` — including
the FastAPI `RequestValidationError` path that QA caught slipping
through as raw `{detail: [...]}`. `field_errors` is a flat dotted-key
map (`body.lines.0.qty`, `path.sales_invoice_id`) per the /grill-me Q4
contract; the leading `body|path|query|header` segment is preserved so
the FE can route the error to a form field vs a banner.

`request_id` is now generated in a pure-ASGI `RequestContextMiddleware`
that runs OUTSIDE the BaseHTTPMiddleware chain. Both the response
header (`X-Request-ID`) and every error body's `request_id` field read
the same value from `scope["state"]`. P1-9 closes here.

7 new tests in `test_validation_envelope.py`; full backend suite at 95
passed / 481 skipped (skipped == DB-fixture integration, unchanged);
ruff + mypy clean.

## Deviations from plan

### 1. `request.state` doesn't propagate from `BaseHTTPMiddleware` to exception handlers

Plan said: "stash request_id on `request.state` from a new middleware,
exception handlers read from there." Reality: Starlette's
`BaseHTTPMiddleware` constructs an internal Request and propagates
`scope` but NOT `request.state` mutations to the exception-handler
dispatcher. So setting `request.state.request_id` inside
LoggingMiddleware (a `BaseHTTPMiddleware`) was invisible to error
handlers; they minted a fresh UUID each time.

- **Fixed by:** new `app/middleware/request_context.py` — a pure ASGI
  middleware (not `BaseHTTPMiddleware`) that writes directly to
  `scope["state"]["request_id"]` and stamps `X-Request-ID` via a `send`
  wrapper. Registered as the OUTERMOST app-internal middleware (just
  inside CORS) so the id is set before any `BaseHTTPMiddleware` wraps
  the request. LoggingMiddleware now READS, never generates.
- **Why not caught in planning:** I didn't probe Starlette's middleware
  contract carefully enough — assumed `request.state` propagation
  worked across both middleware styles. It does not.
- **Impact on later tasks:** zero, but worth noting in
  `architecture.md` someday — pure-ASGI middleware is the right tool
  whenever `scope` mutations need to be visible to exception handlers.

### 2. Pytest fixture indirection masked the validation handler

When I built the test app inside an async fixture (`@pytest.fixture
async def envelope_client`), my custom `RequestValidationError` handler
didn't fire — FastAPI's default raw-`{detail}` response came back
instead. Same code in an inlined `async with _app_with(...)` context
manager (no fixture indirection) works correctly.

- **Fixed by:** dropped the fixture, wrote `_app_with` as an
  `asynccontextmanager` invoked inside each test body. Tests are
  per-test isolated; cheaper than tracking down the Starlette / pytest
  / asyncio interaction.
- **Why not caught in planning:** I assumed async fixtures worked the
  same as inlined async contexts. They do for routes; they do not for
  exception-handler dispatch in this combination of versions.
- **Impact on later tasks:** zero, but if INT-9/10/11 want to share
  test setup, prefer a context-manager helper over a pytest fixture
  for the AsyncClient/app pair.

### 3. `IdempotencyMiddleware` cached cross-test responses by Idempotency-Key

A constant `Idempotency-Key` across 7 tests served the FIRST test's
cached body (with its request_id pinned) to the others — broke
`test_request_id_in_body_matches_header` because the header rotated
per-request but the cached body did not. By design, the middleware
caches 422s as "intent-deterministic" (T-INT-1 CRIT-1), so this is
correct production behavior; the test had to adapt.

- **Fixed by:** `_idemp_key()` mints a fresh UUID per request.
- **Impact on later tasks:** mild — every future router test that
  hits the same path more than once needs unique keys. INT-10 (auth
  shape) will run into this for `/auth/refresh` and `/auth/logout`.

## Things the plan got right (no deviation)

- Flat dotted keys with the `body|path|query|header` prefix — tested
  cleanly in 4 separate cases (body root, body nested, path UUID,
  malformed JSON) and the same map shape handles all four.
- Single `_envelope()` helper in `errors.py` keeps every handler on
  the same shape; future handlers can't drift.
- Existing `AppError`/`Exception` handlers absorbed the new
  `request_id` field with a one-line change.

## Pre-INT-9 checklist

### 1. INT-9 needs to flip integration tests to `fabric_app` role

`tests/conftest.py` `sync_engine` fixture currently connects with
`DATABASE_URL` (the `fabric` superuser). After INT-9, the runtime
`DATABASE_URL` will use `fabric_app`. The fixture must follow,
otherwise tests run as a role that bypasses RLS and the new RLS
guarantees aren't actually exercised.

### 2. INT-9 should expect to surface latent app-layer-only filter bugs

When `fabric_app` (NOBYPASSRLS) starts driving tests, any query that
relied solely on application-level `WHERE org_id =` filtering will
break — that's the whole point. Each one becomes a sub-fix in the
INT-9 PR.

### 3. WITH CHECK audit

Before INT-9 ships, run `\d+ <table>` on every multi-tenant table
and confirm RLS policies have BOTH `USING` and `WITH CHECK` clauses.
USING-only policies let an attacker INSERT rows for another tenant.

## Open flags carried over

- **`backend/.env` propagation across CI.** INT-7's CI run will exercise
  the new `MIGRATION_DATABASE_URL` env var; if CI is set up to copy
  `.env.example` to `.env`, the new key flows through. If CI sets env
  vars directly (likely), `MIGRATION_DATABASE_URL` may be unset and
  alembic falls back to `DATABASE_URL` — works pre-INT-9, breaks
  post-INT-9 if CI uses the app role for migrations. INT-9's PR must
  update `.github/workflows/*.yml` to set `MIGRATION_DATABASE_URL`.

## Observable state at end of task

- New module: `app/middleware/request_context.py`.
- Modified: `app/middleware/errors.py` (handlers + envelope helper),
  `app/middleware/logging.py` (reads request_id, no longer generates),
  `app/middleware/__init__.py` (exports), `main.py` (registers new
  middleware), `tests/test_config.py` (port of `_env_file=None` fix
  from INT-7).
- New tests: `tests/test_validation_envelope.py` — 7 cases.
- The clean uvicorn QA process on `:8001` (PID 69831) is still running
  but does NOT have these changes loaded; it's frozen on INT-7's image.
  INT-9 may want to restart it.
