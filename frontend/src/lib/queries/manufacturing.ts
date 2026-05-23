/*
 * manufacturing.ts — Manufacturing view-model wiring (TASK-TR-A12 v1).
 *
 * Live-mode hooks call the A01–A08 backend endpoints; mock-mode keeps
 * the click-dummy fixture so demos still render. Same dual pattern as
 * `inventory.ts` (TASK-TR-B02) — pick a branch via `IS_LIVE` and let
 * Vite tree-shake the dead one.
 *
 * Scope shipped in this PR (v1):
 *   - `useManufacturingOrders()` — wraps `useMos()` + maps to the legacy
 *     `ManufacturingOrder` Kanban shape used by `ManufacturingPipeline`.
 *   - `useMos()` / `useMo(id)` — live `GET /manufacturing/mo` +
 *     `GET /manufacturing/mo/{id}`.
 *   - `useDesigns()` / `useDesign(id)` — live `GET /designs` +
 *     `GET /designs/{id}` (A02).
 *   - `useBoms()` / `useBom(id)` — live `GET /boms` + `GET /boms/{id}`
 *     (A03).
 *   - `useRoutings()` / `useRouting(id)` — live `GET /routings` +
 *     `GET /routings/{id}` (A04).
 *
 * Deferred to follow-up tasks (each is meaningfully more UI work):
 *   - Create-MO dialog / flow.
 *   - BOM editor.
 *   - Routing-graph editor.
 *   - Operation-progress UI (start / qty_in / qty_out / complete).
 *   - Material-issue UI.
 *   - Karigar dispatch / receive-back UI.
 *   - QC UI (waits on A10).
 *
 * Shape-mismatch adaptations (the queries layer absorbs these so
 * consumer pages don't have to):
 *   - The Kanban groups by an MO `stage` (PLANNED / CUTTING / EMBROIDERY
 *     / STITCHING / QC / PACKED), but the BE only exposes a header-level
 *     `MoStatus` (DRAFT / RELEASED / IN_PROGRESS / COMPLETED / CLOSED).
 *     Per-operation granularity needs the operations array (only on the
 *     detail endpoint) and a coherent routing — neither is reliable for
 *     a list view today. We collapse `MoStatus` → `MoStage` so the Kanban
 *     renders sensibly; finer stage placement is a follow-up.
 *   - `MoListItem` carries no product / customer / due-date / UoM. We
 *     surface what we have (`finished_item_id` / `mo_date` / a placeholder
 *     product label) and leave the visual fields for the follow-up that
 *     joins MO ↔ item / party / sales-order.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import {
  KANBAN_COLUMNS,
  manufacturingOrders,
  type ManufacturingOrder,
  type MoStage,
} from '@/lib/mock/manufacturing';
import { authStore } from '@/store/auth';
import type { components } from '@/types/api';

export { KANBAN_COLUMNS };
export type { ManufacturingOrder, MoStage };

// ── BE types (sourced from the OpenAPI snapshot) ──────────────────────

export type BackendMoListItem = components['schemas']['MoListItem'];
export type BackendMoListResponse = components['schemas']['MoListResponse'];
export type BackendMoResponse = components['schemas']['MoResponse'];
export type BackendMoStatus = components['schemas']['MoStatus'];

export type BackendDesignResponse = components['schemas']['DesignResponse'];
export type BackendDesignListResponse = components['schemas']['DesignListResponse'];

export type BackendBomResponse = components['schemas']['BomResponse'];
export type BackendBomListResponse = components['schemas']['BomListResponse'];

export type BackendRoutingResponse = components['schemas']['RoutingResponse'];
export type BackendRoutingListResponse = components['schemas']['RoutingListResponse'];

export type BackendMoCompletionPreviewResponse =
  components['schemas']['MoCompletionPreviewResponse'];
export type BackendMoCompleteRequest = components['schemas']['MoCompleteRequest'];

export type BackendOperationMasterResponse = components['schemas']['OperationMasterResponse'];
export type BackendOperationMasterListResponse =
  components['schemas']['OperationMasterListResponse'];

// A3 operations drawer — request + response shapes for the start /
// issue-materials / per-operation progress endpoints. Imported by the
// drawer + Issue Materials dialog below.
export type BackendMoTransitionRequest = components['schemas']['MoTransitionRequest'];
export type BackendMaterialIssueCreateRequest = components['schemas']['MaterialIssueCreateRequest'];
export type BackendMaterialIssueLineInput = components['schemas']['MaterialIssueLineInput'];
export type BackendMaterialIssueResponse = components['schemas']['MaterialIssueResponse'];
export type BackendOperationStartRequest = components['schemas']['OperationStartRequest'];
export type BackendOperationQtyInRequest = components['schemas']['OperationQtyInRequest'];
export type BackendOperationQtyOutRequest = components['schemas']['OperationQtyOutRequest'];
export type BackendOperationCompleteRequest = components['schemas']['OperationCompleteRequest'];
export type BackendOperationProgressResponse = components['schemas']['OperationProgressResponse'];
export type BackendMoOperationState = components['schemas']['MoOperationState'];
export type BackendOperationType = components['schemas']['OperationType'];

// A2 MO Create Wizard — request shape for POST /manufacturing/mo.
export type BackendMoCreateRequest = components['schemas']['MoCreateRequest'];

// ── MO list ↔ Kanban view-model mapper ────────────────────────────────

/**
 * Collapse the header-level `MoStatus` to a Kanban `MoStage`. The BE
 * doesn't track an explicit current-stage on the MO header (the per-
 * operation lifecycle lives on `mo_operation.state`), so this is a
 * coarse mapping for the list view. The MO-detail screen — once it
 * lands as a follow-up — should drive stage placement off the live
 * operations array, not this fallback.
 */
