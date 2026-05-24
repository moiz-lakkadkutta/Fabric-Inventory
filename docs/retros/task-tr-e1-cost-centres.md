# TASK-TR-E1-COSTCENTRES retro — deviations from plan and pre-next checklist

**Date:** 2026-05-24
**Branch:** task/tr-e1-cost-centres
**Plan:** four-sibling parallel E1 dispatch (cost centres slice)

## Summary

Shipped the cost-centres master-data slice: a new `/manufacturing/cost-centres` route with a 5-state list (idle / loading / error / empty / filtered-empty) and a 720px create dialog. Added `useCostCentres` + `useCreateCostCentre` to `lib/queries/manufacturing.ts` and stood up a brand-new `lib/api/manufacturing.ts` adapter (didn't exist before). All 471 frontend tests pass, lint and tsc are clean. The slice is the simplest of the five E1 deliverables — three fields, no FK pickers, no nested forms.

## Deviations from plan

### 1. Backend has no `description` column on `CostCentre`
Plan said the create body is `{code, name, description?}`. The BE `CostCentreCreateRequest` only accepts `{firm_id, code, name, cost_centre_type?, parent_cost_centre_id?, is_active}` — no description.
- **Fixed by:** kept the description textarea in the dialog (per design spec) but drop it on the wire. Documented in both the queries-module comment and the dialog test ("description is UI-only — BE has no column for it"). The list column renders an em-dash placeholder so the layout doesn't collapse.
- **Why not caught in planning:** the task brief said "Backend (already shipped) … POST /cost-centres — body: `{code, name, description?}`", which didn't match the actual `backend/app/schemas/manufacturing.py:CostCentreCreateRequest`. Reality came from grepping the schema, not the brief.
- **Impact on later tasks:** if anyone wants real description persistence, they need a schema migration + a column add. Tracked as a follow-up in the queries-module comment.

### 2. Backend has no `ops_linked` count on `CostCentreResponse`
Spec calls for an "Ops linked" column with the operation count using each CC.
- **Fixed by:** column renders an em-dash. The BE would need to LEFT JOIN `operation_master` and return the count — out of scope for this slice. Documented inline.
- **Why not caught in planning:** same as #1 — design spec assumed richer BE shape than reality.
- **Impact on later tasks:** if the E1-Operations sibling wires the operation-master list and we want to enrich CCs, the BE response shape will need a new column.

### 3. Auto-suggest algorithm produces `CC-IN-HOU-STI` not `CC-INH-STC`
Sample data in `phase6-shared.jsx` uses 3-letter chunks of meaningful syllables ("INH-STC" for "In-house stitching"). The implemented algorithm just takes the first 3 chars of each whitespace-separated letter run.
- **Fixed by:** kept the simpler algorithm — it's predictable and `CC-IN-HOU-STI` is still legible. User can override the suggestion any time (the dialog stops auto-overwriting once the code is dirty).
- **Why not caught in planning:** matching the sample-data codes exactly would need a syllable / abbreviation dictionary which is way out of scope.
- **Impact on later tasks:** none. The auto-suggest is convenience-only.

## Things the plan got right (no deviation)

- `useDesigns` + `useCreateMo` pattern mapped cleanly onto the new cost-centre hooks. Same `requireFirmId` + idempotency-key handshake.
- Live-mode integration tests via `vi.mock('@/lib/api/mode')` before importing the page is the same pattern `MoList.test.tsx` uses — copied wholesale.
- The Sidebar already supports `sub` items (Sales, Masters); plugging the cost-centres entry under a new Manufacturing sub-nav was one diff.

## Pre-TASK-NNN+1 checklist

### 1. Rebase against sibling E1 PRs
Four siblings touch `App.tsx`, `Sidebar.tsx`, `lib/queries/manufacturing.ts`, and `lib/api/manufacturing.ts`. The BOM sibling already merged adjacent changes into `lib/api/manufacturing.ts` cleanly during this session — that's a good signal. On rebase to main, take both sides on the import block + the `__live` test exports.

### 2. Wire `useCostCentres` into E1-Operations
The Operations sibling has a graceful-degrade fallback for the cost-centre picker; once both PRs land, their dialog should pick up live CC data on rebase. No action needed here — they call the hook.

### 3. Schema follow-up: description + ops_count
Not blocking, but worth a one-pointer task: add a `description TEXT NULL` column to `cost_centre`, plumb it through the schema, and surface ops_count via a LEFT JOIN. Until then the list page shows em-dashes in those columns.

## Open flags carried over

- **Description persistence**: collected in the UI, dropped on the wire. Will resurface when someone needs to display it.
- **Ops-linked count**: same — placeholder em-dash. Needs a BE JOIN.
- **Sidebar Manufacturing sub-nav**: this PR introduces sub-items (Pipeline / MOs / Cost centres). If a sibling adds Operations / BOMs they'll want to extend this list — the diff is mechanical.

## Observable state at end of task

- New file: `frontend/src/lib/api/manufacturing.ts` (existed via the BOM sibling but this PR was the canonical first-mover for cost-centre wrappers).
- New routes: `/manufacturing/cost-centres`.
- Sidebar Manufacturing entry is now a sub-nav with 3 items.
- All 471 tests pass on this branch; lint + tsc clean.
