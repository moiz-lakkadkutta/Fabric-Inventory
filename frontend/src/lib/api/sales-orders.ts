/*
 * Live-mode HTTP wrappers for Sales Orders (TASK-CUT-203).
 *
 * Thin JSON-in / JSON-out calls that mirror /sales-orders. Keeping them
 * here (rather than in queries/) lets future callers — DC create from a
 * confirmed SO, the InvoiceCreate "from SO" path, etc. — import the
 * shapes without depending on the React-Query hook.
 *
 * Wire shapes come from `@/types/api` (CUT-106 codegen). The aliases
 * below name them for convenience and document the SO subset of the
 * generated schema.
 */

import { api } from '@/lib/api/client';
import type { components } from '@/types/api';

export type BackendSO = components['schemas']['SOResponse'];
export type BackendSOLine = components['schemas']['SOLineResponse'];
export type BackendSOListResponse = components['schemas']['SOListResponse'];
export type BackendSOCreateBody = components['schemas']['SOCreateRequest'];
export type BackendSOLineRequest = components['schemas']['SOLineRequest'];
export type BackendSalesOrderStatus = components['schemas']['SalesOrderStatus'];

export interface ListSOsParams {
  firm_id?: string;
  party_id?: string;
  status?: BackendSalesOrderStatus;
  limit?: number;
  offset?: number;
}

function buildQuery(params: ListSOsParams): string {
  const usp = new URLSearchParams();
  if (params.firm_id) usp.set('firm_id', params.firm_id);
  if (params.party_id) usp.set('party_id', params.party_id);
  if (params.status) usp.set('status', params.status);
  usp.set('limit', String(params.limit ?? 200));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  return usp.toString();
}

export async function liveListSOs(params: ListSOsParams = {}): Promise<BackendSOListResponse> {
  const qs = buildQuery(params);
  return api<BackendSOListResponse>(`/sales-orders?${qs}`);
}

export async function liveGetSO(soId: string): Promise<BackendSO> {
  return api<BackendSO>(`/sales-orders/${soId}`);
}

export async function liveCreateSO(
  body: BackendSOCreateBody,
  idempotencyKey: string,
): Promise<BackendSO> {
  return api<BackendSO>('/sales-orders', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

export async function liveConfirmSO(soId: string, idempotencyKey: string): Promise<BackendSO> {
  return api<BackendSO>(`/sales-orders/${soId}/confirm`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
}

export async function liveCancelSO(soId: string, idempotencyKey: string): Promise<BackendSO> {
  return api<BackendSO>(`/sales-orders/${soId}/cancel`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
}
