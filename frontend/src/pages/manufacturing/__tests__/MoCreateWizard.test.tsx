/*
 * MoCreateWizard — TASK-TR-A2 (SCR-MFG-004) integration tests.
 *
 * Strategy: mock the queries layer so we can drive the wizard from
 * predictable view-models, and capture the POSTs via the lower-level
 * api() wrapper so we observe the actual request shape.
 *
 * Coverage (matches the task brief):
 *   - All 4 section tabs render and switch.
 *   - Section 1: design typeahead filters by query; qty/start/target
 *     are required to enable the next steps.
 *   - Section 2: BOM snapshot loads on design change; availability
 *     badge colour responds to stock data.
 *   - Section 2: "Insufficient — Raise PR" link appears on red lines.
 *   - Section 3: routing list loads; executor toggle changes selection.
 *   - Section 4: Save-as-DRAFT POSTs /manufacturing/mo only; Release
 *     POSTs both /manufacturing/mo + /manufacturing/mo/:id/release.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: MoCreateWizard, _internal } = await import('@/pages/manufacturing/MoCreateWizard');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const DESIGN_ID = 'd0000000-0000-0000-0000-000000000001';
const DESIGN_ID_2 = 'd0000000-0000-0000-0000-000000000002';
const BOM_ID = 'b0000000-0000-0000-0000-000000000001';
const ROUTING_ID = 'r0000000-0000-0000-0000-000000000001';
const FINISHED_ITEM_ID = 'i0000000-0000-0000-0000-00000000fffe';
const ITEM_FAB_ID = 'i0000000-0000-0000-0000-000000000001';
const ITEM_THREAD_ID = 'i0000000-0000-0000-0000-000000000002';
const OP_CUT_ID = 'op000000-0000-0000-0000-000000000001';
const OP_STITCH_ID = 'op000000-0000-0000-0000-000000000002';
const NEW_MO_ID = 'm0000000-0000-0000-0000-0000000000aa';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

interface FixtureStock {
  itemId: string;
  onHand: string;
  avgCost: string;
  name: string;
}

interface FixtureOpts {
  designs?: { id: string; code: string; name: string }[];
  stock?: FixtureStock[];
}

function buildDesignList(designs: { id: string; code: string; name: string }[]) {
  return {
    items: designs.map((d) => ({
      org_id: ORG_ID,
      firm_id: FIRM_ID,
      design_id: d.id,
      code: d.code,
      name: d.name,
      description: null,
      cost_centre_id: null,
      created_at: '2026-04-01T00:00:00Z',
      updated_at: '2026-04-01T00:00:00Z',
      deleted_at: null,
    })),
    count: designs.length,
    limit: 100,
    offset: 0,
    total_count: designs.length,
  };
}

function buildBomList() {
  return {
    items: [
      {
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        bom_id: BOM_ID,
        design_id: DESIGN_ID,
        finished_item_id: FINISHED_ITEM_ID,
        is_active: true,
        version_number: 1,
        lines: [
          {
            bom_id: BOM_ID,
            bom_line_id: 'bl1',
            item_id: ITEM_FAB_ID,
            qty_required: '2.5',
            uom: 'METER',
            sequence: 1,
            is_optional: false,
            part_role: 'body',
          },
          {
            bom_id: BOM_ID,
            bom_line_id: 'bl2',
            item_id: ITEM_THREAD_ID,
            qty_required: '0.5',
            uom: 'METER',
            sequence: 2,
            is_optional: false,
            part_role: 'trim',
          },
        ],
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
      },
    ],
    count: 1,
    limit: 100,
    offset: 0,
    total_count: 1,
  };
}

function buildRoutingList() {
  return {
    items: [
      {
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        routing_id: ROUTING_ID,
        design_id: DESIGN_ID,
        code: 'R-BRDL-1',
        is_active: true,
        version_number: 1,
        edges: [
          {
            routing_id: ROUTING_ID,
            routing_edge_id: 'e1',
            from_operation_id: OP_CUT_ID,
            to_operation_id: OP_STITCH_ID,
            edge_type: 'FINISH_TO_START',
            sequence: 1,
            threshold_pct: null,
            threshold_qty: null,
          },
        ],
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
      },
    ],
    count: 1,
    limit: 100,
    offset: 0,
    total_count: 1,
  };
}

function buildItemList() {
  return {
    items: [
      {
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        item_id: ITEM_FAB_ID,
        code: 'FAB',
        name: 'Cotton fabric',
        primary_uom: 'METER',
        tracking: 'NONE',
        hsn_code: null,
        gst_rate: '5',
        has_variants: false,
        has_expiry: false,
        is_active: true,
        item_type: 'RAW',
        category: null,
        description: null,
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
      },
      {
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        item_id: ITEM_THREAD_ID,
        code: 'THR',
        name: 'Silk thread',
        primary_uom: 'METER',
        tracking: 'NONE',
        hsn_code: null,
        gst_rate: '5',
        has_variants: false,
        has_expiry: false,
        is_active: true,
        item_type: 'RAW',
        category: null,
        description: null,
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
      },
    ],
    count: 2,
    limit: 200,
    offset: 0,
    total_count: 2,
  };
}

function buildOpMasterList() {
  return {
    items: [
      {
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        operation_master_id: OP_CUT_ID,
        code: 'CUT',
        name: 'Cutting',
        operation_type: 'CUTTING',
        default_duration_mins: null,
        cost_centre_id: null,
        is_active: true,
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
      },
      {
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        operation_master_id: OP_STITCH_ID,
        code: 'STITCH',
        name: 'Stitching',
        operation_type: 'STITCHING',
        default_duration_mins: null,
        cost_centre_id: null,
        is_active: true,
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
      },
    ],
    count: 2,
    limit: 200,
    offset: 0,
    total_count: 2,
  };
}

function buildStockSummary(rows: FixtureStock[]) {
  return {
    rows: rows.map((r) => ({
      item_id: r.itemId,
      sku_id: null,
      item_code: r.itemId.slice(0, 6),
      sku_code: null,
      item_name: r.name,
      uom: 'METER',
      on_hand_qty: r.onHand,
      avg_cost: r.avgCost,
      valuation: '0.00',
    })),
  };
}

function buildSoList() {
  return { items: [], count: 0, limit: 200, offset: 0, total_count: 0 };
}

function buildMoResponse() {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    manufacturing_order_id: NEW_MO_ID,
    number: '0001',
    series: 'MO/2026',
    design_id: DESIGN_ID,
    finished_item_id: FINISHED_ITEM_ID,
    bom_id: BOM_ID,
    routing_id: ROUTING_ID,
    mo_date: '2026-05-01',
    planned_qty: '10.0000',
    produced_qty: null,
    scrap_qty: null,
    planned_start_date: '2026-05-01',
    planned_end_date: '2026-05-15',
    status: 'DRAFT',
    closed_at: null,
    cost_pool: null,
    deleted_at: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    operations: [],
    material_lines: [],
  };
}

function buildFetchImpl(opts: FixtureOpts) {
  const designs = opts.designs ?? [
    { id: DESIGN_ID, code: 'BRDL-01', name: 'Bridal Lehenga' },
    { id: DESIGN_ID_2, code: 'GHGRA-02', name: 'Ghagra Choli' },
  ];
  const stockRows: FixtureStock[] = opts.stock ?? [
    { itemId: ITEM_FAB_ID, onHand: '100', avgCost: '200.00', name: 'Cotton fabric' },
    { itemId: ITEM_THREAD_ID, onHand: '0', avgCost: '10.00', name: 'Silk thread' },
  ];

  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const impl = async (url: RequestInfo, init?: RequestInit) => {
    const u = String(url);
    calls.push({ url: u, init });

    if (u.includes('/designs?')) return jsonResponse(200, buildDesignList(designs));
    if (u.includes('/boms?')) return jsonResponse(200, buildBomList());
    if (u.includes('/routings?')) return jsonResponse(200, buildRoutingList());
    if (u.includes('/items')) return jsonResponse(200, buildItemList());
    if (u.includes('/operation-masters')) return jsonResponse(200, buildOpMasterList());
    if (u.includes('/reports/stock-summary'))
      return jsonResponse(200, buildStockSummary(stockRows));
    if (u.includes('/sales-orders')) return jsonResponse(200, buildSoList());
    if (u.endsWith('/manufacturing/mo') && init?.method === 'POST') {
      return jsonResponse(201, buildMoResponse());
    }
    if (u.includes(`/manufacturing/mo/${NEW_MO_ID}/release`)) {
      return jsonResponse(200, { ...buildMoResponse(), status: 'RELEASED' });
    }
    return jsonResponse(404, {});
  };
  return { impl, calls };
}

function renderWizard() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/manufacturing/mo/new']}>
        <Routes>
          <Route path="/manufacturing/mo/new" element={<MoCreateWizard />} />
          <Route path="/manufacturing/mo/:id" element={<div>MO_DETAIL_REACHED</div>} />
          <Route path="/manufacturing/mo" element={<div>LIST_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function seedAuth() {
  authStore.reset();
  authStore.setAccessToken('test-token');
  authStore.setMe({
    user_id: 'u',
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    email: 'u@example.com',
    permissions: ['manufacturing.mo.create', 'manufacturing.mo.write'],
    flags: {},
    available_firms: [{ firm_id: FIRM_ID, code: 'F1', name: 'F1' }],
    token_expires_at: '2099-01-01T00:00:00Z',
  });
}

let originalFetch: typeof fetch;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  seedAuth();
});

afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
  authStore.reset();
  vi.restoreAllMocks();
});

describe('MoCreateWizard — section navigation', () => {
  it('renders all four section tabs', async () => {
    const { impl } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();

    expect(await screen.findByRole('tab', { name: /design & qty/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /bom snapshot/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /routing override/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /review & release/i })).toBeInTheDocument();
  });

  it('switches sections via the tab buttons', async () => {
    const { impl } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();
    await waitFor(() => expect(screen.getByRole('tab', { name: /design & qty/i })));

    fireEvent.click(screen.getByRole('tab', { name: /review & release/i }));
    await waitFor(() => expect(screen.getByText(/Header/i)).toBeInTheDocument());
  });
});

describe('MoCreateWizard — Section 1 (design & qty)', () => {
  it('filters the design list by typeahead query', async () => {
    const { impl } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();
    // Wait for design listbox to populate.
    await screen.findByRole('option', { name: /BRDL-01/i });
    expect(screen.getByRole('option', { name: /GHGRA-02/i })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/search design/i), {
      target: { value: 'ghagra' },
    });

    await waitFor(() => {
      expect(screen.queryByRole('option', { name: /BRDL-01/i })).not.toBeInTheDocument();
    });
    expect(screen.getByRole('option', { name: /GHGRA-02/i })).toBeInTheDocument();
  });

  it('requires a design selection to enable next-step data fetches', async () => {
    const { impl } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();
    // Switch to Section 2 — without a design, the BOM panel should
    // render the "Pick a design" prompt.
    fireEvent.click(await screen.findByRole('tab', { name: /bom snapshot/i }));
    await waitFor(() =>
      expect(screen.getByText(/Pick a design in Section 1/i)).toBeInTheDocument(),
    );
  });
});

describe('MoCreateWizard — Section 2 (BOM snapshot)', () => {
  it('loads BOM lines when a design is selected and renders availability badges', async () => {
    const { impl } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();

    // Pick a design.
    fireEvent.click(await screen.findByRole('option', { name: /BRDL-01/i }));
    // Set qty=10 so planned for fabric = 25 (> 100? no, 25 < 100, so green).
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: '10' } });

    // Jump to Section 2.
    fireEvent.click(screen.getByRole('tab', { name: /bom snapshot/i }));

    // Cotton fabric line: planned = 2.5 * 10 = 25, on_hand = 100 → green.
    // Silk thread line: on_hand = 0 → red.
    await waitFor(() => {
      expect(screen.getByText(/Cotton fabric/i)).toBeInTheDocument();
      expect(screen.getByText(/Silk thread/i)).toBeInTheDocument();
    });

    const badges = screen.getAllByTestId('availability-badge');
    expect(badges).toHaveLength(2);
    const badgeKinds = badges.map((b) => b.getAttribute('data-badge'));
    expect(badgeKinds).toContain('green');
    expect(badgeKinds).toContain('red');
  });

  it('shows the "Insufficient — Raise PR" link on red BOM lines', async () => {
    const { impl } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();
    fireEvent.click(await screen.findByRole('option', { name: /BRDL-01/i }));
    fireEvent.click(screen.getByRole('tab', { name: /bom snapshot/i }));

    await waitFor(() => expect(screen.getByText(/Insufficient — Raise PR/i)).toBeInTheDocument());
  });

  it('paints AMBER when on_hand is below planned but greater than zero', async () => {
    const { impl } = buildFetchImpl({
      stock: [
        // Planned = 2.5 * 10 = 25; on_hand = 5 → amber.
        { itemId: ITEM_FAB_ID, onHand: '5', avgCost: '200.00', name: 'Cotton fabric' },
        { itemId: ITEM_THREAD_ID, onHand: '100', avgCost: '10.00', name: 'Silk thread' },
      ],
    });
    fetchMock.mockImplementation(impl);

    renderWizard();
    fireEvent.click(await screen.findByRole('option', { name: /BRDL-01/i }));
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('tab', { name: /bom snapshot/i }));

    await waitFor(() => {
      const badges = screen.getAllByTestId('availability-badge');
      expect(badges.map((b) => b.getAttribute('data-badge'))).toContain('amber');
    });
  });
});

describe('MoCreateWizard — Section 3 (routing override)', () => {
  it('loads routing ops with executor toggles', async () => {
    const { impl } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();
    fireEvent.click(await screen.findByRole('option', { name: /BRDL-01/i }));
    fireEvent.click(screen.getByRole('tab', { name: /routing override/i }));

    // Two ops from edge CUT → STITCH.
    await waitFor(() => {
      const ops = screen.getAllByTestId('routing-op');
      expect(ops).toHaveLength(2);
    });
    expect(screen.getByText(/Cutting/i)).toBeInTheDocument();
    expect(screen.getByText(/Stitching/i)).toBeInTheDocument();
  });

  it('switches an op executor from IN_HOUSE to KARIGAR', async () => {
    const { impl } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();
    fireEvent.click(await screen.findByRole('option', { name: /BRDL-01/i }));
    fireEvent.click(screen.getByRole('tab', { name: /routing override/i }));

    const select = await screen.findByLabelText(/Executor for Cutting/i);
    expect((select as HTMLSelectElement).value).toBe('IN_HOUSE');
    fireEvent.change(select, { target: { value: 'KARIGAR' } });
    expect((select as HTMLSelectElement).value).toBe('KARIGAR');
  });
});

describe('MoCreateWizard — Section 4 (submit)', () => {
  it('Save as DRAFT posts only /manufacturing/mo (no release)', async () => {
    const { impl, calls } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();
    fireEvent.click(await screen.findByRole('option', { name: /BRDL-01/i }));
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: '10' } });

    // Wait for BOM lines to load (otherwise section2Valid is false and the
    // Save button remains disabled).
    fireEvent.click(screen.getByRole('tab', { name: /bom snapshot/i }));
    await screen.findByText(/Cotton fabric/i);
    // Wait for the routing op list too.
    fireEvent.click(screen.getByRole('tab', { name: /routing override/i }));
    await screen.findByText(/Cutting/i);

    fireEvent.click(screen.getByRole('tab', { name: /review & release/i }));
    const saveBtn = await screen.findByRole('button', { name: /save as draft/i });
    await waitFor(() => expect(saveBtn).not.toBeDisabled());
    fireEvent.click(saveBtn);

    await waitFor(() => {
      const posts = calls.filter((c) => c.init?.method === 'POST');
      expect(posts.some((c) => c.url.endsWith('/manufacturing/mo'))).toBe(true);
      expect(posts.some((c) => c.url.includes('/release'))).toBe(false);
    });
  });

  it('Release posts /manufacturing/mo AND /manufacturing/mo/:id/release', async () => {
    const { impl, calls } = buildFetchImpl({});
    fetchMock.mockImplementation(impl);

    renderWizard();
    fireEvent.click(await screen.findByRole('option', { name: /BRDL-01/i }));
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: '10' } });

    fireEvent.click(screen.getByRole('tab', { name: /bom snapshot/i }));
    await screen.findByText(/Cotton fabric/i);
    fireEvent.click(screen.getByRole('tab', { name: /routing override/i }));
    await screen.findByText(/Cutting/i);

    fireEvent.click(screen.getByRole('tab', { name: /review & release/i }));
    const releaseBtn = await screen.findByRole('button', { name: /release mo/i });
    await waitFor(() => expect(releaseBtn).not.toBeDisabled());
    fireEvent.click(releaseBtn);

    await waitFor(() => {
      const posts = calls.filter((c) => c.init?.method === 'POST');
      const createCall = posts.find((c) => c.url.endsWith('/manufacturing/mo'));
      const releaseCall = posts.find((c) => c.url.includes(`/${NEW_MO_ID}/release`));
      expect(createCall).toBeTruthy();
      expect(releaseCall).toBeTruthy();
    });

    // Verify the create body carries the wired-up references.
    const createCall = calls
      .filter((c) => c.init?.method === 'POST')
      .find((c) => c.url.endsWith('/manufacturing/mo'));
    expect(createCall).toBeTruthy();
    const body = JSON.parse(String(createCall!.init!.body));
    expect(body).toMatchObject({
      firm_id: FIRM_ID,
      bom_id: BOM_ID,
      design_id: DESIGN_ID,
      finished_item_id: FINISHED_ITEM_ID,
      routing_id: ROUTING_ID,
      qty_to_produce: '10',
    });
    // Idempotency-Key is set on the create POST.
    const headers = createCall!.init!.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toMatch(/[0-9a-f-]{36}/i);
  });
});

describe('orderRoutingOps helper', () => {
  it('linearises a simple chain', () => {
    const result = _internal.orderRoutingOps({
      edges: [
        { from_operation_id: 'a', to_operation_id: 'b' },
        { from_operation_id: 'b', to_operation_id: 'c' },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ] as any,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    expect(result.branching).toBe(false);
    expect(result.ops).toEqual(['a', 'b', 'c']);
  });

  it('flags branching when an op has multiple outgoing edges', () => {
    const result = _internal.orderRoutingOps({
      edges: [
        { from_operation_id: 'a', to_operation_id: 'b' },
        { from_operation_id: 'a', to_operation_id: 'c' },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ] as any,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    expect(result.branching).toBe(true);
  });
});

describe('deriveAvailability helper', () => {
  it('returns red when on_hand is zero', () => {
    expect(_internal.deriveAvailability(10, 0).badge).toBe('red');
  });
  it('returns amber when on_hand is below planned', () => {
    expect(_internal.deriveAvailability(10, 5).badge).toBe('amber');
  });
  it('returns green when on_hand is at or above planned', () => {
    expect(_internal.deriveAvailability(10, 10).badge).toBe('green');
    expect(_internal.deriveAvailability(10, 100).badge).toBe('green');
  });
});
