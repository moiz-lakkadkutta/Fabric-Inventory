import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { receipts, vouchers } from '@/lib/mock/accounts';
import type { Receipt } from '@/lib/mock/accounts';
import type { components } from '@/types/api';

const RECEIPTS_KEY = ['accounts', 'receipts'] as const;

// Reuse the backend's `mode` enum on POST /receipts directly from the
// codegen so adding a new mode (e.g. CHEQUE) on the BE shows up here
// as a TypeScript surface change. The mock fixture's Receipt.mode is
// wider (it includes CHEQUE for legacy demo rows) — but new receipts
// posted through the UI are constrained to what the API accepts.
export type ReceiptMode = components['schemas']['ReceiptCreateRequest']['mode'];

// ──────────────────────────────────────────────────────────────────────
// Live wire shape — backend returns rupees-as-string. The list endpoint
// joins party + payment_allocation + sales_invoice so the UI gets
// party_name, mode, and the allocated invoice numbers without a second
// roundtrip. `mode` is parsed from the DR voucher line description on
// the backend; it's nullable for legacy/manually-built receipts.
//
// Schemas come from the codegen output; drift is caught by `pnpm
// check:types` in CI.
// ──────────────────────────────────────────────────────────────────────

type BackendReceiptListItem = components['schemas']['ReceiptListItem'];
type BackendReceiptList = components['schemas']['ReceiptListResponse'];

function rupeesToPaise(amount: string | null | undefined): number {
  if (!amount) return 0;
  return Math.round(parseFloat(amount) * 100);
}

function paiseToRupees(paise: number): string {
  return (paise / 100).toFixed(2);
}

const ALLOWED_MODES: Receipt['mode'][] = ['CASH', 'BANK', 'UPI', 'CHEQUE'];

function normalizeMode(raw: string | null | undefined): Receipt['mode'] {
  if (!raw) return 'CASH';
  const upper = raw.toUpperCase() as Receipt['mode'];
  return ALLOWED_MODES.includes(upper) ? upper : 'CASH';
}

function mapReceiptListItem(b: BackendReceiptListItem): Receipt {
  return {
    receipt_id: b.voucher_id,
    number: `${b.series}/${b.number}`,
    date: b.voucher_date,
    party_id: b.party_id ?? '',
    party_name: b.party_name ?? '',
    amount: rupeesToPaise(b.amount),
    mode: normalizeMode(b.mode),
    reference: b.narration ?? '',
    status: 'POSTED',
    // BE schema declares `allocations: list[...] = Field(default_factory=list)`,
    // which pydantic emits as optional in OpenAPI — codegen surfaces this
    // accurately as `Allocation[] | undefined`. Default to [] so the UI's
    // "1 invoice / 2 invoices" pill code can iterate without a guard.
    allocated_to: (b.allocations ?? []).map((a) => a.invoice_number),
  };
}

async function liveListReceipts(): Promise<Receipt[]> {
  const data = await api<BackendReceiptList>('/receipts?limit=100');
  return data.items.map(mapReceiptListItem);
}

export function useReceipts() {
  return useQuery({
    queryKey: RECEIPTS_KEY,
    queryFn: () => (IS_LIVE ? liveListReceipts() : fakeFetch([...receipts])),
  });
}

export function useVouchers() {
  return useQuery({
    queryKey: ['accounts', 'vouchers'],
    queryFn: () => fakeFetch([...vouchers]),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Record-payment mutation — used by InvoiceDetail's "Record payment".
// Mock branch builds a local Receipt; live posts /v1/receipts.
// ──────────────────────────────────────────────────────────────────────

export interface PostReceiptInput {
  partyId: string;
  partyName: string;
  amountPaise: number;
  receiptDate: string;
  mode: ReceiptMode;
  reference?: string;
  idempotencyKey: string;
}

type BackendReceiptResponse = components['schemas']['ReceiptResponse'];

async function livePostReceipt(input: PostReceiptInput): Promise<Receipt> {
  const data = await api<BackendReceiptResponse>('/receipts', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: {
      party_id: input.partyId,
      amount: paiseToRupees(input.amountPaise),
      receipt_date: input.receiptDate,
      mode: input.mode,
      reference: input.reference ?? null,
    },
  });
  return {
    receipt_id: data.voucher_id,
    number: `${data.series}/${data.number}`,
    date: data.voucher_date,
    party_id: input.partyId,
    party_name: input.partyName,
    amount: rupeesToPaise(data.amount),
    mode: input.mode,
    reference: input.reference ?? '',
    status: 'POSTED',
    // Same default-factory rationale as the list mapper above.
    allocated_to: (data.allocations ?? []).map((a) => a.sales_invoice_id),
  };
}

export function usePostReceipt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: PostReceiptInput): Promise<Receipt> => {
      if (IS_LIVE) return livePostReceipt(input);
      return fakeFetch(() => ({
        receipt_id: `rcpt_${Date.now()}`,
        number: `RCT/2526/${String(Date.now() % 9999).padStart(4, '0')}`,
        date: input.receiptDate,
        party_id: input.partyId,
        party_name: input.partyName,
        amount: input.amountPaise,
        mode: input.mode,
        reference: input.reference ?? '',
        status: 'POSTED',
        allocated_to: [],
      }));
    },
    onSuccess: (receipt) => {
      qc.setQueryData<Receipt[]>(RECEIPTS_KEY, (prev) => (prev ? [receipt, ...prev] : [receipt]));
      // Invalidate invoices so the detail page refreshes its lifecycle.
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

export const _internal = {
  mapReceiptListItem,
  rupeesToPaise,
  paiseToRupees,
};
