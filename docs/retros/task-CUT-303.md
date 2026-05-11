# TASK-CUT-303 retro — Forgot-password BE+FE

**Date:** 2026-05-11
**Branch:** task/CUT-303-forgot-password
**Plan:** none (Wave-4 vertical slice per `docs/ops/cutover-plan-2026-05-10.md` W4-C)

## Summary

Shipped the full forgot-password loop end-to-end:

- BE: new `password_reset_token` table (Alembic migration, RLS on, audit-sweep exempt), `password_reset_service` with `request_reset` + `consume`, `email_adapter` Protocol with a `ConsoleEmailAdapter` (dev — prints to stdout) and `RecordingEmailAdapter` (tests). New `POST /auth/forgot` + `POST /auth/reset` routes wired into the existing auth router; both added to `IDEMPOTENT_BY_DESIGN_PATHS` so they're exempt from the Idempotency-Key middleware (consistent with /auth/login + /auth/signup per CUT-002). One new error code: `INVALID_RESET_TOKEN`.
- FE: `Forgot.tsx` upgraded from click-dummy to live (adds an Organization field, calls `useForgotPassword`); new `ResetPassword.tsx` at `/reset/:token` reads the org from `?org=` query string and submits both back; `useForgotPassword` / `useResetPassword` hooks in `lib/queries/identity.ts` with mock/live branches. Routes registered as public (outside `<RequireAuth>`).
- Tests green: 8 new pytest integration tests against migrated Postgres (`backend/tests/test_password_reset.py`), all 226 frontend vitest tests pass (4 new in `Forgot.live.test.tsx` + `ResetPassword.test.tsx`, 2 updated in `Forgot.test.tsx` to wrap in QueryClientProvider).
- Lint clean: `uv run ruff check . && uv run ruff format --check .` both green; `pnpm tsc --noEmit && pnpm exec eslint . && pnpm exec prettier --check .` all green.
- OpenAPI snapshot regenerated; `/auth/forgot` and `/auth/reset` documented in both the FE codegen source and `specs/api-phase1.yaml`.

## Deviations from plan

### 1. `/auth/reset` body grew an `org_name` field

The CUT-303 brief proposed `POST /auth/reset { token, new_password }`. The runtime model has RLS enabled on `password_reset_token` (it's a tenant-scoped table), and `fabric_app` runs NOBYPASSRLS — meaning a SELECT-by-hash on the consume path returns zero rows unless `app.current_org_id` is set first. Chicken-and-egg: we can't seed the GUC without the org, and we can't read the org without the GUC.

- **Fixed by:** the reset link is built as `${FRONTEND_URL}/reset/${token}?org=<urlquoted org_name>`. The `/reset/:token` page reads the org from the query param and submits all three (`token`, `org_name`, `new_password`) to `/auth/reset`. The service uses `org_name` to seed the RLS GUC before looking up the token row. Documented in `password_reset_service.py` module docstring.
- **Why not caught in planning:** the brief assumed the standard "token alone is enough" pattern from systems without RLS; in our environment the RLS layer is part of the security boundary, and any tenant-table lookup needs the GUC seeded.
- **Impact on later tasks:** none. The token still carries 32 bytes of entropy; knowing the org alongside is not a secondary auth factor (it's a routing hint), and an attacker who guesses both has already won via the token alone.

### 2. Existing `Forgot.test.tsx` (mock-mode UI tests) needed a `QueryClientProvider` wrapper

Once the page wires `useForgotPassword`, the existing tests that just `fireEvent.click` the submit button would fail to render without a `QueryClientProvider` in scope. They were also synchronous, but the mutation `onSettled` callback fires on a microtask, so the transition to the confirmation state needed a `waitFor`.

- **Fixed by:** updated `Forgot.test.tsx` to wrap with `QueryClientProvider` + use `waitFor` on the confirmation copy.
- **Why not caught in planning:** the brief said "two new vitest integration tests", which I read as additive; in practice the existing mock-mode tests needed a small migration to stay green.
- **Impact on later tasks:** zero.

## Things the plan got right (no deviation)

- `EmailAdapter` as a `Protocol` with one method is sufficient; widening it for welcome/MFA/invite later is non-breaking.
- 32-byte url-safe secret + sha256 hash + 30-min TTL + single-use is the right shape; matches the established `UserInvite` pattern (CUT-304 will land it similarly).
- `INVALID_RESET_TOKEN` as the single error code (no leakage between expired vs used vs garbage) mirrors `INVALID_CREDENTIALS` on login — same posture for the same threat model.
- `IDEMPOTENT_BY_DESIGN_PATHS` was the right extension point for the middleware exemption; no new middleware needed.
- `org_id`-scoped RLS policy with `NULLIF(...,'')::uuid` matches the rest of the schema, no special-casing.

## Pre-TASK-(NNN+1) checklist

### 1. Rate-limit `/auth/forgot` (5 req/min/IP)

The brief flagged this as nice-to-have ("use Redis ZADD-style sliding window if a primitive exists; else file a follow-up"). The Redis primitive doesn't exist in this codebase yet, so this is the follow-up: spin a small `rate_limit_service` (sliding window via `redis.zadd` + `zremrangebyscore`) and apply it to `/auth/forgot` and `/auth/reset`. Without it, an attacker can churn through token mints and hammer the email adapter.

### 2. Real email provider (Wave-5 / CUT-405)

The `ConsoleEmailAdapter` is dev-only by design. The Wave-5 task swaps it for a Mailgun / Postmark / Resend impl by calling `set_email_adapter(...)` at app boot from `main.create_app`. No service-layer changes required — the Protocol is the seam.

### 3. Cleanup job for expired/used `password_reset_token` rows

Not security-critical (used rows can never be replayed) but hygiene. A daily Celery beat (Wave-5+) running `DELETE FROM password_reset_token WHERE used_at IS NOT NULL OR expires_at < NOW() - INTERVAL '7 days'` keeps the table bounded.

### 4. Forgot/Reset E2E in Playwright

Add a `forgot-password.spec.ts` that exercises the full loop against the dev stack (live Postgres + console adapter; the test reads the stdout of the uvicorn log to extract the link). Wave-4 demo doc workflow assumes this works manually; adding it to the Playwright suite would catch any regression in the link-format or RLS-seed plumbing.

## Observable state at end of task

- New env var: `FRONTEND_URL` (defaults to `http://localhost:5173`). Staging / prod set this explicitly so the reset link points at the right origin.
- New alembic head: `task_cut_303_pw_reset` (depends on `task_cut_104_voucher_party_id`). Migration must run before the new endpoints are reachable; `make migrate` does it.
- Dev workflow for the reset link: `make dev` (uvicorn logs to stdout) → request a reset → grep `[email_adapter] PASSWORD RESET LINK` in the API container logs. The link is printed with a banner so it's easy to eyeball.
- New entity_type in `audit_log`: `auth.password` (action: `reset`). Adds to the existing `auth.session` (signup/login/logout/switch-firm/mfa-verify) family.
- The Vyapar / Tally migration adapters and accounting domain are untouched.
