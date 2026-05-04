import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { invoices as seedInvoices } from '@/lib/mock/invoices';
import type { Invoice, InvoiceLine, InvoiceStatus } from '@/lib/mock/types';
import { authStore } from '@/store/auth';

const KEY = ['invoices'] as const;

// ──────────────────────────────────────────────────────────────────────
// Mock store (click-dummy database). Live branch lives below.
// ──────────────────────────────────────────────────────────────────────

let store: Invoice[] | null = null;

function ensureStore() {
  if (store === null) store = [...seedInvoices];
  return store;
}

export function resetInvoiceStore() {
  store = null;
}

// ──────────────────────────────────────────────────────────────────────
// Live-mode mappers — backend SalesInvoiceResponse → frontend Invoice.
// Money is rupees (Decimal-as-string) on the wire, paise (integer) in
// the click-dummy. We multiply by 100 at the boundary so existing
// components keep their formatting code unchanged.
// ──────────────────────────────────────────────────────────────────────

interface BackendSiLine {
  si_line_id: string;
  item_id: string;
  item_name: string | null;
  item_uom: string | null;
  qty: string;
  price: string;
  line_amount: string | null;
  gst_rate: string | null;
  gst_amount: string | null;
  sequence: number | null;
}

interface BackendSalesInvoice {
  sales_invoice_id: string;
  org_id: string;
  firm_id: string;
  series: string;
  number: string;
  party_id: string;
  party_name: string | null;
  invoice_date: string;
  due_date: string | null;
  invoice_amount: string | null;
  gst_amount: string | null;
  paid_amount: string;
  lifecycle_status: string;
  place_of_supply_state: string | null;
  invoice_type: string | null;
  tax_type: string | null;
  round_off: string;
  notes: string | null;
  lines: BackendSiLine[];
  created_at: string;
  updated_at: string;
}

interface BackendSalesInvoiceListItem {
  sales_invoice_id: string;
  firm_id: string;
  series: string;
  number: string;
  party_id: string;
  party_name: string | null;
  invoice_date: string;
  due_date: string | null;
  invoice_amount: string | null;
  paid_amount: string;
  lifecycle_status: string;
  place_of_supply_state: string | null;
  created_at: string;
}

interface BackendInvoiceListResponse {
  items: BackendSalesInvoiceListItem[];
  limit: number;
  offset: number;
  count: number;
}

function rupeesToPaise(amount: string | null | undefined): number {
  if (!amount) return 0;
  // JS lacks a native decimal — round to the nearest paise to avoid 1599.9999.
  return Math.round(parseFloat(amount) * 100);
}

const STATUS_MAP: Record<string, InvoiceStatus> = {
  DRAFT: 'DRAFT',
  CONFIRMED: 'DRAFT',
  FINALIZED: 'FINALIZED',
  POSTED: 'FINALIZED',
  PARTIALLY_PAID: 'PARTIALLY_PAID',
  PAID: 'PAID',
  OVERDUE: 'OVERDUE',
  CANCELLED: 'CANCELLED',
  DISCARDED: 'CANCELLED',
};

function mapStatus(lifecycle: string): InvoiceStatus {
  return STATUS_MAP[lifecycle] ?? 'DRAFT';
}

function ageingDays(dueDate: string | null, today: Date = new Date()): number {
  if (!dueDate) return 0;
  const due = new Date(dueDate + 'T00:00:00Z');
  const ms = today.getTime() - due.getTime();
  return Math.floor(ms / (1000 * 60 * 60 * 24));
}

function mapLine(line: BackendSiLine): InvoiceLine {
  return {
    item_id: line.item_id,
    item_name: line.item_name ?? '',
    qty: parseFloat(line.qty),
    uom: line.item_uom ?? 'PCS',
    rate: rupeesToPaise(line.price),
    amount: rupeesToPaise(line.line_amount ?? '0'),
    gst_pct: line.gst_rate ? parseFloat(line.gst_rate) : 0,
    gst_amount: rupeesToPaise(line.gst_amount ?? '0'),
  };
}

