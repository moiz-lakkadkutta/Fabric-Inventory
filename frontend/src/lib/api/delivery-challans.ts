/*
 * Live-mode HTTP wrappers for Delivery Challans (TASK-CUT-203).
 *
 * Thin JSON-in / JSON-out calls that mirror /delivery-challans. Wire
 * shapes come from `@/types/api` (CUT-106 codegen).
 */

import { api } from '@/lib/api/client';
import type { components } from '@/types/api';

export type BackendDC = components['schemas']['DCResponse'];
export type BackendDCLine = components['schemas']['DCLineResponse'];
export type BackendDCListResponse = components['schemas']['DCListResponse'];
export type BackendDCCreateBody = components['schemas']['DCCreateRequest'];
export type BackendDCLineRequest = components['schemas']['DCLineRequest'];
export type BackendDCStatus = components['schemas']['DCStatus'];

export interface ListDCsParams {
  firm_id?: string;
  sales_order_id?: string;
  status?: BackendDCStatus;
  limit?: number;
  offset?: number;
}

function buildQuery(params: ListDCsParams): string {
  const usp = new URLSearchParams();
  if (params.firm_id) usp.set('firm_id', params.firm_id);
  if (params.sales_order_id) usp.set('sales_order_id', params.sales_order_id);
  if (params.status) usp.set('status', params.status);
  usp.set('limit', String(params.limit ?? 200));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  return usp.toString();
}

export async function liveListDCs(params: ListDCsParams = {}): Promise<BackendDCListResponse> {
  const qs = buildQuery(params);
  return api<BackendDCListResponse>(`/delivery-challans?${qs}`);
}

export async function liveGetDC(dcId: string): Promise<BackendDC> {
  return api<BackendDC>(`/delivery-challans/${dcId}`);
}

export async function liveCreateDC(
  body: BackendDCCreateBody,
  idempotencyKey: string,
): Promise<BackendDC> {
  return api<BackendDC>('/delivery-challans', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

export async function liveIssueDC(dcId: string, idempotencyKey: string): Promise<BackendDC> {
  return api<BackendDC>(`/delivery-challans/${dcId}/issue`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
}
