# TASK-TR-B01 retro — Inventory list wired to live stock-summary backend

**Date:** 2026-05-15
**Branch:** task/tr-b01-inventory-stock
**Commit:** `<sha>` (pending PR merge)
**Plan:** TASK-TR-B01 brief (no plan file)

## Summary

Closed the audit finding that left `/inventory` rendering a hardcoded
`on_hand: 0` for every row even though the real backend
`GET /reports/stock-summary` had been live since CUT-302 and stock
adjustments were already mutating the underlying ledger. `useSkus()`
now reads the stock-summary envelope and maps each row into the
`SkuRow` view-model the page consumes. `AdjustStockDialog`'s existing
`['inventory']` query invalidation already covers the new query key,
so a successful adjustment immediately refetches the visible on-hand.
Lint, tsc, OpenAPI snapshot check, and the full vitest suite
(273 tests; 3 new) are green.

## What landed

- `frontend/src/lib/queries/inventory.ts`
  - Replaced the `liveListSkus()` zero-stub (which queried `/items`
    and hardcoded `on_hand: 0, lots: 0, reorder: 0, mix: {}`) with a
    real `api<BackendStockSummaryResponse>('/reports/stock-summary')`
    call.
  - Added `mapStockRowToSku()` which maps `StockSummaryRow` →
    `SkuRow`. `on_hand_qty` (decimal-as-string) becomes a number via
    `parseFloat`; qty is not money so the float is tolerated for
    display (matches the `reports.ts` pattern). UoMs the page doesn't
    render natively (LITER, SET, ROLL, …) collapse to PIECE so the
    row still renders with a sane unit suffix.
  - `sku_id` falls back to `item_id` when the BE row has no sku_id
    (fabric items often have no per-SKU breakdown — the BE comment
    on `StockSummaryRow` documents this).
  - Exported `_internal.mapStockRowToSku` for future unit tests; the
    existing tests cover the hook end-to-end via fetchMock.
- `frontend/src/pages/inventory/__tests__/InventoryList.live.test.tsx`
  - Three new live-mode integration tests:
    1. Renders real on-hand from `/reports/stock-summary` (asserts
       12.5 appears in the rendered DOM).
    2. Subtitle reflects the real SKU count from the live payload
       (asserts "2 SKUs" appears).
    3. After AdjustStockDialog success, the SKU list refetches and
       the on-hand updates from 5 → 8.
- `docs/retros/task-tr-b01.md` (this file).

No frontend pages, dialogs, or types other than the inventory query
module changed. `InventoryList.tsx` itself didn't need a diff — it
already reads from `useSkus().data` and the subtitle line
already says `${rows.length} SKUs · ${reduce on r.lots} active lots`.
Both numbers now reflect real data.

## Verdict on `useLots()` / `useLot(lotId)` — descoped to TASK-TR-B02

There's no `/lots` endpoint on the backend today:
- `backend/app/routers/` has `inventory.py` (only `/stock-adjustments`
  + `/locations`), no lots router.
- The OpenAPI snapshot has no `/lots` path. Grep across
  `frontend/src/types/api.ts` confirms.

Per the task brief — "Don't invent a backend endpoint" — I left both
`useLots` and `useLot` on the mock path with explicit `TASK-TR-B02:
wire to GET /lots…` comments. The LotDetail screen continues to read
the `lot001` fixture, which is fine for the click-dummy.

