/*
 * CostCentresList — TASK-TR-E1-COSTCENTRES live-mode integration tests.
 *
 * Coverage:
 *   - Loading skeleton renders while the query is pending.
 *   - Successful GET /cost-centres populates the table + filter counts.
 *   - Empty list renders the "Track where work happens" CTA.
 *   - Filtered-empty surfaces a "Clear filter" affordance.
 *   - Error envelope renders the QueryError shell.
 *
 * Pattern mirrors MoList.test.tsx: pin IS_LIVE before importing the page
 * so the live branch wins tree-shaking, then drive everything through a
 * mocked globalThis.fetch.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: CostCentresList } = await import('@/pages/manufacturing/CostCentresList');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const CC_ACTIVE = 'c0000000-0000-0000-0000-00000000000a';
const CC_INACTIVE = 'c0000000-0000-0000-0000-00000000000b';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildCc(opts: { id: string; code: string; name: string; is_active?: boolean }) {
  return {
    cost_centre_id: opts.id,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    code: opts.code,
    name: opts.name,
    cost_centre_type: null,
    parent_cost_centre_id: null,
    is_active: opts.is_active ?? true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-15T00:00:00Z',
    deleted_at: null,
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
      <MemoryRouter initialEntries={['/manufacturing/cost-centres']}>
        <CostCentresList />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CostCentresList (live-mode integration, TASK-TR-E1-COSTCENTRES)', () => {
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
      permissions: ['manufacturing.cost_centre.read', 'manufacturing.cost_centre.create'],
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

  it('renders the loading skeleton while the query is pending', () => {
    // Never-resolving fetch so the query stays in `isPending`.
    fetchMock.mockImplementation(() => new Promise(() => {}));
    renderList();
    expect(screen.getByRole('status', { name: /loading cost centres/i })).toBeInTheDocument();
  });

  it('renders rows from GET /cost-centres with mixed active/inactive counts', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/cost-centres')) {
        return jsonResponse(200, {
          items: [
            buildCc({ id: CC_ACTIVE, code: 'CC-INH-STC', name: 'In-house stitching' }),
            buildCc({
              id: CC_INACTIVE,
              code: 'CC-BLK-PRT',
              name: 'Block printing — Sanganer',
              is_active: false,
            }),
          ],
          count: 2,
          limit: 200,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    });

    renderList();

    await waitFor(() => expect(screen.getByText(/In-house stitching/)).toBeInTheDocument());
    expect(screen.getByText(/Block printing — Sanganer/)).toBeInTheDocument();
    expect(screen.getByText(/CC-INH-STC/)).toBeInTheDocument();
    expect(screen.getByText(/CC-BLK-PRT/)).toBeInTheDocument();

    // Active / Inactive pills both render (the filter chips + pills both
    // carry the label; finding any match is enough — we just want
    // confidence the status column rendered the right two badges).
    expect(screen.getAllByText(/^Active$/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^Inactive$/i).length).toBeGreaterThanOrEqual(1);

    // Header sub-line reports the counts.
    expect(screen.getByText(/2 cost centres · 1 active/i)).toBeInTheDocument();
  });

  it('Inactive filter chip hides active rows', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/cost-centres')) {
        return jsonResponse(200, {
          items: [
            buildCc({ id: CC_ACTIVE, code: 'CC-INH-STC', name: 'In-house stitching' }),
            buildCc({
              id: CC_INACTIVE,
              code: 'CC-BLK-PRT',
              name: 'Block printing — Sanganer',
              is_active: false,
            }),
          ],
          count: 2,
          limit: 200,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    });

    renderList();
    await waitFor(() => expect(screen.getByText(/In-house stitching/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /^Inactive/i, pressed: false }));

    // Active row disappears; inactive row remains.
    await waitFor(() => {
      expect(screen.queryByText(/In-house stitching/)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/Block printing — Sanganer/)).toBeInTheDocument();
  });

  it('renders the empty-state CTA when GET /cost-centres returns no rows', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/cost-centres')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderList();

    await waitFor(() => expect(screen.getByText(/Track where work happens/i)).toBeInTheDocument());
    // EmptyState CTA opens the dialog.
    const ctas = screen.getAllByRole('button', { name: /new cost centre/i });
    fireEvent.click(ctas[ctas.length - 1]);
    expect(screen.getByText(/A bucket for attributing labour cost/i)).toBeInTheDocument();
  });

  it('filtered-empty: search with no matches renders the "Clear filter" CTA', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/cost-centres')) {
        return jsonResponse(200, {
          items: [buildCc({ id: CC_ACTIVE, code: 'CC-INH-STC', name: 'In-house stitching' })],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    });

    renderList();
    await waitFor(() => expect(screen.getByText(/In-house stitching/)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/search cost centres/i), {
      target: { value: 'vendor warehouse' },
    });

    await waitFor(() =>
      expect(screen.getByText(/No cost centres match "vendor warehouse"/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /clear filter/i })).toBeInTheDocument();
  });

  it('error envelope renders the QueryError shell with a retry button', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(503, {
        code: 'SERVICE_UNAVAILABLE',
        title: 'Service unavailable',
        detail: 'GET /api/v1/cost-centres returned 503 — service unavailable.',
      }),
    );

    renderList();
    await waitFor(() => expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument());
  });
});
