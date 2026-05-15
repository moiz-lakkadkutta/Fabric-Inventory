/*
 * ReportsHub — TASK-TR-B04 Party statement tab live-mode integration tests.
 *
 * Backend's `GET /reports/party-statement/{party_id}?from=&to=` is live;
 * this task wires the FE consumer. Same shape as ledger statement but
 * party-scoped — the panel hosts a party picker (populated from
 * GET /parties), date range inputs, transaction rows + closing balance.
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

const samplePartyList = {
  count: 2,
  limit: 200,
  offset: 0,
  items: [
    {
      party_id: 'p1111111-1111-1111-1111-111111111111',
      org_id: 'o',
      firm_id: 'f',
      code: 'C0001',
      name: 'Anjali Saree Centre LIVE',
      legal_name: null,
      is_customer: true,
      is_supplier: false,
      is_karigar: false,
      is_transporter: false,
      tax_status: 'REGULAR',
      gstin: '27ABCDE1234F1Z5',
      pan: null,
      email: null,
      phone: null,
      state_code: '27',
      credit_limit: null,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    {
      party_id: 'p2222222-2222-2222-2222-222222222222',
      org_id: 'o',
      firm_id: 'f',
      code: 'S0001',
      name: 'Mumbai Yarn Mills LIVE',
      legal_name: null,
      is_customer: false,
      is_supplier: true,
      is_karigar: false,
      is_transporter: false,
      tax_status: 'REGULAR',
      gstin: '27XYZAB5678F1Z3',
      pan: null,
      email: null,
      phone: null,
      state_code: '27',
      credit_limit: null,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
  ],
};

const sampleStatement = {
  party_id: 'p1111111-1111-1111-1111-111111111111',
  party_name: 'Anjali Saree Centre LIVE',
  from_date: '2026-04-01',
  to_date: '2026-04-30',
  opening_balance: '5000.00',
  closing_balance: '12500.00',
  period_change: '7500.00',
  total_debits: '15000.00',
  total_credits: '7500.00',
  rows: [
    {
      voucher_id: 'v1111111-1111-1111-1111-111111111111',
      voucher_type: 'SALES_INVOICE',
      voucher_date: '2026-04-05',
      series: 'SI/2526',
      number: '0010',
      narration: 'Diwali order — sarees',
      reference_type: 'SalesInvoice',
      reference_id: 'inv-1',
      debit: '15000.00',
      credit: '0.00',
      balance: '20000.00',
    },
    {
      voucher_id: 'v2222222-2222-2222-2222-222222222222',
      voucher_type: 'RECEIPT',
      voucher_date: '2026-04-25',
      series: 'RC/2526',
      number: '0007',
      narration: 'Part payment received',
      reference_type: 'Receipt',
      reference_id: 'rc-1',
      debit: '0.00',
      credit: '7500.00',
      balance: '12500.00',
    },
  ],
};

describe('ReportsHub Party statement — live-mode integration', () => {
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

  function mockEndpoints(stmtBody: unknown = sampleStatement) {
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
      if (u.includes('/parties') && !u.includes('/reports/') && method === 'GET') {
        return jsonResponse(200, samplePartyList);
      }
      if (u.includes('/reports/party-statement/') && method === 'GET') {
        return jsonResponse(200, stmtBody);
      }
      return jsonResponse(404, {});
    });
  }

  it('Party statement tab shows a party picker populated from GET /parties', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Party statement/i }));

    await waitFor(() => expect(screen.getByLabelText(/party/i)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());
    expect(screen.getByText(/Mumbai Yarn Mills LIVE/i)).toBeInTheDocument();
  });

  it('issues GET /reports/party-statement/{id} after a party is selected', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Party statement/i }));

    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());

    const select = screen.getByLabelText(/party/i) as HTMLSelectElement;
    fireEvent.change(select, {
      target: { value: 'p1111111-1111-1111-1111-111111111111' },
    });

    await waitFor(() =>
      expect(
        urlsHit.some(
          (u) =>
            u.startsWith('GET ') &&
            /\/reports\/party-statement\/p1111111-1111-1111-1111-111111111111/.test(u),
        ),
      ).toBe(true),
    );
  });

  it('renders transaction rows + closing balance after selection', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Party statement/i }));

    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());

    const select = screen.getByLabelText(/party/i) as HTMLSelectElement;
    fireEvent.change(select, {
      target: { value: 'p1111111-1111-1111-1111-111111111111' },
    });

    await waitFor(() => expect(screen.getByText(/Diwali order — sarees/i)).toBeInTheDocument());
    expect(screen.getByText(/Part payment received/i)).toBeInTheDocument();
    // Closing balance 12500 → 12.5 K compact INR
    expect(screen.getAllByText(/12\.\d\s*K|12,500/i).length).toBeGreaterThan(0);
  });

  it('shows a pick-a-party empty state before selection', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Party statement/i }));

    await waitFor(() => expect(screen.getByText(/pick a party to view/i)).toBeInTheDocument());
  });
});
