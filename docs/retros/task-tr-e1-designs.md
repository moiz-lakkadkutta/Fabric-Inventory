# TASK-TR-E1-DESIGNS retro — deviations from plan and pre-next checklist

**Date:** 2026-05-24
**Branch:** task/tr-e1-designs
**Plan:** trial-prep E1 (Manufacturing masters: Designs)

## Summary

Shipped the Designs master list (`/manufacturing/designs`) and the 720px
NewDesignDialog modal that mirrors NewJournalVoucherDialog's shell.
List renders the five spec states (Full / Loading / Error / Empty /
FilteredEmpty), each verified by a vitest test. Dialog auto-derives the
code from the name (slugify-uppercase), gates submit on
code + name >= 3 chars + finished-item selection, runs a typeahead
filtered to `item_type === 'FINISHED'`, and POSTs `/designs` with an
Idempotency-Key. Wired the route under the existing protected layout
and added a Manufacturing > Designs sub-nav entry. Lint, typecheck, and
the full 468-test vitest suite pass green; no backend, no new design
tokens, no other manufacturing pages touched.

## Deviations from plan

### 1. BE `DesignCreateRequest` has no `finished_item_id` column

Plan said `POST /designs` accepts `{code, name, description?, finished_item_id}`.
Reality: `backend/app/schemas/manufacturing.py:35` shows the BE schema
is `{code, name, firm_id, description?, cost_centre_id?}` — `finished_item_id`
is a BOM-level relation (`bom.finished_item_id`), not a Design column.
- **Fixed by:** the dialog still collects the finished item via a
  typeahead (UI fidelity to `phase6-designs.jsx`), validates that the
  user picks one before enabling Submit, but DOES NOT send the field
  on the wire. A test asserts the request body excludes `finished_item_id`.
- **Why not caught in planning:** the design spec describes a future-
  state schema that hasn't shipped yet; the BE was finalised against
  the canonical Design model that pre-dates the E1 design pass.
- **Impact on later tasks:** when the BE grows `Design.finished_item_id`
  (or moves the cost_centre to a finished-item link), the dialog's
  `submit()` plumbs through with a 1-line addition (`finished_item_id:
  finishedItemId,`). No FE refactor needed.

### 2. No `createDesign(body)` in a separate `lib/api/manufacturing.ts`

Plan said add `createDesign` to `frontend/src/lib/api/manufacturing.ts`.
Reality: no such file exists — the repo convention is to inline
`liveCreateMo` / `liveListMos` inside `lib/queries/manufacturing.ts`,
not a separate api/ module. Introducing a new file just for one create
would diverge from every existing manufacturing endpoint.
- **Fixed by:** added `liveCreateDesign` + `useCreateDesign` inside
  `lib/queries/manufacturing.ts` next to `liveCreateMo` / `useCreateMo`.
  Exported via the existing `__live` test-helper barrel.
- **Why not caught in planning:** the plan's file-layout was drafted
  in symmetry with `lib/api/parties.ts`, but masters and manufacturing
  evolved differently — items and parties have api/ modules; sales-
  orders / manufacturing don't.
- **Impact on later tasks:** sibling E1 PRs (Operations, CostCentres,
  BOMs, Routings) should follow the same `liveXxx` + `useXxx` pattern
  inside `lib/queries/manufacturing.ts`. Rebase will collide on the
  `__live` export list — resolve by taking both sides.

### 3. BOM / Routing version counts not surfaced on the list

Spec column lineup includes `BOM v` and `Routing v` per-design counts.
The BE `/designs` list returns `DesignResponse`, which doesn't carry
aggregate counts; resolving them client-side would mean N+1 list calls
(one `/boms?design_id=X` per row).
- **Fixed by:** render an em-dash placeholder in both columns so the
  spec's column lineup is preserved without faking numbers. Columns
  light up the moment the BE grows aggregate counts (or the FE swaps
  to a single `/designs?include=bom_count,routing_count` call).
- **Why not caught in planning:** the spec writer assumed the BE list
  shape was richer than it is.
- **Impact on later tasks:** sibling E1 BOMs / Routings PRs may want
  the same placeholder pattern when version-counting on Routings list,
  etc.

## Things the plan got right (no deviation)

- Mirror `PartyList.tsx` structure exactly — page header / filter chips
  / search bar / table fell out cleanly.
- `NewJournalVoucherDialog.tsx` is the right reference for the 720px
  modal shell + validation banner slot + footer with Cancel + Submit.
- Per-form-mount Idempotency-Key (reset on close, on success, on error)
  matches the BE replay-cache contract.
- `useMoDetail.test.tsx` is the right vitest pattern: pin `IS_LIVE`
  before importing, drive everything via a `globalThis.fetch` mock.

## Pre-TASK-TR-E2 checklist

Ordered by what bites next.

### 1. Sibling E1 PRs (Operations, CostCentres, BOMs, Routings) will collide on `lib/queries/manufacturing.ts` + Sidebar.tsx + App.tsx

What: each adds its own `liveCreateXxx` / `useCreateXxx` next to mine,
and each adds a route + sub-nav entry. Rebase resolution = take both.
The `__live` barrel + `DESIGN_KEY` / `BOM_KEY` constants pattern is
already established; just append.

### 2. Add an `include_inactive` toggle to the BE `/designs` list

What: the Inactive filter chip is visible but currently always empty
because the BE filters soft-deleted designs server-side by default.
A 1-line addition (`include_inactive: bool = False` query param) plus
the corresponding service kwarg unlocks the chip's real semantics.
Out of scope for E1 by the task brief ("Don't touch the BE"); flag for
a follow-up B-track ticket.

### 3. Surface BOM / Routing version counts on `/designs` list response

What: extend `DesignListResponse` items with `active_bom_version: int?`
and `active_routing_version: int?` (or expose `bom_versions: int`).
Removes the em-dash placeholder. Same B-track follow-up.

## Open flags carried over

- **Spec drift:** `phase6-designs.jsx` shows `finished_item_id` on the
  design; the BE doesn't store it. Either the BE schema or the spec
  needs to be reconciled before the design detail page (E2?) ships.
  Re-surfaces in the Design detail task and the BOM editor task (both
  rely on knowing the "finished item" for a design).

## Observable state at end of task

- New route: `/manufacturing/designs`. Reachable via Sidebar >
  Manufacturing > Designs.
- The Manufacturing sidebar entry now has a 3-row sub-nav (Pipeline /
  Manufacturing orders / Designs). Other E1 sibling PRs will append.
- No new dev dependencies. No `.env` changes.
- Tests added: `DesignsList.test.tsx` (5), `NewDesignDialog.test.tsx`
  (6 incl. a pure `slugifyCode` unit case).
