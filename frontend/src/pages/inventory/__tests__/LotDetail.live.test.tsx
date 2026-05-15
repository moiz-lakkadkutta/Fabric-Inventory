/*
 * TASK-TR-B02 — Live-mode LotDetail asserts the BE LotResponse shape
 * is fetched from `/lots/{id}` and rendered (lot number, item code,
 * supplier lot, qty_on_hand). Cousin of the click-dummy test in
 * `Inventory.test.tsx` which exercises the mock branch.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: LotDetail } = await import('@/pages/inventory/LotDetail');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const LOT_ID = 'a1111111-1111-1111-1111-111111111111';
const ITEM_ID = 'i1111111-1111-1111-1111-111111111111';
const GRN_ID = 'g1111111-1111-1111-1111-111111111111';

function backendLot() {
  return {
    lot_id: LOT_ID,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    item_id: ITEM_ID,
    item_code: 'SLK-GEO-60',
    item_name: 'Silk Georgette 60"',
    primary_uom: 'METER',
    lot_number: 'LOT/SLK-GEO-60/2026-Q1-018',
    supplier_lot_number: 'VENDOR-ABC-1',
    mfg_date: null,
    expiry_date: null,
    received_date: '2026-03-12',
    primary_cost: '185.00',
    currency: 'INR',
    grn_id: GRN_ID,
    qty_on_hand: '38.00',
    created_at: '2026-03-12T00:00:00Z',
    updated_at: '2026-03-12T00:00:00Z',
  };
}

function renderLotDetail() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/inventory/lots/${LOT_ID}`]}>
        <Routes>
          <Route path="/inventory/lots/:id" element={<LotDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TR-B02 LotDetail (live mode)', () => {
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
      permissions: ['inventory.lot.read'],
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

  it('hits GET /lots/{id} and renders the BE LotResponse fields', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes(`/lots/${LOT_ID}`)) {
        return jsonResponse(200, backendLot());
      }
      return jsonResponse(404, {});
    });

    renderLotDetail();

    // Wait for the lot number heading — proves the GET resolved.
    await waitFor(() => expect(screen.getByText('LOT/SLK-GEO-60/2026-Q1-018')).toBeInTheDocument());

    // qty_on_hand renders with the UoM suffix.
    expect(screen.getByText(/38\s*meter/i)).toBeInTheDocument();
    // Supplier lot appears in the subtitle.
    expect(screen.getByText(/supplier VENDOR-ABC-1/i)).toBeInTheDocument();
    // Item summary surfaces both code and name (one in heading subtitle,
    // one in the field grid).
    expect(screen.getAllByText(/Silk Georgette 60/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/SLK-GEO-60/).length).toBeGreaterThanOrEqual(1);

    // Confirm we actually called the /lots endpoint (not a stale mock).
    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calls.some((c) => c.includes(`/lots/${LOT_ID}`))).toBe(true);
  });

  it('renders "Lot not found" when the API 404s', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(404, {
        code: 'NOT_FOUND',
        title: 'Not found',
        detail: 'Lot not found',
        status: 404,
        field_errors: {},
      }),
    );

    renderLotDetail();

    await waitFor(() => expect(screen.getByText(/lot not found/i)).toBeInTheDocument());
  });
});
