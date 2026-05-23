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
 *     / STITCHING / QC / PACKED). TASK-TR-A1: `useManufacturingOrders`
 *     opts into `?include=operations` and `deriveMoStage` walks the
 *     loaded operations + each op's `operation_master.operation_type`
 *     to pick the lane. Falls back to header-status mapping when ops
 *     are absent (lean shape).
 *   - `MoListItem.finished_item_name` is server-resolved via LEFT JOIN
 *     so the card surfaces the product name (no more "MO {number}"
 *     placeholder). Customer slot stays empty until MO ↔ sales-order
 *     link lands — the Kanban is about WHAT is being made.
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
export type BackendMoOperationListItem = components['schemas']['MoOperationListItem'];
export type BackendMoOperationState = components['schemas']['MoOperationState'];
export type BackendOperationType = components['schemas']['OperationType'];

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

// A5 QC actions — start-qc + record-verdict + read-latest-verdict.
export type BackendQcStartRequest = components['schemas']['QcStartRequest'];
export type BackendQcResultRequest = components['schemas']['QcResultRequest'];
export type BackendQcResultResponse = components['schemas']['QcResultResponse'];
export type BackendQcOperationResponse = components['schemas']['QcOperationResponse'];

// A4 karigar — request + response shapes for the dispatch / acknowledge /
// receive / close path. The wider ``KarigarOperationResponse`` carries
// ``acknowledged_at`` + ``outward_challan_id`` for the drawer's JWO
// deep-link; the detail GET returns the narrower OperationProgressResponse
// + event log, from which the same fields can be re-derived on cold
// reloads.
export type BackendKarigarOperationResponse = components['schemas']['KarigarOperationResponse'];
export type BackendKarigarDispatchRequest = components['schemas']['KarigarDispatchRequest'];
export type BackendKarigarAcknowledgeRequest = components['schemas']['KarigarAcknowledgeRequest'];
export type BackendKarigarReceiveRequest = components['schemas']['KarigarReceiveRequest'];
export type BackendKarigarCloseRequest = components['schemas']['KarigarCloseRequest'];
export type BackendOperationDetailResponse = components['schemas']['OperationDetailResponse'];
export type BackendProductionEventResponse = components['schemas']['ProductionEventResponse'];

// ── MO list ↔ Kanban view-model mapper ────────────────────────────────

/**
 * Op states that mean "this op is still part of the current chain"
 * for the purpose of picking the *current* lane. CLOSED + SKIPPED +
 * CANCELLED are "done with this op", so we skip past them.
 *
 * TASK-TR-A1: the Kanban lane is driven by the FIRST non-CLOSED op in
 * the chain (lowest sequence), with its operation_type mapped into a
 * lane. PENDING / READY / DISPATCHED / ACKNOWLEDGED / IN_PROGRESS /
 * RECEIVED_PARTIAL / RECEIVED_FULL / QC_PENDING / REWORK all count as
 * "the chain hasn't moved past this op".
 */
const OP_STATE_DONE: ReadonlySet<BackendMoOperationState> = new Set([
  'CLOSED',
  'SKIPPED',
  'CANCELLED',
]);

/**
 * Map an ``OperationType`` to a Kanban lane.
 *
 * Lane choices reflect the textile-trade routing the trial customer
 * runs today (cutting → embroidery → stitching → QC → packing). When
 * the operation_type doesn't fit a specific lane (WEAVING / DYEING /
 * OTHER) we drop into "CUTTING" — that's the visual home for "raw-
 * material prep" in the textile shop floor.
 */
