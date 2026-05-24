/*
 * DesignsList — TASK-TR-E1 live-mode integration tests.
 *
 * Pin IS_LIVE before importing the page so the live branch of the
 * queries hook wins tree-shaking, then drive everything through a
 * fetch mock. Covers the five list states the design spec calls out:
 *   - Full           — 8 rows incl. one inactive (muted opacity).
 *   - Loading        — skeleton role status visible during pending.
 *   - Error          — QueryError surfaces and a Retry button shows.
 *   - Empty          — true-empty CTA "New design" opens dialog.
 *   - FilteredEmpty  — search returned nothing (distinct copy from
 *                      true-empty so an operator knows to clear).
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
const { default: DesignsList } = await import('@/pages/manufacturing/DesignsList');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildDesign(opts: {
  id: string;
  code?: string;
  name?: string;
  description?: string | null;
  active?: boolean;
  updated_at?: string;
}) {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: opts.id,
    code: opts.code ?? 'DSN-ANK-PNK',
    name: opts.name ?? 'Anarkali Pink Embroidered',
    description: opts.description ?? null,
    cost_centre_id: null,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: opts.updated_at ?? '2026-04-14T00:00:00Z',
    deleted_at: opts.active === false ? '2026-04-02T00:00:00Z' : null,
  };
}

const DESIGN_FIXTURES = [
  buildDesign({ id: 'd-1', code: 'DSN-ANK-PNK', name: 'Anarkali Pink Embroidered' }),
  buildDesign({ id: 'd-2', code: 'DSN-SHR-GLD', name: 'Sharara Set Gold' }),
  buildDesign({ id: 'd-3', code: 'DSN-SLW-BLU', name: 'Salwar Kameez Blue Cotton' }),
  buildDesign({ id: 'd-4', code: 'DSN-LHG-MRN', name: 'Lehenga Maroon Banarasi' }),
  buildDesign({ id: 'd-5', code: 'DSN-KRT-IND', name: 'Kurta Indigo Block Print' }),
  buildDesign({ id: 'd-6', code: 'DSN-DPT-CHM', name: 'Dupatta Champagne Mukaish' }),
  buildDesign({ id: 'd-7', code: 'DSN-KRT-OFW', name: 'Kurta Off-white Chikankari' }),
  buildDesign({
    id: 'd-8',
    code: 'DSN-LHG-PCH',
    name: 'Lehenga Peach Mirror Work',
    active: false,
  }),
];

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/manufacturing/designs']}>
        <Routes>
          <Route path="/manufacturing/designs" element={<DesignsList />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DesignsList (live-mode, TASK-TR-E1)', () => {
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
      permissions: ['manufacturing.design.read', 'manufacturing.design.create'],
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

  it('FULL state: renders 8 rows and breadcrumb, inactive row muted', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/designs')) {
        return jsonResponse(200, {
          items: DESIGN_FIXTURES,
          count: DESIGN_FIXTURES.length,
          limit: 100,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    });

    renderPage();

    await waitFor(() => expect(screen.getByText(/Anarkali Pink Embroidered/)).toBeInTheDocument());

    // Breadcrumb path renders.
    expect(screen.getByText(/Masters/)).toBeInTheDocument();
    // Page header.
    expect(screen.getByRole('heading', { name: 'Designs' })).toBeInTheDocument();

    // All 8 designs surfaced.
    expect(screen.getByText(/Sharara Set Gold/)).toBeInTheDocument();
    expect(screen.getByText(/Lehenga Peach Mirror Work/)).toBeInTheDocument();

    // Filter chips visible.
    expect(screen.getByRole('button', { name: /All/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Active/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Inactive/ })).toBeInTheDocument();

    // Active / Inactive pill rendering — "Active" appears as a Pill on
    // each active row PLUS the filter chip, "Inactive" as the pill on
    // the one inactive row PLUS the filter chip. Both render somewhere.
    expect(screen.getAllByText('Active').length).toBeGreaterThanOrEqual(7);
    expect(screen.getAllByText('Inactive').length).toBeGreaterThanOrEqual(2);

    // Inactive row is muted — find the row containing "Lehenga Peach Mirror Work".
    const inactiveCell = screen.getByText(/Lehenga Peach Mirror Work/);
    const inactiveRow = inactiveCell.closest('tr');
    expect(inactiveRow).not.toBeNull();
    expect((inactiveRow as HTMLElement).style.opacity).toBe('0.55');
  });

  it('LOADING state: skeleton rows visible while fetch is pending', async () => {
    // Never resolve so the query stays pending.
    fetchMock.mockImplementation(
      () => new Promise<Response>(() => {}) as unknown as Promise<Response>,
    );

    renderPage();

    // The skeleton container has role=status with the loading aria label.
    expect(await screen.findByRole('status', { name: /loading designs/i })).toBeInTheDocument();
    // Filter count placeholder is "—" during pending.
    expect(screen.getByText(/—/)).toBeInTheDocument();
  });

  it('ERROR state: QueryError renders with a Retry affordance', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(503, {
        code: 'UNKNOWN',
        title: 'Service unavailable',
        detail: 'GET /designs returned 503',
        status: 503,
        field_errors: {},
      }),
    );

    renderPage();

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('EMPTY state: true-empty CTA opens the new-design dialog', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/designs')) {
        return jsonResponse(200, { items: [], count: 0, limit: 100, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderPage();

    await waitFor(() => expect(screen.getByText(/Create your first design/i)).toBeInTheDocument());
    // CTA inside the EmptyState — distinct from the page-header "+ New design".
    const ctas = screen.getAllByRole('button', { name: /new design/i });
    expect(ctas.length).toBeGreaterThanOrEqual(1);
    fireEvent.click(ctas[ctas.length - 1]);
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /new design/i })).toBeInTheDocument(),
    );
  });

  it('FILTERED-EMPTY state: search miss shows a distinct empty copy', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/designs')) {
        return jsonResponse(200, {
          items: DESIGN_FIXTURES,
          count: DESIGN_FIXTURES.length,
          limit: 100,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    });

    renderPage();

    await waitFor(() => expect(screen.getByText(/Anarkali Pink Embroidered/)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Search designs/i), {
      target: { value: 'kanjeevaram' },
    });

    await waitFor(() =>
      expect(screen.getByText(/No designs match "kanjeevaram"/i)).toBeInTheDocument(),
    );
    // True-empty CTA copy must NOT appear (distinct from filtered-empty).
    expect(screen.queryByText(/Create your first design/i)).not.toBeInTheDocument();
    // Clear filter affordance.
    expect(screen.getByRole('button', { name: /clear filter/i })).toBeInTheDocument();
  });
});
