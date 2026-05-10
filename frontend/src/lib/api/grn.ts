/*
 * Live-mode HTTP wrappers for GRN endpoints (TASK-CUT-202).
 *
 * Mirrors the BE OpenAPI contract for `/grns` (see
 * `backend/app/routers/procurement.py` and the codegen output at
 * `frontend/src/types/api.ts`). Thin, single-purpose wrappers so the
 * React-Query hooks in `lib/queries/grn.ts` can compose them and shape
 * the response into a click-dummy-friendly type at exactly one boundary.
 */

import { api } from '@/lib/api/client';
import type { components } from '@/types/api';

export type BackendGrn = components['schemas']['GRNResponse'];
export type BackendGrnLine = components['schemas']['GRNLineResponse'];
export type BackendGrnListResponse = components['schemas']['GRNListResponse'];
export type BackendGrnCreateBody = components['schemas']['GRNCreateRequest'];
export type BackendGrnLineCreateBody = components['schemas']['GRNLineRequest'];
export type BackendGrnStatus = components['schemas']['GRNStatus'];

export interface ListGrnsParams {
  firm_id?: string;
  purchase_order_id?: string;
  status?: BackendGrnStatus;
  limit?: number;
  offset?: number;
}

function buildQuery(params: ListGrnsParams): string {
  const usp = new URLSearchParams();
  if (params.firm_id) usp.set('firm_id', params.firm_id);
  if (params.purchase_order_id) usp.set('purchase_order_id', params.purchase_order_id);
  if (params.status) usp.set('status', params.status);
  usp.set('limit', String(params.limit ?? 200));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  return usp.toString();
}

export async function liveListGrns(params: ListGrnsParams = {}): Promise<BackendGrnListResponse> {
  const qs = buildQuery(params);
  return api<BackendGrnListResponse>(`/grns?${qs}`);
}

export async function liveGetGrn(grnId: string): Promise<BackendGrn> {
  return api<BackendGrn>(`/grns/${grnId}`);
}

export async function liveCreateGrn(
  body: BackendGrnCreateBody,
  idempotencyKey: string,
): Promise<BackendGrn> {
  return api<BackendGrn>('/grns', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

export async function liveReceiveGrn(grnId: string, idempotencyKey: string): Promise<BackendGrn> {
  return api<BackendGrn>(`/grns/${grnId}/receive`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
}

export async function liveDeleteGrn(grnId: string, idempotencyKey: string): Promise<void> {
  await api<void>(`/grns/${grnId}`, {
    method: 'DELETE',
    idempotencyKey,
  });
}
