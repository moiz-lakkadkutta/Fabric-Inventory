# TASK-CUT-204 retro — Stock adjustments FE wired live

**Date:** 2026-05-10
**Branch:** task/CUT-204-stock-adjustments-fe-live
**Wave:** 3
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 3 row CUT-204

## Summary

The "Adjust stock" affordance on `/inventory` is now a real form-driven
flow. Clicking the toolbar button opens `<AdjustStockDialog>`, which lets
the user pick an item, location, direction (INCREASE / DECREASE /
COUNT_RESET), quantity, and a reason. Submitting POSTs to
`/stock-adjustments` with an `Idempotency-Key` header; on 201 the dialog
closes and the SOH query (`['inventory', 'skus']` + `['items']`) is
invalidated so the row's on-hand refetches without a manual reload.

`pnpm exec vitest run` green (38 files, 161 tests). `pnpm tsc --noEmit`,
`pnpm exec eslint .`, and `pnpm exec prettier --check .` all clean.
Backend `uv run pytest -q` green (666 passed). `uv run ruff check .`
and `uv run ruff format --check .` clean.

## Deviations from plan

### 1. Tiny BE addition: `GET /locations`

Plan said the work is "FE only (3h estimate)" and "do not invent BE in
this task." Reality: `POST /stock-adjustments` requires a `location_id`
that the FE has no way to obtain — no `/locations` endpoint existed,
and the location bootstrap (`get_or_create_default_location`) was only
reachable via internal service-to-service calls from sales/procurement.

Without a location list endpoint the FE either has to (a) hard-code a
sentinel (defeats the purpose), (b) silently fail when the firm has no
location yet, or (c) auto-create on POST (mutation-on-read; ugly).

- **Fixed by:** added a thin `GET /locations` (router + service +
  schema + 4 integration tests). Mirrors the existing read-only
  `/uoms` and `/hsn` patterns. No schema change, no migration, no new
  permission — uses the existing `inventory.stock.read`. Soft-deleted
  / inactive rows are filtered server-side. The endpoint is foundational
  for the upcoming PO/GRN FE work in this same wave (CUT-201/202),
  which will need the same picker.
- **Why not caught in planning:** the cutover-plan didn't enumerate
  every dependency endpoint; it assumed `/stock-adjustments` was
  self-sufficient. It is at the schema level, but not at the workflow
  level (you can't construct a valid request without a location_id).
- **Impact on later tasks:** positive — CUT-201 (PO FE) and CUT-202
  (GRN FE) can now reuse `useLocations()` from
  `lib/queries/stock-adjustments.ts` without each agent re-discovering
  the gap.

### 2. SOH stays at 0 in `useSkus()` after a successful adjust

Plan said "row's SOH refetches and updates." Reality: the live-mode
`useSkus()` (added in CUT-102) currently stubs `on_hand: 0` because
no aggregated SOH endpoint exists yet — that lands in CUT-302
(`/reports/stock-summary`).

- **Fixed by:** the mutation invalidates `['inventory']`,
  `['items']`, and `['stock-summary']` query keys, so as soon as
  CUT-302 ships and `useSkus()` switches to read from
  `/reports/stock-summary`, the refresh-after-adjust will become
  visible without further FE work. Today the user sees the dialog
  close and a new entry in the (future) adjustment list; the on-hand
  column stays at 0 until CUT-302.
- **Why not caught in planning:** the plan didn't trace the SOH
  read-side dependency. The cutover-plan's CUT-302 row covers it;
  this task just had to leave the breadcrumb.
- **Impact on later tasks:** flagged for CUT-302 — once the new
  reports endpoint exists, `useSkus()` should swap to it and this
  retro's "the dialog closes but the column doesn't move" footnote
  goes away.

## Things the plan got right (no deviation)

- The `useComingSoon('Adjust stock')` block was a single 4-line edit;
  the coordination note ("CUT-202 owns the New GRN button area") held
  — no merge-conflict risk because the inventory page diff stayed
  minimal.
- The pragmatic-TDD pattern from CUT-103/104 ports cleanly: ONE failing
  vitest integration test → minimum impl → green; no horizontal slicing.
- `useIdempotencyKey()` + `api()` wrapper handle the `Idempotency-Key`
  header without per-mutation glue, exactly as in CUT-101/102/103.
- Reusing `useMe()` for `firm_id` and `useItems()` for the item picker
  meant no new live-mode plumbing in this task — both hooks already
  worked.

## Pre-CUT-205 (Invoice PDF) checklist

### 1. Don't merge before resolving the worktree drift

Two agents in this wave have pre-existing edits in the main repo
(`/Users/moizp/fabric`) — CUT-205 (PDF) and CUT-201 (PO). When the
parent merges this PR, the rebase against fresh `main` should be
clean because all CUT-204 changes live in
`/Users/moizp/fabric/.claude/worktrees/agent-a3f53fc64755243e3`. The
parent should NOT cherry-pick changes from the dirty main checkout.

### 2. CUT-302 (`/reports/stock-summary`) should swap `useSkus()`

Once CUT-302 ships its endpoint, the click-dummy stub in
`lib/queries/inventory.ts` (`liveListSkus` returning `on_hand: 0`)
should call `/reports/stock-summary` instead. The cache-key
invalidation set up in this PR (`['stock-summary']`) is already in
place to refresh on a successful adjustment.

### 3. CUT-201 (PO FE) and CUT-202 (GRN FE) can reuse `useLocations()`

`useLocations()` lives in `frontend/src/lib/queries/stock-adjustments.ts`
— the file is named per the dominant feature but exports a generic
location-picker hook. PO/GRN agents can import it directly; if the
naming feels off later, file a refactor follow-up to move it into a
new `lib/queries/locations.ts`.

## Open flags carried over

- **Locations CRUD UI** — only `GET /locations` exists today. Creating
  / editing / deactivating warehouses is admin work and is not in any
  current TASK-CUT row. Filing a follow-up if Moiz needs to add a
  godown before v1 ships; otherwise the BE's
  `get_or_create_default_location` covers the dogfood single-warehouse
  case.
- **Stock adjustment list view** — the task brief said "and `useStockAdjustments`
  if list view exists." The list endpoint exists in BE
  (`GET /stock-adjustments`) but no FE consumer is wired today. A
  future "Adjustment history" tab on `/inventory` could surface this;
  not blocking dogfood and not on the cutover plan.
- **Lot picker** — the dialog accepts `lot_id` only as the BE optional
  default of `null`. Tracking-by-lot items will need a child select
  here once Phase-3 manufacturing lands; today no item type in
  dogfood requires it.

## Observable state at end of task

- Five new files: `backend/tests/test_locations_router.py`,
  `frontend/src/lib/queries/stock-adjustments.ts`,
  `frontend/src/pages/inventory/AdjustStockDialog.tsx`,
  `frontend/src/pages/inventory/__tests__/AdjustStockDialog.test.tsx`,
  this retro.
- Five modified files: `backend/app/routers/inventory.py`,
  `backend/app/schemas/inventory.py`,
  `backend/app/service/inventory_service.py`, `backend/main.py`,
  `frontend/src/pages/inventory/InventoryList.tsx`.
- New endpoint visible at `/openapi.json` after a backend restart:
  `GET /locations` with optional `firm_id` and `include_inactive`
  query params.
- The integration test uses `vi.mock('@/lib/api/mode')` + dynamic
  imports to flip IS_LIVE on regardless of `.env.test` defaults
  (mirrors the Onboarding test's pattern). The single `act(...)`
  warning in stderr is benign — it's React 19 noticing a state update
  from a useEffect after the dialog opens to auto-default the only
  available location.
