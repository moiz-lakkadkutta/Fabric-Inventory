/*
 * Live-mode HTTP wrappers for Purchase Order endpoints.
 *
 * - Read wrappers (list / get) added in TASK-CUT-202 (so the GRN form
 *   could pick a confirmed PO).
 * - Create + lifecycle (approve/confirm/cancel) wrappers added in
 *   TASK-CUT-201 (Purchase Order FE wired live).
 *
 * Pure JSON-in/JSON-out; no React or caching here. The query module
 * `lib/queries/purchase-orders.ts` composes these into hooks and maps
 * BE shapes → click-dummy `PurchaseOrder` shape.
 */

import { api } from '@/lib/api/client';
import type { components } from '@/types/api';

export type BackendPo = components['schemas']['POResponse'];
export type BackendPoLine = components['schemas']['POLineResponse'];
export type BackendPoListResponse = components['schemas']['POListResponse'];
export type BackendPoCreateRequest = components['schemas']['POCreateRequest'];
export type BackendPurchaseOrderStatus = components['schemas']['PurchaseOrderStatus'];

export interface ListPosParams {
  firm_id?: string;
  party_id?: string;
  status?: BackendPurchaseOrderStatus;
  limit?: number;
  offset?: number;
}

function buildQuery(params: ListPosParams): string {
  const usp = new URLSearchParams();
  if (params.firm_id) usp.set('firm_id', params.firm_id);
  if (params.party_id) usp.set('party_id', params.party_id);
  if (params.status) usp.set('status', params.status);
  usp.set('limit', String(params.limit ?? 200));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  return usp.toString();
}

export async function liveListPos(params: ListPosParams = {}): Promise<BackendPoListResponse> {
  const qs = buildQuery(params);
  return api<BackendPoListResponse>(`/purchase-orders?${qs}`);
}

export async function liveGetPo(poId: string): Promise<BackendPo> {
  return api<BackendPo>(`/purchase-orders/${poId}`);
}

export async function liveCreatePo(
  body: BackendPoCreateRequest,
  idempotencyKey: string,
): Promise<BackendPo> {
  return api<BackendPo>('/purchase-orders', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

export type PoLifecycleAction = 'approve' | 'confirm' | 'cancel';

export async function liveLifecyclePo(
  action: PoLifecycleAction,
  poId: string,
  idempotencyKey: string,
): Promise<BackendPo> {
  return api<BackendPo>(`/purchase-orders/${poId}/${action}`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
}
