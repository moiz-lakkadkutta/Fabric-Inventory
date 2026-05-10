import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import type { BackendItemListResponse } from '@/lib/api/items';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { findLot, lots, skuRows, type SkuRow } from '@/lib/mock/inventory';

/**
 * Live-mode SKU row — best-effort derivation from the items list.
 *
 * The BE has NO aggregated stock-on-hand endpoint yet. Real on-hand
 * computation lives behind Wave 3 TASK-CUT-204 (stock adjustments) and
 * Wave 4 reports (TASK-CUT-302's `/reports/stock-summary`). Until then,
 * live-mode `useSkus()` queries `GET /items` and stubs `on_hand: 0`
 * across all rows so the InventoryList page renders without crashing
 * but transparently shows zeros.
 *
 * TODO(CUT-204 / CUT-302): replace with `GET /reports/stock-summary`
 * once it ships, or hit `GET /skus` per item and aggregate via the
 * stock_ledger.
 */
async function liveListSkus(): Promise<SkuRow[]> {
  const data = await api<BackendItemListResponse>('/items?limit=200');
  return data.items.map((item) => ({
    sku_id: item.item_id, // No SKUs aggregated; stand in with item_id.
    code: item.code,
    name: item.name,
    uom: (['METER', 'PIECE', 'KG'].includes(item.primary_uom)
      ? item.primary_uom
      : 'PIECE') as SkuRow['uom'],
    on_hand: 0,
    reorder: 0,
    mix: {},
    lots: 0,
  }));
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
    queryFn: () => fakeFetch([...lots]),
  });
}

export function useLot(lotId: string | undefined) {
  return useQuery({
    queryKey: ['inventory', 'lots', lotId],
    enabled: lotId !== undefined,
    queryFn: () => fakeFetch(() => (lotId ? (findLot(lotId) ?? null) : null)),
  });
}
