/*
 * Live-mode HTTP wrappers for Purchase Invoice endpoints (TASK-CUT-202).
 *
 * Mirrors the BE OpenAPI contract for `/purchase-invoices` (see
 * `backend/app/routers/procurement.py`). Single-purpose, JSON-in /
 * JSON-out wrappers consumed by `lib/queries/purchase-invoices.ts`.
 */

import { api } from '@/lib/api/client';
import type { components } from '@/types/api';

export type BackendPi = components['schemas']['PIResponse'];
export type BackendPiLine = components['schemas']['PILineResponse'];
export type BackendPiListResponse = components['schemas']['PIListResponse'];
export type BackendPiCreateBody = components['schemas']['PICreateRequest'];
export type BackendPiLineCreateBody = components['schemas']['PILineRequest'];
export type BackendVoucherStatus = components['schemas']['VoucherStatus-Input'];

export interface ListPisParams {
  firm_id?: string;
  party_id?: string;
  grn_id?: string;
  status?: BackendVoucherStatus;
  limit?: number;
  offset?: number;
}

function buildQuery(params: ListPisParams): string {
  const usp = new URLSearchParams();
  if (params.firm_id) usp.set('firm_id', params.firm_id);
  if (params.party_id) usp.set('party_id', params.party_id);
  if (params.grn_id) usp.set('grn_id', params.grn_id);
  if (params.status) usp.set('status', params.status);
  usp.set('limit', String(params.limit ?? 200));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  return usp.toString();
}

export async function liveListPis(params: ListPisParams = {}): Promise<BackendPiListResponse> {
  const qs = buildQuery(params);
  return api<BackendPiListResponse>(`/purchase-invoices?${qs}`);
}

export async function liveGetPi(piId: string): Promise<BackendPi> {
  return api<BackendPi>(`/purchase-invoices/${piId}`);
}

export async function liveCreatePi(
  body: BackendPiCreateBody,
  idempotencyKey: string,
): Promise<BackendPi> {
  return api<BackendPi>('/purchase-invoices', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

export async function livePostPi(piId: string, idempotencyKey: string): Promise<BackendPi> {
  return api<BackendPi>(`/purchase-invoices/${piId}/post`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
}

export async function liveVoidPi(piId: string, idempotencyKey: string): Promise<BackendPi> {
  return api<BackendPi>(`/purchase-invoices/${piId}/void`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
}
