/*
 * TanStack Query hooks for Sales Orders (TASK-CUT-203).
 *
 * Mirrors the parties / items / invoices pattern: thin BE wrappers in
 * `lib/api/sales-orders.ts`, plus this module that composes them, maps
 * BE shapes to FE shapes, and provides cache-aware mutation hooks.
 *
 * The click-dummy never had Sales Orders (the route was a Placeholder
 * before this task). Mock-mode therefore returns an empty list and no-op
 * mutations — IS_LIVE=true is the only meaningful path. The mock branch
 * stays here only to keep the dev server alive when VITE_API_MODE=mock.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import {
  liveCancelSO,
  liveConfirmSO,
  liveCreateSO,
  liveGetSO,
  liveListSOs,
  type BackendSO,
  type BackendSOCreateBody,
  type BackendSOLine,
  type BackendSalesOrderStatus,
  type ListSOsParams,
} from '@/lib/api/sales-orders';
import { fakeFetch } from '@/lib/mock/api';

const KEY = ['sales-orders'] as const;

// ──────────────────────────────────────────────────────────────────────
// FE shape — money in paise (CLAUDE.md), dates as ISO YYYY-MM-DD strings
// (matches the rest of the app, no Date objects in stores).
// ──────────────────────────────────────────────────────────────────────

export interface SalesOrderLine {
  so_line_id: string;
  item_id: string;
  qty_ordered: number;
  qty_dispatched: number;
  /** Per-unit price in paise. */
  price: number;
  /** Total line amount in paise (price * qty). */
  line_amount: number;
  /** GST percentage as a number (e.g. 5, 12, 18). */
  gst_pct: number;
  sequence: number | null;
}

export interface SalesOrder {
  sales_order_id: string;
  org_id: string;
  firm_id: string;
  series: string;
  number: string;
  /** `${series}/${number}` — for display. */
  display_number: string;
  party_id: string;
  so_date: string;
  delivery_date: string | null;
  status: BackendSalesOrderStatus;
  /** Total amount in paise (subtotal across lines, no GST). */
  total_amount: number;
  notes: string | null;
  lines: SalesOrderLine[];
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

function mapLine(line: BackendSOLine): SalesOrderLine {
  return {
    so_line_id: line.so_line_id,
    item_id: line.item_id,
    qty_ordered: parseFloat(line.qty_ordered),
    qty_dispatched: line.qty_dispatched ? parseFloat(line.qty_dispatched) : 0,
    price: rupeesToPaise(line.price),
    line_amount: rupeesToPaise(line.line_amount),
    gst_pct: line.gst_rate ? parseFloat(line.gst_rate) : 0,
    sequence: line.sequence,
  };
}

function mapSO(b: BackendSO): SalesOrder {
  return {
    sales_order_id: b.sales_order_id,
    org_id: b.org_id,
    firm_id: b.firm_id,
    series: b.series,
    number: b.number,
    display_number: `${b.series}/${b.number}`,
    party_id: b.party_id,
    so_date: b.so_date,
    delivery_date: b.delivery_date,
    status: b.status,
    total_amount: rupeesToPaise(b.total_amount),
    notes: b.notes,
    lines: b.lines.map(mapLine),
    created_at: b.created_at,
    updated_at: b.updated_at,
  };
}

// ──────────────────────────────────────────────────────────────────────
// Queries.
// ──────────────────────────────────────────────────────────────────────

async function liveList(params: ListSOsParams = {}): Promise<SalesOrder[]> {
  const data = await liveListSOs(params);
  return data.items.map(mapSO);
}

export function useSalesOrders(params: ListSOsParams = {}) {
  return useQuery({
    queryKey: [...KEY, params],
    queryFn: () => (IS_LIVE ? liveList(params) : fakeFetch(() => [] as SalesOrder[])),
  });
}

export function useSalesOrder(soId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, soId],
    enabled: soId !== undefined,
    queryFn: () =>
      IS_LIVE ? liveGetSO(soId as string).then(mapSO) : fakeFetch(() => null as SalesOrder | null),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Mutations — create / confirm / cancel.
// ──────────────────────────────────────────────────────────────────────

export interface CreateSoLineInput {
  item_id: string;
  qty_ordered: number;
  /** Per-unit price in paise (FE convention). */
  price: number;
  gst_pct?: number;
  sequence?: number;
}

export interface CreateSoInput {
  firm_id: string;
  party_id: string;
  so_date: string;
  delivery_date?: string;
  series?: string;
  notes?: string;
  lines: CreateSoLineInput[];
  idempotencyKey: string;
}

export function buildCreateBody(input: CreateSoInput): BackendSOCreateBody {
  if (input.lines.length === 0) {
    throw new Error('Sales order requires at least one line.');
  }
  return {
    firm_id: input.firm_id,
    party_id: input.party_id,
    so_date: input.so_date,
    delivery_date: input.delivery_date ?? null,
    series: input.series ?? 'SO/2526',
    notes: input.notes ?? null,
    lines: input.lines.map((line, idx) => ({
      item_id: line.item_id,
      qty_ordered: line.qty_ordered.toString(),
      price: paiseToRupees(line.price),
      gst_rate: line.gst_pct !== undefined ? line.gst_pct.toString() : null,
      sequence: line.sequence ?? idx + 1,
    })),
  };
}

async function liveCreate(input: CreateSoInput): Promise<SalesOrder> {
  const body = buildCreateBody(input);
  const data = await liveCreateSO(body, input.idempotencyKey);
  return mapSO(data);
}

export function useCreateSo() {
  const qc = useQueryClient();
  return useMutation<SalesOrder, ApiError | Error, CreateSoInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveCreate(input)
        : fakeFetch(() => {
            throw new Error(
              'Mock mode: Sales Orders are live-only. Set VITE_API_MODE=live to use this feature.',
            );
          }),
    onSuccess: (so) => {
      qc.setQueryData([...KEY, so.sales_order_id], so);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}

export interface SoLifecycleInput {
  soId: string;
  idempotencyKey: string;
}

export function useConfirmSo() {
  const qc = useQueryClient();
  return useMutation<SalesOrder, ApiError | Error, SoLifecycleInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveConfirmSO(input.soId, input.idempotencyKey).then(mapSO)
        : fakeFetch(() => {
            throw new Error('Mock mode: Sales Orders are live-only.');
          }),
    onSuccess: (so) => {
      qc.setQueryData([...KEY, so.sales_order_id], so);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}

export function useCancelSo() {
  const qc = useQueryClient();
  return useMutation<SalesOrder, ApiError | Error, SoLifecycleInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveCancelSO(input.soId, input.idempotencyKey).then(mapSO)
        : fakeFetch(() => {
            throw new Error('Mock mode: Sales Orders are live-only.');
          }),
    onSuccess: (so) => {
      qc.setQueryData([...KEY, so.sales_order_id], so);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}

// Test-only exports.
export const _internal = {
  mapSO,
  mapLine,
  rupeesToPaise,
  paiseToRupees,
  buildCreateBody,
};
