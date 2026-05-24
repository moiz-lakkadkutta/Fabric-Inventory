/*
 * OperationsList — TASK-TR-E1-OPERATIONS integration tests.
 *
 * Drives every list state (Full / Loading / Error / Empty / Filtered-
 * Empty) via fetch-mocked live mode + asserts the type-filter popover.
 *
 * Pattern follows MoList.test.tsx: pin IS_LIVE before importing the
 * page so the live branch wins tree-shaking, then drive everything via
 * a mocked globalThis.fetch.
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
const { default: OperationsList } = await import('@/pages/manufacturing/OperationsList');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildOp(opts: {
  id: string;
  code: string;
  name: string;
  type?: 'WEAVING' | 'DYEING' | 'EMBROIDERY' | 'STITCHING' | 'QC' | 'PACKING' | 'OTHER' | null;
  dur?: string | null;
  active?: boolean;
}) {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    operation_master_id: opts.id,
    code: opts.code,
    name: opts.name,
    operation_type: opts.type ?? 'OTHER',
    default_duration_mins: opts.dur ?? null,
    cost_centre_id: null,
    is_active: opts.active ?? true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-12T00:00:00Z',
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
      <MemoryRouter initialEntries={['/manufacturing/operations']}>
        <Routes>
          <Route path="/manufacturing/operations" element={<OperationsList />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('OperationsList (live-mode, TASK-TR-E1)', () => {
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
      permissions: ['manufacturing.operation_master.read', 'manufacturing.operation_master.create'],
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

  // --- 1: Full state ---------------------------------------------------
  it('renders the full list with code + name + OpTypePill per row', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      if (String(url).includes('/operation-masters')) {
        return jsonResponse(200, {
          items: [
            buildOp({
              id: '11111111-1111-1111-1111-111111111111',
              code: 'OP-EMB-AAR',
              name: 'Hand Embroidery — Aari',
              type: 'EMBROIDERY',
              dur: '480',
            }),
            buildOp({
              id: '22222222-2222-2222-2222-222222222222',
              code: 'OP-QC-VIS',
              name: 'Quality Check — visual',
              type: 'QC',
              dur: '15',
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
    await waitFor(() => expect(screen.getByText('OP-EMB-AAR')).toBeInTheDocument());
    expect(screen.getByText('Hand Embroidery — Aari')).toBeInTheDocument();
    expect(screen.getByText('OP-QC-VIS')).toBeInTheDocument();
    // OpTypePill carries data-op-type — one per row.
    const pills = screen.getAllByTestId('op-type-pill');
    const types = pills.map((p) => p.getAttribute('data-op-type'));
    expect(types).toEqual(expect.arrayContaining(['EMBROIDERY', 'QC']));
  });

  // --- 2: Loading state ------------------------------------------------
  it('renders the loading skeleton before the first response', async () => {
    let resolve: (r: Response) => void = () => {};
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((res) => {
          resolve = res;
        }),
    );
    renderList();
    expect(screen.getByRole('status', { name: /loading operations/i })).toBeInTheDocument();
    resolve(jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 }));
    await waitFor(() =>
      expect(screen.queryByRole('status', { name: /loading operations/i })).not.toBeInTheDocument(),
    );
  });

  // --- 3: Error state --------------------------------------------------
  it('renders the QueryError surface when the GET fails', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(503, { title: 'Service Unavailable', detail: 'down' }),
    );
    renderList();
    await waitFor(() => expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument());
  });

  // --- 4: Empty state --------------------------------------------------
  it('renders the empty state with a New operation CTA when zero rows are returned', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 }),
    );
    renderList();
    await waitFor(() =>
      expect(screen.getByText(/Define your manufacturing steps/i)).toBeInTheDocument(),
    );
    // EmptyState exposes a button with the CTA label.
    const ctas = screen.getAllByRole('button', { name: /new operation/i });
    expect(ctas.length).toBeGreaterThanOrEqual(1);
  });

  // --- 5: Filtered-empty state -----------------------------------------
  it('renders the "no operations match" state when a search has no results', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(200, {
        items: [
          buildOp({
            id: '11111111-1111-1111-1111-111111111111',
            code: 'OP-EMB-AAR',
            name: 'Hand Embroidery — Aari',
            type: 'EMBROIDERY',
          }),
        ],
        count: 1,
        limit: 200,
        offset: 0,
      }),
    );
    renderList();
    await waitFor(() => expect(screen.getByText('OP-EMB-AAR')).toBeInTheDocument());
    const search = screen.getByRole('searchbox', { name: /search operations/i });
    fireEvent.change(search, { target: { value: 'screen printing' } });
    await waitFor(() => expect(screen.getByText(/No operations match/i)).toBeInTheDocument());
    // The Clear-filter affordance is visible.
    expect(screen.getByRole('button', { name: /clear filter/i })).toBeInTheDocument();
  });

  // --- Type-filter popover --------------------------------------------
  it('opens the By-type popover and filters by selected type', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(200, {
        items: [
          buildOp({
            id: '11111111-1111-1111-1111-111111111111',
            code: 'OP-EMB-AAR',
            name: 'Hand Embroidery — Aari',
            type: 'EMBROIDERY',
          }),
          buildOp({
            id: '22222222-2222-2222-2222-222222222222',
            code: 'OP-QC-VIS',
            name: 'Quality Check — visual',
            type: 'QC',
          }),
        ],
        count: 2,
        limit: 200,
        offset: 0,
      }),
    );
    renderList();
    await waitFor(() => expect(screen.getByText('OP-EMB-AAR')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /by type/i }));
    const popover = await screen.findByRole('dialog', {
      name: /filter by operation type/i,
    });
    expect(popover).toBeInTheDocument();
    const qcCheckbox = screen.getByRole('checkbox', { name: /^qc$/i });
    fireEvent.click(qcCheckbox);
    await waitFor(() => {
      expect(screen.queryByText('OP-EMB-AAR')).not.toBeInTheDocument();
      expect(screen.getByText('OP-QC-VIS')).toBeInTheDocument();
    });
  });
});
