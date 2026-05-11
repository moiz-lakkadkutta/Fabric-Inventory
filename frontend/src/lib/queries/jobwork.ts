/*
 * jobwork.ts (TASK-CUT-401) — live + mock branches.
 *
 * Hooks:
 *   useJobWorkOrders()         — GET /job-work-orders?firm_id=…
 *   useCreateJobWorkOrder()    — POST /job-work-orders (Idempotency-Key)
 *   useReceiveJobWork()        — POST /job-work-orders/{id}/receive (Idempotency-Key)
 *   useKarigars()              — GET /parties?party_type=karigar
 *
 * Wire-shape types are pulled from the generated `@/types/api` so they
 * stay locked to the OpenAPI snapshot (CUT-106).
 *
 * Per-karigar grouping (qty pending = sent − received − wastage) is
 * derived in `groupByKarigar` so the dashboard component and any
 * future report sharing the rollup hit the same code path.
 *
 * Quantities are Decimal-as-string over the wire (CLAUDE.md "money is
 * Decimal" applies to qty too — fabric job-work runs in 0.5m / 1.5m
 * lots). The UI sends the raw user string; the BE validates.
 *
 * Mock branch note: job-work was never in the click-dummy fixtures, so
 * mock mode simply resolves to empty lists / synthetic 201 success
 * objects (no mock-store coupling), per the CUT-401 grep-clean
 * acceptance criterion.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { liveListParties, type BackendParty } from '@/lib/api/parties';
import type { components } from '@/types/api';

// ──────────────────────────────────────────────────────────────────────
// Wire shapes — re-exported from the OpenAPI snapshot.
// ──────────────────────────────────────────────────────────────────────

export type JobWorkOrder = components['schemas']['JobWorkOrderResponse'];
export type JobWorkOrderListResponse = components['schemas']['JobWorkOrderListResponse'];
export type JobWorkOrderCreateRequest = components['schemas']['JobWorkOrderCreateRequest'];
export type JobWorkOrderLineRequest = components['schemas']['JobWorkOrderLineRequest'];
export type JobWorkReceiveRequest = components['schemas']['JobWorkReceiveRequest'];
export type JobWorkReceiptResponse = components['schemas']['JobWorkReceiptResponse'];
export type JobWorkReceiptLineRequest = components['schemas']['JobWorkReceiptLineRequest'];
export type JobWorkOrderStatus = JobWorkOrder['status'];

const JWO_KEY = ['jobwork', 'orders'] as const;
const KARIGARS_KEY = ['jobwork', 'karigars'] as const;

// ──────────────────────────────────────────────────────────────────────
// List
// ──────────────────────────────────────────────────────────────────────

export interface ListJobWorkOrdersParams {
  firmId?: string | null;
  karigarPartyId?: string | null;
  status?: JobWorkOrderStatus | null;
  limit?: number;
  offset?: number;
}

async function liveListJobWorkOrders(
  params: ListJobWorkOrdersParams = {},
): Promise<JobWorkOrder[]> {
  const usp = new URLSearchParams();
  if (params.firmId) usp.set('firm_id', params.firmId);
  if (params.karigarPartyId) usp.set('karigar_party_id', params.karigarPartyId);
  if (params.status) usp.set('status', params.status);
  usp.set('limit', String(params.limit ?? 200));
  usp.set('offset', String(params.offset ?? 0));
  const qs = usp.toString();
  const data = await api<JobWorkOrderListResponse>(`/job-work-orders${qs ? `?${qs}` : ''}`);
  return data.items;
}

export function useJobWorkOrders(params: ListJobWorkOrdersParams = {}) {
  const cacheKey = [
    ...JWO_KEY,
    params.firmId ?? null,
    params.karigarPartyId ?? null,
    params.status ?? null,
  ] as const;
  return useQuery<JobWorkOrder[], ApiError | Error>({
    queryKey: cacheKey,
    queryFn: () => (IS_LIVE ? liveListJobWorkOrders(params) : Promise.resolve<JobWorkOrder[]>([])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Create send-out
// ──────────────────────────────────────────────────────────────────────

export interface CreateJobWorkOrderInput {
  body: JobWorkOrderCreateRequest;
  idempotencyKey: string;
}

async function liveCreateJobWorkOrder(input: CreateJobWorkOrderInput): Promise<JobWorkOrder> {
  return await api<JobWorkOrder>('/job-work-orders', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: input.body,
  });
}

function mockCreateJobWorkOrder(input: CreateJobWorkOrderInput): Promise<JobWorkOrder> {
  const now = new Date().toISOString();
  return Promise.resolve<JobWorkOrder>({
    job_work_order_id: `jwo_mock_${Date.now()}`,
    org_id: 'o_mock',
    firm_id: input.body.firm_id,
    karigar_party_id: input.body.karigar_party_id,
    series: input.body.series ?? 'JW/2026-27',
    number: `JW/2026-27/${String(Date.now()).slice(-4)}`,
    challan_date: input.body.challan_date,
    status: 'SENT',
    operation: input.body.operation ?? null,
    expected_return_date: input.body.expected_return_date ?? null,
    notes: input.body.notes ?? null,
    from_location_id: 'loc_main_mock',
    to_location_id: 'loc_jobwork_mock',
    created_at: now,
    updated_at: now,
    lines: input.body.lines.map((line, idx) => ({
      job_work_order_line_id: `jwol_mock_${idx}`,
      line_no: idx + 1,
      item_id: line.item_id,
      lot_id: line.lot_id ?? null,
      qty_sent: String(line.qty_sent),
      qty_received: '0',
      qty_wastage: '0',
      uom: line.uom,
      notes: line.notes ?? null,
    })),
  });
}

export function useCreateJobWorkOrder() {
  const qc = useQueryClient();
  return useMutation<JobWorkOrder, ApiError | Error, CreateJobWorkOrderInput>({
    mutationFn: (input) =>
      IS_LIVE ? liveCreateJobWorkOrder(input) : mockCreateJobWorkOrder(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JWO_KEY });
      // Sending stock out moves it MAIN → JOBWORK in the BE; the
      // inventory page's SOH derives from items aggregation, so
      // invalidate broadly.
      qc.invalidateQueries({ queryKey: ['inventory'] });
      qc.invalidateQueries({ queryKey: ['items'] });
      qc.invalidateQueries({ queryKey: ['stock-summary'] });
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Receive back
// ──────────────────────────────────────────────────────────────────────

export interface ReceiveJobWorkInput {
  jwoId: string;
  body: JobWorkReceiveRequest;
  idempotencyKey: string;
}

async function liveReceiveJobWork(input: ReceiveJobWorkInput): Promise<JobWorkReceiptResponse> {
  return await api<JobWorkReceiptResponse>(
    `/job-work-orders/${encodeURIComponent(input.jwoId)}/receive`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body: input.body,
    },
  );
}

function mockReceiveJobWork(input: ReceiveJobWorkInput): Promise<JobWorkReceiptResponse> {
  const now = new Date().toISOString();
  return Promise.resolve<JobWorkReceiptResponse>({
    job_work_receipt_id: `jwrcp_mock_${Date.now()}`,
    org_id: 'o_mock',
    firm_id: 'f_mock',
    job_work_order_id: input.jwoId,
    receipt_date: input.body.receipt_date,
    status: 'POSTED',
    notes: input.body.notes ?? null,
    created_at: now,
    updated_at: now,
    lines: input.body.lines.map((line, idx) => ({
      job_work_receipt_line_id: `jwrl_mock_${idx}`,
      line_no: idx + 1,
      job_work_order_line_id: line.job_work_order_line_id,
      item_id: 'i_mock',
      qty_received: String(line.qty_received ?? '0'),
      qty_wastage: String(line.qty_wastage ?? '0'),
      uom: 'PIECE',
      notes: line.notes ?? null,
    })),
  });
}

export function useReceiveJobWork() {
  const qc = useQueryClient();
  return useMutation<JobWorkReceiptResponse, ApiError | Error, ReceiveJobWorkInput>({
    mutationFn: (input) => (IS_LIVE ? liveReceiveJobWork(input) : mockReceiveJobWork(input)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JWO_KEY });
      qc.invalidateQueries({ queryKey: ['inventory'] });
      qc.invalidateQueries({ queryKey: ['items'] });
      qc.invalidateQueries({ queryKey: ['stock-summary'] });
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Karigars (parties where is_karigar=true)
// ──────────────────────────────────────────────────────────────────────

export interface KarigarRow {
  party_id: string;
  code: string;
  name: string;
  state_code: string | null;
}

function mapPartyToKarigar(p: BackendParty): KarigarRow {
  return {
    party_id: p.party_id,
    code: p.code,
    name: p.name,
    state_code: p.state_code ?? null,
  };
}

async function liveListKarigars(): Promise<KarigarRow[]> {
  const data = await liveListParties({ limit: 200, party_type: 'karigar' });
  return data.items.map(mapPartyToKarigar);
}

export function useKarigars() {
  return useQuery<KarigarRow[], ApiError | Error>({
    queryKey: KARIGARS_KEY,
    queryFn: () => (IS_LIVE ? liveListKarigars() : Promise.resolve<KarigarRow[]>([])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Karigar rollups — derive pending per-karigar from the JWO list.
// pending = sum(qty_sent) − sum(qty_received) − sum(qty_wastage)
// on every line of every order with that karigar.
//
// Quantities arrive as decimal-strings; we parse to Number for the
// rollup display only (no money math here — these are quantities for
// a UI card). The raw strings stay untouched for any downstream call.
// ──────────────────────────────────────────────────────────────────────

export interface KarigarRollup {
  karigar_party_id: string;
  /** Open JWOs = status != CLOSED and != CANCELLED. */
  open_orders: number;
  total_orders: number;
  /** Sum of remaining qty across all open JWO lines, by uom. */
  pending_by_uom: Record<string, number>;
}

function parseQty(s: string | null | undefined): number {
  if (!s) return 0;
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : 0;
}

export function groupByKarigar(orders: JobWorkOrder[]): KarigarRollup[] {
  const byKarigar = new Map<string, KarigarRollup>();
  for (const order of orders) {
    const k =
      byKarigar.get(order.karigar_party_id) ??
      ({
        karigar_party_id: order.karigar_party_id,
        open_orders: 0,
        total_orders: 0,
        pending_by_uom: {},
      } satisfies KarigarRollup);
    k.total_orders += 1;
    const isOpen = order.status !== 'CLOSED' && order.status !== 'CANCELLED';
    if (isOpen) k.open_orders += 1;
    for (const line of order.lines ?? []) {
      const remaining =
        parseQty(line.qty_sent) - parseQty(line.qty_received) - parseQty(line.qty_wastage);
      if (remaining > 0) {
        const uom = line.uom || 'UNIT';
        k.pending_by_uom[uom] = (k.pending_by_uom[uom] ?? 0) + remaining;
      }
    }
    byKarigar.set(order.karigar_party_id, k);
  }
  return Array.from(byKarigar.values());
}
