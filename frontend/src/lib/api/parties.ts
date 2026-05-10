/*
 * Live-mode HTTP wrappers for parties (TASK-CUT-101).
 *
 * Each function is a single-purpose, JSON-in / JSON-out call that mirrors
 * the backend OpenAPI contract for `/parties`. They have no React or
 * caching concerns — that lives in `lib/queries/parties.ts`. Keeping
 * them thin lets the queries layer compose them and shape the response
 * into the click-dummy `Party` type at exactly one boundary.
 *
 * If TASK-CUT-106 (OpenAPI codegen) lands first, swap these
 * hand-written interfaces for the generated `components['schemas']`
 * types. Until then we mirror the live `/openapi.json` shape directly
 * (matches `backend/app/schemas/masters.py`).
 */

import { api } from '@/lib/api/client';

export interface BackendParty {
  party_id: string;
  org_id: string;
  firm_id: string | null;
  code: string;
  name: string;
  legal_name: string | null;
  is_supplier: boolean | null;
  is_customer: boolean | null;
  is_karigar: boolean | null;
  is_transporter: boolean | null;
  tax_status: string;
  gstin: string | null;
  pan: string | null;
  phone: string | null;
  email: string | null;
  state_code: string | null;
  contact_person: string | null;
  credit_limit: string | number | null;
  notes: string | null;
  is_active: boolean | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface BackendPartyListResponse {
  items: BackendParty[];
  limit: number;
  offset: number;
  count: number;
}

export interface BackendPartyCreateBody {
  code: string;
  name: string;
  firm_id?: string | null;
  legal_name?: string | null;
  is_supplier?: boolean;
  is_customer?: boolean;
  is_karigar?: boolean;
  is_transporter?: boolean;
  tax_status?: string;
  gstin?: string | null;
  pan?: string | null;
  phone?: string | null;
  email?: string | null;
  state_code?: string | null;
}

export interface BackendPartyPatchBody {
  name?: string;
  legal_name?: string | null;
  is_supplier?: boolean;
  is_customer?: boolean;
  is_karigar?: boolean;
  is_transporter?: boolean;
  tax_status?: string;
  gstin?: string | null;
  pan?: string | null;
  phone?: string | null;
  email?: string | null;
  state_code?: string | null;
  is_active?: boolean;
}

export interface ListPartiesParams {
  /** Filter by tenancy on the BE (RLS still applies regardless). */
  firm_id?: string;
  /** Backend uses 'supplier'|'customer'|'karigar'|'transporter' (lowercase). */
  party_type?: 'customer' | 'supplier' | 'karigar' | 'transporter';
  is_active?: boolean;
  search?: string;
  limit?: number;
  offset?: number;
}

function buildQuery(params: ListPartiesParams): string {
  const usp = new URLSearchParams();
  if (params.firm_id) usp.set('firm_id', params.firm_id);
  if (params.party_type) usp.set('party_type', params.party_type);
  if (params.is_active !== undefined) usp.set('is_active', String(params.is_active));
  if (params.search) usp.set('search', params.search);
  usp.set('limit', String(params.limit ?? 200));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  return usp.toString();
}

export async function liveListParties(
  params: ListPartiesParams = {},
): Promise<BackendPartyListResponse> {
  const qs = buildQuery(params);
  return api<BackendPartyListResponse>(`/parties?${qs}`);
}

export async function liveGetParty(partyId: string): Promise<BackendParty> {
  return api<BackendParty>(`/parties/${partyId}`);
}

export async function liveCreateParty(
  body: BackendPartyCreateBody,
  idempotencyKey: string,
): Promise<BackendParty> {
  return api<BackendParty>('/parties', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

export async function livePatchParty(
  partyId: string,
  body: BackendPartyPatchBody,
  idempotencyKey: string,
): Promise<BackendParty> {
  return api<BackendParty>(`/parties/${partyId}`, {
    method: 'PATCH',
    idempotencyKey,
    body,
  });
}

export async function liveDeleteParty(partyId: string, idempotencyKey: string): Promise<void> {
  await api<void>(`/parties/${partyId}`, {
    method: 'DELETE',
    idempotencyKey,
  });
}
