import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError } from '@/lib/api/client';
import type {
  BackendHsn,
  BackendHsnListResponse,
  BackendItem,
  BackendItemListResponse,
  BackendSku,
  BackendSkuListResponse,
  BackendUom,
  BackendUomListResponse,
  HsnChoice,
  ItemCreateBody,
  ItemDetail,
  SkuCreateBody,
  SkuDetail,
  UomChoice,
} from '@/lib/api/items';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { items as mockItems } from '@/lib/mock/items';
import type { Item as MockItem } from '@/lib/mock/types';

// ──────────────────────────────────────────────────────────────────────
// Live-mode mappers — backend ItemResponse → frontend ItemDetail.
// Keep null-safe: GST-exempt items have null gst_rate; the InvoiceCreate
// dropdown reads the field directly so we coerce to 0 (not NaN).
// ──────────────────────────────────────────────────────────────────────

function rupeesToPaise(amount: string | null | undefined): number | null {
  if (amount === null || amount === undefined) return null;
  return Math.round(parseFloat(amount) * 100);
}

function mapItemDetail(b: BackendItem): ItemDetail {
  return {
    item_id: b.item_id,
    firm_id: b.firm_id,
    code: b.code,
    name: b.name,
    description: b.description,
    category: b.category,
    item_type: b.item_type,
    primary_uom: b.primary_uom,
    tracking: b.tracking ?? 'NONE',
    hsn_code: b.hsn_code,
    // Coerce missing/null gst_rate to 0 (GST-exempt items / Bill of Supply).
    // The InvoiceCreate dropdown reads this field into the line's gst_pct;
    // null/NaN there would break the GST calculation.
    gst_rate: b.gst_rate === null || b.gst_rate === undefined ? 0 : parseFloat(b.gst_rate),
    has_variants: b.has_variants ?? false,
    has_expiry: b.has_expiry ?? false,
    // Default to true for legacy rows where is_active hasn't been set;
    // a soft-deleted item has deleted_at != null and is filtered server-side.
    is_active: b.is_active ?? true,
    created_at: b.created_at,
    updated_at: b.updated_at,
  };
}

function mapSku(b: BackendSku): SkuDetail {
  return {
    sku_id: b.sku_id,
    firm_id: b.firm_id,
    item_id: b.item_id,
    code: b.code,
    attributes: b.variant_attributes ?? {},
    barcode_ean13: b.barcode_ean13,
    default_cost: rupeesToPaise(b.default_cost),
    created_at: b.created_at,
    updated_at: b.updated_at,
  };
}

function mapUom(b: BackendUom): UomChoice {
  return { code: b.code, label: b.name };
}

function mapHsn(b: BackendHsn): HsnChoice {
  return {
    hsn_id: b.hsn_id,
    hsn_code: b.hsn_code,
    description: b.description,
    gst_rate: b.gst_rate === null || b.gst_rate === undefined ? null : parseFloat(b.gst_rate),
  };
}

// ──────────────────────────────────────────────────────────────────────
// Mock-branch shim — the click-dummy uses a narrower Item shape.
// Map it to the live shape so consumers (ItemList page, InvoiceCreate
// dropdown) only need one type to think about.
// ──────────────────────────────────────────────────────────────────────

function mockItemToDetail(m: MockItem): ItemDetail {
  // Mock items use `type` ('RAW'/'FINISHED'/'SEMI_FINISHED'). Any of the
  // 7 BE enum values would be valid here; we coerce mock 'RAW' to 'RAW'
  // and 'SEMI_FINISHED' to 'SEMI_FINISHED'. The mock 'FINISHED' lines
  // up directly.
  const itemType: ItemDetail['item_type'] = m.type;
  const uom: ItemDetail['primary_uom'] = m.uom;
  return {
    item_id: m.item_id,
    firm_id: null,
    code: m.code,
    name: m.name,
    description: null,
    category: null,
    item_type: itemType,
    primary_uom: uom,
    tracking: 'NONE',
    hsn_code: m.hsn,
    gst_rate: 5, // Mock items default to 5% so the InvoiceCreate flow shows non-zero GST.
    has_variants: false,
    has_expiry: false,
    is_active: true,
    created_at: '2026-04-30T00:00:00Z',
    updated_at: '2026-04-30T00:00:00Z',
  };
}

