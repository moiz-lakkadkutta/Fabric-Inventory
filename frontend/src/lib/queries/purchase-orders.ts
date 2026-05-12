import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import {
  liveCreatePo as livePostCreatePo,
  liveGetPo as liveGetBackendPo,
  liveLifecyclePo,
  liveListPos as liveGetBackendPos,
  type BackendPo,
  type BackendPoCreateRequest,
  type BackendPoLine,
  type PoLifecycleAction,
} from '@/lib/api/purchase-orders';
import { fakeFetch } from '@/lib/mock/api';
import { findPurchaseOrder, purchaseOrders as seedPos } from '@/lib/mock/purchase';
import type { MatchStatus, PoLine, PoStatus, PurchaseOrder } from '@/lib/mock/purchase';
import { authStore } from '@/store/auth';

/*
 * Purchase-Order queries — TASK-CUT-201.
 *
 * Mirrors the `lib/queries/invoices.ts` shape:
 *   - one mock branch (click-dummy continues to render seed data)
 *   - one live branch (hits real BE endpoints when IS_LIVE is true)
 *
 * Lifecycle endpoints (BE):
 *   POST /purchase-orders/{id}/approve  — DRAFT → APPROVED
 *   POST /purchase-orders/{id}/confirm  — DRAFT|APPROVED → CONFIRMED
 *   POST /purchase-orders/{id}/cancel   — refused once any GRN posted
 *
 * BE PurchaseOrderStatus enum:
 *   DRAFT | APPROVED | CONFIRMED | PARTIAL_GRN | FULLY_RECEIVED | CANCELLED
 *
 * FE click-dummy PoStatus enum:
 *   DRAFT | OPEN | GRN_RECEIVED | INVOICED | CLOSED | CANCELLED
 *
 * Mapping: APPROVED + CONFIRMED both collapse to OPEN (the FE click-dummy
 * doesn't differentiate); PARTIAL_GRN → GRN_RECEIVED; FULLY_RECEIVED →
 * CLOSED. INVOICED isn't reachable from the BE PO state (it lives on the
 * PI side) — the FE-only INVOICED value is preserved for the seed mock.
 */

const KEY = ['purchase', 'orders'] as const;

// Default series for new POs. Matches the BE's `default="PO/25-26"`
// posture for sales (`RT/2526`); the BE accepts whatever string we send
// as the `series` field, so this is a UI default only.
const DEFAULT_SERIES = 'PO/25-26';

// ──────────────────────────────────────────────────────────────────────
// Mock store — same shape as invoices.ts.
// ──────────────────────────────────────────────────────────────────────

let mockStore: PurchaseOrder[] | null = null;

function ensureMockStore(): PurchaseOrder[] {
  if (mockStore === null) mockStore = [...seedPos];
  return mockStore;
}

export function resetPurchaseOrderStore() {
  mockStore = null;
}

// ──────────────────────────────────────────────────────────────────────
// Live-mode mappers — backend POResponse → frontend PurchaseOrder.
// Money is rupees (Decimal-as-string) on the wire, paise (integer) in
// the click-dummy. We multiply by 100 at the boundary so existing
// components keep their formatting code unchanged.
// ──────────────────────────────────────────────────────────────────────

function rupeesToPaise(amount: string | null | undefined): number {
  if (!amount) return 0;
  return Math.round(parseFloat(amount) * 100);
}

function paiseToRupees(paise: number): string {
  return (paise / 100).toFixed(2);
}

const STATUS_MAP: Record<string, PoStatus> = {
  DRAFT: 'DRAFT',
  APPROVED: 'OPEN',
  CONFIRMED: 'OPEN',
  PARTIAL_GRN: 'GRN_RECEIVED',
  FULLY_RECEIVED: 'CLOSED',
  CANCELLED: 'CANCELLED',
};

function mapStatus(beStatus: string): PoStatus {
  return STATUS_MAP[beStatus] ?? 'DRAFT';
}

function mapLine(line: BackendPoLine): PoLine {
  const qty = parseFloat(line.qty_ordered);
  const ratePaise = rupeesToPaise(line.rate);
  return {
    item_id: line.item_id,
    // `item_name` is populated by the BE PO response (TASK-CUT-QA-03a)
    // so the detail page renders the human-readable name instead of the
    // raw UUID (bug B9). Optional — older cached payloads may omit it.
    item_name: line.item_name ?? undefined,
    qty,
    rate: ratePaise,
    amount: rupeesToPaise(line.line_amount ?? '0'),
    // PO doesn't track GST today on the BE side — taxes_applicable is a
    // free-form JSON dict, deferred to a future flow. Use 0 so totals
    // line up.
    gst_pct: 0,
  };
}