function mapDocType(tax_type: string | null, invoice_type: string | null): Invoice['doc_type'] {
  if (invoice_type === 'CASH_MEMO') return 'CASH_MEMO';
  if (invoice_type === 'BILL_OF_SUPPLY') return 'BILL_OF_SUPPLY';
  if (invoice_type === 'ESTIMATE') return 'ESTIMATE';
  if (tax_type === 'NIL_LUT' || tax_type === 'NIL_NOT_A_SUPPLY') return 'BILL_OF_SUPPLY';
  return 'TAX_INVOICE';
}

function mapDetail(b: BackendSalesInvoice): Invoice {
  const subtotalPaise = rupeesToPaise(b.invoice_amount) - rupeesToPaise(b.gst_amount);
  return {
    invoice_id: b.sales_invoice_id,
    number: `${b.series}/${b.number}`,
    date: b.invoice_date,
    due_date: b.due_date ?? b.invoice_date,
    party_id: b.party_id,
    party_name: b.party_name ?? '',
    party_state: b.place_of_supply_state ?? '',
    status: mapStatus(b.lifecycle_status),
    subtotal: subtotalPaise,
    gst_total: rupeesToPaise(b.gst_amount),
    total: rupeesToPaise(b.invoice_amount),
    paid: rupeesToPaise(b.paid_amount),
    ageing_days: ageingDays(b.due_date),
    lines: b.lines.map(mapLine),
    doc_type: mapDocType(b.tax_type, b.invoice_type),
  };
}

function mapListItem(b: BackendSalesInvoiceListItem): Invoice {
  return {
    invoice_id: b.sales_invoice_id,
    number: `${b.series}/${b.number}`,
    date: b.invoice_date,
    due_date: b.due_date ?? b.invoice_date,
    party_id: b.party_id,
    party_name: b.party_name ?? '',
    party_state: b.place_of_supply_state ?? '',
    status: mapStatus(b.lifecycle_status),
    subtotal: 0,
    gst_total: 0,
    total: rupeesToPaise(b.invoice_amount),
    paid: rupeesToPaise(b.paid_amount),
    ageing_days: ageingDays(b.due_date),
    lines: [],
    doc_type: 'TAX_INVOICE',
  };
}

// ──────────────────────────────────────────────────────────────────────
// Public hooks — both Q6 branches.
// ──────────────────────────────────────────────────────────────────────

async function liveListInvoices(): Promise<Invoice[]> {
  const data = await api<BackendInvoiceListResponse>('/invoices?limit=200');
  return data.items.map(mapListItem);
}

async function liveGetInvoice(invoiceId: string): Promise<Invoice | null> {
  const data = await api<BackendSalesInvoice>(`/invoices/${invoiceId}`);
  return mapDetail(data);
}

export function useInvoices() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => (IS_LIVE ? liveListInvoices() : fakeFetch(() => [...ensureStore()])),
  });
}

export function useInvoice(invoiceId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, invoiceId],
    enabled: invoiceId !== undefined,
    queryFn: () =>
      IS_LIVE
        ? liveGetInvoice(invoiceId as string)
        : fakeFetch(() => ensureStore().find((i) => i.invoice_id === invoiceId) ?? null),
  });
}

// ──────────────────────────────────────────────────────────────────────
// create + finalize — both Q6 branches.
//
// Live branch maps the frontend's paise-Invoice draft into the backend's
// rupees-as-string SalesInvoiceCreateRequest. Finalize hits
// `/v1/invoices/{id}/finalize`; INVOICE_STATE_ERROR (already finalized)
// is caught by the api() wrapper and surfaces as ApiError, which the
// caller maps to a refresh affordance.
// ──────────────────────────────────────────────────────────────────────

interface BackendCreateLine {
  item_id: string;
  qty: string;
  price: string;
  gst_rate: string;
  sequence: number;
}

interface BackendCreateBody {
  firm_id: string;
  party_id: string;
  invoice_date: string;
  due_date: string | null;
  ship_to_state: string | null;
  lines: BackendCreateLine[];
}

function paiseToRupees(paise: number): string {
  return (paise / 100).toFixed(2);
}

