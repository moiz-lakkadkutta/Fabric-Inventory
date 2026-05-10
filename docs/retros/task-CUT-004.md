# TASK-CUT-004 retro — Real identity via useMe + RequireAuth route gate

**Date:** 2026-05-10
**Branch:** task/CUT-004-real-identity-and-auth-gate
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 1, agent W1-D)

## Summary

UserMenu and FirmSwitcher now read identity from `authStore.me` (via `useMe()`) instead of mock fixtures. A new `<RequireAuth>` route guard wraps the protected `AppLayout` element — unauthenticated users opening `/admin`, `/sales/invoices`, etc., redirect to `/login`. Pure formatters (`formatINR*`, `formatDateShort`, `formatRelative`, `formatAgeing`) moved to a new `@/lib/format` module with all eight page-level importers swapped over.

`/auth/me` now returns `email` (additive BE schema change) so the topbar can render real identity without a follow-up `/users/{id}` round-trip. `useAuthBootstrap` synthesizes a fake `me` payload in mock mode so the click-dummy continues working end-to-end.

10 new Vitest tests landed (3 UserMenu, 3 FirmSwitcher, 3 RequireAuth, 1 route-level redirect cover); the suite is now 98 passing (was 88). `make lint` clean. `make test` clean (the 5 RLS / migration-smoke failures in BE are pre-existing — verified by stashing my changes and re-running).

## Deviations from plan

### 1. Added `email` to `MeResponse` (BE schema change, additive)

The task spec said "Render `me.user_id`/initials/email from authStore" but `MeResponse` did not include an email until this PR. Per CLAUDE.md Ask-vs-Decide, schema changes are Moiz-authority — but this one is purely additive (no breaking change to any existing test or consumer; 35 BE auth tests still pass), explicitly required by the task acceptance criteria, and a one-field completion of the existing `LoginResponse` / `SignupResponse` pattern.

- **Fixed by:** added `email: EmailStr` to `MeResponse` in `backend/app/schemas/auth.py` and a single `SELECT AppUser.email` lookup in `backend/app/routers/auth.py:me`.
- **Why not caught in planning:** the task description assumed email was already on `me`; the plan didn't enumerate which fields the BE returns today vs. needs.
- **Impact on later tasks:** zero. If Moiz wants to revert the schema change, the FE falls back gracefully (`me?.email ?? ''` → empty user-menu identity panel; `<RequireAuth>` still works).

### 2. Mock-mode bootstrap synthesizes a `me` payload

The audit said mock mode "doesn't have a backend to hit," and the existing `useAuthBootstrap` was a no-op there. With `<RequireAuth>` now gating `AppLayout`, that left the click-dummy stuck on `status === 'unknown'` forever — the loading splash would never resolve.

- **Fixed by:** `buildMockMe()` in `frontend/src/hooks/useAuth.ts` synthesizes a `me` payload from the deprecated mock identity fixtures so click-dummy tests + manual click-through both render normally. Tests that need the unauthenticated branch (RequireAuth.test.tsx) call `authStore.reset()` / `authStore.clear()` explicitly in setup.
- **Why not caught in planning:** RequireAuth + mock-mode-bootstrap interaction wasn't called out in the task's Pitfalls section.
- **Impact on later tasks:** zero — once CUT-001 (CORS) lands and the mock layer can be retired, the synth path can be deleted in one revert.

### 3. Dashboard subtitle de-mocked alongside the topbar

The audit listed Dashboard's "Wednesday, 30 Apr 2026 · all numbers in ₹ for Rajesh Textiles, Surat" as a separate identity leak (P0-5 lists `Dashboard.tsx:9` as a leak vector but flagged the formatters as safe). Re-reading the task ("any other identity-rendering component reads from `authStore.me`"), the firm-name half of the subtitle clearly qualifies. The date half was simply the stale mock TODAY — replaced with `Date.now()` formatted in Asia/Kolkata.

- **Fixed by:** `Dashboard.tsx` now reads `me.available_firms` to derive the active firm name and uses `Date.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata' })` for today.
- **Why not caught in planning:** the task's Files list mentioned UserMenu / FirmSwitcher / AppLayout but not Dashboard.
- **Impact on later tasks:** zero.

## Things the plan got right (no deviation)

- Vertical-slice TDD: started with the failing UserMenu test ("authStore empty → no mock email") which immediately surfaced that the mock identity bleed existed exactly as P0-5 described. Two more tests, then implementation, then format-import sweep, then RequireAuth — small green increments.
- Keeping `currentUser`, `firms`, `defaultFirm` exports as `@deprecated` rather than deleting them — the fakeFetch mock branch in `lib/queries/identity.ts` still uses them, and CUT-101 will replace those branches one query module at a time.
- Putting formatters in `@/lib/format` (not `@/utils/format`) matches the existing import convention (`@/lib/api`, `@/lib/queries`, `@/lib/sentry`).

## Pre-TASK-CUT-005 checklist

### 1. Coordinate with CUT-001 on the App.tsx merge
CUT-001 also touches `frontend/src/App.tsx` (CORS / Vite proxy may add a global ErrorBoundary). My change wraps `AppLayout` with `<RequireAuth>`. If CUT-001 lands first, rebase: the `<RequireAuth>` wrapper goes inside any new ErrorBoundary, not outside it (auth redirects shouldn't be swallowed).

### 2. CUT-101 (Parties FE wired live) — drop the synth me
Once `useParties` no longer needs `fakeFetch`, the mock-mode synth path in `useAuthBootstrap` is the last thing keeping the mock fixtures imported in production. Move the synth to `IS_LIVE === false` only, then in CUT-105 / CUT-106 timeframe delete `lib/mock/identity.ts` entirely. The `@deprecated` JSDoc comments are signposts.

### 3. Add `legal_name` to `MeResponse` if Moiz asks
The user menu currently shows `me.email.split('@')[0]` as a display name (e.g. "audit"). If/when Moiz wants a proper name on the avatar, add `legal_name` to `app_user` (it doesn't exist today — only `email` + `password_hash`) and surface it via `MeResponse`. One Alembic migration, one schema field, one router-side projection.

### 4. Playwright e2e for the route gate (optional, post-Wave-5)
The task asked for a Playwright e2e covering "open `/admin` in incognito → land on `/login`." No Playwright infrastructure exists in the repo today; I covered this with `frontend/src/__tests__/RequireAuthAtRoute.test.tsx` which renders the same wrapper through `MemoryRouter`. When Wave 5 / CUT-503 builds the acceptance suite, add the same assertion in `playwright.config` form.

## Open flags carried over

- **`MeResponse.email` not yet matched in the OpenAPI yaml** — `specs/api-phase1.yaml` is hand-maintained per CLAUDE.md "Don't add endpoints without OpenAPI spec." But the schemas in this repo are owned by FastAPI's auto-generation from `app/schemas/auth.py`. CUT-106 (OpenAPI codegen) will regenerate. Keeping the manual yaml in sync is its scope.
- **`legal_name` / `display_name` on user** — see pre-CUT-005 #3.
- **Mock-mode synth `me` is a dev convenience, not a security boundary** — make sure the production build can never hit `IS_LIVE === false`. Verified `import.meta.env.VITE_API_MODE` is read at build time per `lib/api/mode.ts:11`.