// ──────────────────────────────────────────────────────────────────────
// Public hooks.
// ──────────────────────────────────────────────────────────────────────

const ITEMS_KEY = ['items'] as const;
const SKUS_KEY = ['skus'] as const;
const UOMS_KEY = ['uoms'] as const;
const HSN_KEY = ['hsn'] as const;

async function liveListItems(): Promise<ItemDetail[]> {
  const data = await api<BackendItemListResponse>('/items?limit=200');
  return data.items.map(mapItemDetail);
}

async function liveGetItem(itemId: string): Promise<ItemDetail | null> {
  const data = await api<BackendItem>(`/items/${itemId}`);
  return mapItemDetail(data);
}

async function liveListSkusForItem(itemId: string): Promise<SkuDetail[]> {
  const data = await api<BackendSkuListResponse>(`/items/${itemId}/skus`);
  return data.items.map(mapSku);
}

async function liveListUoms(): Promise<UomChoice[]> {
  const data = await api<BackendUomListResponse>('/uoms');
  return data.items.map(mapUom);
}

async function liveListHsn(): Promise<HsnChoice[]> {
  const data = await api<BackendHsnListResponse>('/hsn?limit=200');
  return data.items.map(mapHsn);
}

export function useItems() {
  return useQuery({
    queryKey: ITEMS_KEY,
    queryFn: () => (IS_LIVE ? liveListItems() : fakeFetch(() => mockItems.map(mockItemToDetail))),
  });
}

export function useItem(itemId: string | undefined) {
  return useQuery({
    queryKey: [...ITEMS_KEY, itemId],
    enabled: itemId !== undefined,
    queryFn: () =>
      IS_LIVE
        ? liveGetItem(itemId as string)
        : fakeFetch(() => {
            const m = mockItems.find((i) => i.item_id === itemId);
            return m ? mockItemToDetail(m) : null;
          }),
  });
}

export function useSkusForItem(itemId: string | undefined) {
  return useQuery({
    queryKey: [...SKUS_KEY, itemId],
    enabled: itemId !== undefined,
    queryFn: () =>
      IS_LIVE ? liveListSkusForItem(itemId as string) : fakeFetch(() => [] as SkuDetail[]),
  });
}

export function useUoms() {
  return useQuery({
    queryKey: UOMS_KEY,
    queryFn: () =>
      IS_LIVE
        ? liveListUoms()
        : fakeFetch(() =>
            (
              [
                'METER',
                'PIECE',
                'KG',
                'LITER',
                'SET',
                'GROSS',
                'DOZEN',
                'ROLL',
                'BUNDLE',
                'OTHER',
              ] as const
            ).map((code) => ({ code, label: code.charAt(0) + code.slice(1).toLowerCase() })),
          ),
  });
}