function buildCreateBody(
  draft: Omit<Invoice, 'invoice_id' | 'number' | 'status'>,
): BackendCreateBody {
  const me = authStore.get().me;
  if (!me?.firm_id) {
    // Live mode requires an active firm in the JWT — same posture as
    // /v1/dashboard/kpis. Surface a clean error rather than letting the
    // api() wrapper return a confusing PERMISSION_DENIED later.
    throw new Error('No active firm in this session — switch to a firm first.');
  }
  return {
    firm_id: me.firm_id,
    party_id: draft.party_id,
    invoice_date: draft.date,
    due_date: draft.due_date || null,
    ship_to_state: draft.party_state || null,
    lines: draft.lines.map((line, idx) => ({
      item_id: line.item_id,
      qty: line.qty.toString(),
      price: paiseToRupees(line.rate),
      gst_rate: line.gst_pct.toString(),
      sequence: idx + 1,
    })),
  };
}

async function liveCreateDraft(
  draft: Omit<Invoice, 'invoice_id' | 'number' | 'status'>,
  idempotencyKey: string,
): Promise<Invoice> {
  const body = buildCreateBody(draft);
  const data = await api<Parameters<typeof mapDetail>[0]>('/invoices', {
    method: 'POST',
    idempotencyKey,
    body,
  });
  return mapDetail(data);
}

async function liveFinalize(invoiceId: string, idempotencyKey: string): Promise<Invoice> {
  const data = await api<Parameters<typeof mapDetail>[0]>(`/invoices/${invoiceId}/finalize`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
  return mapDetail(data);
}

export interface FinalizeInput {
  invoiceId: string;
  idempotencyKey: string;
}

export function useFinalizeInvoice() {
  const qc = useQueryClient();
  return useMutation<Invoice, ApiError | Error, FinalizeInput | string>({
    mutationFn: async (input) => {
      // Back-compat: existing callers pass a plain invoiceId string.
      // New callers pass {invoiceId, idempotencyKey} so the live mutation
      // gets a proper key.
      const invoiceId = typeof input === 'string' ? input : input.invoiceId;
      const idempotencyKey = typeof input === 'string' ? crypto.randomUUID() : input.idempotencyKey;
      if (IS_LIVE) return liveFinalize(invoiceId, idempotencyKey);
      return fakeFetch(() => {
        const list = ensureStore();
        const idx = list.findIndex((i) => i.invoice_id === invoiceId);
        if (idx === -1) throw new Error(`Invoice ${invoiceId} not found`);
        const next: Invoice = { ...list[idx], status: 'FINALIZED' };
        store = [...list.slice(0, idx), next, ...list.slice(idx + 1)];
        return next;
      });
    },
    onSuccess: (next) => {
      qc.setQueryData<Invoice[]>(
        KEY,
        (prev) => prev?.map((i) => (i.invoice_id === next.invoice_id ? next : i)) ?? prev,
      );
      qc.setQueryData([...KEY, next.invoice_id], next);
    },
  });
}

export interface CreateDraftInput {
  draft: Omit<Invoice, 'invoice_id' | 'number' | 'status'>;
  idempotencyKey: string;
}

export function useCreateDraftInvoice() {
  const qc = useQueryClient();
  return useMutation<
    Invoice,
    ApiError | Error,
    CreateDraftInput | Omit<Invoice, 'invoice_id' | 'number' | 'status'>
  >({
    mutationFn: async (input) => {
      const draft =
        'idempotencyKey' in input && 'draft' in input
          ? (input as CreateDraftInput).draft
          : (input as Omit<Invoice, 'invoice_id' | 'number' | 'status'>);
      const idempotencyKey =
        'idempotencyKey' in input && 'draft' in input
          ? (input as CreateDraftInput).idempotencyKey
          : crypto.randomUUID();
      if (IS_LIVE) return liveCreateDraft(draft, idempotencyKey);
      return fakeFetch(() => {
        const list = ensureStore();
        const seq = 2000 + list.length;
        const created: Invoice = {
          ...draft,
          invoice_id: `inv_${seq}`,
          number: `RT/2526/${String(seq - 1000).padStart(4, '0')}`,
          status: 'DRAFT',
        };
        store = [created, ...list];
        return created;
      });
    },
    onSuccess: (created) => {
      qc.setQueryData<Invoice[]>(KEY, (prev) => (prev ? [created, ...prev] : [created]));
      qc.setQueryData([...KEY, created.invoice_id], created);
    },
  });
}

// Test-only exports — used by the live-mapping unit tests.
export const _internal = {
  mapDetail,
  mapListItem,
  mapStatus,
  rupeesToPaise,
  ageingDays,
  paiseToRupees,
  buildCreateBody,
};
