/*
 * Live-mode HTTP wrappers for Purchase Order endpoints (TASK-CUT-202).
 *
 * Read-only here. The PO list / create / lifecycle FE wiring is the
 * CUT-201 task; we ship the read API only so the GRN form (CUT-202)
 * can pick a confirmed PO. CUT-201 will land its own wrappers and
 * extend what's here without conflict.
 */

import { api } from '@/lib/api/client';
import type { components } from '@/types/api';

export type BackendPo = components['schemas']['POResponse'];
export type BackendPoLine = components['schemas']['POLineResponse'];
export type BackendPoListResponse = components['schemas']['POListResponse'];
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
