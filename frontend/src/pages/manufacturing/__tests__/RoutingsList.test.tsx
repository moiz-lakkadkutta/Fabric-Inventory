/*
 * RoutingsList — TASK-TR-E1-ROUTINGS live-mode integration tests.
 *
 * Pattern follows MoList.test.tsx: pin IS_LIVE before importing the
 * page, then drive everything via a mocked globalThis.fetch.
 *
 * Coverage (the 5 list states + interactions):
 *   1. Full list — rows grouped by design, operation trail renders.
 *   2. Loading skeleton.
 *   3. Empty state ("Wire your first routing") + CTA navigation.
 *   4. Filtered-empty state ("No routings match …") + Clear filter.
 *   5. Error state surfaces via QueryError.
 *   + Filter chips refetch with active_only.
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
const { default: RoutingsList } = await import('@/pages/manufacturing/RoutingsList');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const DESIGN_ID = 'd0000000-0000-0000-0000-000000000001';
const DESIGN_ID_2 = 'd0000000-0000-0000-0000-000000000002';
const RTG_ID_A = 'r0000000-0000-0000-0000-00000000000a';
const RTG_ID_B = 'r0000000-0000-0000-0000-00000000000b';
const RTG_ID_C = 'r0000000-0000-0000-0000-00000000000c';
const OP_CUT = 'op000000-0000-0000-0000-000000000001';
const OP_STITCH = 'op000000-0000-0000-0000-000000000002';
const OP_QC = 'op000000-0000-0000-0000-000000000003';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildRouting(opts: {
  id: string;
  designId: string;
  code: string;
  version: number;
  active: boolean;
  edges?: { from: string; to: string }[];
}) {
  return {
    routing_id: opts.id,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: opts.designId,
    code: opts.code,
    version_number: opts.version,
    is_active: opts.active,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-05-10T00:00:00Z',
    deleted_at: null,
    edges: (
      opts.edges ?? [
        { from: OP_CUT, to: OP_STITCH },
        { from: OP_STITCH, to: OP_QC },
      ]
    ).map((e, i) => ({
      routing_edge_id: `e${opts.id}-${i}`,
      routing_id: opts.id,
      from_operation_id: e.from,
      to_operation_id: e.to,
      edge_type: 'FINISH_TO_START',
      sequence: i + 1,
      threshold_pct: null,
      threshold_qty: null,
    })),
  };
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

function buildOpMasterList() {
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

function renderList() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/manufacturing/routings']}>
        <Routes>
          <Route path="/manufacturing/routings" element={<RoutingsList />} />
          <Route path="/manufacturing/routings/new" element={<div>NEW_ROUTING_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RoutingsList (live-mode integration, TASK-TR-E1-ROUTINGS)', () => {
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

  function setupHappyFetch(opts?: { activeOnlyCalls?: { count: number } }) {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/routings')) {
        if (u.includes('active_only=true') && opts?.activeOnlyCalls) {
          opts.activeOnlyCalls.count += 1;
        }
        return jsonResponse(200, {
          items: [
            buildRouting({
              id: RTG_ID_A,
              designId: DESIGN_ID,
              code: 'RTG-LHG-MRN',
              version: 2,
              active: true,
            }),
            buildRouting({
              id: RTG_ID_B,
              designId: DESIGN_ID,
              code: 'RTG-LHG-MRN',
              version: 1,
              active: false,
            }),
            buildRouting({
              id: RTG_ID_C,
              designId: DESIGN_ID_2,
              code: 'RTG-ANK',
              version: 1,
              active: true,
            }),
          ],
          count: 3,
          total_count: 3,
          limit: 50,
          offset: 0,
        });
      }
      if (u.includes('/designs')) {
        return jsonResponse(
          200,
          buildDesignList([
            { id: DESIGN_ID, code: 'DSN-LHG-MRN', name: 'Lehenga Maroon Banarasi' },
            { id: DESIGN_ID_2, code: 'DSN-ANK', name: 'Anarkali Coral' },
          ]),
        );
      }
      if (u.includes('/operation-masters')) {
        return jsonResponse(200, buildOpMasterList());
      }
      return jsonResponse(404, {});
    });
  }

  it('renders rows grouped by design with the operation sequence preview', async () => {
    setupHappyFetch();
    renderList();
    await waitFor(() => expect(screen.getByText(/Lehenga Maroon Banarasi/i)).toBeInTheDocument());
    expect(screen.getByText(/Anarkali Coral/i)).toBeInTheDocument();
    // Two routings on DSN-LHG-MRN: v2 + v1, plus v1 on DSN-ANK
    expect(screen.getByTestId(`routing-row-${RTG_ID_A}`)).toBeInTheDocument();
    expect(screen.getByTestId(`routing-row-${RTG_ID_B}`)).toBeInTheDocument();
    expect(screen.getByTestId(`routing-row-${RTG_ID_C}`)).toBeInTheDocument();
    // Operation names resolve into the trail.
    expect(screen.getAllByText('Cutting').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Stitching').length).toBeGreaterThan(0);
  });

  it('clicking "Active only" filters the rows', async () => {
    const activeOnlyCalls = { count: 0 };
    setupHappyFetch({ activeOnlyCalls });
    renderList();
    await waitFor(() => expect(screen.getByTestId(`routing-row-${RTG_ID_A}`)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /active only/i }));
    await waitFor(() => expect(activeOnlyCalls.count).toBeGreaterThanOrEqual(1));
  });

  it('shows the empty state with a "New routing" CTA when no routings exist', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/routings')) {
        return jsonResponse(200, { items: [], count: 0, total_count: 0, limit: 50, offset: 0 });
      }
      if (u.includes('/designs')) {
        return jsonResponse(200, buildDesignList([]));
      }
      if (u.includes('/operation-masters')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0, total_count: 0 });
      }
      return jsonResponse(404, {});
    });
    renderList();
    await waitFor(() => expect(screen.getByText(/wire your first routing/i)).toBeInTheDocument());
    const ctas = screen.getAllByRole('button', { name: /new routing/i });
    fireEvent.click(ctas[ctas.length - 1]);
    expect(screen.getByText('NEW_ROUTING_REACHED')).toBeInTheDocument();
  });

  it('shows the filtered-empty state when the search misses', async () => {
    setupHappyFetch();
    renderList();
    await waitFor(() => expect(screen.getByText(/Lehenga Maroon Banarasi/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/search routings/i), {
      target: { value: 'zzz-not-in-fixture' },
    });
    await waitFor(() =>
      expect(screen.getByText(/no routings match "zzz-not-in-fixture"/i)).toBeInTheDocument(),
    );
    // Clear filter CTA brings the rows back.
    fireEvent.click(screen.getByRole('button', { name: /clear filter/i }));
    await waitFor(() => expect(screen.getByTestId(`routing-row-${RTG_ID_A}`)).toBeInTheDocument());
  });

  it('surfaces a QueryError on a 503 from /routings', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/routings')) {
        return jsonResponse(503, {
          code: 'UNKNOWN',
          title: 'Service unavailable',
          detail: 'routing service is offline',
          status: 503,
          field_errors: {},
        });
      }
      if (u.includes('/designs')) {
        return jsonResponse(200, buildDesignList([]));
      }
      if (u.includes('/operation-masters')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0, total_count: 0 });
      }
      return jsonResponse(404, {});
    });
    renderList();
    await waitFor(() => expect(screen.getByText(/couldn't load this view/i)).toBeInTheDocument());
    // Detail surfaces verbatim from the 503 envelope.
    expect(screen.getByText(/routing service is offline/i)).toBeInTheDocument();
  });

  it('shows the loading skeleton while /routings is in flight', async () => {
    const pending: { resolve: (r: Response) => void } = {
      resolve: () => undefined,
    };
    fetchMock.mockImplementation((url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/routings')) {
        return new Promise<Response>((resolve) => {
          pending.resolve = resolve;
        });
      }
      if (u.includes('/designs')) {
        return Promise.resolve(jsonResponse(200, buildDesignList([])));
      }
      if (u.includes('/operation-masters')) {
        return Promise.resolve(
          jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0, total_count: 0 }),
        );
      }
      return Promise.resolve(jsonResponse(404, {}));
    });
    renderList();
    expect(await screen.findByLabelText(/loading routings/i)).toBeInTheDocument();
    pending.resolve(
      jsonResponse(200, { items: [], count: 0, total_count: 0, limit: 50, offset: 0 }),
    );
    await waitFor(() => expect(screen.getByText(/wire your first routing/i)).toBeInTheDocument());
  });
});
