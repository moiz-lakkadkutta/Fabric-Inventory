# TASK-CUT-006 retro — Wave-1 integration hot-fix

**Date:** 2026-05-10
**Wave:** 1 (post-merge integration)
**PRs landed before this:** #55 CUT-002, #56 CUT-005, #57 CUT-004, #58 CUT-003, #59 CUT-001

## What broke

After all 5 Wave-1 PRs merged to `main`, `pnpm test` (Vitest) showed **17 failures across 7 files**, but each individual PR had passed CI in isolation. Two distinct root causes, neither caught by per-PR CI:

1. **`<RequireAuth>` (CUT-004) blocks every protected-route test.** Tests rendering `<App />` or pages mounted under `<AppLayout>` with no explicit `authStore.setMe(...)` setup hit the `'unknown'` placeholder and never see the page content. CUT-004's `useAuthBootstrap` mock-mode synth runs in `useEffect`, so it fires AFTER the test's first synchronous `getBy*` assertion.

2. **Local `.env` divergence between dev box and CI.** This dev box had `frontend/.env` with `VITE_API_MODE=live` (set during the audit for browser dogfooding). Vitest loads `.env` by default in `mode=test`, so on this machine tests ran with `IS_LIVE=true` — every `useInvoices()` etc. branched into the live-API path that queries a non-existent backend in jsdom, and CUT-001's new `QueryError` component rendered (correctly) in place of the expected mock data. CI passes because CI has no `frontend/.env` at all.

## What shipped

Three small additions, no behavior change in production code:

- **`frontend/src/test-setup.ts`** — added a global `beforeEach` that pre-populates `authStore` with a mock-mode `me` payload. Mirrors the existing `useAuthBootstrap` mock synth, but applied SYNCHRONOUSLY so first-render assertions don't have to await an effect.
- **`frontend/.env.test`** — pins `VITE_API_MODE=mock` for vitest runs so tests are deterministic regardless of what a dev sets in `frontend/.env` for browser dogfooding. Vitest's `loadEnv` resolves `mode=test` and applies this AFTER `.env`, overriding it.
- **`frontend/src/components/layout/__tests__/UserMenu.test.tsx`**, **`FirmSwitcher.test.tsx`**, **`components/auth/__tests__/RequireAuth.test.tsx`**, **`store/__tests__/auth.test.ts`**, **`lib/queries/__tests__/invoices.live.test.ts`** — added `beforeEach(() => authStore.reset())` to override the new global pre-populate for tests whose assertions depend on the empty/unknown initial state. The existing `afterEach(() => authStore.reset())` stays for cleanup symmetry.

## TDD discipline

This was a hot-fix, not a feature, so a fresh failing test → minimum impl → green wasn't possible — the failures were the tests themselves. The work was: identify the regression, write the smallest fix that flips them green, verify the fix doesn't introduce silent test-skipping (every previously-passing test still passes; no tests were quarantined).

Final state: **30 test files, 111 tests, 0 failures, 0 skipped.**

## Why this didn't fail per-PR CI

CI runs each PR's diff against `main`. Each Wave-1 PR's CI was green because:
- CUT-004 added new tests that explicitly populate `authStore`; the auth-gate change to `App.tsx` isn't exercised by CUT-004's own test diff.
- CUT-001 / CUT-003 / CUT-002 / CUT-005 don't touch tests that happen to render `<AppLayout>` end-to-end.

The integration regression only surfaces when all 5 PRs land together AND the auth-gate change in `App.tsx` interacts with pre-existing tests authored before the gate existed.

## Pre-Wave-2 checklist (unblocks the next wave)

- [x] All Wave-1 PRs merged to `main`: #55, #56, #57, #58, #59
- [x] Hot-fix CUT-006 merged
- [x] `pnpm test` green on `main`
- [x] `make lint` green
- [ ] **Pending:** Moiz runs `docs/ops/wave-1-demo.md` (10 min browser walk) — gates Wave 2 spawn

## Process improvement for future waves

The audit's "wave-acceptance gate" predicted exactly this: per-PR CI is necessary but not sufficient. Going forward, after every wave's last merge, the parent (Claude) MUST run `make test` + `make lint` on `main` HEAD before declaring the wave gate-ready. If a regression like this surfaces, file a hot-fix TASK-CUT-NNN before writing the wave-demo doc. Captured this in `docs/ops/cutover-plan-2026-05-10.md`'s "Wave structure" notes.

Also flagging: the audit found `VITE_API_MODE=live` in `frontend/.env` and didn't anticipate it would bleed into tests. The new `.env.test` is a permanent fix for this class of bug.