export function useHsn() {
  return useQuery({
    queryKey: HSN_KEY,
    queryFn: () =>
      IS_LIVE
        ? liveListHsn()
        : fakeFetch(
            () =>
              [
                { hsn_id: 'h-mock-1', hsn_code: '5208', description: 'Cotton fabric', gst_rate: 5 },
                {
                  hsn_id: 'h-mock-2',
                  hsn_code: '5407',
                  description: 'Synthetic fabric',
                  gst_rate: 5,
                },
                { hsn_id: 'h-mock-3', hsn_code: '6109', description: 'Apparel', gst_rate: 12 },
              ] as HsnChoice[],
          ),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Mutations — create / update / delete (live + mock).
//
// The live POST /items takes `hsn_code` (the digit string), NOT
// `hsn_id`. The BE looks up the HSN row by code. Caller MUST pass the
// digit code from the dropdown's `hsn_code` field.
// ──────────────────────────────────────────────────────────────────────

export interface CreateItemInput {
  body: ItemCreateBody;
  idempotencyKey: string;
}

async function liveCreateItem(input: CreateItemInput): Promise<ItemDetail> {
  const data = await api<BackendItem>('/items', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: input.body,
  });
  return mapItemDetail(data);
}

export function useCreateItem() {
  const qc = useQueryClient();
  return useMutation<ItemDetail, ApiError | Error, CreateItemInput>({
    mutationFn: async (input) => {
      if (IS_LIVE) return liveCreateItem(input);
      // Mock branch: construct a plausible item locally so the table
      // shows the new row. Doesn't persist beyond the page session.
      return fakeFetch(() => {
        const seq = mockItems.length + 1;
        const created: ItemDetail = {
          item_id: `i_mock_${seq}`,
          firm_id: input.body.firm_id ?? null,
          code: input.body.code,
          name: input.body.name,
          description: input.body.description ?? null,
          category: input.body.category ?? null,
          item_type: input.body.item_type,
          primary_uom: input.body.primary_uom,
          tracking: input.body.tracking ?? 'NONE',
          hsn_code: input.body.hsn_code ?? null,
          gst_rate: input.body.gst_rate ? parseFloat(input.body.gst_rate) : 0,
          has_variants: input.body.has_variants ?? false,
          has_expiry: input.body.has_expiry ?? false,
          is_active: input.body.is_active ?? true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        return created;
      });
    },
    onSuccess: (created) => {
      qc.setQueryData<ItemDetail[]>(ITEMS_KEY, (prev) => (prev ? [created, ...prev] : [created]));
      qc.setQueryData([...ITEMS_KEY, created.item_id], created);
    },
  });
}

export interface CreateSkuInput {
  itemId: string;
  body: SkuCreateBody;
  idempotencyKey: string;
}

async function liveCreateSku(input: CreateSkuInput): Promise<SkuDetail> {
  // POST /skus takes item_id as a query parameter (verified in BE router).
  const data = await api<BackendSku>(`/skus?item_id=${encodeURIComponent(input.itemId)}`, {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: input.body,
  });
  return mapSku(data);
}

export function useCreateSku() {
  const qc = useQueryClient();
  return useMutation<SkuDetail, ApiError | Error, CreateSkuInput>({
    mutationFn: async (input) => {
      if (IS_LIVE) return liveCreateSku(input);
      return fakeFetch(() => {
        const created: SkuDetail = {
          sku_id: `s_mock_${Date.now()}`,
          firm_id: input.body.firm_id ?? null,
          item_id: input.itemId,
          code: input.body.code,
          attributes: input.body.variant_attributes ?? {},
          barcode_ean13: input.body.barcode_ean13 ?? null,
          default_cost: input.body.default_cost ? rupeesToPaise(input.body.default_cost) : null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        return created;
      });
    },
    onSuccess: (created) => {
      qc.setQueryData<SkuDetail[]>([...SKUS_KEY, created.item_id], (prev) =>
        prev ? [...prev, created] : [created],
      );
    },
  });
}

export interface DeleteSkuInput {
  skuId: string;
  itemId: string;
  idempotencyKey: string;
}

async function liveDeleteSku(input: DeleteSkuInput): Promise<void> {
  await api<void>(`/skus/${input.skuId}`, {
    method: 'DELETE',
    idempotencyKey: input.idempotencyKey,
    body: {},
  });
}

export function useDeleteSku() {
  const qc = useQueryClient();
  return useMutation<void, ApiError | Error, DeleteSkuInput>({
    mutationFn: async (input) => {
      if (IS_LIVE) return liveDeleteSku(input);
      // Mock branch: no-op
      return fakeFetch(() => undefined);
    },
    onSuccess: (_, input) => {
      qc.setQueryData<SkuDetail[]>([...SKUS_KEY, input.itemId], (prev) =>
        prev ? prev.filter((s) => s.sku_id !== input.skuId) : prev,
      );
    },
  });
}

// Test-only exports.
export const _internal = {
  mapItemDetail,
  mapSku,
  mapUom,
  mapHsn,
  rupeesToPaise,
};
