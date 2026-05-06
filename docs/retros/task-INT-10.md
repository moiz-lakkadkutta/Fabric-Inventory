# TASK-INT-10 retro — auth shape (P1-3, P1-4, P1-5, P3 refresh-key)

**Date:** 2026-05-06
**Branch:** `task/INT-10-auth-shape`
**Plan:** in-conversation `/grill-me` master plan, INT-10 section.

## Summary

The auth surface now matches the /grill-me Q6 contract: the FE can complete
login in one round-trip, logout/refresh accept the HttpOnly cookie alone,
duplicate-email signups return the spec'd 409 envelope, and refresh is
exempt from the `Idempotency-Key` requirement (it's intrinsically idempotent).

- `LogoutRequest.refresh_token` and `RefreshRequest` are now optional;
  routes accept body OR cookie. Body still wins when explicitly provided
  (preserves the "access token in body → 400" diagnostic path).
- `LoginResponse` mirrors `SignupResponse` shape: `org_id`, `firm_id`
  (auto-populated when user has exactly one firm), `available_firms`
  list. Drops the FE's `/auth/me` follow-up.
- New `EmailTakenError` (`USER_EMAIL_TAKEN`, status 409). Signup checks
  email-in-org first, falls through to org-name uniqueness for the
  email-not-collision case.
- `IdempotencyMiddleware` exempts `/auth/refresh` via a new
  `IDEMPOTENT_BY_DESIGN_PATHS` allowlist.

6 new tests in `test_int10_auth_shape.py`; full suite 590 passed; ruff +
mypy clean.

## Deviations from plan

### 1. Body-then-cookie precedence (not cookie-only)

Plan implied "cookie always wins." Reality: an existing test
(`test_logout_with_access_token_returns_400`) sends an access token in
the body to verify the 400 diagnostic. Cookie-takes-all would make the
cookie hide the test's body and the diagnostic disappears.

- **Fixed by:** `body.refresh_token if body and body.refresh_token else
  fabric_refresh`. Body wins when explicit; cookie is the fallback.
- **Why not caught in planning:** I framed the change as cookie-canonical
  but didn't enumerate the existing tests that depend on body precedence
  for diagnostic semantics.
- **Impact on later tasks:** zero.

### 2. Login response mirrors signup, but firm_id auto-populates from `len(firms) == 1`

Plan said "auto-populate when user has exactly 1 firm." Implementation
reads from the firm list directly (without an explicit firm-membership
check). For dogfood + early customers this is correct because Owners
see every firm in their org; non-Owner refinement (UserFirmScope) lands
later. Recorded as a sub-flag for INT-12.

- **Why not caught in planning:** the plan's "exactly one firm" was
  ambiguous about firm-vs-membership scoping; will need attention when
  RBAC firm-scoping ships.

## Things the plan got right (no deviation)

- The `IDEMPOTENT_BY_DESIGN_PATHS` allowlist is a clean exit for
  intrinsically-idempotent operations. Future endpoints (`/auth/me`-as-
  POST, etc.) can opt in by adding to the set.
- Per-org email model holds up: same email + different org now
  documented and tested as intentional.
- New `USER_EMAIL_TAKEN` code keeps `VALIDATION_ERROR` reserved for
  generic Pydantic body validation (per INT-8's contract).

## Pre-INT-11 checklist

### 1. INT-11 needs a fresh GST migration

Schema additions: `2110/2120/2130` ledger seeds in `seed_service`,
`gstr1_section` column on `sales_invoice`, `tax_status` column on `firm`.
Use `make migrate-create M="..."` to scaffold.

### 2. CA-VALIDATED-PENDING comment in `gst_service.py`

Per /grill-me Q7, INT-11 marks the place-of-supply engine for CA review
without blocking on it. Concrete sentinel: `# CA-VALIDATED-PENDING: <date>`
+ a TODO listing edge cases (mixed exempt/taxable lines, NIL_LUT export).

### 3. Update QA `qa-manual-test.md` 5.10/5.11 for IGST-always

INT-12 owns the doc rewrite. The /grill-me record stands as truth: inter-
state is always IGST regardless of value; the 2.5L threshold is a GSTR-1
filing-section flag (`gstr1_section: B2CL | B2CS`).

## Open flags carried over

- **Refresh-token JTI rotation in DB**: `_resolve_org_by_name` already
  seeds the GUC, but if the lookup raises `InvalidCredentialsError`
  before SET LOCAL, no transaction state lingers. Cleanup happens via
  rollback. Would benefit from a regression test once the rate-limiter
  lands (TASK-017).
- **Multi-firm `firm_id` auto-population**: when a user has > 1 firm
  visible (Owner of an org with multiple firms), `firm_id` returns
  null and the FE's firm-picker handles the choice. Add a regression
  test in INT-12 once the UI ships.

## Observable state at end of task

- New: `app/exceptions.py` defines `EmailTakenError` + `USER_EMAIL_TAKEN`
  code. `app/middleware/idempotency.py` exposes
  `IDEMPOTENT_BY_DESIGN_PATHS`. `app/schemas/auth.py` has the new
  LoginResponse fields.
- Modified: `app/routers/auth.py` — signup email-then-org check, login
  populates new fields, logout/refresh accept cookie-only.
- New tests: `backend/tests/test_int10_auth_shape.py` — 6 cases.
- Branch successfully merged from main after INT-9 landed; no merge
  conflicts on auth.py despite both branches editing it (different
  sections).
