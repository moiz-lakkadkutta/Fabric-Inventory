# TASK-192 retro — MO completion fabricates phantom finished-goods stock

**Date:** 2026-09-02
**Branch:** fix/issue-192
**Commit:** `<sha>` (NOT merged — PENDING MOIZ + CA SIGN-OFF)
**Plan:** GitHub issue #192 comment (implementation plan)

## Summary

`complete_mo_with_settlement` / `preview_completion` in
`backend/app/service/mo_completion_service.py` now reconcile the operator-supplied
`produced_qty` against reality before booking any finished-goods stock or posting a
`MANUFACTURING_COMPLETION` voucher. Three gates were added (Phase 3/3.5 in the
settlement path, mirrored as `blocking_reasons` in the preview): (1) `produced_qty`
must not exceed `planned_qty`; (2) `produced_qty` must equal the verified good output
— the sum of `qty_out` on the routing's terminal (sink) operations, with QC ops
contributing their cumulative `qty_passed` (which they store in `qty_out`); (3) all
non-optional `mo_material_line`s must be fully issued. Zero-op / no-routing / no-edge
MOs fail closed. The ALL_OR_NONE `completion_policy` semantics changed in the service
only (no migration, no schema change): it no longer means `produced == planned`
(which deadlocked any MO with real spoilage and was the exact behaviour the QA
campaign exploited), it means `produced == verified actual` and `produced <= planned`,
with the full WIP cost pool absorbing into the good units (normal-loss costing).

Verification: `ruff check` + `ruff format` clean on all changed files; `mypy` clean on
the service; `test_mo_completion.py` (21) + `test_mo_completion_preview.py` (8) green;
regression sweep of `test_qc_operation`, `test_qc_rework_clone`,
`test_operation_progress`, `test_material_issue`, `test_routing_flow`,
`test_karigar_send_out`, `test_seed_demo_manufacturing` all green (145 tests total
across the touched surface). The QA repro is fixed: final op `qty_out=8` + complete
`produced_qty=10` → 422 (no voucher, no stock); `produced_qty=8` → 200, FG +8 at
unit_cost = pool/8.

## Deviations from plan

### 1. `specs/api-phase3.yaml` has no MO completion / preview endpoints to update
Plan §7 acceptance said "update completion/preview descriptions (no shape change)".
Reality: the MO-level `POST /manufacturing/mo/{id}/complete` and
`GET .../completion-preview` endpoints were never added to `api-phase3.yaml` in the
first place (a known gap carried since TASK-TR-A11 — the spec only has the
`mo-operations/{id}/complete` op-level path).
- **Fixed by:** nothing — left the spec alone rather than author brand-new endpoint
  entries, which would be scope creep beyond a correctness hotfix.
- **Why not caught in planning:** plan assumed the endpoints were specced.
- **Impact on later tasks:** the spec still lags the MO completion surface; fold it
  into a dedicated spec-sync task.

### 2. Existing `test_complete_mo_rejects_partial_produced_qty` reason changed
Plan didn't call it out, but its assertion (`"all_or_none" or "does not equal"`) no
longer matches: with all ops CLOSED at 10, completing with 9 is now rejected by the
output-reconciliation gate ("does not match the verified final-operation output 10"),
not the old planned-equality gate.
- **Fixed by:** updated the assertion to `"does not match" and "output"` in
  `tests/test_mo_completion.py`; likewise `test_preview_blocked_when_qty_does_not_match_planned`
  in the preview file. Semantics preserved (partial qty still 422), reason updated.

## Things the plan got right (no deviation)

- Sink-operation derivation as the mirror of the Kahn source computation (op-masters
  with no outgoing edge) — worked exactly; diamond/multi-sink handled by summing.
- QC `qty_out` = cumulative `qty_passed` makes it the uniform good-output column — no
  QC special-casing needed in the sink sum.
- Excluding rework clones (`rework_of_mo_operation_id IS NULL`) — kept
  `test_complete_mo_rejects_when_qc_is_rework` green (REWORK op is non-terminal-state
  and blocked earlier anyway).
- No migration needed; `completion_policy` stays VARCHAR, only its enforced meaning
  moved into the service.
- `seed_demo` MOs already reconcile (final_out == produced), so
  `test_seed_demo_manufacturing` stayed green with no seed change.

## Pre-next-task checklist

### 1. Get D1–D3 sign-off from Moiz + CA before merge
This branch is HELD. The load-bearing decision (D1) is: ALL_OR_NONE = "produced ==
verified actual, ≤ planned; full WIP pool absorbs into good units (normal-loss
costing); scrap cost carried by good units, NOT posted to a P&L abnormal-loss ledger".
Abnormal-loss posting is explicitly out of scope (future CA-guided task).

### 2. Demo-tenant data repair (deferred, NOT done in code)
Phantom stock already booked by the QA campaign on the demo tenant is untouched by
this fix. Detection queries are in issue #192 §9. Recommended repair per the plan:
wipe + re-run `seed_demo_service.seed_demo` (idempotent) for the demo org after this
lands. If the detection query returns rows in any NON-demo org, stop and escalate for
a surgical reversal (reversing voucher + outbound stock adjustment, CA sign-off).

### 3. Add the MO completion + preview endpoints to `api-phase3.yaml`
See deviation #1.

## Open flags carried over

- Abnormal-loss / scrap-to-P&L GL posting — deferred, future CA-guided task.
- P2 findings from the QA review (can-start MO-status check, QC "PASS" verdict naming,
  completion-preview raw-UUID display G18) — out of scope for #192.

## Observable state at end of task

- Test DB `test_192` is migrated to head; no schema change was applied (no migration).
- Branch `fix/issue-192` committed but NOT merged/pushed — orchestrator integrates
  after sign-off.
