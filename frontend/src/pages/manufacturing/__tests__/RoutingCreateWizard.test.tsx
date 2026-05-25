/*
 * RoutingCreateWizard — TASK-TR-E1-ROUTINGS integration tests.
 *
 * Mocks IS_LIVE + globalThis.fetch (same pattern as MoCreateWizard.test
 * + MoList.test) so the live branch wins tree-shaking.
 *
 * Coverage:
 *   - Renders the 3 tabs + the editorial/dense variant toggle.
 *   - Tab A picks a design and the chrome shows v{N}.
 *   - Cycle detection inline blocks the activate button.
 *   - Switching editorial ↔ dense preserves nodes + edges (no data loss).
 *   - Activate POSTs /routings with the wire payload + Idempotency-Key.
 *   - BE 422 detail (cycle / unreachable) surfaces verbatim.
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
const { default: RoutingCreateWizard } = await import('@/pages/manufacturing/RoutingCreateWizard');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const DESIGN_ID = 'd0000000-0000-0000-0000-000000000001';
const NEW_ROUTING_ID = 'r0000000-0000-0000-0000-0000000000aa';
const OP_CUT = 'op000000-0000-0000-0000-000000000001';
const OP_STITCH = 'op000000-0000-0000-0000-000000000002';
const OP_QC = 'op000000-0000-0000-0000-000000000003';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildDesignList() {
  return {
    items: [
      {
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        design_id: DESIGN_ID,
        code: 'DSN-LHG-MRN',
        name: 'Lehenga Maroon',
        description: null,
        cost_centre_id: null,
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

function buildOpMasters() {
  return {
    items: [
      {
        operation_master_id: OP_CUT,
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        code: 'CUT',
        name: 'Cutting',
        operation_type: 'STITCHING',
        default_duration_mins: null,
        cost_centre_id: null,
        is_active: true,
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
      },
      {
        operation_master_id: OP_STITCH,
        org_id: ORG_ID,
        firm_id: FIRM_ID,
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
      {
        operation_master_id: OP_QC,
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        code: 'QC',
        name: 'QC',
        operation_type: 'QC',
        default_duration_mins: null,
        cost_centre_id: null,
        is_active: true,
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
      },
    ],
    count: 3,
    limit: 200,
    offset: 0,
    total_count: 3,
  };
}

function buildRoutingResponse() {
  return {
    routing_id: NEW_ROUTING_ID,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: DESIGN_ID,
    code: 'RTG-DSN-LHG-MRN',
    version_number: 1,
    is_active: true,
    created_at: '2026-05-23T00:00:00Z',
    updated_at: '2026-05-23T00:00:00Z',
    deleted_at: null,
    edges: [],
  };
}

interface BuildOptions {
  /** Override the POST /routings response. */
  postResponse?: (init: RequestInit | undefined) => Response | Promise<Response>;
  /** Existing routings for the design (for clone-graph testing). */
  existingRoutings?: ReturnType<typeof buildRoutingResponse>[];
}

