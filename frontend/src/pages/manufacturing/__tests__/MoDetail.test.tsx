/*
 * MoDetail — TASK-TR-A14-FU live-mode integration tests.
 *
 * Coverage:
 *   - Three tabs render and switch (Operations / Materials / Cost).
 *   - "Complete MO" button is disabled when status ≠ IN_PROGRESS.
 *   - Dialog open fires GET /completion-preview against the current
 *     produced_qty_target.
 *   - can_complete=false disables Confirm and surfaces blocking reasons.
 *   - can_complete=true enables Confirm; clicking it POSTs /complete
 *     with an Idempotency-Key.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: MoDetail } = await import('@/pages/manufacturing/MoDetail');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const MO_ID = 'm0000000-0000-0000-0000-000000000001';
const DESIGN_ID = 'd0000000-0000-0000-0000-000000000001';
const ITEM_ID = 'i0000000-0000-0000-0000-000000000001';
const OP_MASTER_ID = 'op000000-0000-0000-0000-000000000001';
const MO_OP_ID = 'mp000000-0000-0000-0000-000000000001';
const MO_MAT_LINE_ID = 'mm000000-0000-0000-0000-000000000001';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

interface BuildMoOpts {
  status?: 'DRAFT' | 'RELEASED' | 'IN_PROGRESS' | 'COMPLETED' | 'CLOSED';
  producedQty?: string | null;
}

function buildMo(opts: BuildMoOpts = {}) {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: DESIGN_ID,
    finished_item_id: ITEM_ID,
    manufacturing_order_id: MO_ID,
    mo_date: '2026-05-01',
    number: '0001',
    series: 'MO/2026',
    bom_id: null,
    routing_id: null,
    planned_qty: '100.0000',
    produced_qty: opts.producedQty ?? null,
    scrap_qty: null,
    planned_start_date: '2026-05-02',
    planned_end_date: '2026-05-15',
    status: opts.status ?? 'IN_PROGRESS',
    closed_at: null,
    deleted_at: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    operations: [
      {
        manufacturing_order_id: MO_ID,
        mo_operation_id: MO_OP_ID,
        operation_master_id: OP_MASTER_ID,
        operation_sequence: 10,
        executor: 'IN_HOUSE',
        qty_in: '100.0000',
        qty_out: '95.0000',
        state: 'IN_PROGRESS',
      },
    ],
    material_lines: [
      {
        manufacturing_order_id: MO_ID,
        mo_material_line_id: MO_MAT_LINE_ID,
        item_id: ITEM_ID,
        qty_required: '50.0000',
        qty_issued: '20.0000',
        qty_scrap: '0.0000',
        is_optional: false,
      },
    ],
  };
}

function buildOperationMaster() {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    operation_master_id: OP_MASTER_ID,
    code: 'STITCH',
    name: 'Stitching',
    operation_type: 'STITCHING',
    default_duration_mins: null,
    cost_centre_id: null,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function buildItem() {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    item_id: ITEM_ID,
    code: 'FAB',
    name: 'Cotton fabric',
    description: null,
    category: null,
    item_type: 'RAW',
    primary_uom: 'METER',
    tracking: 'NONE',
    hsn_code: '5208',
    gst_rate: '5',
    has_variants: false,
    has_expiry: false,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function buildDesign() {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: DESIGN_ID,
    code: 'BRDL-01',
    name: 'Bridal Lehenga',
    description: null,
    season: null,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function buildPreview(opts: {
  canComplete: boolean;
  blockingReasons?: string[];
  unitCost?: string;
  costPool?: string;
}) {
  return {
    mo_id: MO_ID,
    status: 'IN_PROGRESS',
    policy: 'ALL_OR_NONE',
    planned_qty: '100.0000',
    produced_qty_target: '100.0000',
    scrap_qty: '0.0000',
    wastage_qty: '0.0000',
    by_product_qty: '0.0000',
    rework_qty: '0.0000',
    cost_pool: opts.costPool ?? '50000.00',
    unit_cost: opts.unitCost ?? '500.000000',
    can_complete: opts.canComplete,
    blocking_reasons: opts.blockingReasons ?? [],
    ledger_codes: { inventory_dr: '1300', wip_cr: '1310' },
  };
}

function renderMoDetail() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/manufacturing/mo/${MO_ID}`]}>
        <Routes>
          <Route path="/manufacturing/mo/:id" element={<MoDetail />} />
          <Route path="/manufacturing/mo" element={<div>LIST_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('MoDetail (live-mode integration, TASK-TR-A14-FU)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    authStore.reset();
    authStore.setAccessToken('test-token');
    authStore.setMe({
      user_id: 'u',
      org_id: ORG_ID,
      firm_id: FIRM_ID,
      email: 'u@example.com',
      // A3: complete + start + issue + per-op progress all live under
      // these slugs on the backend. Granting them here unblocks the
      // existing complete-flow tests (which used to use a placeholder
      // `manufacturing.mo.complete`) and the new A3 affordances.
      permissions: [
        'manufacturing.mo.read',
        'manufacturing.mo.write',
        'manufacturing.material_issue.write',
        'manufacturing.operation.progress',
      ],
      flags: {},
      available_firms: [{ firm_id: FIRM_ID, code: 'F1', name: 'F1' }],
      token_expires_at: '2099-01-01T00:00:00Z',
    });
  });

  afterEach(() => {
    cleanup();
    globalThis.fetch = originalFetch;
    authStore.reset();
    vi.restoreAllMocks();
  });

  function defaultFetchImpl(mo: ReturnType<typeof buildMo>) {
    return async (url: RequestInfo) => {
      const u = String(url);
      if (
        u.includes('/manufacturing/mo/') &&
        !u.includes('completion-preview') &&
        !u.includes('complete')
      ) {
        return jsonResponse(200, mo);
      }
      if (u.includes('/designs/')) {
        return jsonResponse(200, buildDesign());
      }
      if (u.includes('/designs')) {
        return jsonResponse(200, { items: [buildDesign()], count: 1, limit: 100, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [buildItem()], count: 1, limit: 200, offset: 0 });
      }
      if (u.includes('/operation-masters')) {
        return jsonResponse(200, {
          items: [buildOperationMaster()],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    };
  }

  it('renders Operations / Materials / Cost tabs and switches between them', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo()));
    renderMoDetail();

    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    // Operations tab is default — Stitching op (from operation master lookup) is visible.
    await waitFor(() => expect(screen.getByText(/Stitching/)).toBeInTheDocument());
    expect(screen.getByText(/IN_HOUSE/)).toBeInTheDocument();

    // Switch to Materials.
    fireEvent.click(screen.getByRole('tab', { name: /materials/i }));
    await waitFor(() => expect(screen.getByText(/Cotton fabric/)).toBeInTheDocument());

    // Switch to Cost.
    fireEvent.click(screen.getByRole('tab', { name: /^cost$/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Final per-unit cost is computed at completion/i),
      ).toBeInTheDocument(),
    );
  });

  it('"Complete MO" is disabled when status is not IN_PROGRESS', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo({ status: 'DRAFT' })));
    renderMoDetail();

    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    const btn = screen.getByRole('button', { name: /complete mo/i });
    expect(btn).toBeDisabled();
  });

  it('opens the complete dialog, fetches preview, and disables Confirm when can_complete=false', async () => {
    let previewCalls = 0;
    let lastPreviewUrl: string | null = null;
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('completion-preview')) {
        previewCalls += 1;
        lastPreviewUrl = u;
        return jsonResponse(
          200,
          buildPreview({
            canComplete: false,
            blockingReasons: ['Operation 10 (Stitching) is still IN_PROGRESS.'],
          }),
        );
      }
      return defaultFetchImpl(buildMo())(url);
    });

    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /complete mo/i }));

    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /complete mo/i })).toBeInTheDocument(),
    );
    await waitFor(() => expect(previewCalls).toBeGreaterThan(0));

    // The preview URL carries firm_id and produced_qty_target.
    expect(lastPreviewUrl).toContain('firm_id=');
    expect(lastPreviewUrl).toContain('produced_qty_target=100.0000');

    const dialog = screen.getByRole('dialog', { name: /complete mo/i });

    // Blocking reason is rendered verbatim.
    await waitFor(() =>
      expect(
        within(dialog).getByText(/Operation 10 \(Stitching\) is still IN_PROGRESS/),
      ).toBeInTheDocument(),
    );

    // Cost numbers are surfaced even when can_complete is false.
    expect(within(dialog).getByText(/Cost pool/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Unit cost/i)).toBeInTheDocument();

    // Ledger codes show as a tooltip on the unit cost row.
    const unitCostLabel = within(dialog).getByText(/Unit cost/i);
    const unitCostValue = unitCostLabel.parentElement?.querySelector('[title]');
    expect(unitCostValue).toBeTruthy();
    expect((unitCostValue as HTMLElement).getAttribute('title')).toContain('DR 1300');
    expect((unitCostValue as HTMLElement).getAttribute('title')).toContain('CR 1310');

    // Confirm button is disabled.
    expect(within(dialog).getByRole('button', { name: /confirm complete/i })).toBeDisabled();
  });

  it('enables Confirm and POSTs /complete with Idempotency-Key when can_complete=true', async () => {
    let completePayload: Record<string, unknown> | null = null;
    let completeIdempotencyKey: string | null = null;
    let completePath: string | null = null;

    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.includes('completion-preview')) {
        return jsonResponse(200, buildPreview({ canComplete: true }));
      }
      if (u.endsWith('/complete') && method === 'POST') {
        completePath = u;
        completeIdempotencyKey =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
        completePayload = JSON.parse((init?.body as string) ?? '{}');
        return jsonResponse(200, buildMo({ status: 'COMPLETED', producedQty: '100.0000' }));
      }
      return defaultFetchImpl(buildMo())(url);
    });

    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /complete mo/i }));

    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /complete mo/i })).toBeInTheDocument(),
    );

    const dialog = screen.getByRole('dialog', { name: /complete mo/i });

    // Confirm button becomes enabled after the preview returns can_complete=true.
    await waitFor(() => {
      const confirmBtn = within(dialog).getByRole('button', { name: /confirm complete/i });
      expect(confirmBtn).not.toBeDisabled();
    });

    fireEvent.click(within(dialog).getByRole('button', { name: /confirm complete/i }));

    await waitFor(() => expect(completePath).not.toBeNull());
    expect(completePath).toContain(`/manufacturing/mo/${MO_ID}/complete`);
    expect(completePayload).toMatchObject({
      firm_id: FIRM_ID,
      produced_qty: '100.0000',
    });
    expect(completeIdempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);

    // Dialog closes on success.
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /complete mo/i })).not.toBeInTheDocument(),
    );
  });

  // ── A3 operations drawer + start + issue-materials ────────────────

  it('A3: Start MO button is disabled unless status === RELEASED', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo({ status: 'DRAFT' })));
    renderMoDetail();

    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    const startBtn = screen.getByRole('button', { name: /^start mo$/i });
    expect(startBtn).toBeDisabled();
    // Tooltip surfaces the blocking reason.
    expect(startBtn.getAttribute('title')).toMatch(/release the mo|cannot be started/i);
  });

  it('A3: Start MO POSTs /start with idempotency-key when RELEASED', async () => {
    let startPath: string | null = null;
    let startIdem: string | null = null;
    let startPayload: unknown = null;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.endsWith('/start') && method === 'POST') {
        startPath = u;
        startIdem =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
        startPayload = JSON.parse((init?.body as string) ?? '{}');
        return jsonResponse(200, buildMo({ status: 'IN_PROGRESS' }));
      }
      return defaultFetchImpl(buildMo({ status: 'RELEASED' }))(url);
    });

    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    const startBtn = screen.getByRole('button', { name: /^start mo$/i });
    expect(startBtn).not.toBeDisabled();
    fireEvent.click(startBtn);

    await waitFor(() => expect(startPath).not.toBeNull());
    expect(startPath).toContain(`/manufacturing/mo/${MO_ID}/start`);
    expect(startIdem).toMatch(/^[0-9a-f-]{36}$/i);
    // Empty narration body — MoTransitionRequest is just `{}`.
    expect(startPayload).toEqual({});
  });

  it('A3: Issue Materials button opens dialog with remaining qty pre-populated', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo({ status: 'IN_PROGRESS' })));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('tab', { name: /materials/i }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /issue all remaining/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole('button', { name: /issue all remaining/i }));

    const dialog = await screen.findByRole('dialog', { name: /issue materials/i });
    // qty_required = 50, qty_issued = 20 → remaining = 30.0000.
    const qtyInput = within(dialog).getByLabelText(/Qty to issue for Cotton fabric/i);
    expect((qtyInput as HTMLInputElement).value).toBe('30.0000');
  });

  it('A3: Issue Materials confirm POSTs lines with idempotency-key', async () => {
    let issuePath: string | null = null;
    let issueIdem: string | null = null;
    let issuePayload: Record<string, unknown> | null = null;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.endsWith('/issue-materials') && method === 'POST') {
        issuePath = u;
        issueIdem =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
        issuePayload = JSON.parse((init?.body as string) ?? '{}');
        return jsonResponse(201, {
          created_at: '2026-05-01T00:00:00Z',
          firm_id: FIRM_ID,
          issue_date: '2026-05-01',
          lines: [],
          manufacturing_order_id: MO_ID,
          material_issue_id: 'mi000000-0000-0000-0000-000000000001',
        });
      }
      return defaultFetchImpl(buildMo({ status: 'IN_PROGRESS' }))(url);
    });

    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: /materials/i }));
    fireEvent.click(screen.getByRole('button', { name: /issue all remaining/i }));

    const dialog = await screen.findByRole('dialog', { name: /issue materials/i });
    fireEvent.click(within(dialog).getByRole('button', { name: /confirm issue/i }));

    await waitFor(() => expect(issuePath).not.toBeNull());
    expect(issuePath).toContain(`/manufacturing/mo/${MO_ID}/issue-materials`);
    expect(issueIdem).toMatch(/^[0-9a-f-]{36}$/i);
    expect(issuePayload).toMatchObject({
      firm_id: FIRM_ID,
      lines: [
        {
          mo_material_line_id: MO_MAT_LINE_ID,
          qty_to_issue: '30.0000',
        },
      ],
    });
  });

  it('A3: clicking an operation row opens the drawer with snapshot', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo({ status: 'IN_PROGRESS' })));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    // The Stitching row is rendered as role="button" via the row click
    // affordance (aria-label "Open Stitching operation").
    const row = await screen.findByRole('button', { name: /open stitching operation/i });
    fireEvent.click(row);

    const drawer = await screen.findByRole('dialog', { name: /operation stitching/i });
    // Snapshot shows the op's qty_in / qty_out.
    expect(within(drawer).getByText(/Snapshot/i)).toBeInTheDocument();
    expect(within(drawer).getByText(/^100\.0000$/)).toBeInTheDocument();
    expect(within(drawer).getByText(/^95\.0000$/)).toBeInTheDocument();
    // Sequence + executor surfaced.
    expect(within(drawer).getByText(/#10 of 1/)).toBeInTheDocument();
  });

  it('A3: PENDING IN_HOUSE op shows the Start operation button only', async () => {
    const mo = buildMo({ status: 'IN_PROGRESS' });
    // PENDING op hasn't recorded any qty yet; the BE shape allows null
    // here even though the fixture's inferred type narrowed to string.
    mo.operations[0] = {
      ...mo.operations[0],
      qty_in: null as unknown as string,
      qty_out: null as unknown as string,
      state: 'PENDING',
    };
    fetchMock.mockImplementation(defaultFetchImpl(mo));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open stitching operation/i }));

    const drawer = await screen.findByRole('dialog', { name: /operation stitching/i });
    expect(within(drawer).getByRole('button', { name: /start operation/i })).toBeInTheDocument();
    // qty-in form not present for PENDING op.
    expect(within(drawer).queryByLabelText(/^qty added$/i)).not.toBeInTheDocument();
  });

  it('A3: IN_PROGRESS IN_HOUSE op shows qty-in / qty-out / complete forms', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo({ status: 'IN_PROGRESS' })));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open stitching operation/i }));

    const drawer = await screen.findByRole('dialog', { name: /operation stitching/i });
    expect(within(drawer).getByLabelText(/^qty added$/i)).toBeInTheDocument();
    expect(within(drawer).getByLabelText(/^qty produced$/i)).toBeInTheDocument();
    // qty_out > 0 in fixture, so Complete operation surfaces too.
    expect(within(drawer).getByRole('button', { name: /complete operation/i })).toBeInTheDocument();
  });

  it('A3: qty-in POSTs delta with idempotency-key', async () => {
    let qtyInPath: string | null = null;
    let qtyInIdem: string | null = null;
    let qtyInBody: Record<string, unknown> | null = null;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.endsWith('/qty-in') && method === 'POST') {
        qtyInPath = u;
        qtyInIdem =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
        qtyInBody = JSON.parse((init?.body as string) ?? '{}');
        return jsonResponse(200, {
          created_at: '2026-05-01T00:00:00Z',
          end_date: null,
          executor: 'IN_HOUSE',
          is_rework_paid: false,
          manufacturing_order_id: MO_ID,
          mo_operation_id: MO_OP_ID,
          operation_master_id: OP_MASTER_ID,
          operation_sequence: 10,
          qty_byproduct: '0.0000',
          qty_in: '105.0000',
          qty_out: '95.0000',
          qty_rejected: '0.0000',
          qty_wastage: '0.0000',
          start_date: '2026-05-01',
          state: 'IN_PROGRESS',
          updated_at: '2026-05-01T00:00:00Z',
          version: 2,
        });
      }
      return defaultFetchImpl(buildMo({ status: 'IN_PROGRESS' }))(url);
    });

    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open stitching operation/i }));

    const drawer = await screen.findByRole('dialog', { name: /operation stitching/i });
    const qtyInput = within(drawer).getByLabelText(/^qty added$/i);
    fireEvent.change(qtyInput, { target: { value: '5' } });
    // The Add button next to qty-in is the first "Add" button in the
    // drawer (qty-out also has one, but in DOM order the qty-in form
    // ships first).
    const addButtons = within(drawer).getAllByRole('button', { name: /^add$/i });
    fireEvent.click(addButtons[0]);

    await waitFor(() => expect(qtyInPath).not.toBeNull());
    expect(qtyInPath).toContain(`/manufacturing/mo-operations/${MO_OP_ID}/qty-in`);
    expect(qtyInIdem).toMatch(/^[0-9a-f-]{36}$/i);
    expect(qtyInBody).toMatchObject({
      firm_id: FIRM_ID,
      qty_in: '5',
    });
  });

  it('A3: conservation indicator warns when projected qty-out exceeds qty-in', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo({ status: 'IN_PROGRESS' })));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open stitching operation/i }));

    const drawer = await screen.findByRole('dialog', { name: /operation stitching/i });
    // qty_in=100, qty_out=95; adding qty_out=10 → projected 105 > 100.
    const qtyOut = within(drawer).getByLabelText(/^qty produced$/i);
    fireEvent.change(qtyOut, { target: { value: '10' } });
    await waitFor(() =>
      expect(within(drawer).getByText(/conservation: total qty-out/i)).toBeInTheDocument(),
    );
  });

  it('A3: KARIGAR op renders A4 placeholder', async () => {
    const mo = buildMo({ status: 'IN_PROGRESS' });
    mo.operations[0] = {
      ...mo.operations[0],
      executor: 'KARIGAR',
      state: 'PENDING',
    };
    fetchMock.mockImplementation(defaultFetchImpl(mo));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open stitching operation/i }));

    const drawer = await screen.findByRole('dialog', { name: /operation stitching/i });
    expect(within(drawer).getByText(/Karigar actions ship in TASK-TR-A4/i)).toBeInTheDocument();
    expect(
      within(drawer).queryByRole('button', { name: /start operation/i }),
    ).not.toBeInTheDocument();
  });

  it('A3: QC op renders A5 placeholder', async () => {
    const mo = buildMo({ status: 'IN_PROGRESS' });
    mo.operations[0] = {
      ...mo.operations[0],
      executor: 'IN_HOUSE',
      state: 'QC_PENDING',
    };
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/operation-masters')) {
        // Operation master returns operation_type=QC so the drawer
        // takes the QC branch.
        return jsonResponse(200, {
          items: [{ ...buildOperationMaster(), operation_type: 'QC' }],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      return defaultFetchImpl(mo)(url);
    });
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open stitching operation/i }));

    const drawer = await screen.findByRole('dialog', { name: /operation stitching/i });
    expect(within(drawer).getByText(/QC actions ship in TASK-TR-A5/i)).toBeInTheDocument();
  });
});
