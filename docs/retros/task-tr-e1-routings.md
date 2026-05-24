# TASK-TR-E1-ROUTINGS retro — Routings list + 3-tab DAG-editor wizard

**Date:** 2026-05-24
**Branch:** task/tr-e1-routings
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Phase 6 manufacturing masters)

## Summary

Shipped the Routings masters surface: `/manufacturing/routings` list page (grouped by design, 5 list states, filter chips + 280px search) and `/manufacturing/routings/new` 3-tab wizard. Tab B has two render modes — an editorial DAG canvas with left-rail operation masters, draggable nodes, click-to-connect handles, FS/SS edge type toggle, and live cycle detection chip; and a dense sequence-row variant with predecessor pills + inline `+ pred` picker. Both editors are controlled and share the same `{nodes, edges}` model so the view toggle is a render-flip (no data loss). The wizard POSTs `/routings` with the BE wire shape (only edges; nodes are implicit on the BE) and surfaces 422 details verbatim. Lint, typecheck, and the full vitest suite (85 files / 480 tests, including 23 new tests across the three new files) all pass.

## Deviations from plan

### 1. BE has no `nodes` field on `RoutingCreateRequest`
The brief said the create body is `{design_id, name?, version?, nodes: [...], edges: [...], is_active?}`. The actual BE schema (`backend/app/schemas/manufacturing.py::RoutingCreateRequest`) only accepts `{firm_id, design_id, code, edges}`. There's no `name`, no `version_number` (auto-bumped), no explicit `nodes` (derived from edge endpoints), no `is_active` (set to true on create, and the previous active version is auto-superseded by the unique `(firm_id, code, version_number)` key).
- **Fixed by:** kept node positions + executor strictly client-side state inside the wizard; serialised edges only via `toRoutingPayload()` in `_components/RoutingDagEditor.tsx`. `name` is stored as a UI-only "routing name" input that doesn't go to the BE.
- **Why not caught in planning:** brief described the design contract; BE was already shipped with a tighter shape.
- **Impact on later tasks:** when the BE gains explicit node persistence (executor per node, free-form name), the FE only needs to widen `toRoutingPayload` — the rest of the editor already stores the shape.

### 2. No dedicated `/routings/{id}/activate` endpoint
Brief listed `PATCH /routings/{id}/activate`. None exists in `backend/app/routers/manufacturing.py`.
- **Fixed by:** `useActivateRouting` is wired but currently calls `GET /routings/{id}` and returns it unchanged. Creating a routing already activates it (BE marks `is_active=true` on the newest version per design + code). The hook + the wizard's "Set as active" toggle remain so a future BE switch is a single-line drop-in.
- **Why not caught in planning:** mismatch between design assumption and BE-shipped reality.
- **Impact on later tasks:** none until someone wants to toggle a previously-superseded routing back to active. That's a follow-up.

### 3. DAG visualisation written inline rather than vendoring a library
Per the constraints, no new npm package. The canvas is ~430 LOC of absolutely-positioned divs + SVG cubic Bézier paths between right-handle of source and left-handle of target node. Cycle detection is a vanilla DFS (`detectCycleNodes`) that flags every node participating in a back-edge.
- **Fixed by:** see `frontend/src/pages/manufacturing/_components/RoutingDagEditor.tsx`.
- **Impact on later tasks:** node drag is grid-snapped (col/row indexes, not free pixels) — sufficient for the trial customer, but a follow-up wanting a panning/zooming canvas will need to rework the coordinate space.

## Things the plan got right (no deviation)

- 3-tab wizard chrome maps 1:1 from `MoCreateWizard` — same tablist semantics, Back/Cancel/Next footer, validation gate on each step.
- The render-flip between editorial/dense is genuinely free once both editors are controlled — wiring the same `{nodes, edges}` setter through both means zero data loss on switch (verified by the wizard test).
- BE `routing_service._detect_cycle` is the source of truth for cycles; client DFS is an early-warning chip. Tested by the 422-surfacing happy path.

## Pre-next-task checklist

### 1. Decide whether routing nodes carry executor server-side
Today executor (`IN_HOUSE` / `KARIGAR` / `QC`) is FE-only. The MO Create wizard already accepts a per-op executor override locally; if the BE adds it to the routing model, both surfaces snap into alignment. Open question for the next manufacturing-masters PR.

### 2. Wire `useActivateRouting` to a real endpoint when one ships
`frontend/src/lib/api/manufacturing.ts::activateRouting` is a stub today. Two call-sites already wired (`RoutingCreateWizard` "Set as active" toggle + `useActivateRouting` mutation hook).

### 3. Sidebar Manufacturing entry now has 3 sub-items
Pipeline / Manufacturing orders / Routings. If a future masters task adds Operations / BOMs / Designs / Cost centres, slot them under the same `MANUFACTURING_NAV.sub` array in `frontend/src/components/layout/Sidebar.tsx`.

## Open flags carried over

- Routing name field is FE-only — surfaces only in the wizard, never persisted. Re-evaluate when the BE adds `name` to `Routing`.
- Drag-to-move is grid-snapped to (col, row) integers. Free-pixel canvas is a Phase 6+ polish item.
- Activation history (`v3 active → v4 active`) is implicit on the BE via the unique key. A user-visible audit trail would need a separate listing or a routing-detail page; not in this PR's scope.

## Observable state at end of task

- New routes reachable: `/manufacturing/routings` + `/manufacturing/routings/new`.
- Sidebar Manufacturing now expands into a sub-menu (Pipeline, MOs, Routings).
- New files:
  - `frontend/src/lib/api/manufacturing.ts` (createRouting + activateRouting client wrappers)
  - `frontend/src/pages/manufacturing/RoutingsList.tsx`
  - `frontend/src/pages/manufacturing/RoutingCreateWizard.tsx`
  - `frontend/src/pages/manufacturing/_components/RoutingDagEditor.tsx`
  - `frontend/src/pages/manufacturing/_components/RoutingSequenceEditor.tsx`
  - 3 vitest files (23 new tests).
- Edited files: `App.tsx`, `Sidebar.tsx`, `lib/queries/manufacturing.ts`.
- Sibling-agent collision points: App.tsx + Sidebar + `lib/queries/manufacturing.ts` will need a take-both-sides merge if four sibling PRs land in parallel.
