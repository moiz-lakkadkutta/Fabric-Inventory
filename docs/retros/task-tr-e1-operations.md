# TASK-TR-E1-OPERATIONS retro — deviations from plan and pre-next checklist

**Date:** 2026-05-24
**Branch:** task/tr-e1-operations
**Plan:** customer-trial / Phase 6 manufacturing masters
**Spec:** `docs/design/phase6/phase6-operations.jsx`

## Summary

Shipped the first of the five Phase 6 manufacturing master pages —
operations. New surface includes `OperationsList` at
`/manufacturing/operations` with all five list states (Full / Loading /
Error / Empty / FilteredEmpty) wired to the live `GET /operation-masters`
endpoint, a 720px `NewOperationDialog` that posts to
`POST /operation-masters` with an Idempotency-Key, and a reusable
`OpTypePill` component that ports the seven-colour `OP_TYPE_TOK` palette
verbatim from the design spec for use by sibling BOM / Routing pages.

Three test files added (19 new assertions: 9 OpTypePill, 6 OperationsList,
4 NewOperationDialog). Full FE suite — 85 files / 476 tests — passes.
`tsc --noEmit` and `eslint` both clean on touched files.

## Deviations from plan

### 1. `useCostCentres` hook not yet shipped

Plan said the create dialog's cost-centre picker would use
`useCostCentres`. The hook doesn't exist on `main` yet (sibling agent
work in flight on the cost-centres surface).

- **Fixed by:** added a local `useCostCentresFallback()` returning an
  empty list so the field renders with the load-bearing hint copy
  "Cost centres are loading — pick one or leave blank". Operator can
  leave it blank — the BE accepts a null `cost_centre_id`.
- **Why not caught in planning:** the brief flagged this case and
  prescribed the graceful-empty pattern; my deviation is just that I
  noted it explicitly in the file rather than wiring a real hook.
- **Impact on later tasks:** when `useCostCentres` lands (sibling
  E1-Cost-Centres agent), swap the body of `useCostCentresFallback()`
  for `useCostCentres()` — one-line change.

### 2. Cost-centre column shows truncated UUID rather than the cost-centre name

The list-row cost-centre column shows the first 8 chars of the
cost_centre_id when populated, rather than the resolved cost-centre
name + code from the spec.

- **Fixed by:** placeholder formatting that won't render junk text when
  the cost-centres list is finally wired through.
- **Why not caught in planning:** same root cause as deviation #1 —
  without a cost-centres query hook there's nothing to resolve names
  against client-side. Could have done a per-row `useCostCentre(id)`
  lookup but that'd waterfall N+1 fetches on a page that already shows
  the right column when the operator clicks through.
- **Impact on later tasks:** when E1-Cost-Centres ships, replace the
  truncated-UUID renderer in `OperationsList.tsx` with a
  `costCentreNameById.get(op.cost_centre_id)` lookup mirroring the
  MoList → designs pattern.

## Things the plan got right (no deviation)

- Five list states mapped one-to-one onto the design spec.
- The `OpTypePill` palette was lifted verbatim from `OP_TYPE_TOK` in
  `phase6-shared.jsx` — no chroma drift.
- Sibling-agent collision callouts were accurate: `App.tsx`, Sidebar,
  and `lib/queries/manufacturing.ts` are the three rebase touchpoints.
- `useIdempotencyKey` + `idem.reset()` after a failed submit kept the
  dialog recoverable without forcing a full reload.

## Pre-next-task checklist

### 1. Wire `useCostCentres` once the sibling E1-Cost-Centres PR lands

Swap `useCostCentresFallback()` in `NewOperationDialog.tsx` for the
real hook. The fallback was deliberately kept tiny so the swap is a
one-import edit.

### 2. Resolve cost-centre names in the list row

In `OperationsList.tsx`, replace the truncated-UUID cell renderer with
a `costCentreNameById` map populated by `useCostCentres()`. Mirrors the
MoList → designs pattern.

### 3. Reuse `OpTypePill` in BOM / Routing pages

The component is intentionally page-state-free so sibling agents can
import `@/components/manufacturing/OpTypePill` directly. The palette
constant `OP_TYPE_TOK` is also exported for any non-pill rendering
(e.g. radio-group accent stripe in their create dialogs).

## Open flags carried over

- **Cost-centre UX in this dialog**: should the picker be a typeahead
  rather than a `<select>`? Defer to E1-Cost-Centres which will define
  the canonical cost-centre picker component.

## Observable state at end of task

- New route: `/manufacturing/operations` — accessible from the
  Manufacturing sidebar sub-nav (alongside Pipeline / MOs).
- Sidebar gained a sub-nav for Manufacturing; existing Pipeline /
  MOs paths still navigate as before. The `end={true}` flag on the
  Pipeline sub-link prevents auto-activation when on /mo or /operations.
- `useCreateOperationMaster` is now exported from
  `frontend/src/lib/queries/manufacturing.ts` (mutation, idempotency-
  key). The thin client wrapper `liveCreateOperationMaster` is also
  exposed via `__live` for fetch-mocked integration tests.
- `lib/api/manufacturing.ts` is a new file with the operations CRUD
  wrappers; sibling agents will append BOM / Routing / Cost-Centre
  wrappers here as their PRs merge.
