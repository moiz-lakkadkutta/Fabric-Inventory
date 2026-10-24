# fix-mo-create-qc-verdict retro — deviations from plan and pre-next checklist

**Date:** 2026-10-24
**Branch:** fix/mo-create-and-qc-verdict
**Commit:** see PR (not merged; awaiting review)
**Plan:** bug list from the demo-film recording session (no plan file)

## Summary

Three bugs hit while recording the demo films, each fixed test-first:

1. **Nobody could create an MO from the UI.** `MoCreateWizard.tsx` gated
   Save/Release on `manufacturing.mo.create`, a code that does not exist in
   the RBAC catalogue (`_SYSTEM_PERMISSIONS` in `rbac_service.py`), so no
   role — not even Owner (`_ALL_PERMS`) — held it. The backend gates
   `POST /manufacturing/mo` **and** `/release` (and start/complete/close) on
   `manufacturing.mo.write`, which Owner and Production Manager both hold.
   The FE now checks `manufacturing.mo.write` for both buttons. No RBAC
   change was needed.
2. **First QC verdict could not be recorded.** `GET /qc-result` read
   `predecessor_qty_out` / `predecessor_mo_operation_id` only off the latest
   `QC_RESULT_RECORDED` event, so before any verdict it returned `0` / `null`
   and the drawer's "Record verdict" stayed disabled. Root cause is that the
   read side never resolved the QC source; only the write side
   (`record_qc_result`) did. Fixed in the service layer:
   `qc_service.get_qc_source_context()` resolves the source live using the
   same walk as the write path (extracted into `_resolve_rework_leaf`), and
   the router uses it. Same bug also affected re-records: in REWORK the
   endpoint returned the *previous* round's source qty instead of the leaf
   clone's qty_out (the drawer comment already documented the intended
   contract), and the predecessor id pointed at the clone rather than the
   chain root, which broke the drawer's clone-chain walk on round 2+.
3. **Invoice Rate input scrambled digits** ("2950" → ₹2.02) because it was a
   controlled input re-formatted with `toFixed(2)` on every keystroke. New
   `RateInput` keeps the raw draft while editing and formats on blur; paise
   are still pushed on every change so totals stay live.

Verification: new `tests/test_qc_result_context.py` (3 tests, real Postgres)
plus the related backend suites (QC, rework, MO completion, MO/manufacturing,
operation progress, karigar, RBAC, material issue, routing — 287 passed).
Frontend: full vitest 605/605, `tsc --noEmit`, eslint, prettier clean.
Backend: ruff check + format, mypy clean. No OpenAPI change (schema docs
added as `#` comments, not docstrings, to avoid snapshot drift).

## Deviations from plan

### 1. QC fix also covers the REWORK re-record path
Brief said "pre-first-verdict returns 0". Reality: the same event-only read
was wrong for re-record too (returned round-N-1 source qty, clone id as
"predecessor").
- **Fixed by:** `get_qc_source_context` handles QC_PENDING/PENDING/READY
  (predecessor qty_out) and REWORK (leaf clone qty_out); CLOSED falls back to
  the event's recorded source qty. `predecessor_mo_operation_id` is now always
  the original routing predecessor.
- **Why not caught in planning:** the existing tests only assert
  `predecessor_qty_out` after a PASS verdict, where payload == live value.
- **Impact on later tasks:** zero; FE already expected this contract.

## Things the plan got right (no deviation)

- The FE check was the bug, not role seeding — Owner and Production Manager
  both already hold `manufacturing.mo.write`.
- The rate-input fix stayed small (one local component).

## Pre-next checklist

### 1. Re-record the MO-create and QC scenes of the demo films
Both blockers are gone; the films that worked around them can be re-shot.

## Open flags carried over

- None needing Moiz's decision. `manufacturing.mo.write` deliberately covers
  create + release + lifecycle (per catalogue comment); if a "can draft but not
  release" split is ever wanted, that's a new permission + seeding change
  (security call for Moiz).

## Observable state at end of task

- Test DB `test_moqc` (Homebrew PG, cloned from `test_template`) left on disk;
  drop when done: `psql -h localhost -U fabric -d postgres -c 'DROP DATABASE test_moqc'`.
