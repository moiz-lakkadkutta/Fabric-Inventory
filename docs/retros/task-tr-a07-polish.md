# TASK-TR-A07 polish retro — Operation progress follow-ups

**Date:** 2026-05-23
**Branch:** `task/tr-a07-polish` (worktree `~/fabric-worktrees/tr-a07-polish`)
**Parent PR:** #38 (TR-A07 in-house operation progress)

## Summary

Six small follow-ups carved out of the PR-#38 review on the A07 operation
progress service:

1. **Counter column replaces event-count heuristic.** A new
   `mo_operation.qty_in_record_count INTEGER NOT NULL DEFAULT 0` column
   drives the "first call overwrites the planning figure" branch of
   `record_qty_in`. The previous heuristic counted prior
   `OPERATION_QTY_IN_RECORDED` `ProductionEvent` rows; any future code
   path emitting the same event type would silently flip that branch
   off. New Alembic migration: `task_tr_a07_polish` (chains off
   `task_tr_a06_followups`).
2. **Rework-op tolerance gap documented.** The 5% over-receive tolerance
   uses `mo.planned_qty`; for a rework op
   (`rework_of_mo_operation_id IS NOT NULL`) that figure is the original
   MO's plan, not the rework's plan. Docstring on `record_qty_in` now
   calls this out explicitly. No code change today — no service creates
   rework ops yet; A09/A10 will revisit (likely deriving the baseline
   from the parent op's `qty_rejected`).
3. **`version` exposed on `OperationProgressResponse`.** The
   optimistic-concurrency counter is now in the API contract so the FE
   can stamp it into a future `If-Match` / `X-Expected-Version` header.
   OpenAPI snapshot + FE `api.ts` regenerated.
4. **Accountant read-permission test.**
   `test_accountant_can_read_operation_but_not_progress` locks in the
   RBAC contract: Accountant can `GET` operation + events but `POST`s
   to `/start` return 403. Helper `_make_user_with_role` factored out
   of the existing `_make_salesperson` so future role tests reuse it.
5. **`firm_id` filter on `list_events_for_operation`.** Defense-in-
   depth on top of RLS: load the operation under the org-scoped
   session, then filter events by both `org_id` AND the resolved
   `firm_id`. Mirrors the explicit-firm-filter pattern in
   `list_operations`.
6. **Dead `selectinload` sidestep removed.** The `_ = selectinload`
   line and the import were both deleted; no caller eager-loads on
   `get_operation`.

Three new integration tests on top of the four covering the polish:
- `test_record_qty_in_overwrites_first_then_adds` — locks in the
  counter-column branch.
- `test_response_exposes_version_counter` — version monotonically
  increments through `/start` → `/qty-in`.
- `test_accountant_can_read_operation_but_not_progress`.

11/11 operation-progress integration tests pass; 66/66 manufacturing-
adjacent tests pass.

## Open items

- **Rework-op tolerance baseline** stays unresolved; pending A09/A10
  when a service actually creates rework operations. Tracking this in
  the docstring rather than a TASK because we have no concrete service
  surface to test against yet.

## Pre-next-task checklist

- The `MoOperation.version` counter is now publicly observed by the
  FE. Any future progress mutation that bypasses `version += 1` will
  surface as a stale `version` in the response. Bake the increment
  into a service-layer helper if the next progress endpoint adds one.
- `_make_user_with_role` is now the canonical RBAC test helper in
  `test_operation_progress.py`; future manufacturing RBAC tests
  should call it rather than copy-paste the role lookup loop.
