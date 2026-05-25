/*
 * Live-mode HTTP wrappers for manufacturing masters (TASK-TR-E1-COSTCENTRES).
 *
 * Each function is a single-purpose, JSON-in / JSON-out call that mirrors
 * the backend OpenAPI contract. They have no React or caching concerns
 * — that lives in `lib/queries/manufacturing.ts`. Keeping them thin lets
 * the queries layer compose them at exactly one boundary.
 *
 * v1 (E1) ships cost-centre list + create wrappers. PATCH / DELETE land
 * with the row-edit follow-up; the BE endpoints already exist.
 */

import { api } from '@/lib/api/client';
import type { components } from '@/types/api';

export type BackendCostCentre = components['schemas']['CostCentreResponse'];
export type BackendCostCentreListResponse = components['schemas']['CostCentreListResponse'];
export type BackendCostCentreCreateBody = components['schemas']['CostCentreCreateRequest'];

export interface ListCostCentresParams {
  /** Filter by tenancy on the BE (RLS still applies regardless). */
  firm_id?: string;
  /**
   * Spec wording is "include_inactive" but the BE param is the tri-state
   * `is_active`: omit to get all rows, `true` for active only, `false`
   * for inactive only. The queries-layer adapter translates the FE-side
   * "include inactive" toggle into this shape.
   */
  is_active?: boolean | null;
  /** Free-text search against code + name. */
  search?: string;
  limit?: number;
  offset?: number;
}

function buildQuery(params: ListCostCentresParams): string {
  const usp = new URLSearchParams();
  if (params.firm_id) usp.set('firm_id', params.firm_id);
  if (params.is_active === true) usp.set('is_active', 'true');
  if (params.is_active === false) usp.set('is_active', 'false');
  if (params.search) usp.set('search', params.search);
  usp.set('limit', String(params.limit ?? 200));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  return usp.toString();
}

export async function listCostCentres(
  params: ListCostCentresParams = {},
): Promise<BackendCostCentreListResponse> {
  const qs = buildQuery(params);
  return api<BackendCostCentreListResponse>(`/cost-centres?${qs}`);
}

export async function createCostCentre(
  body: BackendCostCentreCreateBody,
  idempotencyKey: string,
): Promise<BackendCostCentre> {
  return api<BackendCostCentre>('/cost-centres', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

/* ─────────────────────────────────────────────────────────────
 * BOMs (E1-BOMS, PR #169)
 *
 * The live-mode helpers `liveListBoms` + `liveGetBom` are already
 * inline-defined in `lib/queries/manufacturing.ts` and stay there.
 * This file is the canonical home for the mutation wrappers.
 * ───────────────────────────────────────────────────────────── */

export type BackendBomCreateRequest = components['schemas']['BomCreateRequest'];
export type BackendBomLineInput = components['schemas']['BomLineInput'];
export type BackendBomResponse = components['schemas']['BomResponse'];

/**
 * POST /boms. Server auto-bumps `version_number` per (firm,
 * finished_item) partition and promotes the new row to active in the
 * same transaction. The wire body does NOT carry `scrap_pct` (the BE
 * has no column for it); the wizard computes scrap allowance for the
 * cost-rollup UI only.
 */
export async function createBom(
  body: BackendBomCreateRequest,
  idempotencyKey: string,
): Promise<BackendBomResponse> {
  return api<BackendBomResponse>('/boms', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

/**
 * POST /boms/{id}/activate. Demotes every other version in the same
 * (firm, finished_item) partition and flips this BOM's `is_active=true`.
 */
export async function activateBom(
  bomId: string,
  idempotencyKey: string,
): Promise<BackendBomResponse> {
  return api<BackendBomResponse>(`/boms/${bomId}/activate`, {
    method: 'POST',
    idempotencyKey,
    body: {},
  });
}

/* ─────────────────────────────────────────────────────────────
 * Operation masters (E1-OPERATIONS, PR #166)
 * ───────────────────────────────────────────────────────────── */

export type BackendOperationMaster = components['schemas']['OperationMasterResponse'];
export type BackendOperationMasterList = components['schemas']['OperationMasterListResponse'];
export type BackendOperationMasterCreateBody =
  components['schemas']['OperationMasterCreateRequest'];
export type BackendOperationMasterPatchBody = components['schemas']['OperationMasterUpdateRequest'];
export type BackendOperationType = components['schemas']['OperationType'];

export interface ListOperationMastersQuery {
  firm_id?: string;
  operation_type?: BackendOperationType;
  is_active?: boolean;
  search?: string;
  limit?: number;
  offset?: number;
}

function buildOperationMasterQuery(params: ListOperationMastersQuery): string {
  const usp = new URLSearchParams();
  if (params.firm_id) usp.set('firm_id', params.firm_id);
  if (params.operation_type) usp.set('operation_type', params.operation_type);
  if (params.is_active !== undefined) usp.set('is_active', String(params.is_active));
  if (params.search) usp.set('search', params.search);
  usp.set('limit', String(params.limit ?? 200));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  return usp.toString();
}

export async function liveListOperationMasters(
  params: ListOperationMastersQuery = {},
): Promise<BackendOperationMasterList> {
  const qs = buildOperationMasterQuery(params);
  return api<BackendOperationMasterList>(`/operation-masters?${qs}`);
}

export async function liveCreateOperationMaster(
  body: BackendOperationMasterCreateBody,
  idempotencyKey: string,
): Promise<BackendOperationMaster> {
  return api<BackendOperationMaster>('/operation-masters', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

export async function livePatchOperationMaster(
  operationMasterId: string,
  body: BackendOperationMasterPatchBody,
  idempotencyKey: string,
): Promise<BackendOperationMaster> {
  return api<BackendOperationMaster>(`/operation-masters/${operationMasterId}`, {
    method: 'PATCH',
    idempotencyKey,
    body,
  });
}

export async function liveDeleteOperationMaster(
  operationMasterId: string,
  idempotencyKey: string,
): Promise<void> {
  await api<void>(`/operation-masters/${operationMasterId}`, {
    method: 'DELETE',
    idempotencyKey,
  });
}
