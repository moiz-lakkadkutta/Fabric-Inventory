/*
 * TanStack Query hooks for Delivery Challans (TASK-CUT-203).
 *
 * Same pattern as sales-orders.ts — thin BE wrappers in
 * `lib/api/delivery-challans.ts` plus this module that maps shapes and
 * provides cache-aware mutations. Mock mode returns an empty list (the
 * click-dummy never had DCs).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import {
  liveCreateDC,
  liveGetDC,
  liveIssueDC,
  liveListDCs,
  type BackendDC,
  type BackendDCCreateBody,
  type BackendDCLine,
  type BackendDCStatus,
  type ListDCsParams,
} from '@/lib/api/delivery-challans';
import { fakeFetch } from '@/lib/mock/api';

const KEY = ['delivery-challans'] as const;

// ──────────────────────────────────────────────────────────────────────
// FE shape — money in paise (CLAUDE.md).
// ──────────────────────────────────────────────────────────────────────

export interface DeliveryChallanLine {
  dc_line_id: string;
  delivery_challan_id: string;
  item_id: string;
  lot_id: string | null;
  qty_dispatched: number;
  /** Per-unit price in paise (nullable on the BE for transfer DCs). */
  price: number | null;
  sequence: number | null;
}

export interface DeliveryChallan {
  delivery_challan_id: string;
  org_id: string;
  firm_id: string;
  series: string;
  number: string;
  /** `${series}/${number}` — for display. */
  display_number: string;
  sales_order_id: string | null;
  party_id: string;
  bill_to_address: string | null;
  ship_to_address: string | null;
  place_of_supply_state: string | null;
  dispatch_date: string;
  status: BackendDCStatus;
  total_qty: number;
  /** Total amount in paise. */
  total_amount: number;
  lines: DeliveryChallanLine[];
  created_at: string;
  updated_at: string;
}

// ──────────────────────────────────────────────────────────────────────
// Mappers — BE rupees-as-string → FE paise-as-int.
// ──────────────────────────────────────────────────────────────────────

function rupeesToPaise(amount: string | number | null | undefined): number {
  if (amount === null || amount === undefined) return 0;
  const n = typeof amount === 'number' ? amount : parseFloat(amount);
  if (!Number.isFinite(n)) return 0;
  return Math.round(n * 100);
}

function paiseToRupees(paise: number): string {
  return (paise / 100).toFixed(2);
}

function mapLine(line: BackendDCLine): DeliveryChallanLine {
  return {
    dc_line_id: line.dc_line_id,
    delivery_challan_id: line.delivery_challan_id,
    item_id: line.item_id,
    lot_id: line.lot_id,
    qty_dispatched: parseFloat(line.qty_dispatched),
    price: line.price ? rupeesToPaise(line.price) : null,
    sequence: line.sequence,
  };
}

function mapDC(b: BackendDC): DeliveryChallan {
  // BE `status` is typed as a free-form string in the response model; the
  // values are constrained to the DCStatus enum at the ORM level. Cast
  // narrows to the enum so consumers can switch over a finite set.
  const status = (b.status ?? 'DRAFT') as BackendDCStatus;
  return {
    delivery_challan_id: b.delivery_challan_id,
    org_id: b.org_id,
    firm_id: b.firm_id,
    series: b.series,
    number: b.number,
    display_number: `${b.series}/${b.number}`,
    sales_order_id: b.sales_order_id,
    party_id: b.party_id,
    bill_to_address: b.bill_to_address,
    ship_to_address: b.ship_to_address,
    place_of_supply_state: b.place_of_supply_state,
    dispatch_date: b.dispatch_date,
    status,
    total_qty: b.total_qty ? parseFloat(b.total_qty) : 0,
    total_amount: rupeesToPaise(b.total_amount),
    lines: b.lines.map(mapLine),
    created_at: b.created_at,
    updated_at: b.updated_at,
  };
}

