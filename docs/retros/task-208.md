# TASK-208 retro — deviations from plan and pre-next checklist

**Date:** 2026-09-02
**Branch:** fix/issue-208
**Commit:** `<pending>` (NOT merged — PENDING MOIZ SIGN-OFF)
**Plan:** GitHub issue #208 (implementation-plan comment)

## Summary

Fixed two onboarding defects. (a) Email identity is now case-insensitive
end-to-end: one `identity_service.normalize_email` helper (trim + lowercase)
is applied at every write (signup, invite, register_user, org.admin_email)
and every lookup (login, mfa-verify, service login, password-reset,
invite existing-user checks) via `func.lower(...) == normalized`. An Alembic
migration (`t208_email_lowercase`) backfills `app_user.email`,
`user_invite.email`, `organization.admin_email` to lowercase behind a
fail-closed collision pre-check, and adds a `(org_id, lower(email))` unique
index (`uq_app_user_org_lower_email`). (b) The signup token now carries the
sole firm's id (`firm_id=firm.firm_id`), and mfa-verify got the same
single-firm auto-select as login, so firm-scoped endpoints work straight off
the token instead of 403'ing "No active firm".

Verification: 12 new integration tests pass; 168 tests across the affected
auth/invite/reset suites pass; ruff check + format clean; mypy clean on the
4 changed modules; migration upgrade + downgrade round-trip verified on
test_208; index confirmed present.

## Deviations from plan

### 1. `down_revision` chains off `190_voucher_posting_unique`, not `f2_ap_payment_schema`
The plan text (written against `main`) said `down_revision = "f2_ap_payment_schema"`.
The actual head in the integration worktree is `190_voucher_posting_unique`
(the #190/#192 merge batch landed after the plan was drafted).
- **Fixed by:** set `down_revision = "190_voucher_posting_unique"` in
  `alembic/versions/2026090200002_t208_email_lowercase.py`; migration revision id is `t208_email_lowercase`.
- **Why not caught in planning:** plan drafted before the concurrency batch merged.
- **Impact on later tasks:** none; orchestrator rebases if another migration lands first.

### 2. Collision pre-check fired during TDD on the shared test DB
The RED run of `test_db_unique_index_blocks_mixed_case_duplicate` raw-inserted
`IDX-208@X.COM` alongside `idx-208@x.com` while no index existed yet, leaving a
case-variant duplicate in `test_208`. The migration's fail-closed pre-check then
correctly refused to run.
- **Fixed by:** hand-deleted the polluting uppercase row, then re-ran the migration.
  This actually validated the pre-check works as designed.
- **Impact on later tasks:** none.

## Things the plan got right (no deviation)

- Exact file:line citations for every lookup/write site were accurate.
- The auto-firm fix (`firm_id=firm.firm_id`) needed no permission rework —
  Owner role is org-wide, snapshot carries the full permission set.
- Keeping the existing case-sensitive constraint + adding the lower() index
  (rather than replacing) was the right backward-compatible call.
- `str.lower()` (not `casefold()`) keeps Python and SQL `lower()` byte-identical.

## Open flags carried over

- **Ask-vs-Decide gate: PENDING MOIZ SIGN-OFF.** Auth/security change (login
  matching, token contents) + schema change (backfill + unique index). D1
  (case-insensitive identity), D2 (belt-and-suspenders index), D3 (mfa_verify
  auto-firm) all implemented with recommended defaults; do NOT merge until Moiz
  signs off on the PR.
- Prod/dogfood `make migrate` will hit the same pre-check — if it finds real
  case-variant duplicate accounts, Moiz must soft-delete the orphan (they may
  own vouchers/audit rows — never auto-merge) before the migration runs.

## Observable state at end of task

- New migration head on this branch: `t208_email_lowercase`.
- test_208 is migrated to that head with the index present.
- No frontend / OpenAPI / DDL-file changes (Alembic owns the delta).
