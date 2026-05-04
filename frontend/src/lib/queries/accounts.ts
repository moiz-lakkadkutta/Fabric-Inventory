import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { receipts, vouchers } from '@/lib/mock/accounts';
import type { Receipt } from '@/lib/mock/accounts';

const RECEIPTS_KEY = ['accounts', 'receipts'] as const;

// ──────────────────────────────────────────────────────────────────────
// Live wire shape — backend returns rupees-as-string; allocations carry
// the sales_invoice_id (UUID). The mock fixture keys allocations by
// invoice number (display string). For live mode we just stash the UUIDs
// in `allocated_to` — the AccountingHub's Receipt table renders them
// verbatim, which is fine for dogfood until a join lands.
// ──────────────────────────────────────────────────────────────────────

interface BackendReceiptListItem {
  voucher_id: string;
  series: string;
  number: string;
  voucher_date: string;
  amount: string;
  narration: string | null;
  created_at: string;
}

interface BackendReceiptList {
  items: BackendReceiptListItem[];
  count: number;
}

function rupeesToPaise(amount: string | null | undefined): number {
  if (!amount) return 0;
  return Math.round(parseFloat(amount) * 100);
}

function paiseToRupees(paise: number): string {
  return (paise / 100).toFixed(2);
}

function mapReceiptListItem(b: BackendReceiptListItem): Receipt {
  return {
    receipt_id: b.voucher_id,
    number: `${b.series}/${b.number}`,
    date: b.voucher_date,
    party_id: '',
    party_name: '',
    amount: rupeesToPaise(b.amount),
    mode: 'CASH',
    reference: b.narration ?? '',
    status: 'POSTED',
    allocated_to: [],
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
  mode: 'CASH' | 'BANK';
  reference?: string;
  idempotencyKey: string;
}

interface BackendReceiptResponse {
  voucher_id: string;
  series: string;
  number: string;
  voucher_date: string;
  amount: string;
  party_id: string | null;
  mode: string | null;
  allocations: Array<{ sales_invoice_id: string; amount: string }>;
  unallocated: string;
  narration: string | null;
  created_at: string;
}

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
    allocated_to: data.allocations.map((a) => a.sales_invoice_id),
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