export function operationTypeToStage(opType: BackendOperationType | null | undefined): MoStage {
  switch (opType) {
    case 'EMBROIDERY':
      return 'EMBROIDERY';
    case 'STITCHING':
      return 'STITCHING';
    case 'QC':
      return 'QC';
    case 'PACKING':
      // PACKING is the LAST op of a typical routing. While packing
      // is in flight we render the MO in PACKED — visually it's
      // already past the QC gate; the progress badge gives the
      // operator the "not 100% yet" cue.
      return 'PACKED';
    case 'WEAVING':
    case 'DYEING':
    case 'OTHER':
    case null:
    case undefined:
      // Textile fabric-prep ops (weaving / dyeing) and unclassified
      // ops live in the "CUTTING" lane — that's where the trial
      // customer's first physical handling happens.
      return 'CUTTING';
    default: {
      // Exhaustiveness guard: TypeScript flags this if a new
      // OperationType lands and isn't handled above.
      const _exhaustive: never = opType;
      void _exhaustive;
      return 'CUTTING';
    }
  }
}

/**
 * Derive the current Kanban stage for an MO from its operations array
 * + header status (TASK-TR-A1).
 *
 * Algorithm:
 *   1. DRAFT or RELEASED                          → PLANNED
 *   2. Every op is in a "done" state              → PACKED
 *   3. Otherwise, pick the FIRST non-done op
 *      (lowest sequence) and map its op type      → lane
 *   4. No operations array (lean shape)           → fall back to header
 *      ``MoStatus``-derived lane (legacy mapping)
 */
export function deriveMoStage(
  status: BackendMoStatus,
  ops: BackendMoOperationListItem[] | null | undefined,
): MoStage {
  if (status === 'DRAFT' || status === 'RELEASED') return 'PLANNED';
  if (status === 'COMPLETED' || status === 'CLOSED') return 'PACKED';
  if (!ops || ops.length === 0) {
    // Lean shape (no ?include=operations) — fall back to the legacy
    // status-only mapping.
    return moStatusToStage(status);
  }
  const sorted = [...ops].sort((a, b) => (a.operation_sequence ?? 0) - (b.operation_sequence ?? 0));
  if (sorted.every((op) => OP_STATE_DONE.has(op.state))) return 'PACKED';
  const current = sorted.find((op) => !OP_STATE_DONE.has(op.state));
  if (!current) return 'PACKED';
  return operationTypeToStage(current.operation_type);
}

/**
 * Days since an op transitioned into its active state, from
 * ``start_date``. Returns 0 when start_date is missing (op hasn't
 * started yet) — the card just shows no SLA badge.
 */
export function daysSinceStart(
  startDate: string | null | undefined,
  now: Date = new Date(),
): number {
  if (!startDate) return 0;
  const start = new Date(startDate);
  if (Number.isNaN(start.getTime())) return 0;
  const ms = now.getTime() - start.getTime();
  return Math.max(0, Math.floor(ms / (1000 * 60 * 60 * 24)));
}

/**
 * Collapse the header-level `MoStatus` to a Kanban `MoStage`. Legacy
 * fallback for the lean list shape (no operations array). The richer
 * ``deriveMoStage`` is preferred when the FE asks for
 * ``?include=operations``.
 */
