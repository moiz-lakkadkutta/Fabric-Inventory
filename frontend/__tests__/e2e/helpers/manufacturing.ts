/**
 * TASK-TR-A13 — Manufacturing E2E helpers.
 *
 * Per-step HTTP helpers for ``manufacturing-pipeline.spec.ts``. Each
 * helper wraps a single backend endpoint, stamps a fresh
 * ``Idempotency-Key`` on every mutation (the global
 * ``IdempotencyMiddleware`` requires it on POSTs), and returns a
 * minimally-typed payload so the spec reads like a story.
 *
 * Design notes:
 *   - All paths go through the Vite proxy at ``/api/*`` — the spec
 *     anchors against ``http://localhost:5173``, same as the cutover
 *     acceptance suite (TASK-CUT-503).
 *   - We use Playwright's ``APIRequestContext`` (the ``request``
 *     fixture) rather than driving a ``page``: A14-FU MO list/detail
 *     UI screens are not yet built (task #48), so there is no page-
 *     object surface to attach to. This spec proves the *API* chain.
 *   - Auth: we sign up an owner (org-level token, ``firm_id=None``)
 *     and then call ``/auth/login`` to get a firm-scoped token —
 *     because ``/reports/tb`` (used for the WIP/Inventory invariant)
 *     calls ``_require_active_firm`` and needs the firm in the JWT.
 *   - Idempotency: every mutating call gets a UUID v4
 *     ``Idempotency-Key``. Re-runs are deterministic because each
 *     ``signupOwner`` mints a brand-new org by timestamp.
 */

import type { APIRequestContext } from '@playwright/test';
import { randomUUID } from 'node:crypto';

// ---------------------------------------------------------------------------
// Owner / auth
// ---------------------------------------------------------------------------

export interface OwnerSession {
  accessToken: string;
  orgId: string;
  firmId: string;
  email: string;
  orgName: string;
}

interface SignupResponse {
  user_id: string;
  org_id: string;
  firm_id: string;
  access_token: string;
}

interface LoginResponse {
  access_token: string;
  firm_id: string | null;
}

/**
 * Sign up a fresh owner + firm and return a firm-scoped session.
 *
 * Signup itself issues an org-level token (``firm_id=None`` in the
 * JWT). The reports endpoints (``/reports/tb`` in particular) refuse
 * org-level tokens with a 400 — so we follow up with ``/auth/login``
 * which auto-binds the single firm and reissues a firm-scoped JWT.
 */
