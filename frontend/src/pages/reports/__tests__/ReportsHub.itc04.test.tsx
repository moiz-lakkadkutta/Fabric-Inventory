/*
 * ReportsHub — TASK-TR-B04 ITC-04 tab live-mode integration tests.
 *
 * Backend's `GET /reports/itc04?firm_id=&period=` is live; this task
 * wires the FE consumer. The panel hosts a month picker (mirrors
 * GSTR-1) and renders two sections — Send-outs and Receipts — driven
 * by the response's `send_outs` / `receipts` arrays. `firm_id` is
 * required on this endpoint (unlike the other reports which derive
 * firm from JWT), and the FE pulls it from the auth store.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: ReportsHub } = await import('@/pages/reports/ReportsHub');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderReports() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ReportsHub />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const sampleItc04 = {
  firm_id: 'f',
  period: '2026-04',
  from_date: '2026-04-01',
  to_date: '2026-04-30',
  total_send_outs: 2,
  total_receipts: 1,
  send_outs: [
    {
      job_work_order_id: 'jwo-1',
      challan_no: 'JWC/2526/0001',
      challan_date: '2026-04-05',
      karigar_party_id: 'k1',
      karigar_name: 'Rahim Karigar LIVE',
      karigar_gstin: '27KARIG1234F1Z5',
      item_id: 'i1',
      item_name: 'Dyed cotton fabric',
      hsn: '5208',
      qty_sent: '120.500',
      uom: 'METER',
      nature_of_job: 'Dyeing',
    },
    {
      job_work_order_id: 'jwo-2',
      challan_no: 'JWC/2526/0002',
      challan_date: '2026-04-10',
      karigar_party_id: 'k1',
      karigar_name: 'Rahim Karigar LIVE',
      karigar_gstin: '27KARIG1234F1Z5',
      item_id: 'i2',
      item_name: 'Greige fabric',
      hsn: '5209',
      qty_sent: '80.000',
      uom: 'METER',
      nature_of_job: 'Printing',
    },
  ],
  receipts: [
    {
      job_work_receipt_id: 'jwr-1',
      original_challan_no: 'JWC/2526/0001',
      original_challan_date: '2026-04-05',
      receipt_date: '2026-04-20',
      karigar_party_id: 'k1',
      karigar_name: 'Rahim Karigar LIVE',
      karigar_gstin: '27KARIG1234F1Z5',
      item_id: 'i1',
      item_name: 'Dyed cotton fabric',
      hsn: '5208',
      qty_received: '118.000',
      qty_wastage: '2.500',
      uom: 'METER',
    },
  ],
};

describe('ReportsHub ITC-04 — live-mode integration', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;
  let urlsHit: string[];

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    urlsHit = [];
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    authStore.reset();
    authStore.setAccessToken('test-token');
    authStore.setMe({
      user_id: 'u',
      org_id: 'o',
      firm_id: 'f',
      email: 'u@example.com',
      permissions: ['accounting.report.view'],
      flags: {},
      available_firms: [{ firm_id: 'f', code: 'F1', name: 'F1' }],
      token_expires_at: '2099-01-01T00:00:00Z',
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    authStore.reset();
    vi.restoreAllMocks();
  });

  function mockEndpoints(body: unknown = sampleItc04) {
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      urlsHit.push(`${method} ${u}`);
      if (u.includes('/reports/pnl') && method === 'GET') {
        return jsonResponse(200, {
          period: { from_date: '2026-04-01', to_date: '2026-04-30' },
          total_income: '0',
          cogs: '0',
          gross_profit: '0',
          expenses: '0',
          net_profit: '0',
          by_ledger_group: [],
        });
      }
      if (u.includes('/reports/itc04') && method === 'GET') {
        return jsonResponse(200, body);
      }
      return jsonResponse(404, {});
    });
  }

  it('ITC-04 tab issues GET /reports/itc04 with firm_id + period', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /ITC-04/i }));

    await waitFor(() =>
      expect(
        urlsHit.some(
          (u) =>
            u.startsWith('GET ') && /\/reports\/itc04\?.*firm_id=f.*period=\d{4}-\d{2}/.test(u),
        ),
      ).toBe(true),
    );
  });

  it('renders Send-outs and Receipts section headings', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /ITC-04/i }));

    // Karigar name appears in both Send-outs and Receipts rows — getAllBy.
    await waitFor(() =>
      expect(screen.getAllByText(/Rahim Karigar LIVE/i).length).toBeGreaterThan(0),
    );

    expect(screen.getByRole('heading', { name: /Send-outs?/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Receipts?/i })).toBeInTheDocument();
  });

  it('renders send-out rows with challan, karigar, item, qty + uom', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /ITC-04/i }));

    await waitFor(() =>
      expect(screen.getAllByText(/Rahim Karigar LIVE/i).length).toBeGreaterThan(0),
    );

    // JWC/2526/0001 is both a send-out challan_no and the receipt's
    // original_challan_no — getAllBy is the correct query.
    expect(screen.getAllByText(/JWC\/2526\/0001/).length).toBeGreaterThan(0);
    expect(screen.getByText(/JWC\/2526\/0002/)).toBeInTheDocument();
    // Item names — Dyed cotton fabric appears twice (send-out + receipt)
    expect(screen.getAllByText(/Dyed cotton fabric/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Greige fabric/i)).toBeInTheDocument();
    // Nature of job (send-out only)
    expect(screen.getByText(/Dyeing/i)).toBeInTheDocument();
    expect(screen.getByText(/Printing/i)).toBeInTheDocument();
  });

  it('renders receipt rows with qty received + wastage', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /ITC-04/i }));

    await waitFor(() =>
      expect(screen.getAllByText(/Dyed cotton fabric/i).length).toBeGreaterThan(0),
    );

    // 118 received + 2.5 wastage. Allow Indian-grouping or plain.
    expect(screen.getAllByText(/118/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2\.5/).length).toBeGreaterThan(0);
  });

  it('renders empty-state in both sections when no rows are returned', async () => {
    mockEndpoints({
      firm_id: 'f',
      period: '2026-04',
      from_date: '2026-04-01',
      to_date: '2026-04-30',
      total_send_outs: 0,
      total_receipts: 0,
      send_outs: [],
      receipts: [],
    });
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /ITC-04/i }));

    await waitFor(() =>
      expect(screen.getByText(/no send-outs? in this period/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/no receipts? in this period/i)).toBeInTheDocument();
  });

  it('refetches when the user changes the period', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /ITC-04/i }));

    await waitFor(() => expect(screen.getByLabelText(/ITC-04 period/i)).toBeInTheDocument());

    const monthInput = screen.getByLabelText(/ITC-04 period/i);
    fireEvent.change(monthInput, { target: { value: '2026-03' } });

    await waitFor(() =>
      expect(urlsHit.some((u) => /\/reports\/itc04\?.*firm_id=f.*period=2026-03/.test(u))).toBe(
        true,
      ),
    );
  });
});