export function moStatusToStage(status: BackendMoStatus): MoStage {
  switch (status) {
    case 'DRAFT':
    case 'RELEASED':
      return 'PLANNED';
    case 'IN_PROGRESS':
      // Without operations + routing, we can't know which middle stage
      // an in-progress MO sits in. Park it at STITCHING — the most common
      // bottleneck in the trial customer's flow. Follow-up will compute
      // this from `mo.operations[]` once the detail-view UI lands.
      return 'STITCHING';
    case 'COMPLETED':
    case 'CLOSED':
      return 'PACKED';
    default:
      return 'PLANNED';
  }
}

/**
 * Map a BE MO list-item into the legacy `ManufacturingOrder` shape the
 * Kanban consumes. Fields we can't derive yet (product / customer /
 * UoM / due-date / progress / SLA timers) get sensible placeholders so
 * the Kanban still renders cleanly. A future task that joins MO with
 * the finished-item master + sales-order link can fill these in.
 */
export function mapMoListItemToKanban(b: BackendMoListItem): ManufacturingOrder {
  return {
    mo_id: b.manufacturing_order_id,
    number: b.series ? `${b.series}/${b.number}` : b.number,
    // Product name needs a join through finished_item_id → item.name; not
    // available in the list shape. Surface the MO number as a friendly
    // placeholder so the card isn't blank.
    product: `MO ${b.number}`,
    qty: parseFloat(b.planned_qty || '0'),
    // No UoM on the list shape; default to PIECE — the only other supported
    // Kanban UoM is METER and the list page tolerates either.
    uom: 'PIECE',
    // No customer link on the MO header today; left blank rather than
    // faking a value. The card just renders an empty customer slot.
    customer: '',
    // No planned_end_date on the list shape; surface mo_date so something
    // useful shows ("Due 2026-05-14").
    due_date: b.mo_date,
    stage: moStatusToStage(b.status),
    // No progress / SLA derivation in this PR — needs operations and
    // routing standards. Render flat 0 for IN_PROGRESS, 100 for COMPLETED.
    progress_pct: b.status === 'COMPLETED' || b.status === 'CLOSED' ? 100 : 0,
    days_in_stage: 0,
    std_days_in_stage: 0,
  };
}

// ── Live wrappers ─────────────────────────────────────────────────────

export interface ListMosParams {
  firm_id?: string;
  status?: BackendMoStatus;
  design_id?: string;
  limit?: number;
  offset?: number;
}

function requireFirmId(explicit?: string): string {
  const firm_id = explicit ?? authStore.get().me?.firm_id;
  if (!firm_id) {
    throw new Error('No active firm in this session — switch to a firm first.');
  }
  return firm_id;
}

