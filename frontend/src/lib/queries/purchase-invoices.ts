import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import {
  liveCreatePi,
  liveGetPi,
  liveListPis,
  livePostPi,
  liveVoidPi,
  type BackendPi,
  type BackendPiCreateBody,
  type ListPisParams,
} from '@/lib/api/purchase-invoices';
import { fakeFetch } from '@/lib/mock/api';

const KEY = ['purchase-invoices'] as const;

async function liveListAll(params: ListPisParams = {}): Promise<BackendPi[]> {
  const data = await liveListPis(params);
  return data.items;
}

export function usePurchaseInvoices(params: ListPisParams = {}) {
  return useQuery({
    queryKey: [...KEY, params],
    queryFn: () => (IS_LIVE ? liveListAll(params) : fakeFetch<BackendPi[]>(() => [])),
  });
}

export function usePurchaseInvoice(piId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, piId],
    enabled: piId !== undefined,
    queryFn: () => (IS_LIVE ? liveGetPi(piId as string) : fakeFetch<BackendPi | null>(() => null)),
  });
}

export interface CreatePiInput {
  body: BackendPiCreateBody;
  idempotencyKey: string;
}

export function useCreatePurchaseInvoice() {
  const qc = useQueryClient();
  return useMutation<BackendPi, ApiError | Error, CreatePiInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveCreatePi(input.body, input.idempotencyKey)
        : Promise.reject(new Error('Mock branch: PI create not implemented in click-dummy')),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.setQueryData([...KEY, created.purchase_invoice_id], created);
    },
  });
}

export interface PostPiInput {
  piId: string;
  idempotencyKey: string;
}

export function usePostPurchaseInvoice() {
  const qc = useQueryClient();
  return useMutation<BackendPi, ApiError | Error, PostPiInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? livePostPi(input.piId, input.idempotencyKey)
        : Promise.reject(new Error('Mock branch: PI post not implemented in click-dummy')),
    onSuccess: (next) => {
      qc.setQueryData([...KEY, next.purchase_invoice_id], next);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}

export interface VoidPiInput {
  piId: string;
  idempotencyKey: string;
}

export function useVoidPurchaseInvoice() {
  const qc = useQueryClient();
  return useMutation<BackendPi, ApiError | Error, VoidPiInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveVoidPi(input.piId, input.idempotencyKey)
        : Promise.reject(new Error('Mock branch: PI void not implemented in click-dummy')),
    onSuccess: (next) => {
      qc.setQueryData([...KEY, next.purchase_invoice_id], next);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}
