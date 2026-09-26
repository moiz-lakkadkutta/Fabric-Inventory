# TASK-206 retro — cap cumulative DC dispatch at SO ordered qty; block issue against CANCELLED SO

**Date:** 2026-09-03
**Branch:** fix/issue-206 (worktree; orchestrator integrates)
**Commit:** two commits on `fix/issue-206`
**Plan:** GitHub issue #206 comment (agent-ready implementation plan)

## Summary

Fixed two Delivery-Challan bugs in `backend/app/service/sales_service.py`:
(1) a DC could over-dispatch its SO (only per-line stock was checked, never
cumulative dispatched-vs-ordered), and (2) a DC could be ISSUED against a
CANCELLED SO, which resurrected the SO to PARTIAL_DC. Added a new
`_validate_dc_lines_against_so` helper (per-item cumulative cap, hard 422, zero
tolerance + off-SO-item rejection), wired it into both `create_dc` (early UX)
and `issue_dc` (authoritative, under a `SELECT ... FOR UPDATE` on the SO row),
added a CANCELLED/DRAFT SO status guard in `issue_dc` (409), and made
`_advance_so_status_after_dc` no-op on a CANCELLED SO (defense-in-depth). Lint
(ruff), typecheck (mypy), and tests all pass: 148 in the broad regression set
plus the new concurrency test. Both original repros are fixed.

## Deviations from plan

### 1. Base branch already had #202 (lot/FIFO stock) but NOT #190's DC lock
Plan (written against `main` HEAD `bdc7a30`) assumed `issue_dc` still used a
single `remove_stock` call and that #190's DC-row lock would coexist.
- **Reality:** integration base has #202's split path — `remove_stock` for an
  explicit `line.lot_id`, else `remove_stock_fifo` — and no DC-row lock in
  `issue_dc` yet.
- **Fixed by:** inserted the SO lock + guards *before* that stock loop (guards
  run before any stock moves regardless of which branch fires). Kept #202's
  lot/FIFO consumption untouched, and #198's COGS-at-finalize skip comment
  intact. Lock order remains DC → SO for when #190 lands.
- **Impact on later tasks:** none. If #190 later adds a DC-row lock in
  `issue_dc`, keep it before the SO lock.

### 2. `issue_dc` now reuses the locked SO instead of re-fetching
Plan step (b) said "pass the already-locked `so` to `_advance_so_status_after_dc`
instead of re-fetching." Implemented exactly: the tail `get_so(...)` +
`_advance_so_status_after_dc(so=so)` became `if locked_so is not None:
_advance_so_status_after_dc(so=locked_so)`. Noted here because it removes the
second SO SELECT that existed on `main`.

### 3. OpenAPI spec had no `/delivery-challans/{dc_id}/issue` path at all
Plan said "descriptions note the new 422/409 conditions." The create path was a
stub and the issue path was entirely absent.
- **Fixed by:** added a 422 response + description to the create POST and added
  the whole `/delivery-challans/{dc_id}/issue` path block with 200/409/422 and
  `x-permission: sales.dc.approve`. No shape change to existing responses.

## Things the plan got right (no deviation)

- DC lines link to the SO by item only (no `so_line_id`); per-item aggregation
  is the correct granularity and mirrors `_advance_so_status_after_dc` exactly.
- The `<=` boundary (exact-fill passes) and partial-dispatch legality — the
  existing 100/60 and 60+40 tests kept passing unchanged.
- SERVICE items count toward dispatch quantities but skip stock — the cap stays
  consistent with the advancement query (no special-casing).
- No migration needed — all columns already exist.
- The PO-side `test_parallel_receives_cannot_exceed_ordered` (#200) was the
  perfect template for the SO-side concurrency test.

## Open flags carried over

- **Ask-vs-Decide (product policy):** the cap is a hard 422 with 0 tolerance.
  If textile reality later needs an over-dispatch allowance, it is a one-const
  change mirroring the PO-side tolerance from #200. Flagged in the PR for Moiz —
  **not a blocker; implemented as a bugfix.** No CA/money/tax/schema gate.
- **DATA-REPAIR (QA orgs, disposable):** two known bad rows exist only in QA
  orgs — the resurrected SO behind DC `3cc4747f-…` (org `2162728c-…`) and
  over-dispatched SO 0002 (25/10, org `4a5e65ca-…`). Not touched here (test DB
  is `test_206`, isolated). Detection query (1) `so_line.qty_dispatched >
  qty_ordered` will keep showing the legacy 25/10 row until the QA org is
  dropped; the new cap governs future DCs only.
- Out of scope (stated in plan): blocking `cancel_so` while DRAFT DCs exist
  (harmless now — a stale DRAFT DC can never issue), a `dc_line.so_line_id`
  column (schema gate), SO-cancel cascade-closing DCs.

## Observable state at end of task

- No new dev-env requirements, no migration, no feature flag.
- Concurrency test verified meaningful: temporarily removing `.with_for_update()`
  makes `test_parallel_issues_cannot_exceed_ordered` fail with `['OK','OK']`
  (both threads over-dispatch); restored.
- Files touched: `backend/app/service/sales_service.py`,
  `backend/tests/test_dc_service.py`, `backend/tests/test_dc_routers.py`,
  `backend/tests/test_concurrency_postings.py`, `specs/api-phase1.yaml`.
