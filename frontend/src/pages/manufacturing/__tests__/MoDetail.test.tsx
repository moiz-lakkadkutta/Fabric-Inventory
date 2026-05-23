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

  // A4 shipped real KarigarActions (replacing the A3 placeholder). The
  // associated A3 placeholder test is removed because the assertion
  // `Karigar actions ship in TASK-TR-A4` no longer holds. Re-add karigar
  // drawer coverage as a follow-up if the existing KarigarActions code
  // path needs broader vitest coverage.

  // ── A5 QC actions + REWORK chain UI ───────────────────────────────
  //
  // The A5 drawer covers four lifecycle states (PENDING / QC_PENDING /
  // REWORK / CLOSED) and the rework-chain card that walks the
  // `rework_of_mo_operation_id` graph. Each test pins the QC op's state
  // + mocks the relevant endpoints so we don't depend on a real BE.

  const PRED_MO_OP_ID = 'mp000000-0000-0000-0000-000000000002';
  const QC_OP_MASTER_ID = 'op000000-0000-0000-0000-000000000002';
  const CLONE_MO_OP_ID = 'mp000000-0000-0000-0000-000000000003';
  const CLONE_2_MO_OP_ID = 'mp000000-0000-0000-0000-000000000004';

  function buildMoWithQc(opts: {
    status?: 'DRAFT' | 'RELEASED' | 'IN_PROGRESS' | 'COMPLETED' | 'CLOSED';
    qcState: 'PENDING' | 'QC_PENDING' | 'REWORK' | 'CLOSED';
    clones?: Array<{
      mo_operation_id: string;
      rework_of_mo_operation_id: string;
      state: 'PENDING' | 'IN_PROGRESS' | 'CLOSED';
      executor?: 'IN_HOUSE' | 'KARIGAR';
      is_rework_paid?: boolean;
      qty_in?: string | null;
      qty_out?: string | null;
    }>;
  }) {
    const mo = buildMo({ status: opts.status ?? 'IN_PROGRESS' });
    // Predecessor op (the stitching row already in the fixture) — leave
    // sequence 10, qty_out=95 so the conservation check has a known
    // target.
    mo.operations[0] = {
      ...mo.operations[0],
      mo_operation_id: PRED_MO_OP_ID,
      operation_master_id: OP_MASTER_ID,
    };
    // QC op feeding off the stitch.
    mo.operations.push({
      manufacturing_order_id: MO_ID,
      mo_operation_id: MO_OP_ID,
      operation_master_id: QC_OP_MASTER_ID,
      operation_sequence: 20,
      executor: 'IN_HOUSE',
      qty_in: opts.qcState === 'PENDING' ? null : '95.0000',
      qty_out: opts.qcState === 'CLOSED' ? '90.0000' : null,
      state: opts.qcState,
      is_rework_paid: false,
    } as unknown as (typeof mo.operations)[number]);
    for (const c of opts.clones ?? []) {
      mo.operations.push({
        manufacturing_order_id: MO_ID,
        mo_operation_id: c.mo_operation_id,
        operation_master_id: OP_MASTER_ID,
        operation_sequence: null,
        executor: c.executor ?? 'IN_HOUSE',
        qty_in: c.qty_in ?? null,
        qty_out: c.qty_out ?? null,
        state: c.state,
        is_rework_paid: c.is_rework_paid ?? false,
        rework_of_mo_operation_id: c.rework_of_mo_operation_id,
      } as unknown as (typeof mo.operations)[number]);
    }
    return mo;
  }

  function buildQcOperationMaster() {
    return {
      org_id: ORG_ID,
      firm_id: FIRM_ID,
      operation_master_id: QC_OP_MASTER_ID,
      code: 'QC',
      name: 'Quality Check',
      operation_type: 'QC',
      default_duration_mins: null,
      cost_centre_id: null,
      is_active: true,
      created_at: '2026-04-01T00:00:00Z',
      updated_at: '2026-04-01T00:00:00Z',
      deleted_at: null,
    };
  }

  function buildQcResult(opts: {
    recorded?: boolean;
    predecessorQtyOut: string;
    verdict?: 'PASS' | 'REWORK' | null;
    qtyPassed?: string;
    qtyRejected?: string;
    qtyByproduct?: string;
    qtyWastage?: string;
    qtyRework?: string;
    predecessorId?: string;
  }) {
    return {
      mo_operation_id: MO_OP_ID,
      occurred_at: opts.recorded ? '2026-05-01T00:00:00Z' : null,
      predecessor_mo_operation_id: opts.predecessorId ?? PRED_MO_OP_ID,
      predecessor_qty_out: opts.predecessorQtyOut,
      qty_byproduct: opts.qtyByproduct ?? '0.0000',
      qty_passed: opts.qtyPassed ?? '0.0000',
      qty_rejected: opts.qtyRejected ?? '0.0000',
      qty_rework: opts.qtyRework ?? '0.0000',
      qty_wastage: opts.qtyWastage ?? '0.0000',
      recorded: opts.recorded ?? false,
      verdict: opts.verdict ?? null,
    };
  }

  function withQcMasters(
    mo: ReturnType<typeof buildMoWithQc>,
    options: {
      qcResult?: ReturnType<typeof buildQcResult> | null;
      onStartQc?: (init: RequestInit) => void;
      onRecord?: (init: RequestInit) => Response | Promise<Response> | undefined | void;
    } = {},
  ) {
    return async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.includes('/operation-masters')) {
        return jsonResponse(200, {
          items: [buildOperationMaster(), buildQcOperationMaster()],
          count: 2,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/qc-result') && method === 'GET') {
        if (options.qcResult === null) return jsonResponse(404, {});
        return jsonResponse(
          200,
          options.qcResult ?? buildQcResult({ predecessorQtyOut: '95.0000' }),
        );
      }
      if (u.endsWith('/start-qc') && method === 'POST') {
        options.onStartQc?.(init ?? {});
        return jsonResponse(200, {
          created_at: '2026-05-01T00:00:00Z',
          end_date: null,
          executor: 'IN_HOUSE',
          manufacturing_order_id: MO_ID,
          mo_operation_id: MO_OP_ID,
          operation_master_id: QC_OP_MASTER_ID,
          operation_sequence: 20,
          operation_type: 'QC',
          qty_byproduct: '0.0000',
          qty_in: '95.0000',
          qty_out: '0.0000',
          qty_rejected: '0.0000',
          qty_wastage: '0.0000',
          start_date: '2026-05-01',
          state: 'QC_PENDING',
          updated_at: '2026-05-01T00:00:00Z',
          version: 2,
        });
      }
      if (u.endsWith('/record-qc-result') && method === 'POST') {
        const overridden = options.onRecord?.(init ?? {});
        if (overridden) return overridden;
        return jsonResponse(200, {
          created_at: '2026-05-01T00:00:00Z',
          end_date: '2026-05-01',
          executor: 'IN_HOUSE',
          manufacturing_order_id: MO_ID,
          mo_operation_id: MO_OP_ID,
          operation_master_id: QC_OP_MASTER_ID,
          operation_sequence: 20,
          operation_type: 'QC',
          qty_byproduct: '0.0000',
          qty_in: '95.0000',
          qty_out: '95.0000',
          qty_rejected: '0.0000',
          qty_wastage: '0.0000',
          start_date: '2026-05-01',
          state: 'CLOSED',
          updated_at: '2026-05-01T00:00:00Z',
          version: 3,
        });
      }
      return defaultFetchImpl(mo)(url);
    };
  }

  function grantQcWrite() {
    authStore.setMe({
      ...(authStore.get().me as NonNullable<ReturnType<typeof authStore.get>['me']>),
      permissions: [
        'manufacturing.mo.read',
        'manufacturing.mo.write',
        'manufacturing.material_issue.write',
        'manufacturing.operation.progress',
        'manufacturing.qc.write',
        'manufacturing.qc.read',
      ],
    });
  }

  it('A5: PENDING QC op shows "Start QC inspection" button', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({ qcState: 'PENDING' });
    fetchMock.mockImplementation(withQcMasters(mo));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    // Open the QC op row (sequence 20, "Quality Check").
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    expect(
      within(drawer).getByRole('button', { name: /start qc inspection/i }),
    ).toBeInTheDocument();
  });

  it('A5: Start QC POSTs /start-qc with firm_id + idempotency-key', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({ qcState: 'PENDING' });
    let startBody: Record<string, unknown> | null = null;
    let startIdem: string | null = null;
    fetchMock.mockImplementation(
      withQcMasters(mo, {
        onStartQc: (init) => {
          startIdem =
            (init.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
          startBody = JSON.parse((init.body as string) ?? '{}');
        },
      }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    fireEvent.click(within(drawer).getByRole('button', { name: /start qc inspection/i }));
    await waitFor(() => expect(startBody).not.toBeNull());
    expect(startBody).toMatchObject({ firm_id: FIRM_ID });
    expect(startIdem).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it('A5: QC_PENDING op renders 5 bucket inputs with conservation indicator', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({ qcState: 'QC_PENDING' });
    fetchMock.mockImplementation(
      withQcMasters(mo, { qcResult: buildQcResult({ predecessorQtyOut: '95.0000' }) }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    await waitFor(() => expect(within(drawer).getByLabelText(/^passed$/i)).toBeInTheDocument());
    expect(within(drawer).getByLabelText(/^rejected$/i)).toBeInTheDocument();
    expect(within(drawer).getByLabelText(/^by-product$/i)).toBeInTheDocument();
    expect(within(drawer).getByLabelText(/^wastage$/i)).toBeInTheDocument();
    expect(within(drawer).getByLabelText(/^rework$/i)).toBeInTheDocument();
    // Surface the source qty so the operator knows the target.
    const sourceLine = within(drawer).getByText(/source qty arriving/i);
    expect(sourceLine).toBeInTheDocument();
    expect(sourceLine.textContent).toContain('95.0000');
  });

  it('A5: submit is disabled when bucket sum != predecessor qty_out', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({ qcState: 'QC_PENDING' });
    fetchMock.mockImplementation(
      withQcMasters(mo, { qcResult: buildQcResult({ predecessorQtyOut: '95.0000' }) }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    await waitFor(() => expect(within(drawer).getByLabelText(/^passed$/i)).toBeInTheDocument());
    fireEvent.change(within(drawer).getByLabelText(/^passed$/i), { target: { value: '50' } });
    // Sum is 50 != 95 → mismatch indicator + disabled submit.
    const conservation = within(drawer).getByRole('status');
    expect(conservation.getAttribute('data-conservation-state')).toBe('mismatch');
    const submitBtn = within(drawer).getByRole('button', { name: /record verdict/i });
    expect(submitBtn).toBeDisabled();
  });

  it('A5: PASS verdict (rework=0) enables submit when sum == predecessor', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({ qcState: 'QC_PENDING' });
    let recordBody: Record<string, unknown> | null = null;
    let recordIdem: string | null = null;
    fetchMock.mockImplementation(
      withQcMasters(mo, {
        qcResult: buildQcResult({ predecessorQtyOut: '95.0000' }),
        onRecord: (init) => {
          recordIdem =
            (init.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
          recordBody = JSON.parse((init.body as string) ?? '{}');
          return undefined;
        },
      }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    await waitFor(() => expect(within(drawer).getByLabelText(/^passed$/i)).toBeInTheDocument());
    // 90 passed + 3 rejected + 2 wastage = 95 → conservation OK.
    fireEvent.change(within(drawer).getByLabelText(/^passed$/i), { target: { value: '90' } });
    fireEvent.change(within(drawer).getByLabelText(/^rejected$/i), { target: { value: '3' } });
    fireEvent.change(within(drawer).getByLabelText(/^wastage$/i), { target: { value: '2' } });
    const conservation = within(drawer).getByRole('status');
    expect(conservation.getAttribute('data-conservation-state')).toBe('ok');
    const submitBtn = within(drawer).getByRole('button', { name: /record verdict \(pass\)/i });
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);
    await waitFor(() => expect(recordBody).not.toBeNull());
    expect(recordBody).toMatchObject({
      firm_id: FIRM_ID,
      qty_passed: '90',
      qty_rejected: '3',
      qty_byproduct: 0,
      qty_wastage: '2',
      qty_rework: 0,
    });
    expect(recordIdem).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it('A5: REWORK verdict button label flips to "Record verdict (REWORK)" when rework > 0', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({ qcState: 'QC_PENDING' });
    fetchMock.mockImplementation(
      withQcMasters(mo, { qcResult: buildQcResult({ predecessorQtyOut: '95.0000' }) }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    await waitFor(() => expect(within(drawer).getByLabelText(/^passed$/i)).toBeInTheDocument());
    fireEvent.change(within(drawer).getByLabelText(/^passed$/i), { target: { value: '80' } });
    fireEvent.change(within(drawer).getByLabelText(/^rework$/i), { target: { value: '15' } });
    expect(
      within(drawer).getByRole('button', { name: /record verdict \(rework\)/i }),
    ).not.toBeDisabled();
  });

  it('A5: REWORK state + non-CLOSED clone disables verdict form with tooltip', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({
      qcState: 'REWORK',
      clones: [
        {
          mo_operation_id: CLONE_MO_OP_ID,
          rework_of_mo_operation_id: PRED_MO_OP_ID,
          state: 'IN_PROGRESS',
          qty_in: '15.0000',
        },
      ],
    });
    fetchMock.mockImplementation(
      withQcMasters(mo, {
        qcResult: buildQcResult({
          predecessorQtyOut: '95.0000',
          recorded: true,
          verdict: 'REWORK',
          qtyPassed: '80.0000',
          qtyRework: '15.0000',
        }),
      }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    // Two ops with name "Quality Check" would conflict — the parent
    // stitching row is "Stitching" so QC name is unique. Clone shares
    // the parent's master so its row is also "Stitching".
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    await waitFor(() =>
      expect(within(drawer).getByText(/finish the rework operation/i)).toBeInTheDocument(),
    );
    const submitBtn = within(drawer).getByRole('button', { name: /record verdict/i });
    expect(submitBtn).toBeDisabled();
    expect(submitBtn.getAttribute('title')).toMatch(/finish the rework operation/i);
  });

  it('A5: REWORK + CLOSED clone re-enables the verdict form with Round 2 header', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({
      qcState: 'REWORK',
      clones: [
        {
          mo_operation_id: CLONE_MO_OP_ID,
          rework_of_mo_operation_id: PRED_MO_OP_ID,
          state: 'CLOSED',
          qty_in: '15.0000',
          qty_out: '15.0000',
        },
      ],
    });
    fetchMock.mockImplementation(
      withQcMasters(mo, {
        // For a re-record, predecessor_qty_out comes from the CLOSED
        // clone's qty_out (15.0000), per A10-FU.
        qcResult: buildQcResult({
          predecessorQtyOut: '15.0000',
          recorded: true,
          verdict: 'REWORK',
        }),
      }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    await waitFor(() => expect(within(drawer).getByText(/round 2 verdict/i)).toBeInTheDocument());
    // Form inputs are enabled now.
    const passed = within(drawer).getByLabelText(/^passed$/i) as HTMLInputElement;
    expect(passed.disabled).toBe(false);
  });

  it('A5: rework chain card walks multiple rounds', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({
      qcState: 'REWORK',
      clones: [
        {
          mo_operation_id: CLONE_MO_OP_ID,
          rework_of_mo_operation_id: PRED_MO_OP_ID,
          state: 'CLOSED',
          is_rework_paid: false,
          qty_in: '15.0000',
          qty_out: '15.0000',
        },
        {
          mo_operation_id: CLONE_2_MO_OP_ID,
          rework_of_mo_operation_id: CLONE_MO_OP_ID,
          state: 'IN_PROGRESS',
          is_rework_paid: true,
          qty_in: '5.0000',
        },
      ],
    });
    fetchMock.mockImplementation(
      withQcMasters(mo, {
        qcResult: buildQcResult({ predecessorQtyOut: '15.0000', verdict: 'REWORK' }),
      }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    await waitFor(() => expect(within(drawer).getByText(/rework chain/i)).toBeInTheDocument());
    expect(within(drawer).getByText(/2 rounds/i)).toBeInTheDocument();
    expect(within(drawer).getByText(/round 1/i)).toBeInTheDocument();
    expect(within(drawer).getByText(/round 2/i)).toBeInTheDocument();
    // Both rounds have "View op →" navigation.
    const viewLinks = within(drawer).getAllByRole('button', { name: /view round \d+ operation/i });
    expect(viewLinks).toHaveLength(2);
    // Round 1 is free rework, round 2 is billable.
    expect(within(drawer).getByText(/free rework/i)).toBeInTheDocument();
    expect(within(drawer).getByText(/billable rework/i)).toBeInTheDocument();
  });

  it('A5: clicking "View op →" swaps the drawer to the clone op', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({
      qcState: 'REWORK',
      clones: [
        {
          mo_operation_id: CLONE_MO_OP_ID,
          rework_of_mo_operation_id: PRED_MO_OP_ID,
          state: 'IN_PROGRESS',
          qty_in: '15.0000',
        },
      ],
    });
    fetchMock.mockImplementation(
      withQcMasters(mo, {
        qcResult: buildQcResult({ predecessorQtyOut: '95.0000', verdict: 'REWORK' }),
      }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    const viewLink = await within(drawer).findByRole('button', {
      name: /view round 1 operation/i,
    });
    fireEvent.click(viewLink);
    // Drawer aria-label flips to the clone op's name. The clone shares
    // the original op_master (Stitching) so the dialog name changes.
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /operation stitching/i })).toBeInTheDocument(),
    );
  });

  it('A5: CLOSED QC op shows the verdict summary (no editable form)', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({ qcState: 'CLOSED' });
    fetchMock.mockImplementation(
      withQcMasters(mo, {
        qcResult: buildQcResult({
          predecessorQtyOut: '95.0000',
          recorded: true,
          verdict: 'PASS',
          qtyPassed: '90.0000',
          qtyRejected: '3.0000',
          qtyWastage: '2.0000',
        }),
      }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    await waitFor(() => expect(within(drawer).getByText(/^PASS$/)).toBeInTheDocument());
    expect(within(drawer).queryByLabelText(/^passed$/i)).not.toBeInTheDocument();
    expect(
      within(drawer).queryByRole('button', { name: /record verdict/i }),
    ).not.toBeInTheDocument();
  });

  it('A5: salesperson without manufacturing.qc.write sees disabled Start QC', async () => {
    // Default beforeEach permissions DON'T include qc.write.
    const mo = buildMoWithQc({ qcState: 'PENDING' });
    fetchMock.mockImplementation(withQcMasters(mo));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open quality check operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation quality check/i });
    const startBtn = within(drawer).getByRole('button', { name: /start qc inspection/i });
    expect(startBtn).toBeDisabled();
    expect(startBtn.getAttribute('title')).toMatch(/permission/i);
  });

  it('A5: IN_HOUSE non-QC op does NOT render the QC section (regression)', async () => {
    // Same as the A3 IN_PROGRESS test, but explicitly assert the QC
    // form's "Passed" input is absent so we don't regress on the
    // operation_type routing.
    fetchMock.mockImplementation(defaultFetchImpl(buildMo({ status: 'IN_PROGRESS' })));
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /open stitching operation/i }));
    const drawer = await screen.findByRole('dialog', { name: /operation stitching/i });
    expect(within(drawer).queryByLabelText(/^passed$/i)).not.toBeInTheDocument();
    expect(within(drawer).queryByText(/source qty arriving/i)).not.toBeInTheDocument();
  });

  it('A5: clones appear inline in the Operations table beneath their parent', async () => {
    grantQcWrite();
    const mo = buildMoWithQc({
      qcState: 'REWORK',
      clones: [
        {
          mo_operation_id: CLONE_MO_OP_ID,
          rework_of_mo_operation_id: PRED_MO_OP_ID,
          state: 'IN_PROGRESS',
          is_rework_paid: false,
          qty_in: '15.0000',
        },
      ],
    });
    fetchMock.mockImplementation(
      withQcMasters(mo, {
        qcResult: buildQcResult({ predecessorQtyOut: '95.0000', verdict: 'REWORK' }),
      }),
    );
    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    // Indented clone row carries the "Rework of #10" label.
    expect(await screen.findByText(/rework of #10/i)).toBeInTheDocument();
    // And the "Free rework" pill renders on its executor cell.
    expect(screen.getByText(/free rework/i)).toBeInTheDocument();
  });
});
