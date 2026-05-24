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
