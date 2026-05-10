# TASK-CUT-002 retro — idempotency cookie strip + auth-by-design exemption

**Date:** 2026-05-10
**Branch:** `task/CUT-002-idempotency-no-cookie-leak`
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 1, agent W1-B
**Audit reference:** `docs/ops/platform-audit-2026-05-10.md` P0-4

## Summary

The Redis idempotency cache no longer persists `Set-Cookie` or `Authorization`
response headers, and `/auth/login` + `/auth/signup` are now in
`IDEMPOTENT_BY_DESIGN_PATHS` so their handlers always re-execute (issuing
fresh tokens) instead of replaying a cached envelope.

Two-layer fix:

1. **Auth-by-design exemption** — the primary fix. The auth handlers are
   bypassed by the middleware entirely, so a same-key replay re-runs the
   handler and rotates tokens. This eliminates the leak at the source for
   the audit's exact attack vector (`/auth/signup`, `/auth/login`).
2. **Strip-on-cache (defense-in-depth)** — for any *other* mutating
   endpoint that may emit a credential header (e.g. `/auth/switch-firm`,
   future `/auth/mfa-verify` callers, or any handler that echoes a Bearer
   token), the cache write site now drops `set-cookie` and `authorization`
   keys (case-insensitive) before `setex`. The first caller still
   receives the cookie on the wire; only the cached copy is sanitized.

Verified: 4 new tests RED then GREEN; 623 backend tests GREEN; ruff +
ruff format + mypy clean. Frontend untouched.

## Deviations from plan

### 1. One existing auth-router test was updated (expected behavior change)

`tests/test_auth_routers.py::test_signup_with_malformed_idempotency_key_rejected`
asserted that the middleware caught a malformed `Idempotency-Key` on
`POST /auth/signup` and returned `400 IDEMPOTENCY_KEY_REQUIRED`. With
`/auth/signup` now in `IDEMPOTENT_BY_DESIGN_PATHS`, the middleware
short-circuits before key validation and the handler runs successfully
(`201`).

- **Fixed by:** renaming the test to
  `test_signup_ignores_idempotency_key_per_auth_by_design_exemption` and
  asserting the new contract (`201` on a malformed key). Generic
  malformed-key coverage still lives in
  `tests/test_middleware_idempotency.py::test_post_with_malformed_key_returns_400`
  against the synthetic `/echo` route.
- **Why not caught in planning:** the task brief flagged it implicitly
  ("auth-by-design exemption must not break the cached-replay-on-422
  contract for non-auth endpoints"); the explicit signup-key-validation
  test at the auth-router layer was easy to miss.
- **Impact on later tasks:** zero. The non-auth contract is unchanged.

## Things the plan got right (no deviation)

- The audit's exact reproducer (`POST /auth/signup` then read the Redis
  cache key) translated cleanly into a test (test 4 in the new file).
  Pre-fix the second `POST /auth/signup` returned `201` with the
  cached-from-the-first-call tokens; post-fix it returns `409
  USER_EMAIL_TAKEN` because the handler re-runs and the email-already-
  exists check fires. That's the cleanest possible proof that the cache
  was bypassed.
- The case-insensitive strip-set required the test to deliberately mix
  cases (`Authorization` vs lowercase `set-cookie`). Both stripped.
- Defense-in-depth approach (exempt + strip) is correct: the exemption
  handles today's known leak, the strip prevents tomorrow's accidental
  leak from any future cookie-emitting POST.

## Pre-TASK-CUT-003 checklist

### 1. Onboarding wizard signup wire-up (CUT-003) gets fresh tokens for free

Now that `/auth/signup` is exempt, CUT-003 doesn't need to worry about a
"first signup attempt failed silently because of a stale Idempotency-Key
collision in Redis." The handler always re-executes; collisions surface
as the spec'd `409 USER_EMAIL_TAKEN`.

### 2. Other cookie-emitting routers are now safe-by-default

`/auth/switch-firm` is the only non-auth-by-design endpoint that calls
`_set_refresh_cookie`. Its `200` response was previously cacheable AND
carrying a refresh cookie, so it had the same leak signature as signup.
The strip-on-cache layer now protects it without further changes — any
follow-up that touches `switch-firm` should rely on this default rather
than re-introducing manual cookie handling.

### 3. Logout / refresh / mfa-verify already exempt or non-cacheable

`/auth/refresh` was already in `IDEMPOTENT_BY_DESIGN_PATHS` (INT-10).
`/auth/logout` and `/auth/mfa-verify` were not added to the exempt set
because they're not part of the audit's attack surface, but the
strip-on-cache layer handles their cookie emissions anyway. Punted to
TASK-CUT-NNN follow-up if a concrete attack scenario emerges.

## Open flags carried over

- **Multi-value `Set-Cookie` headers**: the strip uses
  `dict(response.headers)`, which collapses duplicate keys. Starlette's
  current code path emits at most one `Set-Cookie` per call so this is
  not a live bug, but a future change that calls `response.set_cookie`
  twice in the same handler would put one of the cookies into a
  comma-joined header that the strip filter would still catch (because
  the filter is on the key, not the value). Documented here for future
  readers.
- **`response.headers` on the rebuilt Response (line 177)** still
  contains the cookie — that's intentional, the FIRST caller must
  receive the cookie on the wire. Only the persisted copy is stripped.

## Observable state at end of task

- Modified: `backend/app/middleware/idempotency.py` — added
  `IDEMPOTENT_BY_DESIGN_PATHS` entries, `_SENSITIVE_RESPONSE_HEADERS`
  set, `_strip_sensitive_headers` helper, and the strip call at the
  cache-write site.
- Modified: `backend/tests/test_auth_routers.py` — renamed +
  re-asserted one test (see deviation #1).
- New: `backend/tests/test_idempotency_no_cookie_leak.py` — 4 tests:
  - cached headers strip `Set-Cookie` + `Authorization`
  - replay path doesn't re-emit the stripped cookie
  - `/auth/login` replay returns tokens with distinct `jti`
  - `/auth/signup` replay returns `409 USER_EMAIL_TAKEN` (proves the
    handler re-ran rather than the cache being replayed)
- New: this retro.
- No schema changes. No router signature changes. No frontend changes.
