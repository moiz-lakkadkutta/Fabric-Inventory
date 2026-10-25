# fix-sign-out retro: "Sign out" left the session alive

## Summary

Found while recording the flow films. The user menu's "Sign out" only
navigated to `/login`. It never called `POST /auth/logout`, so the refresh
cookie stayed valid and the next page load could silently restore the
session on a shared shop computer. `useLogout` already existed but nothing
used it.

Fix: Sign out calls `useLogout` (revokes the refresh token and the access
token server-side, clears the cookie), then goes to `/login` whether or not
the call succeeds. `liveLogout` now clears local identity in a `finally`.

## Deviations from plan

None. Frontend only; the backend logout endpoint was already correct.

## Things the plan got right (no deviation)

- The backend revokes the bearer token up front, independent of the
  refresh-token outcome, so a partial failure can't leave it alive.

## Pre-next-task checklist

### 1. Live-mode logout has no direct unit test

`liveLogout` is selected by the module-level `IS_LIVE` constant, which the
test setup doesn't flip. The UserMenu tests cover the call; an E2E sign-out
→ reload → still-on-login check would cover the rest.

## Open flags carried over

- None.

## Observable state at end of task

- `UserMenu.test.tsx` +1 test (fails on the old code); frontend 604/604, tsc, eslint, prettier clean.