function pendingMatch(): MatchStatus {
  return 'pending';
}

function mapPo(b: BackendPo): PurchaseOrder {
  return {
    po_id: b.purchase_order_id,
    number: `${b.series}/${b.number}`,
    date: b.po_date,
    supplier_id: b.party_id,
    // The list/detail endpoints don't include supplier_name on the wire;
    // PartyList separately populates this when the user navigates from
    // a list. Use empty string as a safe default — the UI shows the
    // supplier_id-resolved name from useParty(supplier_id) if present.
    supplier_name: '',
    total: rupeesToPaise(b.total_amount),
    status: mapStatus(b.status),
    // Live POs render with a 'pending' triple until CUT-202 wires GRN/PI
    // live and CUT-205 brings the 3-way match status down to the row.
    po_match: pendingMatch(),
    grn_match: pendingMatch(),
    pi_match: pendingMatch(),
    expected_date: b.delivery_date ?? '',
    lines: b.lines.map(mapLine),
  };
}

// The list endpoint returns the same POResponse shape, so we share mapPo.
function mapPoListItem(b: BackendPo): PurchaseOrder {
  return mapPo(b);
}

// ──────────────────────────────────────────────────────────────────────
// Public hooks — list / detail.
// ──────────────────────────────────────────────────────────────────────

async function liveListPos(): Promise<PurchaseOrder[]> {
  const data = await liveGetBackendPos({ limit: 200 });
  return data.items.map(mapPoListItem);
}

async function liveGetPo(poId: string): Promise<PurchaseOrder | null> {
  const data = await liveGetBackendPo(poId);
  return mapPo(data);
}

export function usePurchaseOrders() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => (IS_LIVE ? liveListPos() : fakeFetch(() => [...ensureMockStore()])),
  });
}

export function usePurchaseOrder(poId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, poId],
    enabled: poId !== undefined,
    queryFn: () =>
      IS_LIVE
        ? liveGetPo(poId as string)
        : fakeFetch(() => (poId ? (findPurchaseOrder(poId) ?? null) : null)),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Create — POST /purchase-orders.
// ──────────────────────────────────────────────────────────────────────

export interface CreatePoLineInput {
  item_id: string;
  qty: number;
  rate: number; // paise
  gst_pct: number;
}

export interface CreatePoDraft {
  supplier_id: string;
  po_date: string; // YYYY-MM-DD
  expected_date: string; // YYYY-MM-DD or empty
  notes?: string;
  lines: CreatePoLineInput[];
}

function buildCreateBody(draft: CreatePoDraft, series: string): BackendPoCreateRequest {
  const me = authStore.get().me;
  if (!me?.firm_id) {
    throw new Error('No active firm in this session — switch to a firm first.');
  }
  return {
    firm_id: me.firm_id,
    party_id: draft.supplier_id,
    po_date: draft.po_date,
    delivery_date: draft.expected_date ? draft.expected_date : null,
    series,
    notes: draft.notes ?? null,
    lines: draft.lines.map((line, idx) => ({
      item_id: line.item_id,
      qty_ordered: line.qty.toString(),
      rate: paiseToRupees(line.rate),
      line_sequence: idx + 1,
    })),
  };
}

export interface CreatePoInput {
  draft: CreatePoDraft;
  idempotencyKey: string;
  series?: string;
}

async function liveCreatePo(input: CreatePoInput): Promise<PurchaseOrder> {
  const body = buildCreateBody(input.draft, input.series ?? DEFAULT_SERIES);
  const data = await livePostCreatePo(body, input.idempotencyKey);
  return mapPo(data);
}

async function mockCreatePo(input: CreatePoInput): Promise<PurchaseOrder> {
  return fakeFetch(() => {
    const list = ensureMockStore();
    const seq = 9100 + list.length + 1;
    const totalPaise = input.draft.lines.reduce((acc, l) => acc + l.qty * l.rate, 0);
    const created: PurchaseOrder = {
      po_id: `po_mock_${seq}`,
      number: `PO/25-26/${String(seq - 9000).padStart(4, '0')}`,
      date: input.draft.po_date,
      supplier_id: input.draft.supplier_id,
      supplier_name: '',
      total: totalPaise,
      status: 'DRAFT',
      po_match: 'pending',
      grn_match: 'pending',
      pi_match: 'pending',
      expected_date: input.draft.expected_date,
      lines: input.draft.lines.map((l) => ({
        item_id: l.item_id,
        qty: l.qty,
        rate: l.rate,
        amount: l.qty * l.rate,
        gst_pct: l.gst_pct,
      })),
    };
    mockStore = [created, ...list];
    return created;
  });
}

