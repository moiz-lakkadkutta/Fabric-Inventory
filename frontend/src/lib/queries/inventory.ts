/*
 * inventory.ts — InventoryList view-model wiring.
 *
 * Live-mode `useSkus()` reads `GET /reports/stock-summary` and maps each
 * BE row into the `SkuRow` view-model consumed by `InventoryList.tsx`.
 * The stock-summary endpoint is the canonical source of on-hand qty +
 * weighted-average cost (CUT-302) and already factors in every
 * stock_ledger movement (GRN, stock adjustments, MO consumption, etc.).
 *
 * Fields that the BE doesn't yet expose on stock-summary:
 *   - `reorder`: no reorder-level column on `item` today; carried as 0
 *     until a future masters/items task adds it. The InventoryList
 *     page renders a "Low stock" pill when `on_hand < reorder` and
 *     reorder > 0, so the pill stays dormant in live mode and lights
 *     up in mock/click-dummy mode where the fixture has thresholds.
 *     TASK-TR-B06 picked path (b) — FE-only signal, no schema change —
 *     because adding a column requires Moiz sign-off per CLAUDE.md
 *     Ask-vs-Decide. When the column lands, set `reorder` from the
 *     BE row here and the visual signal flips on automatically.
 *   - `mix`: stage-by-stage breakdown is a per-lot concept and there's
 *     no aggregated endpoint yet; left empty so `<StatusMixBar>` simply
 *     renders an empty bar.
 *   - `lots`: per-SKU lot count not in the stock-summary projection;
 *     carried as 0 until that aggregate is added. The dedicated
 *     `useLots()` hook below pulls lot rows for the LotDetail screen.
 *
 * Once those gaps land, this mapper extends — the InventoryList page
 * already reads from these fields and will surface them automatically.
 *
 * `useLots()` / `useLot(lotId)` were mock-only through the click-dummy
 * era; TASK-TR-B02 wires them to `GET /lots` and `GET /lots/{lot_id}`
 * in live mode. The mock branch is kept so click-dummy builds continue
 * to render the rich stages-timeline fixture (which the BE doesn't
 * expose for v1).
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { findLot, lots, skuRows, type SkuRow } from '@/lib/mock/inventory';
import { authStore } from '@/store/auth';
import type { components } from '@/types/api';

type BackendStockSummaryResponse = components['schemas']['StockSummaryResponse'];
type BackendStockSummaryRow = components['schemas']['StockSummaryRow'];

export type BackendLot = components['schemas']['LotResponse'];
type BackendLotListResponse = components['schemas']['LotListResponse'];

const SKU_ROW_UOMS = new Set<SkuRow['uom']>(['METER', 'PIECE', 'KG']);

/**
 * Map one stock-summary row to the SkuRow view-model. UoMs the page
 * doesn't render natively (LITER, SET, ROLL, …) collapse to PIECE so
 * the row still appears with a sane unit suffix.
 */
export function mapStockRowToSku(b: BackendStockSummaryRow): SkuRow {
  const uom = SKU_ROW_UOMS.has(b.uom as SkuRow['uom']) ? (b.uom as SkuRow['uom']) : 'PIECE';
  return {
    // BE returns sku_id only when the item has variants; fall back to
    // item_id so the row stays uniquely keyed.
    sku_id: b.sku_id ?? b.item_id,
    code: b.sku_code ?? b.item_code,
    name: b.item_name,
    uom,
    // qty stays a number for display (toLocaleString); precision is
    // tolerated because qty isn't money. See reports.ts mapStockRow.
    on_hand: parseFloat(b.on_hand_qty || '0'),
    // No reorder-level on the BE yet; default to 0. The page renders
    // the row's reorder column in --text-tertiary when 0, so this
    // shows up as a neutral "no threshold" rather than a danger flag.
    reorder: 0,
    // Status mix is a per-lot rollup that needs a richer per-stage
    // aggregation than /lots exposes; leave empty until a future
    // /stock-mix endpoint lands.
    mix: {},
    // Lots count requires a per-SKU rollup the stock-summary doesn't
    // expose today; carried as 0 until that aggregate is added.
    lots: 0,
  };
}

async function liveListSkus(): Promise<SkuRow[]> {
  const data = await api<BackendStockSummaryResponse>('/reports/stock-summary');
  return data.rows.map(mapStockRowToSku);
}

export function useSkus() {
  return useQuery({
    queryKey: ['inventory', 'skus'],
    queryFn: () => (IS_LIVE ? liveListSkus() : fakeFetch([...skuRows])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Lots (TASK-TR-B02) — live-mode hits GET /lots, mock-mode keeps the
// click-dummy fixture so the rich stages timeline still demos.
//
// Live shape is the BE's LotResponse (lot_number, item_code, item_name,
// primary_uom, qty_on_hand, dates, etc.). Click-dummy shape is the
// fixture in `lib/mock/inventory.ts` (with stages + bin). Consumers
// branch on `IS_LIVE` to pick the right renderer.
// ──────────────────────────────────────────────────────────────────────

export interface ListLotsParams {
  firm_id?: string;
  item_id?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

async function liveListLots(params: ListLotsParams): Promise<BackendLot[]> {
  const firm_id = params.firm_id ?? authStore.get().me?.firm_id;
  if (!firm_id) {
    throw new Error('No active firm in this session — switch to a firm first.');
  }
  const usp = new URLSearchParams();
  usp.set('firm_id', firm_id);
  if (params.item_id) usp.set('item_id', params.item_id);
  if (params.search) usp.set('search', params.search);
  usp.set('limit', String(params.limit ?? 50));
  usp.set('offset', String(params.offset ?? 0));
  const data = await api<BackendLotListResponse>(`/lots?${usp.toString()}`);
  return data.items;
}

async function liveGetLot(lotId: string): Promise<BackendLot> {
  return api<BackendLot>(`/lots/${lotId}`);
}

type LotForView = BackendLot | (typeof lots)[number];

export function useLots(params: ListLotsParams = {}) {
  return useQuery<LotForView[]>({
    queryKey: ['inventory', 'lots', params],
    queryFn: async (): Promise<LotForView[]> =>
      IS_LIVE ? await liveListLots(params) : await fakeFetch<LotForView[]>([...lots]),
  });
}

export function useLot(lotId: string | undefined) {
  return useQuery<LotForView | null>({
    queryKey: ['inventory', 'lots', lotId],
    enabled: lotId !== undefined,
    queryFn: async (): Promise<LotForView | null> =>
      IS_LIVE
        ? await liveGetLot(lotId as string)
        : await fakeFetch(() => (lotId ? (findLot(lotId) ?? null) : null)),
  });
}

// Test-only exports — keeps the mapper unit-testable without exposing
// it as a public hook contract.
export const _internal = {
  mapStockRowToSku,
};