export function moStatusToStage(status: BackendMoStatus): MoStage {
  switch (status) {
    case 'DRAFT':
    case 'RELEASED':
      return 'PLANNED';
    case 'IN_PROGRESS':
      // Without operations + routing, we can't know which middle stage
      // an in-progress MO sits in. Park it at STITCHING — the most
      // common bottleneck in the trial customer's flow.
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
 * Kanban consumes. Drives lane + progress + days_in_stage off the
 * eager-loaded ``operations`` array when present; otherwise falls back
 * to the header-status mapping with placeholder zeros for the SLA
 * fields (TASK-TR-A1).
 *
 * ``finished_item_name`` replaces the legacy "MO {number}" placeholder
 * for the card's product line; the ``customer`` slot is repurposed as
 * the finished-item display label since the Kanban is about WHAT is
 * being made, not WHO ordered it (the MO header has no customer link
 * today).
 */
export function mapMoListItemToKanban(
  b: BackendMoListItem,
  now: Date = new Date(),
): ManufacturingOrder {
  const ops = b.operations ?? null;
  const stage = deriveMoStage(b.status, ops);

  // Progress: closed_ops / total_ops × 100. Falls back to the legacy
  // 0/100 binary when the operations array isn't present.
  let progress_pct = 0;
  if (ops && ops.length > 0) {
    const closed = ops.filter((o) => OP_STATE_DONE.has(o.state)).length;
    progress_pct = Math.round((closed / ops.length) * 100);
  } else if (b.status === 'COMPLETED' || b.status === 'CLOSED') {
    progress_pct = 100;
  }

  // days_in_stage: derive from the current IN_PROGRESS op's start_date.
  // If no op is mid-flight (PENDING / READY before start) → 0.
  let days_in_stage = 0;
  if (ops && ops.length > 0) {
    const sorted = [...ops].sort(
      (a, b2) => (a.operation_sequence ?? 0) - (b2.operation_sequence ?? 0),
    );
    const current = sorted.find((op) => !OP_STATE_DONE.has(op.state));
    if (current?.start_date) {
      days_in_stage = daysSinceStart(current.start_date, now);
    }
  }

  return {
    mo_id: b.manufacturing_order_id,
    number: b.series ? `${b.series}/${b.number}` : b.number,
    // Product: prefer finished_item_name (server-resolved) → fall back
    // to the prior placeholder when the field is null (legacy rows).
    product: b.finished_item_name ?? `MO ${b.number}`,
    qty: parseFloat(b.planned_qty || '0'),
    // No UoM on the list shape; default to PIECE — METER is the only
    // other supported Kanban UoM and the list page tolerates either.
    uom: 'PIECE',
    // No customer link on the MO header today; the Kanban renders
    // "WHAT is being made" via the product line. Leave empty so the
    // card collapses cleanly rather than faking a value.
    customer: '',
    // Prefer planned_end_date — when set, that's the real ETA. Fall
    // back to mo_date for legacy MOs created before the persistence
    // followup (so the card still has something useful).
    due_date: b.planned_end_date ?? b.mo_date,
    stage,
    progress_pct,
    days_in_stage,
    // No SLA standards yet — the FE renders the badge only when
    // days_in_stage > std_days_in_stage, so leaving this at 0 keeps
    // the card visually clean. A future task can wire per-routing SLA.
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
  // TASK-TR-A1: comma-separated list of expansions. Currently only
  // "operations" is supported by the BE. Off by default to preserve
  // the lean payload shape for the MO list page.
  include?: string;
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
  if (params.include) usp.set('include', params.include);
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
 * Hook consumed by `ManufacturingPipeline`. Returns the Kanban
 * view-model with per-MO operations eager-loaded so lane placement +
 * progress + days_in_stage come from real op state (TASK-TR-A1).
 *
 * In live mode the underlying GET ``/manufacturing/mo?include=operations``
 * call returns the canonical (non-clone) op chain on each MO. The
 * mock-mode branch keeps the click-dummy fixture so design demos
 * still render.
 */
export function useManufacturingOrders(params: ListMosParams = {}) {
  // Always include operations for the Kanban — its lane mapping
  // depends on per-op state. The MO-list page uses ``useMos`` (lean)
  // for its dense table.
  const effective: ListMosParams = { ...params, include: 'operations' };
  return useQuery<ManufacturingOrder[]>({
    queryKey: [...MO_KEY, 'kanban', effective],
    queryFn: async (): Promise<ManufacturingOrder[]> => {
      if (IS_LIVE) {
        const items = await liveListMos(effective);
        return items.map((b) => mapMoListItemToKanban(b));
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

// ── A5 QC actions (TASK-TR-A5) ───────────────────────────────────────
//
// QC operation lifecycle is driven by three endpoints that the drawer
// surfaces in the right order based on the op's current state:
//   PENDING / READY  → POST /start-qc           (→ QC_PENDING)
//   QC_PENDING       → POST /record-qc-result   (→ CLOSED or REWORK)
//   REWORK           → re-record once the rework clone closes (same endpoint)
//   CLOSED           → read-only GET /qc-result
//
// The GET /qc-result endpoint is load-bearing for the verdict form
// because it surfaces `predecessor_qty_out` — the qty arriving at QC
// that the 5 bucket inputs MUST sum to (the BE enforces strictly).
// Replicating the predecessor lookup on the FE would mean walking the
// routing-edge graph + filtering rework clones; instead we ask the BE.

async function liveStartQc(input: OperationProgressInput): Promise<BackendQcOperationResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendQcStartRequest = { firm_id };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendQcOperationResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/start-qc`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

export interface RecordQcResultInput extends OperationProgressInput {
  qty_passed: string | number;
  qty_rejected: string | number;
  qty_byproduct: string | number;
  qty_wastage: string | number;
  qty_rework: string | number;
}

async function liveRecordQcResult(input: RecordQcResultInput): Promise<BackendQcOperationResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendQcResultRequest = {
    firm_id,
    qty_passed: input.qty_passed,
    qty_rejected: input.qty_rejected,
    qty_byproduct: input.qty_byproduct,
    qty_wastage: input.qty_wastage,
    qty_rework: input.qty_rework,
  };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendQcOperationResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/record-qc-result`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

async function liveGetQcResult(moOperationId: string): Promise<BackendQcResultResponse> {
  return api<BackendQcResultResponse>(`/manufacturing/mo-operations/${moOperationId}/qc-result`);
}

const QC_RESULT_KEY = ['manufacturing', 'qc-result'] as const;

/** POST /manufacturing/mo-operations/{id}/start-qc (PENDING → QC_PENDING). */
export function useStartQc(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendQcOperationResponse, Error, OperationProgressInput>({
    mutationFn: (input) => liveStartQc(input),
    onSuccess: (_next, variables) => {
      invalidateMoAndStock(qc, moId);
      // The verdict form gates on the latest GET /qc-result — drop the
      // cached "not recorded yet" snapshot so the form re-fetches the
      // freshly-resolvable predecessor_qty_out.
      qc.invalidateQueries({ queryKey: [...QC_RESULT_KEY, variables.moOperationId] });
    },
  });
}

/**
 * POST /manufacturing/mo-operations/{id}/record-qc-result. PASS verdicts
 * close the QC op; REWORK verdicts keep it in REWORK and spawn a clone
 * MoOperation that re-emerges in `MoResponse.operations` (A10-FU). We
 * invalidate the MO detail + the QC verdict cache so both forms re-read.
 */
export function useRecordQcResult(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendQcOperationResponse, Error, RecordQcResultInput>({
    mutationFn: (input) => liveRecordQcResult(input),
    onSuccess: (_next, variables) => {
      invalidateMoAndStock(qc, moId);
      qc.invalidateQueries({ queryKey: [...QC_RESULT_KEY, variables.moOperationId] });
    },
  });
}

/**
 * GET /manufacturing/mo-operations/{id}/qc-result. Returns `recorded=false`
 * + zero buckets when the verdict hasn't landed yet — the FE renders an
 * "awaiting QC" state in that case without a 404. The load-bearing
 * field is `predecessor_qty_out`: the qty arriving at QC that the
 * verdict-form's 5 buckets must sum to.
 */
export function useQcResult(
  moOperationId: string | undefined,
  options: { enabled?: boolean } = {},
) {
  return useQuery<BackendQcResultResponse>({
    queryKey: [...QC_RESULT_KEY, moOperationId],
    enabled: options.enabled !== false && moOperationId !== undefined,
    queryFn: () => liveGetQcResult(moOperationId as string),
    // Re-read on every drawer open: predecessor_qty_out can change if
    // the upstream op re-records qty_out before QC starts.
    staleTime: 0,
    gcTime: 0,
  });
}

// ── A4 karigar actions (TASK-TR-A4) ──────────────────────────────────
//
// Mutation hooks for the karigar lifecycle (dispatch → acknowledge →
// receive → close) plus a read-only ``useMoOperationDetail`` that lets
// the drawer reconstruct ``acknowledged_at`` + ``outward_challan_id``
// from the event log on a fresh page load (before any A4 mutation has
// landed in the query cache). Each mutation invalidates the parent MO
// (the operation state flips), the JWO list (dispatch mints a new JWO,
// receives bump line totals), and the inventory namespace (dispatch /
// receive move stock between MAIN and JOBWORK locations).
//
// All five share the operation-detail cache key — A5's QC PR will read
// the same key, so we expose it as a const for cross-PR consistency.

const OP_DETAIL_KEY = ['manufacturing', 'mo-operation-detail'] as const;

async function liveGetMoOperationDetail(
  moOperationId: string,
): Promise<BackendOperationDetailResponse> {
  return api<BackendOperationDetailResponse>(`/manufacturing/mo-operations/${moOperationId}`);
}

/**
 * GET /manufacturing/mo-operations/{id} — operation snapshot + the
 * append-only production event log. The drawer reads
 * ``acknowledged_at`` (presence of an ``OPERATION_ACKNOWLEDGED`` event)
 * and ``outward_challan_id`` (payload of the latest
 * ``OPERATION_DISPATCHED`` event) from this when no karigar mutation
 * has run yet in the current session.
 */
export function useMoOperationDetail(moOperationId: string | undefined) {
  return useQuery<BackendOperationDetailResponse | null>({
    queryKey: [...OP_DETAIL_KEY, moOperationId],
    enabled: moOperationId !== undefined,
    queryFn: () =>
      IS_LIVE
        ? liveGetMoOperationDetail(moOperationId as string)
        : fakeFetch<BackendOperationDetailResponse | null>(null),
    // The event log grows additively on every mutation; staleTime=0
    // keeps the drawer honest after a dispatch / acknowledge / receive.
    staleTime: 0,
  });
}

export interface DispatchKarigarInput {
  moOperationId: string;
  firm_id?: string;
  karigarPartyId: string;
  qtyDispatched: string | number;
  dispatchDate: string;
  itemId?: string | null;
  uom?: string | null;
  lotId?: string | null;
  narration?: string;
  idempotencyKey: string;
}

async function liveDispatchKarigar(
  input: DispatchKarigarInput,
): Promise<BackendKarigarOperationResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendKarigarDispatchRequest = {
    firm_id,
    karigar_party_id: input.karigarPartyId,
    qty_dispatched: input.qtyDispatched,
    dispatch_date: input.dispatchDate,
  };
  // Send item_id / uom / lot_id only when present; the BE defaults
  // item_id to the MO's finished item when omitted (A08-FU wiring).
  if (input.itemId !== undefined && input.itemId !== null) body.item_id = input.itemId;
  if (input.uom !== undefined && input.uom !== null) body.uom = input.uom;
  if (input.lotId !== undefined && input.lotId !== null) body.lot_id = input.lotId;
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendKarigarOperationResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/dispatch-karigar`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

export interface AcknowledgeKarigarInput {
  moOperationId: string;
  firm_id?: string;
  narration?: string;
  idempotencyKey: string;
}

async function liveAcknowledgeKarigar(
  input: AcknowledgeKarigarInput,
): Promise<BackendKarigarOperationResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendKarigarAcknowledgeRequest = { firm_id };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendKarigarOperationResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/acknowledge-karigar`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

export interface ReceiveKarigarInput {
  moOperationId: string;
  firm_id?: string;
  qtyReceived?: string | number;
  qtyScrap?: string | number;
  qtyByproduct?: string | number;
  qtyWastage?: string | number;
  receiptDate?: string | null;
  narration?: string;
  idempotencyKey: string;
}

async function liveReceiveKarigar(
  input: ReceiveKarigarInput,
): Promise<BackendKarigarOperationResponse> {
  const firm_id = requireFirmId(input.firm_id);
  // The BE schema defaults each qty to 0 — but at least one must be >0
  // (the service enforces this). FE-side validation lives in the form.
  const body: BackendKarigarReceiveRequest = {
    firm_id,
    qty_received: input.qtyReceived ?? 0,
    qty_scrap: input.qtyScrap ?? 0,
    qty_byproduct: input.qtyByproduct ?? 0,
    qty_wastage: input.qtyWastage ?? 0,
  };
  if (input.receiptDate !== undefined) body.receipt_date = input.receiptDate;
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendKarigarOperationResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/receive-karigar`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

export interface CloseKarigarInput {
  moOperationId: string;
  firm_id?: string;
  narration?: string;
  idempotencyKey: string;
}

async function liveCloseKarigar(
  input: CloseKarigarInput,
): Promise<BackendKarigarOperationResponse> {
  const firm_id = requireFirmId(input.firm_id);
  const body: BackendKarigarCloseRequest = { firm_id };
  if (input.narration !== undefined) body.narration = input.narration;
  return api<BackendKarigarOperationResponse>(
    `/manufacturing/mo-operations/${input.moOperationId}/close-karigar`,
    {
      method: 'POST',
      idempotencyKey: input.idempotencyKey,
      body,
    },
  );
}

/**
 * Karigar-mutation cache fan-out. Re-uses the in-house helper but also
 * busts the JWO list (dispatch mints a JWO; receive updates line totals)
 * and the operation-detail key (drawer reads ``acknowledged_at`` from
 * the events log) so the drawer re-renders against fresh state.
 */
function invalidateKarigarFanout(
  qc: ReturnType<typeof useQueryClient>,
  moId: string | undefined,
  moOperationId: string,
): void {
  invalidateMoAndStock(qc, moId);
  qc.invalidateQueries({ queryKey: [...OP_DETAIL_KEY, moOperationId] });
  qc.invalidateQueries({ queryKey: ['jobwork', 'orders'] });
}

/** POST /manufacturing/mo-operations/{id}/dispatch-karigar. Mints a JWO. */
export function useDispatchKarigar(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendKarigarOperationResponse, Error, DispatchKarigarInput>({
    mutationFn: (input) => liveDispatchKarigar(input),
    onSuccess: (_resp, input) => invalidateKarigarFanout(qc, moId, input.moOperationId),
  });
}

/** POST /manufacturing/mo-operations/{id}/acknowledge-karigar. */
export function useAcknowledgeKarigar(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendKarigarOperationResponse, Error, AcknowledgeKarigarInput>({
    mutationFn: (input) => liveAcknowledgeKarigar(input),
    onSuccess: (_resp, input) => invalidateKarigarFanout(qc, moId, input.moOperationId),
  });
}

/** POST /manufacturing/mo-operations/{id}/receive-karigar. Cumulative. */
export function useReceiveKarigar(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendKarigarOperationResponse, Error, ReceiveKarigarInput>({
    mutationFn: (input) => liveReceiveKarigar(input),
    onSuccess: (_resp, input) => invalidateKarigarFanout(qc, moId, input.moOperationId),
  });
}

/** POST /manufacturing/mo-operations/{id}/close-karigar. */
export function useCloseKarigar(moId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<BackendKarigarOperationResponse, Error, CloseKarigarInput>({
    mutationFn: (input) => liveCloseKarigar(input),
    onSuccess: (_resp, input) => invalidateKarigarFanout(qc, moId, input.moOperationId),
  });
}

// ── Test-only exports ────────────────────────────────────────────────

/** Mappers exposed for the live-mapping unit tests. */
export const _internal = {
  mapMoListItemToKanban,
  moStatusToStage,
  deriveMoStage,
  operationTypeToStage,
  daysSinceStart,
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
  // A5:
  liveStartQc,
  liveRecordQcResult,
  liveGetQcResult,
  // A4 karigar:
  liveGetMoOperationDetail,
  liveDispatchKarigar,
  liveAcknowledgeKarigar,
  liveReceiveKarigar,
  liveCloseKarigar,
};
