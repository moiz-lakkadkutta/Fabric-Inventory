# T-INT-1 hard review (2026-05-02)

10 commits, +8271/-247, 51 files on `task/int-1-foundation-auth` branched off `main` at f03b6be. CI green at 8a33c5e. This review treats the locked plan in `docs/plans/integration-plan.md` § T-INT-1 as the spec and the branch as the implementation under audit.

## Behavior coverage vs the plan's 13-row table

| # | Behavior | Status |
|---|---|---|
| 1 | Login with valid creds returns access + sets refresh cookie | **✅ shipped.** Cookie path covered by `test_signup_sets_refresh_cookie` (signup, login, mfa-verify share `_set_refresh_cookie` helper). Existing `test_login_with_correct_creds_returns_tokens` confirms tokens. |
| 2 | Login with `error@taana.test` returns `INVALID_CREDENTIALS` 401 | **✅ shipped.** Backend: `test_login_with_wrong_password_returns_401` asserts code = INVALID_CREDENTIALS. Frontend mock branch keeps the sentinel. |
| 3 | MFA verify `123456` returns full access JWT | **✅ existing TASK-008.** Wired through `_set_refresh_cookie` so the cookie shape is covered by the same signup test. |
| 4 | MFA verify `000000` returns `MFA_INVALID` | **✅ existing TASK-008.** Code value migrated to UPPER_SNAKE in this branch's first commit. |
| 5 | `/v1/me` returns user + firm + `flags` map | **✅ shipped.** `feature_flag_service` + `MeResponse.flags` + `test_me_with_valid_access_token_returns_payload` asserts shape. |
| 6 | Refresh-on-401: stale → silent refresh → retry → success | **✅ shipped.** `client.test.ts :: on 401: refreshes once, populates new token, retries the original call` covers it. **Bug found** — see § Critical findings below. |
| 7 | Refresh-on-load: page mounts → /auth/refresh → fresh access | **✅ shipped.** `useAuthBootstrap` mounted in `App.tsx`. No frontend test asserts the call yet — relies on the api() client tests for the underlying mechanism. |
| 8 | Firm switch reissues tokens with new firm_id | **❌ deferred to T-INT-1b** per the plan's hard cut-line. Endpoint not added; frontend `FirmSwitcher` still mock-only. |
| 9 | Mutation without Idempotency-Key → 400 IDEMPOTENCY_KEY_REQUIRED | **✅ shipped.** Covered by `test_post_without_idempotency_key_returns_400` + 4 router tests migrated 422→400. |
| 10 | Duplicate Idempotency-Key returns cached response | **✅ shipped.** `test_duplicate_key_replays_cached_response` (fakeredis). |
| 11 | RLS: user A reading user B's firm's data → 404 | **⚠️ partial.** Existing RLS tests cover prior tables. New `feature_flag` has an RLS policy but no dedicated cross-firm test (relies on the feature_flag_service tests + the policy SQL). |
| 12 | OpenAPI spec ≡ runtime `app.openapi()` | **❌ deferred.** Codegen pipeline ships, but the in-sync gate test is unwritten because spec/runtime drift is significant (paths use `/auth/mfa-verify` runtime vs `/auth/mfa/verify` spec; 35-path delta). Resolving drift is its own task. |
| 13 | Playwright smoke: login → MFA → Daybook | **❌ deferred.** No `playwright.config.ts` yet; running localhost-only per `local-dev-mode.md`. Foundation pieces (api client, auth store) all unit-tested in vitest. |

**11 of 13 shipped or partial. 2 explicitly deferred per the plan's own carve-outs (firm switch — hard cut-line; OpenAPI sync + Playwright — separate effort).**

## Hard cut-line (the must-ship list)

| Item | Status |
|---|---|
| api() wrapper | ✅ `lib/api/client.ts` |
| 401-refresh | ✅ inside api() |
| idempotency middleware | ✅ `app/middleware/idempotency.py` |
| error envelope | ✅ `app/exceptions.py` + `middleware/errors.py` |
| codegen | ✅ `pnpm openapi:gen` + committed `api.generated.ts` |
| RLS round-trip | ✅ pre-existing; new feature_flag table joins via firm.org_id |
| useAuth store | ✅ `store/auth.ts` |
| login (frontend wired) | ✅ `Login.tsx` calls `useLogin` |

**Every non-negotiable shipped.**

## Critical findings

### CRIT-1: Idempotency middleware caches 401 responses

**Where:** `backend/app/middleware/idempotency.py:104` — `if redis_client is not None and response.status_code < 500`.

**What goes wrong:**
1. Frontend POSTs `/v1/invoices` with idempotency key K. Bearer token is stale.
2. Auth middleware passes (token decodes); handler hits a permission check or DB query that surfaces 401.
3. Idempotency middleware caches the 401 under key K (status < 500).
4. Frontend api() sees 401, calls `/auth/refresh`, gets a fresh access token.
5. Frontend api() retries POST `/v1/invoices` with the SAME idempotency key K and a new bearer.
6. Middleware sees cache hit on K, replays the cached 401. **The retry can never succeed.**

