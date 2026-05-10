# TASK-CUT-003 retro — Onboarding wizard wire to /auth/signup

**Date:** 2026-05-10
**Branch:** `task/CUT-003-onboarding-signup-wire`
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` — Wave 1, Agent W1-C
**Audit driver:** `docs/ops/platform-audit-2026-05-10.md` § P0-3

## Summary

The onboarding wizard now actually creates an account. Step 1 collects org name, contact email, and the new password field; step 2 collects firm name, tax regime, GSTIN (with auto-derived state code from the GSTIN's first two chars), and an explicit state code input that stays editable; step 3 keeps the existing opening-balance choice but labels the Vyapar option as "(coming soon — TASK-CUT-402)". "Commit & finish" posts to `/auth/signup`, hydrates `authStore.accessToken` + `authStore.me` via the new `useSignup` hook, then navigates to `/`. Errors (e.g., `USER_EMAIL_TAKEN` 409, validation 422) surface inline using the `ApiError.title`.

13 new tests added (4 unit tests for `liveSignup` in `lib/queries/__tests__/identity.live.test.ts`, 9 integration tests for the wizard in `pages/auth/__tests__/Onboarding.test.tsx`). All 97 frontend tests pass with `VITE_API_MODE=mock` (the suite default). Lint clean. Typecheck clean.

## Deviations from plan

### 1. Integration test is Vitest+RTL, not Playwright

The task spec said "Playwright test FIRST". The repo's actual convention (every existing test) is Vitest + Testing Library, and there is no Playwright config in the tree yet — Wave-1 agent CUT-001 is also creating one in parallel. I wrote the integration test using Vitest + RTL because:

- It's the project convention.
- It exercises the full wizard mount → form fill → submit → assert URL + assert `authStore` directly (better than Playwright's indirect window probing).
- It runs in 230 ms inside the unit-test runner with no extra service to start; CI doesn't need Playwright browsers installed for this acceptance check.

I also added a `frontend/__tests__/e2e/cut-003-onboarding.spec.ts` Playwright spec (matching CUT-001's directory layout and a cloned `playwright.config.ts`). It is `test.describe.skip(...)` for now because it depends on the `__FABRIC_FORCE_LIVE__` runtime hook that CUT-001 lands. Once both PRs merge, drop the `.skip` and it runs against the real dev server.

- **Fixed by:** see new test files. The Vitest test is the primary acceptance gate; the Playwright spec is the e2e equivalent for when CUT-001's mode-override hook is in place.
- **Why not caught in planning:** the task prompt template's "Playwright OR Vitest with rendered component" alternation made it a judgement call; the audit's emphasis on Playwright "fresh load of /onboarding" pulled it the other way. Going with the project's existing convention to keep the diff small.
- **Impact on later tasks:** none. The acceptance criteria all pass via the Vitest test today.

### 2. State code is also editable when GSTIN is present

Plan said "auto-fill, user can override." Implementation is exactly that: typing a GSTIN with a 2-digit prefix populates `state_code`, but the input field stays editable. There's no lock or sync after that — once auto-fill happens, the user can type anything in. The simpler "GSTIN → state code" lock-step would have surprised users (e.g., correcting a typo in GSTIN later would silently overwrite their manually-typed state code).

- **Why not caught in planning:** the plan implied a one-way bind; the actual UX needed a one-shot auto-fill. This is what the audit's "auto-fill, user can override" wording meant.
- **Impact on later tasks:** none.

### 3. Vyapar import option kept (labelled "coming soon"), not removed

Plan offered "removed OR labelled". Kept it labelled because:

- CLAUDE.md decision #5 says Vyapar is the *primary* migration adapter — removing the affordance entirely from the only place a user sees migration options would re-create work later.
- Wave 5's TASK-CUT-402 wires the actual import.
- The label "(coming soon — TASK-CUT-402)" is precise about both timing and what it ties to.

- **Impact on later tasks:** TASK-CUT-402 should remove the "(coming soon — TASK-CUT-402)" suffix when shipping the real adapter.

### 4. `vi.mock('@/lib/api/mode')` in the integration test to force live mode

The codebase tree-shakes the live branch on `import.meta.env.VITE_API_MODE === 'live'` at build time. The Vitest test runner inherits the dev-server's env, so `IS_LIVE` is `false` when running with the suite default `VITE_API_MODE=mock`. The signup-wire-up tests need the live branch.

- **Fixed by:** `vi.mock('@/lib/api/mode', () => ({ API_MODE: 'live', IS_LIVE: true, IS_MOCK: false }))` at the top of `Onboarding.test.tsx`. The mock must be hoisted before the `Onboarding` import — done via dynamic `await import` after the mock declaration.
- **Why not caught in planning:** the plan glossed over how to force live mode in tests; this is the standard Vitest pattern.
- **Impact on later tasks:** future live-mode tests (CUT-101 parties, CUT-102 items, etc.) can use the same hoisted-mock pattern. Could factor a `forceLiveMode()` helper but each test file has only one mock so it's currently inline.

### 5. Excluded `__tests__/e2e/**` from Vitest

Adding the Playwright spec under `frontend/__tests__/e2e/` made Vitest pick it up via its default glob. Added an `exclude` rule to `vite.config.ts` so vitest only runs unit/integration tests; `pnpm run e2e` runs Playwright.

- **Why not caught in planning:** the e2e directory was new — first time vitest's default glob extended to it.
- **Impact on later tasks:** none. The exclude rule is permanent.

## Things the plan got right (no deviation)

- The `useSignup` shape mirrors `useLogin` exactly (lines 72-93 in `identity.ts`). Token storage in `authStore.setAccessToken` → `/auth/me` fetch → `authStore.setMe` is the same sequence, no new abstractions needed.
- Backend's `/auth/signup` accepted the body shape this PR sends without any backend changes — `email`, `password`, `org_name`, `firm_name`, `state_code`, optional `gstin`, `Idempotency-Key` UUID v4.
- The `Idempotency-Key` UUID generation via `crypto.randomUUID()` (per the plan note) is what the backend's `IdempotencyMiddleware` expects.
- Refresh-token cookie is httpOnly with `Path=/auth` per backend `routers/auth.py:75` — the FE legitimately only needs `access_token`. Confirmed.

## Pre-TASK-CUT-004 checklist

### 1. CUT-004 needs to land the `<RequireAuth>` gate

After CUT-003 merges, `/onboarding` puts `authStore.me` in place but the protected routes still don't gate on it (audit P1-4). When CUT-004 lands, ensure the redirect on signup success continues to work:
- Onboarding posts → 201 → fetch /me → `setMe` → `navigate('/')`.
- `<RequireAuth>` should see `status: 'authenticated'` immediately because `setMe` flips it synchronously.
- If CUT-004 introduces an async hop (e.g., `useAuthBootstrap` re-runs), wrap onboarding's `navigate('/')` in a `waitFor` against `authStore.status === 'authenticated'`.

### 2. Drop the `.skip` on the Playwright spec when CUT-001 lands

`frontend/__tests__/e2e/cut-003-onboarding.spec.ts` uses `__FABRIC_FORCE_LIVE__` which CUT-001 introduces in `lib/api/mode.ts`. After CUT-001 merges:
1. Verify `__FABRIC_FORCE_LIVE__` is in `lib/api/mode.ts`.
2. Change `test.describe.skip(...)` to `test.describe(...)` in the spec.
3. Run `pnpm run e2e` locally to confirm the test passes against the dev server.

### 3. CUT-005 spike on Vyapar source format

The wizard now labels Vyapar import as "coming soon — TASK-CUT-402". The CUT-005 spike picks `.vyp` vs Excel-export. Once decided, TASK-CUT-402 ships the adapter and removes the "coming soon" suffix.

## Open flags carried over

- **Phone field is UI-only.** No backend column for it yet (`firm` table has no `phone`). Carrying as cosmetic — could fold into firm settings when admin/firm-edit ships in a later wave.
- **PAN field is UI-only.** Same situation — backend `firm.pan` is encrypted bytea, but signup doesn't accept PAN. PAN entry will live in admin → firm settings (future).
- **`importMode` is recorded in form state but no-ops on submit.** That's intentional today — the wizard sign-up is decoupled from the migration import flow per the audit. CUT-402 wires the actual import endpoint.
- **No password strength meter / confirm-password field.** Backend min-length is 8 chars; the field has `autoComplete="new-password"` so browsers may show their own meter. Could revisit in a UX polish pass post-cutover.

## Observable state at end of task

- New module exports: `useSignup`, `liveSignup`, `SignupInput`, `SignupResult` from `frontend/src/lib/queries/identity.ts`.
- New file: `frontend/src/lib/queries/__tests__/identity.live.test.ts` (4 unit tests).
- New file: `frontend/__tests__/e2e/cut-003-onboarding.spec.ts` (skipped Playwright, awaits CUT-001).
- New file: `frontend/playwright.config.ts` (cloned from CUT-001 branch's identical config to minimise merge conflicts).
- Modified: `frontend/src/pages/auth/Onboarding.tsx` (+170 lines: password field, state code field, useSignup wire, error UI).
- Modified: `frontend/src/pages/auth/__tests__/Onboarding.test.tsx` (rewritten — 9 tests covering wizard state, fields, Vyapar labelling, signup happy path, and 409 error).
- Modified: `frontend/vite.config.ts` (exclude `__tests__/e2e/**` from vitest).
- Default form state is now empty (no more "Rajesh Patel Holdings" pre-fill); audit P1-5 said dev pre-fill is fine, but it didn't apply to onboarding (which is meant for fresh signups). Removed entirely.

### Verified

- `pnpm run test` (with `VITE_API_MODE=mock`, the suite default): 97/97 pass, 26 files.
- `pnpm run test --run src/lib/queries/__tests__/identity.live.test.ts src/pages/auth/__tests__/Onboarding.test.tsx`: 13/13 pass.
- `pnpm run lint`: clean.
- `pnpm run typecheck`: clean.

### Not verified (out of scope or blocked)

- Live e2e against `:8000` — backend `:8000` is wedged per audit P0-1; backend signup verified curl-only via the audit's sidecar uvicorn. Not re-verified here because no backend code changed.
- Playwright spec — skipped pending CUT-001's runtime live-mode hook.
- Cross-browser — only chromium configured in `playwright.config.ts`.
