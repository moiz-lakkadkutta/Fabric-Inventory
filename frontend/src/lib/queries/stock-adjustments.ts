/*
 * stock-adjustments.ts (TASK-CUT-204) — live + mock branches.
 *
 * Hooks:
 *   useLocations()             — GET /locations?firm_id=…
 *   useCreateStockAdjustment() — POST /stock-adjustments (Idempotency-Key)
 *
 * On a successful create, the mutation invalidates the inventory SKU
 * list query (`['inventory', 'skus']`) so the InventoryList row's
 * stock-on-hand refetches without a manual reload.
 *
 * Mock branch is intentionally minimal — the click-dummy never
 * exercised stock adjustments; mock callers see synthetic success
 * envelopes so unit-tests against the dialog can run without a backend.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';

// ──────────────────────────────────────────────────────────────────────
// Wire-shape types — hand-rolled to match backend/app/schemas/inventory.py.
// CUT-106 codegen will replace these once `stock-adjustments` is included
// in the OpenAPI snapshot.
// ──────────────────────────────────────────────────────────────────────

export type LocationType =
  | 'WAREHOUSE'
  | 'GODOWN'
  | 'SHELF'
  | 'BIN'
  | 'IN_TRANSIT'
  | 'STAGING'
  | 'SCRAP';

export interface BackendLocation {
  location_id: string;
  org_id: string;
  firm_id: string;
  code: string;
  name: string;
  location_type: LocationType;
  is_active: boolean | null;
}

export interface BackendLocationListResponse {
  items: BackendLocation[];
  count: number;
}

export type StockAdjustmentDirection = 'INCREASE' | 'DECREASE' | 'COUNT_RESET';

export interface BackendStockAdjustment {
  stock_adjustment_id: string;
  org_id: string;
  firm_id: string;
  item_id: string;
  lot_id: string | null;
  location_id: string;
  qty_change: string;
  reason: string | null;
  requires_approval: boolean | null;
  approved_by: string | null;
  approved_at: string | null;
  created_by: string | null;
  created_at: string;
}

export interface CreateStockAdjustmentBody {
  firm_id: string;
  item_id: string;
  location_id: string;
  /** Decimal-as-string to preserve precision over the wire. */
  qty: string;
  direction: StockAdjustmentDirection;
  lot_id?: string | null;
  reason?: string | null;
  txn_date?: string | null;
  /** INR rupees as decimal-string. Only used by INCREASE / COUNT_RESET. */
  unit_cost?: string | null;
}

// ──────────────────────────────────────────────────────────────────────
// Locations — read-only list
// ──────────────────────────────────────────────────────────────────────

const LOCATIONS_KEY = ['locations'] as const;

async function liveListLocations(firmId: string | null): Promise<BackendLocation[]> {
  const path = firmId ? `/locations?firm_id=${encodeURIComponent(firmId)}` : '/locations';
  const data = await api<BackendLocationListResponse>(path);
  return data.items;
}

export function useLocations(firmId: string | null | undefined) {
  return useQuery({
    queryKey: [...LOCATIONS_KEY, firmId ?? null],
    enabled: firmId !== undefined && firmId !== null,
    queryFn: () =>
      IS_LIVE
        ? liveListLocations(firmId ?? null)
        : fakeFetch<BackendLocation[]>(() => [
            {
              location_id: 'l_mock_main',
              org_id: 'o_mock',
              firm_id: firmId ?? 'f_mock',
              code: 'MAIN',
              name: 'Main Warehouse',
              location_type: 'WAREHOUSE',
              is_active: true,
            },
          ]),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Create stock adjustment
// ──────────────────────────────────────────────────────────────────────

export interface CreateStockAdjustmentInput {
  body: CreateStockAdjustmentBody;
  idempotencyKey: string;
}

async function liveCreate(input: CreateStockAdjustmentInput): Promise<BackendStockAdjustment> {
  return await api<BackendStockAdjustment>('/stock-adjustments', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: input.body,
  });
}

async function mockCreate(input: CreateStockAdjustmentInput): Promise<BackendStockAdjustment> {
  return fakeFetch(() => {
    const direction = input.body.direction;
    const qty = input.body.qty;
    const qtyChange = direction === 'DECREASE' ? `-${qty}` : qty;
    return {
      stock_adjustment_id: `adj_mock_${Date.now()}`,
      org_id: 'o_mock',
      firm_id: input.body.firm_id,
      item_id: input.body.item_id,
      lot_id: input.body.lot_id ?? null,
      location_id: input.body.location_id,
      qty_change: qtyChange,
      reason: input.body.reason ?? null,
      requires_approval: false,
      approved_by: null,
      approved_at: null,
      created_by: 'u_mock',
      created_at: new Date().toISOString(),
    };
  });
}

export function useCreateStockAdjustment() {
  const qc = useQueryClient();
  return useMutation<BackendStockAdjustment, ApiError | Error, CreateStockAdjustmentInput>({
    mutationFn: (input) => (IS_LIVE ? liveCreate(input) : mockCreate(input)),
    onSuccess: () => {
      // SOH derives from the items / stock-summary / skus aggregations;
      // invalidate broadly so any visible inventory view refetches.
      qc.invalidateQueries({ queryKey: ['inventory'] });
      qc.invalidateQueries({ queryKey: ['items'] });
      qc.invalidateQueries({ queryKey: ['stock-summary'] });
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Create location (CUT-206)
//
// Surfaced during the wave-3 demo: the AdjustStockDialog's location
// picker is empty for a fresh-firm user. POST /locations lets the
// dialog's empty-state lay down the first warehouse inline so they
// don't have to reach a future Locations admin page.
// ──────────────────────────────────────────────────────────────────────

export interface CreateLocationBody {
  firm_id: string;
  code: string;
  name: string;
  location_type?: LocationType;
}

export interface CreateLocationInput {
  body: CreateLocationBody;
  idempotencyKey: string;
}

async function liveCreateLocation(input: CreateLocationInput): Promise<BackendLocation> {
  return await api<BackendLocation>('/locations', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: input.body,
  });
}

async function mockCreateLocation(input: CreateLocationInput): Promise<BackendLocation> {
  return fakeFetch(() => ({
    location_id: `l_mock_${Date.now()}`,
    org_id: 'o_mock',
    firm_id: input.body.firm_id,
    code: input.body.code,
    name: input.body.name,
    location_type: input.body.location_type ?? 'WAREHOUSE',
    is_active: true,
  }));
}

export function useCreateLocation() {
  const qc = useQueryClient();
  return useMutation<BackendLocation, ApiError | Error, CreateLocationInput>({
    mutationFn: (input) => (IS_LIVE ? liveCreateLocation(input) : mockCreateLocation(input)),
    onSuccess: () => {
      // After a new location lands the dialog's location dropdown must
      // include it; invalidating the ['locations'] key triggers refetch
      // across all firm scopes.
      qc.invalidateQueries({ queryKey: LOCATIONS_KEY });
    },
  });
}
