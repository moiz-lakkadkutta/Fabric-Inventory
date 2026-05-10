import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Live-mode GRN tests (TASK-CUT-202).
 *
 * Force IS_LIVE=true so the GRN/PI queries branch into the live API
 * path. Stub global.fetch (per task brief — no MSW). Asserts the
 * round-trip from `GET /grns` and the `POST /grns` body shape.
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: GrnList } = await import('@/pages/purchase/GrnList');
const { default: GrnCreate } = await import('@/pages/purchase/GrnCreate');
const { default: GrnDetail } = await import('@/pages/purchase/GrnDetail');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const FIRM_ID = 'f1111111-1111-1111-1111-111111111111';
const PO_ID = 'a1111111-1111-1111-1111-111111111111';
const PO_LINE_ID = 'a2222222-2222-2222-2222-222222222222';
const ITEM_ID = 'b1111111-1111-1111-1111-111111111111';
const PARTY_ID = 'c1111111-1111-1111-1111-111111111111';
const GRN_ID = 'd1111111-1111-1111-1111-111111111111';

function makeQc() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function renderRoutes(initial: string) {
  const qc = makeQc();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/purchase/grns" element={<GrnList />} />
          <Route path="/purchase/grns/new" element={<GrnCreate />} />
          <Route path="/purchase/grns/:id" element={<GrnDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let fetchMock: ReturnType<typeof vi.fn>;
let originalFetch: typeof fetch;

beforeEach(() => {
  authStore.setMe({
    user_id: 'u1',
    org_id: 'o1',
    firm_id: FIRM_ID,
    email: 'tester@example.com',
    permissions: [
      'purchase.po.read',
      'purchase.grn.read',
      'purchase.grn.create',
      'purchase.grn.approve',
      'purchase.invoice.read',
      'purchase.invoice.create',
      'purchase.invoice.post',
      'purchase.invoice.void',
    ],
    flags: {},
    available_firms: [{ firm_id: FIRM_ID, code: 'AC', name: 'Audit Co' }],
    token_expires_at: '2099-01-01T00:00:00Z',
  });
  authStore.setAccessToken('access-token-abc');
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
  authStore.reset();
});

describe('GrnList — live mode', () => {
  it('lists GRNs returned by GET /grns with their number and PO link', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/grns')) {
        return jsonResponse(200, {
          items: [
            {
              grn_id: GRN_ID,
              org_id: 'o1',
              firm_id: FIRM_ID,
              series: 'GRN/25-26',
              number: 'GRN/25-26/0001',
              party_id: PARTY_ID,
              purchase_order_id: PO_ID,
              grn_date: '2026-05-10',
              status: 'DRAFT',
              total_qty_received: '50.000',
              total_amount: '50000.00',
              notes: null,
              lines: [],
              created_at: '2026-05-10T00:00:00Z',
              updated_at: '2026-05-10T00:00:00Z',
            },
          ],
          limit: 200,
          offset: 0,
          count: 1,
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderRoutes('/purchase/grns');
    await waitFor(() => expect(screen.getByText('GRN/25-26/0001')).toBeInTheDocument());
  });
});

describe('GrnCreate — live mode', () => {
  it('picks a confirmed PO, defaults line qty = ordered, and POSTs the body to /grns', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? 'GET';
      if (u.includes('/purchase-orders/') && !u.endsWith('/purchase-orders') && method === 'GET') {
        // Detail call (after PO selected)
        return jsonResponse(200, {
          purchase_order_id: PO_ID,
          org_id: 'o1',
          firm_id: FIRM_ID,
          series: 'PO/25-26',
          number: 'PO/25-26/0001',
          party_id: PARTY_ID,
          po_date: '2026-05-09',
          delivery_date: null,
          status: 'CONFIRMED',
          total_amount: '50000.00',
          notes: null,
          lines: [
            {
              po_line_id: PO_LINE_ID,
              item_id: ITEM_ID,
              qty_ordered: '50.000',
              qty_received: '0',
              rate: '1000.00',
              line_amount: '50000.00',
              line_sequence: 1,
              taxes_applicable: null,
              notes: null,
            },
          ],
          created_at: '2026-05-09T00:00:00Z',
          updated_at: '2026-05-09T00:00:00Z',
        });
      }
      if (u.includes('/purchase-orders') && method === 'GET') {
        return jsonResponse(200, {
          items: [
            {
              purchase_order_id: PO_ID,
              org_id: 'o1',
              firm_id: FIRM_ID,
              series: 'PO/25-26',
              number: 'PO/25-26/0001',
              party_id: PARTY_ID,
              po_date: '2026-05-09',
              delivery_date: null,
              status: 'CONFIRMED',
              total_amount: '50000.00',
              notes: null,
              lines: [
                {
                  po_line_id: PO_LINE_ID,
                  item_id: ITEM_ID,
                  qty_ordered: '50.000',
                  qty_received: '0',
                  rate: '1000.00',
                  line_amount: '50000.00',
                  line_sequence: 1,
                  taxes_applicable: null,
                  notes: null,
                },
              ],
              created_at: '2026-05-09T00:00:00Z',
              updated_at: '2026-05-09T00:00:00Z',
            },
          ],
          limit: 200,
          offset: 0,
          count: 1,
        });
      }
      if (u.endsWith('/grns') && method === 'POST') {
        return jsonResponse(201, {
          grn_id: GRN_ID,
          org_id: 'o1',
          firm_id: FIRM_ID,
          series: 'GRN/25-26',
          number: 'GRN/25-26/0001',
          party_id: PARTY_ID,
          purchase_order_id: PO_ID,
          grn_date: '2026-05-10',
          status: 'DRAFT',
          total_qty_received: '50.000',
          total_amount: '50000.00',
          notes: null,
          lines: [
            {
              grn_line_id: 'e1111111-1111-1111-1111-111111111111',
              grn_id: GRN_ID,
              item_id: ITEM_ID,
              po_line_id: PO_LINE_ID,
              qty_received: '50.000',
              rate: '1000.00',
              lot_number: null,
              line_sequence: 1,
            },
          ],
          created_at: '2026-05-10T00:00:00Z',
          updated_at: '2026-05-10T00:00:00Z',
        });
      }
      throw new Error(`unexpected fetch: ${method} ${u}`);
    });

    renderRoutes('/purchase/grns/new');

    // Pick PO — wait for the dropdown options to populate from the list fetch
    await waitFor(() => expect(screen.getByText(/PO\/25-26\/0001/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/source purchase order/i), {
      target: { value: PO_ID },
    });

    // Wait for line to render (qty defaults to ordered).
    await waitFor(() =>
      expect((screen.getByLabelText(/line 1 qty received/i) as HTMLInputElement).value).toBe('50'),
    );

    fireEvent.click(screen.getByRole('button', { name: /create grn/i }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith('/grns') && (init as RequestInit | undefined)?.method === 'POST',
      );
      expect(postCall).toBeDefined();
    });

    const postCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/grns') && (init as RequestInit | undefined)?.method === 'POST',
    );
    const body = JSON.parse((postCall![1] as RequestInit).body as string);
    expect(body).toMatchObject({
      firm_id: FIRM_ID,
      party_id: PARTY_ID,
      purchase_order_id: PO_ID,
      grn_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      lines: [
        {
          item_id: ITEM_ID,
          po_line_id: PO_LINE_ID,
          qty_received: '50',
          line_sequence: 1,
        },
      ],
    });
    const headers = (postCall![1] as RequestInit).headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
  });
});

describe('GrnDetail — live mode', () => {
  it('renders the GRN number and a link to the source PO', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes(`/grns/${GRN_ID}`)) {
        return jsonResponse(200, {
          grn_id: GRN_ID,
          org_id: 'o1',
          firm_id: FIRM_ID,
          series: 'GRN/25-26',
          number: 'GRN/25-26/0001',
          party_id: PARTY_ID,
          purchase_order_id: PO_ID,
          grn_date: '2026-05-10',
          status: 'DRAFT',
          total_qty_received: '50.000',
          total_amount: '50000.00',
          notes: null,
          lines: [],
          created_at: '2026-05-10T00:00:00Z',
          updated_at: '2026-05-10T00:00:00Z',
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderRoutes(`/purchase/grns/${GRN_ID}`);
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /GRN\/25-26\/0001/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole('link', { name: /source PO/i })).toHaveAttribute(
      'href',
      `/purchase?po=${PO_ID}`,
    );
  });
});
