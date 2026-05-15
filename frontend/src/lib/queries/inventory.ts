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
 *     until a future masters/items task adds it.
 *   - `mix`: stage-by-stage breakdown is a per-lot concept and there's
 *     no aggregated endpoint yet; left empty so `<StatusMixBar>` simply
 *     renders an empty bar.
 *   - `lots`: no `/lots` endpoint exists yet (see retro for TASK-TR-B02
 *     follow-up); carried as 0.
 *
 * Once those gaps land, this mapper extends — the InventoryList page
 * already reads from these fields and will surface them automatically.
 *
 * `useLots()` / `useLot(lotId)` stay on the mock path because the BE has
 * no lots endpoint today. The lot fixture continues to back the
 * click-dummy LotDetail screen; live-mode lot viewing is scoped to
 * TASK-TR-B02.
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { findLot, lots, skuRows, type SkuRow } from '@/lib/mock/inventory';
import type { components } from '@/types/api';

type BackendStockSummaryResponse = components['schemas']['StockSummaryResponse'];
type BackendStockSummaryRow = components['schemas']['StockSummaryRow'];

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
    // Status mix is a per-lot rollup that needs a lots endpoint to
    // compute. Until TASK-TR-B02 ships /lots, leave empty.
    mix: {},
    // Lots count likewise depends on a lots endpoint; carry 0 until
    // TR-B02 lands.
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

export function useLots() {
  return useQuery({
    queryKey: ['inventory', 'lots'],
    // TASK-TR-B02: wire to GET /lots once the BE endpoint exists.
    queryFn: () => fakeFetch([...lots]),
  });
}

export function useLot(lotId: string | undefined) {
  return useQuery({
    queryKey: ['inventory', 'lots', lotId],
    enabled: lotId !== undefined,
    // TASK-TR-B02: wire to GET /lots/{id} once the BE endpoint exists.
    queryFn: () => fakeFetch(() => (lotId ? (findLot(lotId) ?? null) : null)),
  });
}

// Test-only exports — keeps the mapper unit-testable without exposing
// it as a public hook contract.
export const _internal = {
  mapStockRowToSku,
};