export async function signupOwner(request: APIRequestContext): Promise<OwnerSession> {
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 100000)}`;
  const email = `mfg-e2e-${stamp}@example.com`;
  const orgName = `MFG E2E ${stamp}`;
  const password = 'MfgE2EPass1!';

  const signupRes = await request.post('/api/auth/signup', {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': randomUUID(),
    },
    data: {
      email,
      password,
      org_name: orgName,
      firm_name: 'Primary',
      state_code: 'MH',
    },
  });
  if (signupRes.status() !== 201) {
    throw new Error(`signup failed: ${signupRes.status()} ${await signupRes.text()}`);
  }
  const signup = (await signupRes.json()) as SignupResponse;

  // Login to swap the org-level token for a firm-scoped one (one firm
  // → /auth/login auto-binds).
  const loginRes = await request.post('/api/auth/login', {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': randomUUID(),
    },
    data: { email, password, org_name: orgName },
  });
  if (loginRes.status() !== 200) {
    throw new Error(`login failed: ${loginRes.status()} ${await loginRes.text()}`);
  }
  const login = (await loginRes.json()) as LoginResponse;
  if (!login.firm_id) {
    throw new Error('login did not auto-bind a firm_id; expected single firm');
  }

  return {
    accessToken: login.access_token,
    orgId: signup.org_id,
    firmId: login.firm_id,
    email,
    orgName,
  };
}

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

interface ApiCallOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  token?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined>;
}

interface ApiResult {
  status: number;
  body: unknown;
  text: string;
}

async function apiCall(
  request: APIRequestContext,
  path: string,
  opts: ApiCallOptions = {},
): Promise<ApiResult> {
  const method = opts.method ?? 'GET';
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (opts.token) headers['Authorization'] = `Bearer ${opts.token}`;
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['Idempotency-Key'] = randomUUID();

  let url = path.startsWith('/') ? path : `/${path}`;
  if (opts.query) {
    const qs = Object.entries(opts.query)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&');
    if (qs) url = `${url}?${qs}`;
  }

  const res = await request.fetch(url, {
    method,
    headers,
    data: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  return { status: res.status(), body: parsed, text };
}

function expectOk(result: ApiResult, ok: number[], context: string): void {
  if (!ok.includes(result.status)) {
    throw new Error(`${context}: expected ${ok.join('/')} got ${result.status} — ${result.text}`);
  }
}

// ---------------------------------------------------------------------------
// Per-step helpers
// ---------------------------------------------------------------------------

export interface Item {
  item_id: string;
}

/** POST /items — create a raw or finished item. */
export async function createItem(
  request: APIRequestContext,
  owner: OwnerSession,
  args: { code: string; name: string; itemType: 'RAW' | 'FINISHED' | 'SEMI_FINISHED' },
): Promise<Item> {
  const res = await apiCall(request, '/api/items', {
    method: 'POST',
    token: owner.accessToken,
    body: {
      code: args.code,
      name: args.name,
      item_type: args.itemType,
      primary_uom: 'METER',
      firm_id: owner.firmId,
    },
  });
  expectOk(res, [201], `createItem ${args.code}`);
  return res.body as Item;
}

export interface Design {
  design_id: string;
}

/** POST /designs */
export async function createDesign(
  request: APIRequestContext,
  owner: OwnerSession,
  args: { code: string; name: string },
): Promise<Design> {
  const res = await apiCall(request, '/api/designs', {
    method: 'POST',
    token: owner.accessToken,
    body: {
      code: args.code,
      name: args.name,
      firm_id: owner.firmId,
    },
  });
  expectOk(res, [201], `createDesign ${args.code}`);
  return res.body as Design;
}

export interface OperationMaster {
  operation_master_id: string;
}

/** POST /operation-masters — operation_type is required for QC. */
export async function createOperationMaster(
  request: APIRequestContext,
  owner: OwnerSession,
  args: { code: string; name: string; operationType: 'STITCHING' | 'QC' | 'PACKING' | 'OTHER' },
): Promise<OperationMaster> {
  const res = await apiCall(request, '/api/operation-masters', {
    method: 'POST',
    token: owner.accessToken,
    body: {
      code: args.code,
      name: args.name,
      firm_id: owner.firmId,
      operation_type: args.operationType,
    },
  });
  expectOk(res, [201], `createOperationMaster ${args.code}`);
  return res.body as OperationMaster;
}

export interface Bom {
  bom_id: string;
}

/** POST /boms */
export async function createBom(
  request: APIRequestContext,
  owner: OwnerSession,
  args: {
    designId: string;
    finishedItemId: string;
    rawItemId: string;
    qtyRequired: string;
  },
): Promise<Bom> {
  const res = await apiCall(request, '/api/boms', {
    method: 'POST',
    token: owner.accessToken,
    body: {
      firm_id: owner.firmId,
      design_id: args.designId,
      finished_item_id: args.finishedItemId,
      lines: [
        {
          item_id: args.rawItemId,
          qty_required: args.qtyRequired,
          uom: 'METER',
          is_optional: false,
          part_role: 'SHELL',
          sequence: 1,
        },
      ],
    },
  });
  expectOk(res, [201], 'createBom');
  return res.body as Bom;
}

export interface Routing {
  routing_id: string;
}

/** POST /routings — chains the ops in sequence (FINISH_TO_START). */
export async function createRouting(
  request: APIRequestContext,
  owner: OwnerSession,
  args: { designId: string; operationIds: string[] },
): Promise<Routing> {
  const edges = [];
  for (let i = 0; i < args.operationIds.length - 1; i++) {
    edges.push({
      from_operation_id: args.operationIds[i],
      to_operation_id: args.operationIds[i + 1],
      edge_type: 'FINISH_TO_START',
    });
  }
  const res = await apiCall(request, '/api/routings', {
    method: 'POST',
    token: owner.accessToken,
    body: {
      firm_id: owner.firmId,
      design_id: args.designId,
      code: `R-${randomUUID().slice(0, 6)}`,
      edges,
    },
  });
  expectOk(res, [201], 'createRouting');
  return res.body as Routing;
}

interface Location {
  location_id: string;
  code: string;
}

/**
 * Return MAIN location id for the firm, creating it if absent.
 * Mirrors the cutover spec's fallback path for fresh tenants.
 */
export async function ensureMainLocation(
  request: APIRequestContext,
  owner: OwnerSession,
): Promise<string> {
  const listRes = await apiCall(request, '/api/locations', {
    token: owner.accessToken,
    query: { firm_id: owner.firmId },
  });
  expectOk(listRes, [200], 'list locations');
  const list = listRes.body as { items?: Location[] };
  const found = (list.items ?? []).find((l) => l.code === 'MAIN');
  if (found) return found.location_id;
  const createRes = await apiCall(request, '/api/locations', {
    method: 'POST',
    token: owner.accessToken,
    body: { firm_id: owner.firmId, code: 'MAIN', name: 'Main Warehouse' },
  });
  expectOk(createRes, [200, 201], 'create MAIN location');
  return (createRes.body as Location).location_id;
}

/** POST /stock-adjustments — INCREASE the raw item at MAIN with unit_cost. */
export async function preStockRawMaterial(
  request: APIRequestContext,
  owner: OwnerSession,
  args: { itemId: string; locationId: string; qty: string; unitCost: string },
): Promise<void> {
  const res = await apiCall(request, '/api/stock-adjustments', {
    method: 'POST',
    token: owner.accessToken,
    body: {
      firm_id: owner.firmId,
      item_id: args.itemId,
      location_id: args.locationId,
      qty: args.qty,
      direction: 'INCREASE',
      reason: 'TR-A13 E2E seed',
      unit_cost: args.unitCost,
    },
  });
  expectOk(res, [200, 201], 'pre-stock raw material');
}

export interface MoMaterialLine {
  mo_material_line_id: string;
  qty_required: string;
}

export interface MoOperation {
  mo_operation_id: string;
  operation_sequence: number | null;
  operation_master_id: string;
}

export interface Mo {
  manufacturing_order_id: string;
  status: string;
  produced_qty: string | null;
  scrap_qty: string | null;
  material_lines: MoMaterialLine[];
  operations: MoOperation[];
}

/** POST /manufacturing/mo — create DRAFT MO. */
export async function createMo(
  request: APIRequestContext,
  owner: OwnerSession,
  args: {
    designId: string;
    finishedItemId: string;
    bomId: string;
    routingId: string;
    qtyToProduce: string;
  },
): Promise<Mo> {
  const res = await apiCall(request, '/api/manufacturing/mo', {
    method: 'POST',
    token: owner.accessToken,
    body: {
      firm_id: owner.firmId,
      design_id: args.designId,
      finished_item_id: args.finishedItemId,
      bom_id: args.bomId,
      routing_id: args.routingId,
      qty_to_produce: args.qtyToProduce,
      planned_start_date: new Date().toISOString().slice(0, 10),
    },
  });
  expectOk(res, [201], 'create MO');
  return res.body as Mo;
}

export async function getMo(
  request: APIRequestContext,
  owner: OwnerSession,
  moId: string,
): Promise<Mo> {
  const res = await apiCall(request, `/api/manufacturing/mo/${moId}`, {
    token: owner.accessToken,
  });
  expectOk(res, [200], `get MO ${moId}`);
  return res.body as Mo;
}

/** POST /manufacturing/mo/{id}/release — DRAFT → RELEASED. */
export async function releaseMo(
  request: APIRequestContext,
  owner: OwnerSession,
  moId: string,
): Promise<void> {
  const res = await apiCall(request, `/api/manufacturing/mo/${moId}/release`, {
    method: 'POST',
    token: owner.accessToken,
    body: {},
  });
  expectOk(res, [200], `release MO ${moId}`);
}

/** POST /manufacturing/mo/{id}/issue-materials — debits 1310 WIP. */
export async function issueAllMaterials(
  request: APIRequestContext,
  owner: OwnerSession,
  moId: string,
): Promise<void> {
  const mo = await getMo(request, owner, moId);
  const lines = mo.material_lines.map((ln) => ({
    mo_material_line_id: ln.mo_material_line_id,
    qty_to_issue: ln.qty_required,
  }));
  const res = await apiCall(request, `/api/manufacturing/mo/${moId}/issue-materials`, {
    method: 'POST',
    token: owner.accessToken,
    body: { firm_id: owner.firmId, lines },
  });
  expectOk(res, [201], `issue materials for MO ${moId}`);
}

/**
 * Drive one in-house MO operation through start → qty-in → qty-out →
 * complete with the same qty on every step (no scrap).
 */
export async function closeInHouseOp(
  request: APIRequestContext,
  owner: OwnerSession,
  args: { moOperationId: string; qty: string },
): Promise<void> {
  const base = `/api/manufacturing/mo-operations/${args.moOperationId}`;
  const startRes = await apiCall(request, `${base}/start`, {
    method: 'POST',
    token: owner.accessToken,
    body: { firm_id: owner.firmId },
  });
  expectOk(startRes, [200], `start op ${args.moOperationId}`);

  const qtyInRes = await apiCall(request, `${base}/qty-in`, {
    method: 'POST',
    token: owner.accessToken,
    body: { firm_id: owner.firmId, qty_in: args.qty },
  });
  expectOk(qtyInRes, [200], `qty-in op ${args.moOperationId}`);

  const qtyOutRes = await apiCall(request, `${base}/qty-out`, {
    method: 'POST',
    token: owner.accessToken,
    body: { firm_id: owner.firmId, qty_out: args.qty },
  });
  expectOk(qtyOutRes, [200], `qty-out op ${args.moOperationId}`);

  const completeRes = await apiCall(request, `${base}/complete`, {
    method: 'POST',
    token: owner.accessToken,
    body: { firm_id: owner.firmId },
  });
  expectOk(completeRes, [200], `complete op ${args.moOperationId}`);
}

/**
 * Drive a QC op: start-qc → record-qc-result with verdict=PASS
 * (qty_passed equals predecessor.qty_out → state goes to CLOSED).
 */
export async function passQcOp(
  request: APIRequestContext,
  owner: OwnerSession,
  args: { moOperationId: string; qtyPassed: string },
): Promise<void> {
  const base = `/api/manufacturing/mo-operations/${args.moOperationId}`;
  const startRes = await apiCall(request, `${base}/start-qc`, {
    method: 'POST',
    token: owner.accessToken,
    body: { firm_id: owner.firmId },
  });
  expectOk(startRes, [200], `start-qc ${args.moOperationId}`);

  const resultRes = await apiCall(request, `${base}/record-qc-result`, {
    method: 'POST',
    token: owner.accessToken,
    body: { firm_id: owner.firmId, qty_passed: args.qtyPassed },
  });
  expectOk(resultRes, [200], `record-qc-result ${args.moOperationId}`);
}

interface MoCompleteResult {
  status: number;
  body: unknown;
  text: string;
}

/**
 * POST /manufacturing/mo/{id}/complete — drains WIP → Inventory.
 *
 * Returns the raw HTTP result so the spec can assert on success
 * (200 + status=COMPLETED) OR failure (422 with error envelope) for
 * the "blocked" negative test.
 */
export async function completeMo(
  request: APIRequestContext,
  owner: OwnerSession,
  args: { moId: string; producedQty: string },
): Promise<MoCompleteResult> {
  return apiCall(request, `/api/manufacturing/mo/${args.moId}/complete`, {
    method: 'POST',
    token: owner.accessToken,
    body: {
      firm_id: owner.firmId,
      produced_qty: args.producedQty,
    },
  });
}

// ---------------------------------------------------------------------------
// Reports / invariants
// ---------------------------------------------------------------------------

export interface TbRow {
  ledger_code: string;
  debit: string;
  credit: string;
}

export interface Tb {
  total_debits: string;
  total_credits: string;
  balanced: boolean;
  rows: TbRow[];
}

/**
 * GET /reports/tb — return rows + totals for invariant checks.
 *
 * Requires a firm-scoped token (we already swap to one in
 * ``signupOwner``).
 */
export async function getTrialBalance(
  request: APIRequestContext,
  owner: OwnerSession,
): Promise<Tb> {
  const today = new Date().toISOString().slice(0, 10);
  const res = await apiCall(request, '/api/reports/tb', {
    token: owner.accessToken,
    query: { as_of: today },
  });
  expectOk(res, [200], 'GET /reports/tb');
  return res.body as Tb;
}

/** Find a ledger row by code; returns ``null`` if not present (zero-balance). */
export function findLedgerRow(tb: Tb, code: string): TbRow | null {
  return tb.rows.find((r) => r.ledger_code === code) ?? null;
}

export interface StockSummaryRow {
  item_id: string;
  on_hand_qty: string;
  avg_cost: string;
  valuation: string;
}

export interface StockSummary {
  rows: StockSummaryRow[];
}

/**
 * GET /reports/stock-summary — for the finished-goods unit-cost
 * assertion after completion.
 */
export async function getStockSummary(
  request: APIRequestContext,
  owner: OwnerSession,
): Promise<StockSummary> {
  const res = await apiCall(request, '/api/reports/stock-summary', {
    token: owner.accessToken,
    query: { include_zero: 'false' },
  });
  expectOk(res, [200], 'GET /reports/stock-summary');
  const body = res.body as { rows?: StockSummaryRow[] } | undefined;
  return { rows: body?.rows ?? [] };
}

/** Find a stock row by item_id (returns ``null`` if not on hand). */
export function findStockRow(summary: StockSummary, itemId: string): StockSummaryRow | null {
  return summary.rows.find((r) => r.item_id === itemId) ?? null;
}