export function useCreatePo() {
  const qc = useQueryClient();
  return useMutation<PurchaseOrder, ApiError | Error, CreatePoInput>({
    mutationFn: (input) => (IS_LIVE ? liveCreatePo(input) : mockCreatePo(input)),
    onSuccess: (created) => {
      qc.setQueryData<PurchaseOrder[]>(KEY, (prev) => (prev ? [created, ...prev] : [created]));
      qc.setQueryData([...KEY, created.po_id], created);
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Lifecycle mutations — approve / confirm / cancel.
//
// Each is a POST /purchase-orders/{id}/{action}. They take an empty body
// but require an Idempotency-Key (the BE applies it via the
// auth-by-design middleware). Same Idempotency-Key on retry MUST return
// the same outcome (BE's idempotency cache handles it).
// ──────────────────────────────────────────────────────────────────────

export interface LifecycleInput {
  poId: string;
  idempotencyKey: string;
}

async function liveLifecycle(
  action: PoLifecycleAction,
  input: LifecycleInput,
): Promise<PurchaseOrder> {
  const data = await liveLifecyclePo(action, input.poId, input.idempotencyKey);
  return mapPo(data);
}

function mockLifecycle(action: PoLifecycleAction, input: LifecycleInput): Promise<PurchaseOrder> {
  return fakeFetch(() => {
    const list = ensureMockStore();
    const idx = list.findIndex((p) => p.po_id === input.poId);
    if (idx === -1) throw new Error(`Purchase order ${input.poId} not found`);
    const next: PurchaseOrder = { ...list[idx] };
    if (action === 'approve' || action === 'confirm') next.status = 'OPEN';
    if (action === 'cancel') next.status = 'CANCELLED';
    mockStore = [...list.slice(0, idx), next, ...list.slice(idx + 1)];
    return next;
  });
}

function buildLifecycleHook(action: PoLifecycleAction) {
  return function useLifecycle() {
    const qc = useQueryClient();
    return useMutation<PurchaseOrder, ApiError | Error, LifecycleInput>({
      mutationFn: (input) =>
        IS_LIVE ? liveLifecycle(action, input) : mockLifecycle(action, input),
      onSuccess: (next) => {
        qc.setQueryData<PurchaseOrder[]>(
          KEY,
          (prev) => prev?.map((p) => (p.po_id === next.po_id ? next : p)) ?? prev,
        );
        qc.setQueryData([...KEY, next.po_id], next);
      },
    });
  };
}

export const useApprovePo = buildLifecycleHook('approve');
export const useConfirmPo = buildLifecycleHook('confirm');
export const useCancelPo = buildLifecycleHook('cancel');

// ──────────────────────────────────────────────────────────────────────
// Status guards — what's enabled at each lifecycle step.
//
// FE PoStatus is the projection of BE state. The BE rules are:
//   approve : DRAFT only
//   confirm : DRAFT or APPROVED  (FE: DRAFT or OPEN)
//   cancel  : not PARTIAL_GRN nor FULLY_RECEIVED
// ──────────────────────────────────────────────────────────────────────

export function canApprove(status: PoStatus): boolean {
  return status === 'DRAFT';
}

export function canConfirm(status: PoStatus): boolean {
  return status === 'DRAFT' || status === 'OPEN';
}

export function canCancel(status: PoStatus): boolean {
  return status !== 'GRN_RECEIVED' && status !== 'CLOSED' && status !== 'CANCELLED';
}

// Test-only exports — used by the live-mapping unit tests.
export const _internal = {
  mapPo,
  mapPoListItem,
  mapStatus,
  mapLine,
  rupeesToPaise,
  paiseToRupees,
  buildCreateBody,
  DEFAULT_SERIES,
};

// Live wrappers exposed for fetch-mocked integration tests. The hooks
// short-circuit to mock mode in vitest because IS_LIVE is read from
// VITE_API_MODE at module load. Tests call __live.* directly to drive
// the wire-format paths.
export const __live = {
  liveListPos,
  liveGetPo,
  liveCreatePo,
  liveLifecycle,
};
