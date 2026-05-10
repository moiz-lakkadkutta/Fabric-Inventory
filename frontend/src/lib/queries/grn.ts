import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import {
  liveCreateGrn,
  liveGetGrn,
  liveListGrns,
  liveReceiveGrn,
  type BackendGrn,
  type BackendGrnCreateBody,
  type ListGrnsParams,
} from '@/lib/api/grn';
import { IS_LIVE } from '@/lib/api/mode';
import { liveGetPo, liveListPos, type BackendPo } from '@/lib/api/purchase-orders';
import { fakeFetch } from '@/lib/mock/api';

const KEY = ['grns'] as const;

// ──────────────────────────────────────────────────────────────────────
// Public hook shape — keep BackendGrn as the canonical type used by
// pages. The list/detail views render the BE response directly (no
// click-dummy projection lives in the codebase yet for GRN), and money
// is formatted at the boundary by the consumer.
// ──────────────────────────────────────────────────────────────────────

export interface GrnRow extends BackendGrn {
  /** Convenience: total quantity received across all lines (decimal-as-string from BE). */
  total_qty_received: BackendGrn['total_qty_received'];
}

async function liveListAll(params: ListGrnsParams = {}): Promise<GrnRow[]> {
  const data = await liveListGrns(params);
  return data.items;
}

export function useGrns(params: ListGrnsParams = {}) {
  return useQuery({
    queryKey: [...KEY, params],
    queryFn: () => (IS_LIVE ? liveListAll(params) : fakeFetch<GrnRow[]>(() => [])),
  });
}

export function useGrn(grnId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, grnId],
    enabled: grnId !== undefined,
    queryFn: () =>
      IS_LIVE ? liveGetGrn(grnId as string) : fakeFetch<BackendGrn | null>(() => null),
  });
}

export interface CreateGrnInput {
  body: BackendGrnCreateBody;
  idempotencyKey: string;
}

async function liveCreate(input: CreateGrnInput): Promise<BackendGrn> {
  return liveCreateGrn(input.body, input.idempotencyKey);
}

export function useCreateGrn() {
  const qc = useQueryClient();
  return useMutation<BackendGrn, ApiError | Error, CreateGrnInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveCreate(input)
        : Promise.reject(new Error('Mock branch: GRN create not implemented in click-dummy')),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.setQueryData([...KEY, created.grn_id], created);
    },
  });
}

export interface ReceiveGrnInput {
  grnId: string;
  idempotencyKey: string;
}

// ──────────────────────────────────────────────────────────────────────
// PO reader — needed by the "+ New GRN" form so the user can pick a
// confirmed PO. Lives here (rather than in a future `purchase.ts` live
// hook) because PO list + lifecycle FE wiring is the CUT-201 task; we
// only need the *read* slice for the GRN flow today. CUT-201 will land
// its own composing hook on top of `liveListPos` without conflict.
// ──────────────────────────────────────────────────────────────────────

const PO_KEY = ['live-purchase-orders'] as const;

/** PO statuses the GRN flow accepts as a source. */
const GRN_SOURCE_STATUSES = new Set(['CONFIRMED', 'APPROVED', 'PARTIAL_GRN']);

export function useConfirmedPosForGrnForm() {
  return useQuery({
    queryKey: [...PO_KEY, 'confirmed'],
    queryFn: async (): Promise<BackendPo[]> => {
      if (!IS_LIVE) return [];
      const data = await liveListPos({ limit: 200 });
      return data.items.filter((po) => GRN_SOURCE_STATUSES.has(po.status));
    },
  });
}

export function useLivePo(poId: string | undefined) {
  return useQuery({
    queryKey: [...PO_KEY, poId],
    enabled: poId !== undefined,
    queryFn: () => (IS_LIVE ? liveGetPo(poId as string) : Promise.resolve<BackendPo | null>(null)),
  });
}

export function useReceiveGrn() {
  const qc = useQueryClient();
  return useMutation<BackendGrn, ApiError | Error, ReceiveGrnInput>({
    mutationFn: (input) =>
      IS_LIVE
        ? liveReceiveGrn(input.grnId, input.idempotencyKey)
        : Promise.reject(new Error('Mock branch: GRN receive not implemented in click-dummy')),
    onSuccess: (next) => {
      qc.setQueryData([...KEY, next.grn_id], next);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}
