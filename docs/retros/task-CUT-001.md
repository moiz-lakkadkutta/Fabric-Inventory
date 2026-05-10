# TASK-CUT-001 retro — CORS via Vite proxy + invoice-list error copy + login pre-fill cleanup

**Date:** 2026-05-10
**Branch:** `task/CUT-001-cors-and-error-copy`
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 1 W1-A)

## Summary

Closed three Wave-1 audit findings in one PR:

1. **P0-2 CORS.** Added a Vite same-origin proxy at `/api` that forwards to the FastAPI backend (`VITE_API_TARGET` env, defaults to `http://localhost:8000`). `frontend/.env.example` now ships `VITE_API_BASE_URL=/api` so all `lib/api/client.ts` calls hit the proxy and inherit cookies + Authorization without CORS preflight. The backend allowlist is untouched per the task brief.
2. **P1-1 invoice-list error copy.** `QueryError` no longer hard-codes "the mock layer hiccupped". It accepts an `error` prop and surfaces `code: detail` plus a monospaced `request_id: <uuid>` line for `ApiError` envelopes; renders a generic "Network error — couldn't reach the server" for non-envelope failures (CORS, DNS, offline). `InvoiceList` passes `invoicesQuery.error` through.
3. **P1-5 login pre-fill.** `Login.tsx` defaults are now gated by `import.meta.env.DEV && !window.__FABRIC_TEST_NO_PREFILL__`. Production builds render an empty form. The "Remember this device" checkbox stays.

Tests: 92 vitest unit (was 88, added 4 — one Login pre-fill test, three QueryError envelope/network/no-mock-layer tests). Two new Playwright e2e tests at `frontend/__tests__/e2e/cut-001-error-states.spec.ts` cover the runtime error-state and the suppressed pre-fill. `make lint` clean (ruff + mypy + eslint + prettier + tsc). Backend pytest unaffected (119 passed, 500 skipped — same baseline).

## Deviations from plan

### 1. Set up Playwright config + browsers in this task

The plan listed Playwright as already wired (per CLAUDE.md tech stack). The repo had `@playwright/test` in `package.json` but no `playwright.config.ts`, no e2e tests, and no installed browsers in this worktree.

- **Fixed by:** new `frontend/playwright.config.ts` (chromium-only project, runs Vite as `webServer` with `VITE_API_MODE=live`); ran `pnpm exec playwright install chromium chromium-headless-shell` once. The `make e2e-setup` target already installs browsers system-wide.
- **Why not caught in planning:** the cutover plan and audit assumed Playwright was already runnable; reality is the click-dummy phase shipped without ever wiring an e2e suite.
- **Impact on later tasks:** zero — config is in place for future CUT tasks. Vitest excludes `__tests__/e2e/**` so `pnpm test` doesn't import `@playwright/test`.

### 2. Added `request_id` to the Q8a envelope on the FE side

The audit didn't mention that `lib/api/errors.ts:Q8aEnvelope` was missing `request_id`, but the BE has been emitting it (and the new error copy needs it).

- **Fixed by:** added optional `request_id?: string` to `Q8aEnvelope` + `ApiError`, and `decodeError` now also reads `x-request-id` response header as a fallback for non-JSON bodies.
- **Why not caught in planning:** assumed the FE type already mirrored the BE shape.
- **Impact on later tasks:** positive. Future error-rendering UIs in waves 2-4 can rely on `error.request_id` without redoing the plumbing.

### 3. Window kill-switch instead of `vite build` to test the prod-equivalent login

The acceptance criterion said "test loads `/login` with `import.meta.env.DEV=false`". `import.meta.env.DEV` is a build-time literal that flips when the bundle is built via `vite build`, not via runtime config.

- **Fixed by:** Login reads both signals — `import.meta.env.DEV && !window.__FABRIC_TEST_NO_PREFILL__`. Playwright sets the window flag via `addInitScript`; Vitest sets it on the global `window`. Production builds skip pre-fill regardless because `DEV=false` short-circuits.
- **Why not caught in planning:** the prompt's "or whatever your gating uses" left the implementation choice open; the kill-switch is the lighter path.
- **Impact on later tasks:** zero — flag is local to `Login.tsx` and tests.

## Things the plan got right (no deviation)

- "Don't touch backend CORS allowlist" was correct; the proxy makes that work obsolete.
- The QueryError component was a single-file change and the only `mock layer` site reachable in the live UI.
- The Vite proxy preserves cookies and auth headers — confirmed by reading `client.ts` and `auth.ts`; httpOnly cookie path `Path=/auth` is preserved because the proxy only rewrites the prefix, not the response Set-Cookie.

## Pre-TASK-CUT-002 checklist

Ordered by what will bite the next agent first.

### 1. The `frontend/.env` user file is still pointed at `http://localhost:8000`

`make setup` now copies `frontend/.env.example` → `frontend/.env` if missing, but Moiz's existing local file is unchanged. He needs to either delete `frontend/.env` (so `make setup` re-copies) or hand-edit `VITE_API_BASE_URL=/api` and add `VITE_API_MODE=live` if he wants the live branch.

### 2. CUT-002 (idempotency cookie strip) is purely backend; doesn't touch any of CUT-001's surface

Runs in parallel without merge conflicts. Same for CUT-003/004/005. Wave 1 spawn order doesn't matter.

### 3. The `__FABRIC_TEST_NO_PREFILL__` window flag is a TEST AFFORDANCE, not a feature

Don't grow it into a runtime toggle. If a real "open the login form pre-filled for QA" feature lands later, give it a dedicated query-string flag with its own Login component branch.

### 4. The Playwright base config assumes port 5173

If a future task starts a second dev server on the same machine, set `PLAYWRIGHT_PORT` in the test environment. The webServer block has `reuseExistingServer: !process.env.CI` so local re-runs are fast.

## Open flags carried over

- **Backend CORS allowlist still says `http://localhost:5173` only.** The Vite proxy means browser calls don't trigger CORS, but native `curl localhost:8000` from any other origin still hits the same wall. Fine for dev. Wave 5 (Caddy + HTTPS) will deal with prod origin handling.
- **No protected-route gate.** `<RequireAuth>` is W1-D's task (CUT-004). My Playwright test for `/sales/invoices` works because the route is currently public; that test will need a small adjustment in CUT-004 to mint a fake auth token before navigation.
- **Vitest exclude pattern.** I added `__tests__/e2e/**` to `test.exclude`. Other future test directories may need the same treatment.

## Observable state at end of task

- New file: `frontend/playwright.config.ts` (chromium project + webServer with `VITE_API_MODE=live`).
- New file: `frontend/__tests__/e2e/cut-001-error-states.spec.ts` (2 tests).
- New retro: `docs/retros/task-CUT-001.md` (this file).
- Modified: `frontend/vite.config.ts` (proxy + vitest exclude), `frontend/.env.example` (proxy URL + mode), `Makefile` (frontend `.env` bootstrap), `frontend/src/components/ui/query-error.tsx` (rewritten), `frontend/src/components/ui/__tests__/EmptyState.test.tsx` (3 new tests), `frontend/src/lib/api/errors.ts` (request_id field), `frontend/src/pages/sales/InvoiceList.tsx` (pass error), `frontend/src/pages/auth/Login.tsx` (gated pre-fill), `frontend/src/pages/auth/__tests__/Login.test.tsx` (1 new test).
- Playwright browsers (`chromium-1217`, `chromium_headless_shell`) installed at `~/Library/Caches/ms-playwright/`. ~600MB on disk. `make e2e-setup` is the documented installer.
- Vite dev server reuses port 5173 by default; killed any prior instance from earlier QA.