function buildFetchImpl(opts: BuildOptions = {}) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const impl = async (url: RequestInfo, init?: RequestInit) => {
    const u = String(url);
    calls.push({ url: u, init });
    if (u.includes('/designs')) return jsonResponse(200, buildDesignList());
    if (u.includes('/operation-masters')) return jsonResponse(200, buildOpMasters());
    if (u.endsWith('/routings') && init?.method === 'POST') {
      if (opts.postResponse) return opts.postResponse(init);
      return jsonResponse(201, buildRoutingResponse());
    }
    // GET /routings?design_id=... — only return rows if the test
    // explicitly requested them (otherwise it's a fresh design).
    if (u.includes('/routings?') && (!init || init.method === 'GET' || !init.method)) {
      return jsonResponse(200, {
        items: opts.existingRoutings ?? [],
        count: opts.existingRoutings?.length ?? 0,
        total_count: opts.existingRoutings?.length ?? 0,
        limit: 50,
        offset: 0,
      });
    }
    // GET /routings/{id} after activate — returns the routing
    if (u.match(/\/routings\/[a-f0-9-]+$/)) {
      return jsonResponse(200, buildRoutingResponse());
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
      <MemoryRouter initialEntries={['/manufacturing/routings/new']}>
        <Routes>
          <Route path="/manufacturing/routings/new" element={<RoutingCreateWizard />} />
          <Route path="/manufacturing/routings" element={<div>LIST_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let originalFetch: typeof fetch;
let fetchMock: ReturnType<typeof vi.fn>;

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
    permissions: ['manufacturing.routing.read', 'manufacturing.routing.write'],
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

describe('RoutingCreateWizard — chrome', () => {
  it('renders all 3 tabs + the editorial/dense toggle', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();
    expect(await screen.findByRole('tab', { name: /design & version/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /operations/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /review & activate/i })).toBeInTheDocument();
  });

  it('picking a design surfaces v1 in the header chrome', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();
    await screen.findByRole('tab', { name: /design & version/i });
    const designSelect = await screen.findByLabelText(/^design$/i);
    fireEvent.change(designSelect, { target: { value: DESIGN_ID } });
    await waitFor(() => expect(screen.getByText(/Lehenga Maroon · v1/i)).toBeInTheDocument());
  });
});

describe('RoutingCreateWizard — operations tab', () => {
  it('switches editorial ↔ dense without data loss', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();
    await screen.findByRole('tab', { name: /design & version/i });
    const designSelect = await screen.findByLabelText(/^design$/i);
    fireEvent.change(designSelect, { target: { value: DESIGN_ID } });
    fireEvent.click(screen.getByRole('tab', { name: /operations/i }));

    // Default = editorial canvas.
    await waitFor(() => expect(screen.getByTestId('routing-dag-editor')).toBeInTheDocument());
    // Add three nodes from the rail.
    fireEvent.click(screen.getByRole('button', { name: /add cutting to canvas/i }));
    fireEvent.click(screen.getByRole('button', { name: /add stitching to canvas/i }));
    fireEvent.click(screen.getByRole('button', { name: /add qc to canvas/i }));

    // Flip to dense view — the sequence editor renders 3 rows.
    fireEvent.click(screen.getByRole('radio', { name: /sequence view/i }));
    await waitFor(() => expect(screen.getByTestId('routing-sequence-editor')).toBeInTheDocument());
    expect(screen.getAllByText('Cutting').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Stitching').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^QC$/i).length).toBeGreaterThan(0);

    // Flip back to canvas — DAG editor still shows the 3 nodes.
    fireEvent.click(screen.getByRole('radio', { name: /canvas view/i }));
    await waitFor(() => expect(screen.getByTestId('routing-dag-editor')).toBeInTheDocument());
    // Three nodes mean three "Remove ..." buttons.
    expect(screen.getByRole('button', { name: /remove cutting/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove stitching/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^remove qc$/i })).toBeInTheDocument();
  });

  it('cycle detection blocks the Activate button on the review tab', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();
    await screen.findByRole('tab', { name: /design & version/i });
    const designSelect = await screen.findByLabelText(/^design$/i);
    fireEvent.change(designSelect, { target: { value: DESIGN_ID } });
    fireEvent.click(screen.getByRole('tab', { name: /operations/i }));
    await waitFor(() => expect(screen.getByTestId('routing-dag-editor')).toBeInTheDocument());

    // Two nodes + edges both ways = 2-cycle.
    fireEvent.click(screen.getByRole('button', { name: /add cutting to canvas/i }));
    fireEvent.click(screen.getByRole('button', { name: /add stitching to canvas/i }));
    fireEvent.click(screen.getByRole('button', { name: /start edge from cutting/i }));
    fireEvent.click(screen.getByRole('button', { name: /connect edge to stitching/i }));
    fireEvent.click(screen.getByRole('button', { name: /start edge from stitching/i }));
    fireEvent.click(screen.getByRole('button', { name: /connect edge to cutting/i }));

    expect(screen.getByTestId('cycle-status').getAttribute('data-cycle')).toBe('true');

    fireEvent.click(screen.getByRole('tab', { name: /review & activate/i }));
    const activate = await screen.findByRole('button', { name: /activate routing/i });
    expect(activate).toBeDisabled();
  });
});

