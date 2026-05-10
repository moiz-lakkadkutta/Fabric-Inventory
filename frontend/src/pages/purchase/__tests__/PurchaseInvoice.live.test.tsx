import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Live-mode Purchase Invoice tests (TASK-CUT-202).
 *
 * Asserts the PI list/detail/post round-trip. Mocks global.fetch
 * directly per the task brief (no MSW).
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: PurchaseInvoiceList } = await import('@/pages/purchase/PurchaseInvoiceList');
const { default: PurchaseInvoiceDetail } = await import('@/pages/purchase/PurchaseInvoiceDetail');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const FIRM_ID = 'f1111111-1111-1111-1111-111111111111';
const PARTY_ID = 'c1111111-1111-1111-1111-111111111111';
const PI_ID = 'a3333333-3333-3333-3333-333333333333';

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
          <Route path="/purchase/invoices" element={<PurchaseInvoiceList />} />
          <Route path="/purchase/invoices/:id" element={<PurchaseInvoiceDetail />} />
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

describe('PurchaseInvoiceList — live mode', () => {
  it('lists Purchase Invoices returned by GET /purchase-invoices', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/purchase-invoices')) {
        return jsonResponse(200, {
          items: [piPayload({ status: 'DRAFT', lifecycle_status: 'DRAFT' })],
          limit: 200,
          offset: 0,
          count: 1,
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderRoutes('/purchase/invoices');
    await waitFor(() => expect(screen.getByText('PI/25-26/0001')).toBeInTheDocument());
  });
});

describe('PurchaseInvoiceDetail — live mode', () => {
  it('Post button transitions DRAFT → POSTED via /purchase-invoices/{id}/post', async () => {
    let getCount = 0;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? 'GET';
      if (u.includes(`/purchase-invoices/${PI_ID}`) && method === 'GET') {
        getCount += 1;
        return jsonResponse(
          200,
          piPayload({
            status: getCount > 1 ? 'POSTED' : 'DRAFT',
            lifecycle_status: getCount > 1 ? 'FINALIZED' : 'DRAFT',
          }),
        );
      }
      if (u.endsWith(`/purchase-invoices/${PI_ID}/post`) && method === 'POST') {
        return jsonResponse(200, piPayload({ status: 'POSTED', lifecycle_status: 'FINALIZED' }));
      }
      throw new Error(`unexpected fetch: ${method} ${u}`);
    });

    renderRoutes(`/purchase/invoices/${PI_ID}`);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /PI\/25-26\/0001/i })).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole('button', { name: /^post$/i }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith(`/purchase-invoices/${PI_ID}/post`) &&
          (init as RequestInit | undefined)?.method === 'POST',
      );
      expect(postCall).toBeDefined();
    });

    // After the mutation resolves, the cache update + invalidate refresh
    // surfaces the new lifecycle_status.
    await waitFor(() => expect(screen.getByText(/finalized/i)).toBeInTheDocument());

    const postCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith(`/purchase-invoices/${PI_ID}/post`) &&
        (init as RequestInit | undefined)?.method === 'POST',
    );
    const headers = (postCall![1] as RequestInit).headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
  });
});

interface PiOpts {
  status: string;
  lifecycle_status: string;
}

function piPayload(opts: PiOpts) {
  return {
    purchase_invoice_id: PI_ID,
    org_id: 'o1',
    firm_id: FIRM_ID,
    series: 'PI/25-26',
    number: 'PI/25-26/0001',
    party_id: PARTY_ID,
    grn_id: null,
    invoice_date: '2026-05-10',
    invoice_amount: '50000.00',
    gst_amount: '2500.00',
    rcm_applicable: false,
    status: opts.status,
    lifecycle_status: opts.lifecycle_status,
    paid_amount: '0',
    due_date: null,
    notes: null,
    lines: [],
    created_at: '2026-05-10T00:00:00Z',
    updated_at: '2026-05-10T00:00:00Z',
  };
}
