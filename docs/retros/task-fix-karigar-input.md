# fix-karigar-input retro: mid-routing karigar send-out shipped finished goods

**Date:** 2026-10-23
**Branch:** task/fix-karigar-input-item
**Commit:** see PR (not merged; PENDING MOIZ SIGN-OFF)
**Plan:** none (bug found by a verification pass)

## Summary

A karigar dispatch with no explicit `item_id` on any op after the first defaulted to
the MO's finished item, because `mo_service.create_mo` sets every op's
`output_item_id` to the finished item and chains it into the next op's `input_item_id`.
The dispatch then either failed with "Insufficient stock" or silently moved
finished-goods stock MAIN → JOBWORK. Receive-back would then add finished goods that
MO completion adds again.

**This PR ships a stopgap only.**
`karigar_send_out_service._refuse_default_finished_goods_dispatch` returns a 422 with
an actionable message whenever the *default* resolves to the MO's finished item.
Explicit `item_id` still works, and the first op (BOM primary raw) is unchanged. The
MO-detail drawer already shows the 422 detail in its error banner. A new vitest
covers that.

The real fix (stage dimension on `stock_position`, chosen by Moiz) is written up in
`docs/design/wip-stage-stock.md`. It is not implemented.

**Verification:**
- Backend manufacturing, job-work and routing suites (11 files): 191 passed.
- ruff check + format and mypy are clean.
- Frontend: manufacturing vitest 146 passed; tsc and prettier are clean.

## Deviations from plan

### 1. The "correct input item" question has no answer in the current model
The brief assumed the fix was picking the right item, either the predecessor's WIP
output or the BOM components. In fact, after material issue, in-progress pieces exist
only as the GL 1310 pool and the op qty counters. There is no stock position to ship.
- **Fixed by:** fail-closed guard now; design proposal for stage-wise stock.
- **Why not caught in planning:** the A08 retro left "decide intermediate-item
  modelling" open, and the A08 follow-up only half-implemented option (a).
- **Impact on later tasks:** S1–S10 in the design doc.

## Things the plan got right (no deviation)

- No schema or GL change in the stopgap. The guard sits before any stock write, so a
  refused call leaves no partial JWO or stock row.

## Pre-next-task checklist

### 1. Get Moiz and the CA answers to the open questions in `docs/design/wip-stage-stock.md` §9
Q2 (op_type → stage mapping) and Q6 (ITC-04 value) block S1/S9.

### 2. Wait for the concurrent `material_issue_service.py` lot-handling fix before S3
S3 rewrites the issue stock move. Rebase on that fix first.

## Open flags carried over

- The first-op karigar dispatch still ships raw that was already issued to WIP. It
  needs twice the raw on hand and nets to zero after receive-back. This PR leaves it
  unchanged, as the brief required. S5 fixes it.
- Legacy MOs with `input_item_id IS NULL` also resolve to the finished item, so their
  default dispatch is now refused too. That is intentional: finished goods don't exist
  before completion.
- QC rework clones inherit `input_item_id` from their parent, so a default dispatch of
  a rework op on a mid-routing op is refused as well.

## Observable state at end of task

- Test DB `test_karigar` on Homebrew PG (cloned from `test_template`). Drop it once
  merged.
- Redis on :6379 disappeared during the session (it isn't Docker's). The last
  backend run before it went down was green, after all code changes; only a
  `ruff format` reflow happened after that run.
