# TASK-TR-E1-BOMS retro — BOM list + 3-tab create wizard

**Date:** 2026-05-24
**Branch:** task/tr-e1-boms
**Commit:** `<sha>` (PR pending)
**Plan:** brief delivered inline (no separate plan file)

## Summary

Shipped the Bills-of-materials master surface: a list page grouped by
design with version chips (Active pill on the active row, "Superseded"
on prior versions) and a 3-tab create wizard (Design & version → Lines
dense editor → Review & activate with diff). Wired `useCreateBom` +
`useActivateBom` mutations + a thin `createBom` / `activateBom` pair in
`lib/api/manufacturing.ts`. New routes `/manufacturing/boms` +
`/manufacturing/boms/new` are reachable from the Manufacturing sub-nav.

Lint + typecheck + the full vitest suite (496 tests, including 25 new)
all pass.

## Deviations from plan

### 1. `scrap_pct` is UI-only — the BE schema has no column for it

Plan said the wire body would include `scrap_pct?` per line. The
backend `BomLineInput` (read directly from
`backend/app/schemas/manufacturing.py`) has no scrap column.
- **Fixed by:** captured `scrap_pct` on the local `BomLineDraft` and
  drove only the cost-rollup display from it; dropped from the wire
  body. Test asserts the field never reaches the POST.
- **Why not caught in planning:** the brief listed `scrap_pct?` as
  optional but didn't flag the BE gap.
- **Impact on later tasks:** if a future migration adds the column, a
  one-liner in `BomCreateWizard.submit` is the only FE change.

### 2. Activate is POST not PATCH

Plan said `PATCH /boms/{id}/activate`. Backend exposes it as `POST`.
- **Fixed by:** `activateBom` in `lib/api/manufacturing.ts` uses POST.
- **Why not caught in planning:** brief and BE drifted.

### 3. `lib/api/manufacturing.ts` already existed (sibling agent collision)

Brief said "create" the file. A sibling E1-COSTCENTRES PR already
created it.
- **Fixed by:** appended BOM wrappers to the existing file. Same
  decision for `App.tsx` + `Sidebar.tsx` (sibling already added cost-
  centres entries; I added BOM entries alongside).
- **Why not caught in planning:** brief noted the collision risk but
  didn't say which sibling would land first; outcome reads cleanly
  either way.

### 4. No per-item `standard_cost` on the wire today

The cost-rollup design implies a `qty × item.standard_cost` formula,
but the items endpoint surfaces `default_cost` only on SKUs, not on
the item header.
- **Fixed by:** editor displays "—" for std cost + line cost when no
  cost source is wired; cost rollup still computes correctly when the
  parent passes a `standard_cost_paise` value (the unit-tested code
  path). A follow-up can add a per-item rollup query that hydrates
  costs.
- **Why not caught in planning:** the brief mentioned `item.standard_cost`
  without verifying it exists end-to-end.
- **Impact on later tasks:** future "BOM rollup cost" task can plug
  into the same `BomLineItemChoice.standard_cost_paise` field without
  touching the editor.

### 5. List page "Cost / unit" column displays "—"

The list page header includes a Cost-per-unit column per the design.
The BE doesn't return a roll-up cost on the BOM response, so the
column shows "—" for every row.
- **Fixed by:** kept the column for visual fidelity; surfaced "—".
- **Impact:** plumbed; one query change away once a cost endpoint
  exists.

## Things the plan got right (no deviation)

- 3-tab wizard chrome maps cleanly to MoCreateWizard's pattern; reused
  the same tab-progress + footer layout.
- Dense lines editor isolates well into `_components/`. Pure helpers
  (`computeRollup`, `computeLineCostPaise`) are unit-testable without
  React.
- Diff vs current active BOM is straightforward: build two
  `Map<item_id, {qty, uom}>` and walk the union.

## Pre-next checklist

### 1. Verify the rebase order onto main

Four sibling agents touched `App.tsx`, `Sidebar.tsx`, and
`lib/queries/manufacturing.ts`. The CI matrix on PR merge will surface
conflicts on the last of the four; resolution is "take both sides".

### 2. Wire per-item `standard_cost` so the cost rollup is real

Until then, the wizard UI is correct shape-wise but always shows "—"
for cost in production. Add a hydrator hook (probably in `queries/
items.ts` or a new `useItemCosts()` that fetches SKU `default_cost`
and rolls up by item) and pass `standard_cost_paise` through
`lineItems` in `BomCreateWizard`.

### 3. Add scrap_pct column to BomLine on the BE

The UI carries it locally today; a follow-up adds a NUMERIC(5,2)
column + migration so the value persists across sessions.

## Observable state at end of task

- New routes: `/manufacturing/boms`, `/manufacturing/boms/new`.
- New sidebar entry: "Bills of materials" under Manufacturing.
- Manufacturing-namespace permissions touched: `manufacturing.bom.create`,
  `manufacturing.bom.read`, `manufacturing.bom.update`. The BE already
  grants these to the existing Manufacturing manager role.
- All tests + lint pass; no skips, no `xit` / `xdescribe`.