// ──────────────────────────────────────────────────────────────────────
// Queries.
// ──────────────────────────────────────────────────────────────────────

async function liveList(params: ListDCsParams = {}): Promise<DeliveryChallan[]> {
  const data = await liveListDCs(params);
  return data.items.map(mapDC);
}

export function useDeliveryChallans(params: ListDCsParams = {}) {
  return useQuery({
    queryKey: [...KEY, params],
    queryFn: () => (IS_LIVE ? liveList(params) : fakeFetch(() => [] as DeliveryChallan[])),
  });
}

export function useDc(dcId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, dcId],
    enabled: dcId !== undefined,
    queryFn: () =>
      IS_LIVE
        ? liveGetDC(dcId as string).then(mapDC)
        : fakeFetch(() => null as DeliveryChallan | null),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Mutations.
// ──────────────────────────────────────────────────────────────────────

export interface CreateDcLineInput {
  item_id: string;
  qty_dispatched: number;
  /** Per-unit price in paise. Optional for transfer / job-work DCs. */
  price?: number;
  lot_id?: string;
  sequence?: number;
}

export interface CreateDcInput {
  firm_id: string;
  party_id: string;
  dispatch_date: string;
  series?: string;
  sales_order_id?: string;
  bill_to_address?: string;
  ship_to_address?: string;
  /** Two-character state code (e.g. "MH"). Required for inter-state. */
  place_of_supply_state?: string;
  lines: CreateDcLineInput[];
  idempotencyKey: string;
}

export function buildCreateBody(input: CreateDcInput): BackendDCCreateBody {
  if (input.lines.length === 0) {
    throw new Error('Delivery challan requires at least one line.');
  }
  return {
    firm_id: input.firm_id,
    party_id: input.party_id,
    dispatch_date: input.dispatch_date,
    series: input.series ?? 'DC/2526',
    sales_order_id: input.sales_order_id ?? null,
    bill_to_address: input.bill_to_address ?? null,
    ship_to_address: input.ship_to_address ?? null,
    place_of_supply_state: input.place_of_supply_state ?? null,
    lines: input.lines.map((line, idx) => ({
      item_id: line.item_id,
      qty_dispatched: line.qty_dispatched.toString(),
      price: line.price !== undefined ? paiseToRupees(line.price) : null,
      lot_id: line.lot_id ?? null,
      sequence: line.sequence ?? idx + 1,
    })),
  };
}

async function liveCreate(input: CreateDcInput): Promise<DeliveryChallan> {
  const body = buildCreateBody(input);
  const data = await liveCreateDC(body, input.idempotencyKey);
  return mapDC(data);
}

export function useCreateDc() {
  const qc = useQueryClient();
  return useMutation<DeliveryChallan, ApiError | Error, CreateDcInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveCreate(input)
        : fakeFetch(() => {
            throw new Error(
              'Mock mode: Delivery Challans are live-only. Set VITE_API_MODE=live to use this feature.',
            );
          }),
    onSuccess: (dc) => {
      qc.setQueryData([...KEY, dc.delivery_challan_id], dc);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}

export interface IssueDcInput {
  dcId: string;
  idempotencyKey: string;
}

export function useIssueDc() {
  const qc = useQueryClient();
  return useMutation<DeliveryChallan, ApiError | Error, IssueDcInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveIssueDC(input.dcId, input.idempotencyKey).then(mapDC)
        : fakeFetch(() => {
            throw new Error('Mock mode: Delivery Challans are live-only.');
          }),
    onSuccess: (dc) => {
      qc.setQueryData([...KEY, dc.delivery_challan_id], dc);
      qc.invalidateQueries({ queryKey: KEY });
      // Issuing a DC advances the linked SO; bust the SO cache too.
      qc.invalidateQueries({ queryKey: ['sales-orders'] });
    },
  });
}

// Test-only exports.
export const _internal = {
  mapDC,
  mapLine,
  rupeesToPaise,
  paiseToRupees,
  buildCreateBody,
};