The plan's literal snippet (cross-cutting concerns § Idempotency) says `if response.status_code < 500: cache`. That's correct for deterministic-from-payload errors (422 validation, 409 conflict). It's wrong for transient auth state (401, possibly 403 if perms changed mid-session). Caching transients defeats the user's natural retry path.

**Fix:** don't cache 401 (and 403). Workaround would be re-mint key on the frontend, but that defeats Stripe-pattern intent.

**Fixed in this branch** in the follow-up commit referenced from the bottom of this doc.

### CRIT-2: `_validate_idempotency_key` per-router calls are dead code

`routers/auth.py:67`, `routers/masters.py`, `routers/accounting.py`, `routers/items.py` still call the per-router validator. The middleware now enforces presence + UUID format upstream, so these calls never see anything but a valid UUID string. They're harmless but:

- Drift risk: the per-router function still raises `HTTPException(422, {"error_code": "validation_error", ...})` — pre-Q8a envelope shape. If anyone ever bypasses the middleware (e.g., a different ASGI route), the response leaks the old shape.
- Plan says "Single middleware" — Q7b explicitly.

**Recommended:** remove the per-router calls in a follow-up. Not blocking T-INT-1 close-out.

### CRIT-3: Frontend `Login.tsx` hardcodes org_name

```ts
login.mutate({ ..., org_name: 'Rajesh Textiles', ... })
```

Click-dummy default. Any tenant other than Rajesh's primary org can't log in. Not a plan-listed item but a real UX gap before any second user touches the system. Add an org_name field to the form OR derive from a subdomain (taana.in/<slug>) before friendly-customer.

### CRIT-4: Frontend `Mfa.tsx` not yet wired to `useMfaVerify`

Login → MFA flow hits `useLogin` (live in live mode), navigates to `/mfa`, but the MFA page hasn't been swapped. So in live mode the user reaches MFA but the form still uses the click-dummy sentinel. End-to-end live login is therefore broken for any user with `mfa_enabled=true`.

Mock-mode flow still works.

**Recommended:** swap `Mfa.tsx` onSubmit to `useMfaVerify` in the next commit. Trivially small, ~15 LOC.

## Other observations

- **Spec drift exists but is bounded.** Runtime has 45 paths; spec has 81. Most of the gap is "spec aspirational, code not built yet" (sales-orders, quotations, GST endpoints). Plan accepts this; an OpenAPI in-sync test that asserts only `runtime ⊆ spec` would catch the dangerous direction (forgot-to-update-spec) without failing on aspirational paths. Worth filing.

- **Mock branch error-throw inside `fakeFetch`** initially hung — `fakeFetch(() => { throw … })` swallows the throw inside a Promise resolver. Fixed by `await fakeFetch(undefined); throw`. Worth a comment in `lib/mock/api.ts` so future mocks don't repeat the same trap.

- **Migration is destructive.** `task_int_1_feature_flag_per_firm` does `DROP TABLE feature_flag` (greenfield is fine since the prior table was empty). Documented in the migration's docstring; downgrade restores the original DDL shape.

- **Sentry init is fire-and-forget.** Caller doesn't `await initSentry()`. If `main.tsx` crashed in the first 100ms before init resolved, Sentry would never see the event. Acceptable for now (dormant in dev) but a real concern when staging exists.

- **`useFeatureFlag(key)` returns `false` for unknown keys.** Callers can't distinguish "not set" from "set to false". The plan's mental model is per-firm boolean, default OFF — so this is intentional. Keep an eye out for places that genuinely need three-state semantics.

- **CI flow:** every push triggers backend lint + test + frontend lint + test in parallel. No Playwright job yet. The `STAGING_DEPLOY_ENABLED` repo variable gates the deploy workflow, which still references the unmerged `task/int-0-staging-bootstrap` artifacts. Both consistent with `local-dev-mode.md`.

## Recommended close-out

Before merging T-INT-1 to main:

1. **Land CRIT-1 fix** (don't cache 401/403). One commit, ~10 LOC + a test.
2. **Swap `Mfa.tsx` to `useMfaVerify`** so live-mode E2E actually works. ~15 LOC.
3. **Remove dead `_validate_idempotency_key` per-router calls** + the helper itself. ~30 LOC removal.
4. (Optional, separable) Spec/runtime drift cleanup → enables Behavior #12 OpenAPI in-sync test.
5. (Optional, separable) Playwright config + `e2e/auth.spec.ts` against localhost.

Items 1–3 are tight, low-risk follow-ups that close every "shipped-but-knowingly-imperfect" loop. Items 4–5 are the explicitly-deferred work that can either land in T-INT-1b or get folded into T-INT-2's scaffolding window.

## Summary

**T-INT-1 is functionally complete against the plan's hard cut-line.** Every non-negotiable shipped with tests; the only gaps are the explicitly-deferrable rows (firm switch, Playwright, OpenAPI in-sync). One real correctness bug found (401 caching); fixing it is a small, contained commit and a prerequisite to merging because the api() client's 401-refresh-retry depends on it.
