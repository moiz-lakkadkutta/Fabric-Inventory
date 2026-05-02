import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import { invoices as seedInvoices } from '@/lib/mock/invoices';
import type { Invoice } from '@/lib/mock/types';

const KEY = ['invoices'] as const;

// Mutable singleton — the click-dummy's "database". Seeded from the
// invoices module on first read; subsequent mutations replace this
// array via setQueryData so re-reads see the new state.
let store: Invoice[] | null = null;

function ensureStore() {
  if (store === null) store = [...seedInvoices];
  return store;
}

export function resetInvoiceStore() {
  store = null;
}

export function useInvoices() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => fakeFetch(() => [...ensureStore()]),
  });
}

export function useInvoice(invoiceId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, invoiceId],
    enabled: invoiceId !== undefined,
    queryFn: () => fakeFetch(() => ensureStore().find((i) => i.invoice_id === invoiceId) ?? null),
  });
}

export function useFinalizeInvoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (invoiceId: string) =>
      fakeFetch(() => {
        const list = ensureStore();
        const idx = list.findIndex((i) => i.invoice_id === invoiceId);
        if (idx === -1) throw new Error(`Invoice ${invoiceId} not found`);
        const next: Invoice = { ...list[idx], status: 'FINALIZED' };
        store = [...list.slice(0, idx), next, ...list.slice(idx + 1)];
        return next;
      }),
    onSuccess: (next) => {
      qc.setQueryData<Invoice[]>(
        KEY,
        (prev) => prev?.map((i) => (i.invoice_id === next.invoice_id ? next : i)) ?? prev,
      );
      qc.setQueryData([...KEY, next.invoice_id], next);
    },
  });
}

export function useCreateDraftInvoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draft: Omit<Invoice, 'invoice_id' | 'number' | 'status'>) =>
      fakeFetch(() => {
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
      }),
    onSuccess: (created) => {
      qc.setQueryData<Invoice[]>(KEY, (prev) => (prev ? [created, ...prev] : [created]));
      qc.setQueryData([...KEY, created.invoice_id], created);
    },
  });
}