describe('RoutingCreateWizard — submit', () => {
  it('POSTs /routings with the wire payload + Idempotency-Key on Activate', async () => {
    const { impl, calls } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();
    await screen.findByRole('tab', { name: /design & version/i });
    const designSelect = await screen.findByLabelText(/^design$/i);
    fireEvent.change(designSelect, { target: { value: DESIGN_ID } });
    fireEvent.click(screen.getByRole('tab', { name: /operations/i }));
    await waitFor(() => expect(screen.getByTestId('routing-dag-editor')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /add cutting to canvas/i }));
    fireEvent.click(screen.getByRole('button', { name: /add stitching to canvas/i }));
    fireEvent.click(screen.getByRole('button', { name: /start edge from cutting/i }));
    fireEvent.click(screen.getByRole('button', { name: /connect edge to stitching/i }));

    fireEvent.click(screen.getByRole('tab', { name: /review & activate/i }));
    const activate = await screen.findByRole('button', { name: /activate routing/i });
    await waitFor(() => expect(activate).not.toBeDisabled());
    fireEvent.click(activate);

    await waitFor(() => expect(screen.getByText('LIST_REACHED')).toBeInTheDocument());

    const post = calls.find((c) => c.url.endsWith('/routings') && c.init?.method === 'POST');
    expect(post).toBeTruthy();
    const headers = (post!.init!.headers as Record<string, string>) ?? {};
    expect(headers['Idempotency-Key']).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
    const body = JSON.parse(post!.init!.body as string);
    expect(body.firm_id).toBe(FIRM_ID);
    expect(body.design_id).toBe(DESIGN_ID);
    expect(body.code).toMatch(/^RTG-/);
    expect(body.edges).toHaveLength(1);
    expect(body.edges[0].from_operation_id).toBe(OP_CUT);
    expect(body.edges[0].to_operation_id).toBe(OP_STITCH);
    expect(body.edges[0].edge_type).toBe('FINISH_TO_START');
  });

  it('surfaces a BE 422 detail verbatim and stays on the wizard', async () => {
    const { impl } = buildFetchImpl({
      postResponse: () =>
        jsonResponse(422, {
          code: 'VALIDATION_ERROR',
          title: 'Routing validation failed',
          detail: 'Routing edges form a cycle',
          status: 422,
          field_errors: { edges: ['Routing edges form a cycle'] },
        }),
    });
    fetchMock.mockImplementation(impl);
    renderWizard();
    await screen.findByRole('tab', { name: /design & version/i });
    const designSelect = await screen.findByLabelText(/^design$/i);
    fireEvent.change(designSelect, { target: { value: DESIGN_ID } });
    fireEvent.click(screen.getByRole('tab', { name: /operations/i }));
    await waitFor(() => expect(screen.getByTestId('routing-dag-editor')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /add cutting to canvas/i }));
    fireEvent.click(screen.getByRole('button', { name: /add stitching to canvas/i }));
    fireEvent.click(screen.getByRole('button', { name: /start edge from cutting/i }));
    fireEvent.click(screen.getByRole('button', { name: /connect edge to stitching/i }));

    fireEvent.click(screen.getByRole('tab', { name: /review & activate/i }));
    const activate = await screen.findByRole('button', { name: /activate routing/i });
    fireEvent.click(activate);

    await waitFor(() =>
      expect(screen.getByText(/Routing edges form a cycle/i)).toBeInTheDocument(),
    );
    // Still on the wizard.
    expect(screen.queryByText('LIST_REACHED')).not.toBeInTheDocument();
  });
});