async function liveListMos(params: ListMosParams = {}): Promise<BackendMoListItem[]> {
  const usp = new URLSearchParams();
  // firm_id is the strongest filter — wire it whenever available so the
  // list scopes to the user's active firm. RLS already filters by org.
  const firm_id = authStore.get().me?.firm_id ?? params.firm_id;
  if (firm_id) usp.set('firm_id', firm_id);
  if (params.status) usp.set('status', params.status);
  if (params.design_id) usp.set('design_id', params.design_id);
  usp.set('limit', String(params.limit ?? 100));
  usp.set('offset', String(params.offset ?? 0));
  const qs = usp.toString();
  const data = await api<BackendMoListResponse>(`/manufacturing/mo${qs ? `?${qs}` : ''}`);
  return data.items;
}

async function liveGetMo(moId: string): Promise<BackendMoResponse> {
  return api<BackendMoResponse>(`/manufacturing/mo/${moId}`);
}

export interface ListDesignsParams {
  firm_id?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

async function liveListDesigns(params: ListDesignsParams = {}): Promise<BackendDesignResponse[]> {
  const firm_id = requireFirmId(params.firm_id);
  const usp = new URLSearchParams({ firm_id });
  if (params.search) usp.set('search', params.search);
  usp.set('limit', String(params.limit ?? 100));
  usp.set('offset', String(params.offset ?? 0));
  const data = await api<BackendDesignListResponse>(`/designs?${usp.toString()}`);
  return data.items;
}

async function liveGetDesign(designId: string): Promise<BackendDesignResponse> {
  return api<BackendDesignResponse>(`/designs/${designId}`);
}

export interface ListBomsParams {
  firm_id?: string;
  design_id?: string;
  finished_item_id?: string;
  active_only?: boolean;
  limit?: number;
  offset?: number;
}

async function liveListBoms(params: ListBomsParams = {}): Promise<BackendBomResponse[]> {
  const firm_id = requireFirmId(params.firm_id);
  const usp = new URLSearchParams({ firm_id });
  if (params.design_id) usp.set('design_id', params.design_id);
  if (params.finished_item_id) usp.set('finished_item_id', params.finished_item_id);
  if (params.active_only !== undefined) usp.set('active_only', String(params.active_only));
  usp.set('limit', String(params.limit ?? 100));
  usp.set('offset', String(params.offset ?? 0));
  const data = await api<BackendBomListResponse>(`/boms?${usp.toString()}`);
  return data.items;
}

async function liveGetBom(bomId: string): Promise<BackendBomResponse> {
  return api<BackendBomResponse>(`/boms/${bomId}`);
}

export interface ListRoutingsParams {
  firm_id?: string;
  design_id?: string;
  active_only?: boolean;
  limit?: number;
  offset?: number;
}

async function liveListRoutings(
  params: ListRoutingsParams = {},
): Promise<BackendRoutingResponse[]> {
  const firm_id = requireFirmId(params.firm_id);
  const usp = new URLSearchParams({ firm_id });
  if (params.design_id) usp.set('design_id', params.design_id);
  if (params.active_only !== undefined) usp.set('active_only', String(params.active_only));
  usp.set('limit', String(params.limit ?? 100));
  usp.set('offset', String(params.offset ?? 0));
  const data = await api<BackendRoutingListResponse>(`/routings?${usp.toString()}`);
  return data.items;
}

async function liveGetRouting(routingId: string): Promise<BackendRoutingResponse> {
  return api<BackendRoutingResponse>(`/routings/${routingId}`);
}

// ── MO completion preview / complete (A11 + A11-FU) ───────────────────

export interface CompletionPreviewParams {
  moId: string;
  firm_id?: string;
  producedQtyTarget: string | number;
}

async function liveGetMoCompletionPreview(
  params: CompletionPreviewParams,
): Promise<BackendMoCompletionPreviewResponse> {
  const firm_id = requireFirmId(params.firm_id);
  const usp = new URLSearchParams({
    firm_id,
    produced_qty_target: String(params.producedQtyTarget),
  });
  return api<BackendMoCompletionPreviewResponse>(
    `/manufacturing/mo/${params.moId}/completion-preview?${usp.toString()}`,
  );
}

export interface CompleteMoInput {
  moId: string;
  firm_id?: string;
  producedQty: string | number;
  narration?: string;
  idempotencyKey: string;
}

async function liveCompleteMo(input: CompleteMoInput): Promise<BackendMoResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendMoCompleteRequest = {
    firm_id,
    produced_qty: input.producedQty,
  };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendMoResponse>(`/manufacturing/mo/${input.moId}/complete`, {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

// ── Operation masters (lookup for the MO Detail Operations tab) ───────

export interface ListOperationMastersParams {
  firm_id?: string;
  is_active?: boolean;
  search?: string;
  limit?: number;
  offset?: number;
}

async function liveListOperationMasters(
  params: ListOperationMastersParams = {},
): Promise<BackendOperationMasterResponse[]> {
  const usp = new URLSearchParams();
  const firm_id = authStore.get().me?.firm_id ?? params.firm_id;
  if (firm_id) usp.set('firm_id', firm_id);
  if (params.is_active !== undefined) usp.set('is_active', String(params.is_active));
  if (params.search) usp.set('search', params.search);
  usp.set('limit', String(params.limit ?? 200));
  usp.set('offset', String(params.offset ?? 0));
  const data = await api<BackendOperationMasterListResponse>(
    `/operation-masters?${usp.toString()}`,
  );
  return data.items;
}

// ── Public hooks ──────────────────────────────────────────────────────

const MO_KEY = ['manufacturing', 'mos'] as const;
const DESIGN_KEY = ['manufacturing', 'designs'] as const;
const BOM_KEY = ['manufacturing', 'boms'] as const;
const ROUTING_KEY = ['manufacturing', 'routings'] as const;

/**
 * Legacy hook consumed by `ManufacturingPipeline`. Returns the Kanban
 * view-model. In live mode this maps the BE MO list; in mock mode it
 * returns the click-dummy fixture so demos still work.
 */
export function useManufacturingOrders(params: ListMosParams = {}) {
  return useQuery<ManufacturingOrder[]>({
    queryKey: [...MO_KEY, 'kanban', params],
    queryFn: async (): Promise<ManufacturingOrder[]> => {
      if (IS_LIVE) {
        const items = await liveListMos(params);
        return items.map(mapMoListItemToKanban);
      }
      return fakeFetch([...manufacturingOrders]);
    },
  });
}

/** Raw MO list — for the upcoming MO-list page follow-up. */
export function useMos(params: ListMosParams = {}) {
  return useQuery<BackendMoListItem[]>({
    queryKey: [...MO_KEY, 'list', params],
    queryFn: () => (IS_LIVE ? liveListMos(params) : fakeFetch([] as BackendMoListItem[])),
  });
}

export function useMo(moId: string | undefined) {
  return useQuery<BackendMoResponse | null>({
    queryKey: [...MO_KEY, 'detail', moId],
    enabled: moId !== undefined,
    queryFn: () =>
      IS_LIVE ? liveGetMo(moId as string) : fakeFetch<BackendMoResponse | null>(null),
  });
}

export function useDesigns(params: ListDesignsParams = {}) {
  return useQuery<BackendDesignResponse[]>({
    queryKey: [...DESIGN_KEY, 'list', params],
    queryFn: () => (IS_LIVE ? liveListDesigns(params) : fakeFetch([] as BackendDesignResponse[])),
  });
}

export function useDesign(designId: string | undefined) {
  return useQuery<BackendDesignResponse | null>({
    queryKey: [...DESIGN_KEY, 'detail', designId],
    enabled: designId !== undefined,
    queryFn: () =>
      IS_LIVE ? liveGetDesign(designId as string) : fakeFetch<BackendDesignResponse | null>(null),
  });
}

export function useBoms(params: ListBomsParams = {}) {
  return useQuery<BackendBomResponse[]>({
    queryKey: [...BOM_KEY, 'list', params],
    queryFn: () => (IS_LIVE ? liveListBoms(params) : fakeFetch([] as BackendBomResponse[])),
  });
}

export function useBom(bomId: string | undefined) {
  return useQuery<BackendBomResponse | null>({
    queryKey: [...BOM_KEY, 'detail', bomId],
    enabled: bomId !== undefined,
    queryFn: () =>
      IS_LIVE ? liveGetBom(bomId as string) : fakeFetch<BackendBomResponse | null>(null),
  });
}

export function useRoutings(params: ListRoutingsParams = {}) {
  return useQuery<BackendRoutingResponse[]>({
    queryKey: [...ROUTING_KEY, 'list', params],
    queryFn: () => (IS_LIVE ? liveListRoutings(params) : fakeFetch([] as BackendRoutingResponse[])),
  });
}

export function useRouting(routingId: string | undefined) {
  return useQuery<BackendRoutingResponse | null>({
    queryKey: [...ROUTING_KEY, 'detail', routingId],
    enabled: routingId !== undefined,
    queryFn: () =>
      IS_LIVE
        ? liveGetRouting(routingId as string)
        : fakeFetch<BackendRoutingResponse | null>(null),
  });
}

const OPERATION_MASTER_KEY = ['manufacturing', 'operation-masters'] as const;
const COMPLETION_PREVIEW_KEY = ['manufacturing', 'completion-preview'] as const;

/**
 * Read-only completion preview (A11-FU). Stays out of cache mutations —
 * the result is recomputed by the BE on each call against live cost
 * state, so we don't want to surface a stale snapshot if the operator
 * is mid-decision. `enabled` lets the dialog gate the fetch until the
 * input is valid.
 */
export function useMoCompletionPreview(params: {
  moId: string | undefined;
  producedQtyTarget: string | number;
  enabled?: boolean;
}) {
  const firm_id = authStore.get().me?.firm_id;
  return useQuery<BackendMoCompletionPreviewResponse>({
    queryKey: [...COMPLETION_PREVIEW_KEY, params.moId, firm_id, String(params.producedQtyTarget)],
    enabled:
      params.enabled !== false &&
      params.moId !== undefined &&
      params.producedQtyTarget !== '' &&
      Number.isFinite(Number(params.producedQtyTarget)) &&
      Number(params.producedQtyTarget) > 0,
    queryFn: () =>
      liveGetMoCompletionPreview({
        moId: params.moId as string,
        producedQtyTarget: params.producedQtyTarget,
      }),
    // Always go to the network — pre-flight checks (stock available,
    // operations CLOSED, etc.) can change between user actions.
    staleTime: 0,
    gcTime: 0,
  });
}

/**
 * POST /manufacturing/mo/{id}/complete (A11). Money-touching — drains
 * the WIP pool into finished-goods inventory and flips the MO to
 * COMPLETED. On success we invalidate the MO list and the specific
 * detail so the UI re-syncs from the BE.
 */
export function useCompleteMo() {
  const qc = useQueryClient();
  return useMutation<BackendMoResponse, Error, CompleteMoInput>({
    mutationFn: (input) => liveCompleteMo(input),
    onSuccess: (next) => {
      qc.invalidateQueries({ queryKey: MO_KEY });
      qc.setQueryData([...MO_KEY, 'detail', next.manufacturing_order_id], next);
    },
  });
}

/** Operation-master lookup — used by MO Detail to render op names. */
export function useOperationMasters(params: ListOperationMastersParams = {}) {
  return useQuery<BackendOperationMasterResponse[]>({
    queryKey: [...OPERATION_MASTER_KEY, 'list', params],
    queryFn: () =>
      IS_LIVE
        ? liveListOperationMasters(params)
        : fakeFetch([] as BackendOperationMasterResponse[]),
  });
}

// ── A3 operations drawer (TASK-TR-A3) ────────────────────────────────
//
// Hooks for the missing MO-header /start action, the missing
// /issue-materials UI on the Materials tab, and the per-operation
// progress mutations (start / qty-in / qty-out / complete) that the
// Operations drawer drives.

export interface StartMoInput {
  moId: string;
  narration?: string;
  idempotencyKey: string;
}

async function liveStartMo(input: StartMoInput): Promise<BackendMoResponse> {
  const body: BackendMoTransitionRequest = {};
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendMoResponse>(`/manufacturing/mo/${input.moId}/start`, {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

export interface IssueMaterialsInput {
  moId: string;
  firm_id?: string;
  lines: BackendMaterialIssueLineInput[];
  issueDate?: string;
  series?: string;
  narration?: string;
  idempotencyKey: string;
}

async function liveIssueMaterials(
  input: IssueMaterialsInput,
): Promise<BackendMaterialIssueResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendMaterialIssueCreateRequest = {
    firm_id,
    lines: input.lines,
  };
  if (input.issueDate !== undefined) body.issue_date = input.issueDate;
  if (input.series !== undefined) body.series = input.series;
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendMaterialIssueResponse>(`/manufacturing/mo/${input.moId}/issue-materials`, {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

// ── Create / Release (TASK-TR-A2 MO Create Wizard) ───────────────────

export interface CreateMoInput {
  firm_id?: string;
  bom_id: string;
  design_id: string;
  finished_item_id: string;
  routing_id: string;
  /** Decimal-as-string on the wire — never JS-arithmetic this. */
  qty_to_produce: string;
  planned_start_date: string;
  planned_end_date?: string | null;
  series?: string | null;
  narration?: string | null;
  idempotencyKey: string;
}

async function liveCreateMo(input: CreateMoInput): Promise<BackendMoResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendMoCreateRequest = {
    firm_id,
    bom_id: input.bom_id,
    design_id: input.design_id,
    finished_item_id: input.finished_item_id,
    routing_id: input.routing_id,
    qty_to_produce: input.qty_to_produce,
    planned_start_date: input.planned_start_date,
  };
  if (input.planned_end_date !== undefined) body.planned_end_date = input.planned_end_date;
  if (input.series !== undefined) body.series = input.series;
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendMoResponse>('/manufacturing/mo', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

export interface OperationProgressInput {
  moOperationId: string;
  firm_id?: string;
  narration?: string;
  idempotencyKey: string;
}

async function liveStartOperation(
  input: OperationProgressInput,
): Promise<BackendOperationProgressResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendOperationStartRequest = { firm_id };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendOperationProgressResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/start`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

export interface RecordQtyInInput extends OperationProgressInput {
  qty_in: string | number;
}

async function liveRecordQtyIn(input: RecordQtyInInput): Promise<BackendOperationProgressResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendOperationQtyInRequest = {
    firm_id,
    qty_in: input.qty_in,
  };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendOperationProgressResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/qty-in`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

export interface RecordQtyOutInput extends OperationProgressInput {
  qty_out: string | number;
  qty_rejected?: string | number;
  qty_byproduct?: string | number;
  qty_wastage?: string | number;
}

async function liveRecordQtyOut(
  input: RecordQtyOutInput,
): Promise<BackendOperationProgressResponse> {
  const firm_id = requireFirmId(input.firm_id);
  // The BE schema names the rejected counter ``qty_scrap``. The FE
  // input keeps ``qty_rejected`` for parity with the UI label, then
  // maps to the wire field here. Anything not supplied defaults to 0.
  const body: BackendOperationQtyOutRequest = {
    firm_id,
    qty_out: input.qty_out,
    qty_scrap: input.qty_rejected ?? 0,
    qty_byproduct: input.qty_byproduct ?? 0,
    qty_wastage: input.qty_wastage ?? 0,
  };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendOperationProgressResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/qty-out`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

async function liveCompleteOperation(
  input: OperationProgressInput,
): Promise<BackendOperationProgressResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendOperationCompleteRequest = { firm_id };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendOperationProgressResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/complete`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

/**
 * Cache helpers shared by every operation-progress mutation: refresh
 * the MO detail (operations + material lines roll up), the MO list
 * (status / progress may have changed) and the inventory namespace
 * (qty-out can mint scrap, qty-in can short stock).
 */
function invalidateMoAndStock(
  qc: ReturnType<typeof useQueryClient>,
  moId: string | undefined,
): void {
  qc.invalidateQueries({ queryKey: MO_KEY });
  if (moId) qc.invalidateQueries({ queryKey: [...MO_KEY, 'detail', moId] });
  qc.invalidateQueries({ queryKey: ['inventory'] });
}

/**
 * POST /manufacturing/mo/{id}/start (RELEASED → IN_PROGRESS). Side-
 * effect-free as far as inventory goes, but it does flip the header
 * status so we refresh the MO + the Kanban list. Material issues +
 * operation progress remain RELEASED-or-IN_PROGRESS-permitted on the
 * BE; this just makes the IN_PROGRESS-gated affordances visible.
 */
export function useStartMo() {
  const qc = useQueryClient();
  return useMutation<BackendMoResponse, Error, StartMoInput>({
    mutationFn: (input) => liveStartMo(input),
    onSuccess: (next) => {
      qc.invalidateQueries({ queryKey: MO_KEY });
      qc.setQueryData([...MO_KEY, 'detail', next.manufacturing_order_id], next);
    },
  });
}

// ── A2 MO Create Wizard hooks ────────────────────────────────────────

export interface ReleaseMoInput {
  moId: string;
  narration?: string | null;
  idempotencyKey: string;
}

async function liveReleaseMo(input: ReleaseMoInput): Promise<BackendMoResponse> {
  const body: BackendMoTransitionRequest = {};
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendMoResponse>(`/manufacturing/mo/${input.moId}/release`, {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

/**
 * POST /manufacturing/mo (A01). Money-touching once Release happens, but
 * Create alone is just metadata. We invalidate the MO list so the new
 * draft surfaces immediately and prime the detail cache so the caller
 * can navigate to /manufacturing/mo/:id without a refetch flash.
 */
export function useCreateMo() {
  const qc = useQueryClient();
  return useMutation<BackendMoResponse, Error, CreateMoInput>({
    mutationFn: (input) => liveCreateMo(input),
    onSuccess: (mo) => {
      qc.invalidateQueries({ queryKey: MO_KEY });
      qc.setQueryData([...MO_KEY, 'detail', mo.manufacturing_order_id], mo);
    },
  });
}

/**
 * POST /manufacturing/mo/{id}/issue-materials. Stock-touching — drains
 * raw material from on-hand into WIP and bumps each line's qty_issued.
 * The BE auto-starts a RELEASED MO on the first issue, so we always
 * refetch the MO detail + invalidate stock.
 */
export function useIssueMaterials(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendMaterialIssueResponse, Error, IssueMaterialsInput>({
    mutationFn: (input) => liveIssueMaterials(input),
    onSuccess: () => invalidateMoAndStock(qc, moId),
  });
}

/** POST /manufacturing/mo-operations/{id}/start (PENDING → IN_PROGRESS). */
export function useStartOperation(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendOperationProgressResponse, Error, OperationProgressInput>({
    mutationFn: (input) => liveStartOperation(input),
    onSuccess: () => invalidateMoAndStock(qc, moId),
  });
}

/** POST /manufacturing/mo-operations/{id}/qty-in (delta-additive). */
export function useRecordQtyIn(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendOperationProgressResponse, Error, RecordQtyInInput>({
    mutationFn: (input) => liveRecordQtyIn(input),
    onSuccess: () => invalidateMoAndStock(qc, moId),
  });
}

/** POST /manufacturing/mo-operations/{id}/qty-out (delta-additive). */
export function useRecordQtyOut(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendOperationProgressResponse, Error, RecordQtyOutInput>({
    mutationFn: (input) => liveRecordQtyOut(input),
    onSuccess: () => invalidateMoAndStock(qc, moId),
  });
}

/** POST /manufacturing/mo-operations/{id}/complete (→ CLOSED). */
export function useCompleteOperation(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendOperationProgressResponse, Error, OperationProgressInput>({
    mutationFn: (input) => liveCompleteOperation(input),
    onSuccess: () => invalidateMoAndStock(qc, moId),
  });
}

/** POST /manufacturing/mo/:id/release — moves a DRAFT MO to RELEASED. */
export function useReleaseMo() {
  const qc = useQueryClient();
  return useMutation<BackendMoResponse, Error, ReleaseMoInput>({
    mutationFn: (input) => liveReleaseMo(input),
    onSuccess: (mo) => {
      qc.invalidateQueries({ queryKey: MO_KEY });
      qc.setQueryData([...MO_KEY, 'detail', mo.manufacturing_order_id], mo);
    },
  });
}

// ── Test-only exports ────────────────────────────────────────────────

/** Mappers exposed for the live-mapping unit tests. */
export const _internal = {
  mapMoListItemToKanban,
  moStatusToStage,
};

/**
 * Live wrappers exposed for fetch-mocked integration tests. The hooks
 * short-circuit to mock mode in vitest because IS_LIVE is read from
 * VITE_API_MODE at module load. Tests call `__live.*` directly to drive
 * the wire-format paths.
 */
export const __live = {
  liveListMos,
  liveGetMo,
  liveListDesigns,
  liveGetDesign,
  liveListBoms,
  liveGetBom,
  liveListRoutings,
  liveGetRouting,
  liveGetMoCompletionPreview,
  liveCompleteMo,
  liveListOperationMasters,
  // A3:
  liveStartMo,
  liveIssueMaterials,
  liveStartOperation,
  liveRecordQtyIn,
  liveRecordQtyOut,
  liveCompleteOperation,
  // A2:
  liveCreateMo,
  liveReleaseMo,
};
