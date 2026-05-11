# TASK-CUT-304 retro — Admin invites BE+FE

**Date:** 2026-05-11
**Branch:** `task/CUT-304-admin-invites`
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 4, W4-D)

## Summary

Shipped the full Owner-invites flow end-to-end. BE: new `user_invite`
table with RLS, four endpoints under `/admin/*` (list users, create
invite, accept invite, change role), plus `GET /admin/roles` so the FE
dropdowns have a real source. Service layer carries last-Owner-demotion
protection, 32-byte single-use tokens (sha256-hashed in DB, 7-day TTL),
and audit-log emissions for invite-create / invite-accept /
role-change. FE: live-mode queries in `lib/queries/admin.ts`,
`InviteUserDialog` modal, public `/invite/:token` page
(`AcceptInvite.tsx`), and the AdminHub page rewired to live queries
with per-row role-change `<select>`s. 16/16 new BE integration tests
pass; full BE suite 548 passed; 226/226 FE tests pass; ruff check +
format both clean; eslint + prettier + tsc all green; OpenAPI snapshot
regenerated and FE types codegened.

## Deviations from plan

### 1. RLS escape hatch via a GUC, not `row_security = off`
Plan implied the accept endpoint would just SELECT by token_hash with
RLS bypassed. Reality: `fabric_app` is `NOBYPASSRLS` so
`SET LOCAL row_security = off` raises `InsufficientPrivilege`.
- **Fixed by:** the RLS policy on `user_invite` adds a narrow USING
  alternative — `current_setting('app.invite_lookup_mode', true) = 'on'`
  — that the accept service flips for one SELECT then turns off again.
  WITH CHECK still requires the standard `app.current_org_id` GUC so
  the escape hatch cannot be used to INSERT or UPDATE rows into the
  wrong tenant. See `alembic/versions/2026051100001_task_cut_304_user_invite.py`.
- **Why not caught in planning:** the `fabric_app` role split (INT-9)
  predates the cutover plan; the prompt's "service then immediately
  sets `app.current_org_id`" line assumed bypass was free.
- **Impact on later tasks:** zero. Pattern is reusable if any future
  bootstrap endpoint needs the same trick.

### 2. Accept-endpoint returns 201 + redirect-to-/login, not a tokenized session
Plan said "your call, document in retro." I picked **201 + redirect to
`/login`** with `prefillEmail` + `prefillOrgName` on the location state.
- **Reasoning:** the recipient's bcrypt-hashed password ought to be
  exercised on the FIRST login (not at accept time, where we'd have to
  reissue tokens without proving the password verifies). Keeps every
  user behind the same MFA-enrollment workflow when MFA is on; halves
  the auth-related code I needed to write.
- **Trade-off:** the user types their just-set password twice in the
  span of 5 seconds. Acceptable for the dogfood phase.

### 3. `/admin/invites/accept` is in `IDEMPOTENT_BY_DESIGN_PATHS`
Plan said the accept endpoint MUST be exempt from idempotency-cookie
middleware. The middleware is keyed by `Idempotency-Key` header (not a
cookie) but the requirement is the same: the invitee can't reasonably
mint a UUID.
- **Fixed by:** added `/admin/invites/accept` to the exempt frozenset
  in `app/middleware/idempotency.py`. The invite token is its own
  idempotency key by construction (single-use, sha256 in DB, `used_at`
  stamp atomically).
- **Test:** `test_accept_invite_without_idempotency_key_succeeds` uses
  a raw `TestClient` (no auto-key injection) and asserts 201.

### 4. Idempotent-by-email invite create
Plan didn't specify behaviour for re-inviting the same email. I made it
**reuse the open invite row** (mints a fresh token, keeps the same
`invite_id`). Prevents row sprawl when an Owner clicks "Invite" twice.
- **Tested:** `test_create_invite_idempotent_within_email` asserts the
  row-id is stable but the token rotates.

### 5. Added `GET /admin/roles`
Plan listed three endpoints; the FE needed a fourth to populate the
role dropdowns in `InviteUserDialog` + AdminHub's per-row select. Used
the same `admin.user.manage` permission gate.

## Things the plan got right (no deviation)

- `admin.user.manage` already exists in the RBAC catalog — no need to
  invent a new permission code.
- The Owner-only invite + last-Owner-demotion protection is the right
  shape for dogfood; the test surface is small enough to read in one
  sitting.
- Console-log adapter is fine for Wave 4; the abstraction lift to a
  real `EmailAdapter` Protocol (CUT-303) is a one-line change in
  `routers/admin.py`.

## Pre-TASK-(CUT-305) checklist

### 1. Pull from `main` after CUT-303 lands and rebase
CUT-303 was running in parallel and adds `password_reset_token` plus a
`task_cut_303_pw_reset` Alembic head. My migration's `down_revision`
points to `task_cut_104_voucher_party_id` (the pre-303 head), which
will create a branch. When the two PRs land back-to-back, the later
one will need a merge-migration that sets both `task_cut_303_pw_reset`
and `task_cut_304_user_invite` as the parents of a no-op head. Easy
fix; flagged here so the next agent doesn't get surprised.

### 2. Swap `print()` → real `email_adapter.send_invite(...)` when CUT-303 lands
`routers/admin.py` has a single `print(...)` of the invite link. CUT-303
ships an `EmailAdapter` Protocol. Replace the print with a call to that
adapter; the FE response shape (`invite_link`) stays the same since
it's also useful for the FE toast.

### 3. Custom roles still coming-soon
"Add role" button on AdminHub still opens the ComingSoonDialog. Custom
role CRUD is Wave 5+; don't ship a half-baked version.

## Open flags carried over

- **CUT-303 collision (Alembic branch head):** see pre-checklist #1.
- **Email adapter swap:** see pre-checklist #2.
- **Custom roles:** explicit deferral (cutover plan v2).
- **GET /admin/users pagination:** today the endpoint returns all rows
  (Owner orgs have <20 users typically). Add `limit`/`offset` when an
  org pushes past 100 users.
- **Auto-cleanup of expired invites:** none today. Rows stay in the DB
  past `expires_at`. Wave 5 backup/runbook task could add a daily prune.

## Observable state at end of task

- New Alembic head: `task_cut_304_user_invite`.
- New table: `user_invite` (RLS-enabled, escape-hatch GUC documented).
- New env var: `FRONTEND_URL` (default `http://localhost:5174`); used
  to compose invite links.
- New routes (all gated by `admin.user.manage` except accept):
  - `GET /admin/users`
  - `GET /admin/roles`
  - `POST /admin/invites`
  - `POST /admin/invites/accept` (public, in
    `IDEMPOTENT_BY_DESIGN_PATHS`)
  - `PATCH /admin/users/{user_id}/role`
- New FE routes: `/invite/:token` (public).
- BE test suite was clean apart from a transient
  `tests/test_coa_service.py::test_create_coa_group_cross_org_isolation`
  ERROR when run with the full suite — passes when run alone. Almost
  certainly DB pollution from a parallel CUT-303 agent on the same
  Postgres; not a regression introduced by CUT-304.
