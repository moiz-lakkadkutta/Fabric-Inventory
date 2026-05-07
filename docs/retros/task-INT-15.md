# TASK-INT-15 retro — audit emits + activity feed projection (P1-7)

**Date:** 2026-05-07
**Branch:** `task/INT-15-audit-emits-feed`
**Plan:** in-conversation reshuffled deferred-items list (INT-15 first
since it has no external blockers; INT-13/INT-14 wait on the CA call).

## Summary

Activity feed pre-INT-15 only carried `auth.session.switch_firm`
events — every other mutation either wrote a bespoke `AuditLog(...)`
row directly (sales.invoice.create_draft, sales.invoice.finalize,
banking.receipt.post) or didn't emit at all (signup, login, logout,
party.create, item.create). Result: a fresh org's dashboard showed
an empty feed and trained users to ignore it.

Three deliverables:

1. **`app/service/audit_service.py`** — thin `emit(...)` helper that
   wraps `AuditLog(...) + session.add`. Single seam for future
   schema changes (hash chain, async fan-out, etc.). Refactored the
   four pre-existing emits to use it so the construction shape is
   uniform across every call site.

2. **5 new emits**:
   - `auth.session.signup` — at the end of signup with the new
     org/firm/email captured in `changes.after`.
   - `auth.session.login` — non-MFA path; logs auto-selected
     firm_id when the user has only one firm (the common owner case).
   - `auth.session.login` — MFA-verify path; flagged `mfa: true` so
     the feed can distinguish.
   - `auth.session.logout` — only on actual revocation. Naked
     logouts (no cookie, no body) are idempotent no-ops and
     intentionally don't emit, so the feed isn't polluted with
     phantom logouts on app reloads.
   - `masters.party.create` and `masters.item.create` — at the
     service layer where the entity is created.

3. **Title renderer extension**: `_compose_activity_title` now uses
   a `dict[(entity_type, action), str]` lookup table covering all 9
   kinds we emit today. Unknown kinds still fall through to the
   generic `"<entity_type> · <action>"`.

15 new tests across 4 files; 619 backend tests pass; ruff + mypy clean.

## Things the plan got right (no deviation)

- Emits added at the **service** layer for masters (where the entity
  is created) and at the **router** layer for auth (where the request
  context lives). Mixing layers is fine here — auth events are
  inherently HTTP-shaped (cookie → token → user) and don't fit a
  pure service signature.
- Logout-on-no-active-session intentionally doesn't emit. Tested
  explicitly via `test_logout_with_no_active_session_does_not_emit`
  to lock the contract in.
- Lookup-table title renderer instead of an `if/elif` ladder. Adding
  a new kind in INT-13/14/16 will be a one-line dict entry.

## Deliberate non-goals (NOT done in this branch)

- **Hash-chained audit (`prev_hash`/`this_hash`)**: columns exist on
  the model already; this branch sets them to `None`. Real chaining
  is a P3 task — no customer is asking for it yet, and getting it
  right needs careful thought about cross-firm ordering.
- **Async fan-out / event bus**: every emit writes synchronously in
  the same transaction as the underlying mutation. That's the only
  correct shape for ACID-aligned audit; a future async stream would
  duplicate, not replace, this path.
- **Receipt revocation, invoice cancel**: no cancel paths exist in
  the codebase yet (only `cancel_so` on sales orders, which is
  already covered by its own state-machine tests; emit deferred to
  whenever a proper cancel-invoice flow lands).
- **`/dashboard/activity` cache invalidation on emit**: the dashboard
  feed is unbounded-tail-of-audit-log via `ORDER BY created_at DESC
  LIMIT 5`. There's no cached view to invalidate; KPI cache stays.

## Pre-INT-13 / next-task checklist

### 1. Schedule the CA call

Per the INT-12 retro and confirmed today: **INT-13 (GL split into
`2110/2120/2130` ledgers) and INT-14 (Bill of Supply trigger) both
touch real accounting/document-type rules and need CA validation
before they land**. The breadcrumb is in `gst_service.py` at the
`# CA-VALIDATED-PENDING: 2026-05-06` marker. INT-15 was deliberately
sequenced first because it has no external blockers.

### 2. Verify the activity feed visually after merge

`/dashboard/activity` should now show:
- "Signed up" on a fresh org's first dashboard load.
- "Party added" / "Item added" as the user creates masters.
- "Invoice drafted" / "Invoice finalized" / "Receipt posted" as the
  daily flow runs.
- "Logged in" / "Logged out" / "Switched active firm" for session
  events.

### 3. Test cleanups for cross-org RLS tests

`test_party_service.py::test_rls_blocks_cross_org_party_reads` and
`test_item_service.py::test_rls_blocks_cross_org_item_reads` now
delete `audit_log` rows before deleting the `organization` rows in
their teardown — the new emits write FK-bound audit rows that
otherwise block the `DELETE FROM organization`. Mention because
TASK-INT-16 (runtime fabric_app cutover) will discover similar
fixture-coupling issues elsewhere.

## Open flags carried over from INT-12

- **`fabric_app` runtime cutover (TASK-INT-16)**: still on `fabric`
  (superuser, BYPASSRLS) at runtime; tests run under fabric_app via
  the explicit role split in `test_rls_force.py`. Not blocked by
  INT-15.

- **TASK-INT-13 / INT-14**: required before any composition firm
  onboards or before the first GSTR-3B filing. INT-15 doesn't move
  the needle here.

- **`make doctor` cwd bug**: noted in the validation report;
  drive-by fix on the next branch.

## Observable state at end of task

- New: `app/service/audit_service.py` — thin `emit(...)` factory.
- Modified: `app/routers/auth.py` — emits in signup/login/logout/
  mfa-verify; switch_firm refactored to use the helper.
- Modified: `app/service/sales_service.py` — refactored two existing
  emits (create_draft, finalize) to use the helper.
- Modified: `app/service/receipt_service.py` — refactored existing
  emit (banking.receipt.post) to use the helper.
- Modified: `app/service/masters_service.py` — emit on `create_party`.
- Modified: `app/service/items_service.py` — emit on `create_item`.
- Modified: `app/service/dashboard_service.py` — title lookup table
  for the 9 emitted kinds.
- Modified: `tests/test_party_service.py` + `tests/test_item_service.py`
  — RLS isolation cleanup deletes audit_log first.
- New: `tests/test_int15_audit_service.py` (3 cases),
  `tests/test_int15_auth_audit.py` (4 cases),
  `tests/test_int15_masters_audit.py` (2 cases),
  `tests/test_int15_activity_titles.py` (9 cases).

## Bringing it home — INT-15 closes P1-7

| Issue | Status pre-INT-15 | Status now |
|---|---|---|
| P1-7 — audit emits across mutations | activity feed shows only switch_firm | 9 emit kinds covered; helper centralised |

Three QA findings remain, all tracked: **P2-2 → INT-13** (GL split),
**P2-3 → INT-14** (Bill of Supply), runtime fabric_app cutover →
INT-16. Plus the small `make doctor` cwd bug as a drive-by.