The `lots` column on InventoryList now shows 0 for every row in
live mode (the stock-summary envelope doesn't expose lot counts).
That's a real regression from the click-dummy's per-row 6/4/5/8 lot
counts, but it's an honest reflection of the data the BE can
produce today. Calling out as the primary motivation for TR-B02.

## Verdict on reorder levels

The `item` table has no reorder_level column. `ItemResponse` in
`frontend/src/types/api.ts` has no `reorder` field, and the
backend service / schema files confirm. `mapStockRowToSku` carries
`reorder: 0` with a TODO comment. The InventoryList row renders
`0` in `--text-tertiary` neutral colour for the reorder column,
which reads naturally as "no threshold set" rather than as a
danger flag.

Adding reorder-level is a masters-layer feature (a per-item or
per-firm settings field). Scoping it out of this task — flagged for
a future TASK in the items/masters thread.

## Verdict on `mix` (status mix bar)

The `mix` field is a per-lot stage breakdown that needs lots data
to compute (you can't summarise a SKU's status without iterating
the lots in each stage). Left as `{}` in the mapper — the existing
`<StatusMixBar>` simply renders an empty bar when mix has no
entries, which the live-mode users will see as a blank cell.

Same TR-B02 follow-up — once a `/lots` endpoint lands, the mapper
can aggregate lot counts and stage breakdowns into `lots` and `mix`
in the same call.

## Verdict on the AdjustStockDialog refetch

`useCreateStockAdjustment` already invalidates `['inventory']` (the
broad key — see `stock-adjustments.ts:165`). Since the new
`useSkus()` queryKey is `['inventory', 'skus']`, the existing
invalidation covers the new query for free. Confirmed by the third
new test: after a 201 on POST `/stock-adjustments`, the
stock-summary endpoint is hit a second time and the row's on-hand
updates from 5 → 8. No code change needed in the dialog or the
mutation hook.

## Deviations from plan

### 1. Did not extend reorder via a `/items` merge

The brief asked: "if the backend exposes a reorder level on the
item, use it. If not, leave it as 0 with a comment, OR fetch from
`/items` separately and merge. Investigate before implementing."

After investigation, `/items` has no reorder field either, so a
merge would have been pointless. Left as 0 with the comment.
Flagged for future masters work.

### 2. Did not unit-test `mapStockRowToSku` in isolation

The brief specified three component-level live tests; I shipped all
three. I considered adding a separate `inventory.live.test.ts` for
the mapper (like `items.live.test.ts` for `mapItemDetail`) but the
mapper is so thin (no money conversion, no enum normalisation
beyond a single fallback) that the integration tests cover it
already. Exported as `_internal.mapStockRowToSku` if a future task
wants to add unit-tests cheaply.

## Things the plan got right (no deviation)

- The stock-summary endpoint shape on the backend matches what the
  OpenAPI types describe — no codegen drift, `pnpm check:types` is
  clean.
- AdjustStockDialog's existing invalidation pattern was correct;
  no fix needed.
- `IS_MOCK` click-dummy path stayed working (existing
  `Inventory.test.tsx` mock tests pass unchanged).
- The `vi.mock('@/lib/api/mode')` pin-the-mode pattern from
  AdjustStockDialog.test.tsx applied verbatim — Vite would
  otherwise tree-shake the live branch under the test-env's
  `VITE_API_MODE=mock`.

## Pre-TASK-(NNN+1) checklist

### 1. TASK-TR-B02 — `/lots` backend endpoint + frontend wiring

Lot count, status mix, and the LotDetail screen are all currently
mocked. Building this means:
1. Backend `GET /lots?firm_id=…&item_id=…` and `GET /lots/{id}`
   routers backed by the existing `lot` and `stock_position` tables.
2. Aggregating `lots`-count and `mix` into the stock-summary
   response (or via a sibling endpoint).
3. Wiring `useLots` / `useLot` to live, replacing the click-dummy
   fixture.

After B02, the inventory list will be fully live with non-zero
status mix bars and real lot counts.

### 2. Reorder levels on `item` (or `sku`)

A future masters task should:
1. Migration: `ALTER TABLE item ADD COLUMN reorder_level NUMERIC(18,3)`.
2. Schema + service: expose `reorder_level` on ItemResponse.
3. Inventory mapper: read `reorder_level` (probably via a join in
   the stock-summary service) into `SkuRow.reorder`.

## Open flags carried over

- `useLots` / `useLot` still mocked. Resurfaces in TR-B02.
- Reorder level always 0 in live mode. Resurfaces in a masters-layer
  task.
- Status mix bar empty in live mode. Same as above, depends on TR-B02
  data shape.

## Observable state at end of task

- No env-var, migration, or service changes. Pure frontend wiring
  swap on a single query module + one new test file.
- The `/reports/stock-summary` permission is `accounting.report.view`;
  any role that can view the Inventory list will need that
  permission. Confirmed via the existing `require_permission` decorator
  in `backend/app/routers/reports.py:306`. Roles without it will see
  a 403 from the SKU query — the existing error toast surface in
  `InventoryList` (via `skusQuery.isError`) handles this case but
  isn't styled prominently; future a11y pass should add a clearer
  "you don't have permission to view stock levels" empty-state.
