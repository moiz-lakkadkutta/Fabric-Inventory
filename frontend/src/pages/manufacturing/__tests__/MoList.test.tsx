/*
 * MoList — TASK-TR-A14-FU live-mode integration tests.
 *
 * Pattern follows JobWorkOverview.test.tsx: pin IS_LIVE before importing
 * the page so the live branch wins tree-shaking, then drive everything
 * via a mocked globalThis.fetch.
 *
 * Coverage:
 *   - GET /manufacturing/mo populates the table.
 *   - Status filter chips refetch with the BE status param.
 *   - Row click routes to the detail URL.
 *   - Empty-state branch surfaces the "Click New MO" copy.
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
const { default: MoList } = await import('@/pages/manufacturing/MoList');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const MO_ID_A = 'm0000000-0000-0000-0000-00000000000a';
const MO_ID_B = 'm0000000-0000-0000-0000-00000000000b';
const DESIGN_ID = 'd0000000-0000-0000-0000-000000000001';
const ITEM_ID = 'i0000000-0000-0000-0000-000000000001';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildMoListItem(opts: {
  id: string;
  number?: string;
  status?: 'DRAFT' | 'RELEASED' | 'IN_PROGRESS' | 'COMPLETED' | 'CLOSED';
  planned?: string;
}) {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: DESIGN_ID,
    finished_item_id: ITEM_ID,
    manufacturing_order_id: opts.id,
    mo_date: '2026-05-01',
    number: opts.number ?? '0001',
    series: 'MO/2026',
    planned_qty: opts.planned ?? '100.0000',
    status: opts.status ?? 'IN_PROGRESS',
    created_at: '2026-05-01T00:00:00Z',
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

function renderMoList() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/manufacturing/mo']}>
        <Routes>
          <Route path="/manufacturing/mo" element={<MoList />} />
          <Route path="/manufacturing/mo/new" element={<div>NEW_MO_REACHED</div>} />
          <Route path="/manufacturing/mo/:id" element={<div>DETAIL_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('MoList (live-mode integration, TASK-TR-A14-FU)', () => {
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
      permissions: ['manufacturing.mo.read'],
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

  it('renders rows from GET /manufacturing/mo and resolves design names via /designs', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/manufacturing/mo')) {
        return jsonResponse(200, {
          items: [
            buildMoListItem({ id: MO_ID_A, number: '0001', status: 'IN_PROGRESS' }),
            buildMoListItem({ id: MO_ID_B, number: '0002', status: 'DRAFT' }),
          ],
          count: 2,
          total_count: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (u.includes('/designs')) {
        return jsonResponse(200, { items: [buildDesign()], count: 1, limit: 100, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderMoList();

    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    expect(screen.getByText(/MO\/2026\/0002/)).toBeInTheDocument();
    // Design name resolves into the row from the separate /designs query.
    expect(screen.getAllByText(/Bridal Lehenga/).length).toBeGreaterThanOrEqual(2);
  });

  it('clicking the Draft filter refetches with ?status=DRAFT', async () => {
    let listCallsByStatus = { all: 0, DRAFT: 0 };
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/manufacturing/mo')) {
        if (u.includes('status=DRAFT')) {
          listCallsByStatus.DRAFT += 1;
          return jsonResponse(200, {
            items: [buildMoListItem({ id: MO_ID_B, number: '0002', status: 'DRAFT' })],
            count: 1,
            total_count: 1,
            limit: 100,
            offset: 0,
          });
        }
        listCallsByStatus.all += 1;
        return jsonResponse(200, {
          items: [
            buildMoListItem({ id: MO_ID_A, number: '0001', status: 'IN_PROGRESS' }),
            buildMoListItem({ id: MO_ID_B, number: '0002', status: 'DRAFT' }),
          ],
          count: 2,
          total_count: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (u.includes('/designs')) {
        return jsonResponse(200, { items: [], count: 0, limit: 100, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderMoList();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /^Draft$/i }));
    await waitFor(() => expect(listCallsByStatus.DRAFT).toBeGreaterThanOrEqual(1));
    // After the filter, only the DRAFT MO remains.
    await waitFor(() => {
      expect(screen.queryByText(/MO\/2026\/0001/)).not.toBeInTheDocument();
      expect(screen.getByText(/MO\/2026\/0002/)).toBeInTheDocument();
    });
  });

  it('clicking a row navigates to the MO detail route', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/manufacturing/mo')) {
        return jsonResponse(200, {
          items: [buildMoListItem({ id: MO_ID_A, number: '0001' })],
          count: 1,
          total_count: 1,
          limit: 100,
          offset: 0,
        });
      }
      if (u.includes('/designs')) {
        return jsonResponse(200, { items: [], count: 0, limit: 100, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderMoList();
    const link = await screen.findByRole('link', { name: /MO\/2026\/0001/ });
    fireEvent.click(link);
    expect(screen.getByText('DETAIL_REACHED')).toBeInTheDocument();
  });

  it('empty list shows the "No MOs yet" empty state with a New MO CTA', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/manufacturing/mo')) {
        return jsonResponse(200, { items: [], count: 0, total_count: 0, limit: 100, offset: 0 });
      }
      if (u.includes('/designs')) {
        return jsonResponse(200, { items: [], count: 0, limit: 100, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderMoList();
    await waitFor(() => expect(screen.getByText(/no mos yet/i)).toBeInTheDocument());
    // EmptyState renders the CTA as a button; clicking it navigates to /new.
    const ctas = screen.getAllByRole('button', { name: /new mo/i });
    fireEvent.click(ctas[ctas.length - 1]);
    expect(screen.getByText('NEW_MO_REACHED')).toBeInTheDocument();
  });
});
