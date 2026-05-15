/*
 * ReportsHub — TASK-TR-B04 Ledger statement tab live-mode integration tests.
 *
 * The backend's `GET /reports/ledger/{ledger_id}?from=&to=` endpoint is
 * already live; this task wires the FE consumer. The panel renders a
 * ledger picker (populated by GET /ledgers), date range inputs, and
 * the statement table with running balance.
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

const sampleLedgerList = {
  count: 2,
  limit: 200,
  offset: 0,
  items: [
    {
      ledger_id: 'l1111111-1111-1111-1111-111111111111',
      org_id: 'o',
      firm_id: 'f',
      code: '1100',
      name: 'Cash in hand LIVE',
      ledger_type: 'CASH',
      coa_group_id: 'g',
      is_control_account: false,
      party_id: null,
      opening_balance: '0.00',
      opening_balance_date: null,
      is_active: true,
      deleted_at: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    {
      ledger_id: 'l2222222-2222-2222-2222-222222222222',
      org_id: 'o',
      firm_id: 'f',
      code: '1200',
      name: 'Sundry Debtors LIVE',
      ledger_type: 'DEBTOR_CONTROL',
      coa_group_id: 'g',
      is_control_account: true,
      party_id: null,
      opening_balance: '0.00',
      opening_balance_date: null,
      is_active: true,
      deleted_at: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
  ],
};

const sampleStatement = {
  ledger_id: 'l1111111-1111-1111-1111-111111111111',
  ledger_code: '1100',
  ledger_name: 'Cash in hand LIVE',
  group_code: 'ASSETS',
  from_date: '2026-04-01',
  to_date: '2026-04-30',
  opening_balance: '10000.00',
  closing_balance: '17500.00',
  total_debits: '12500.00',
  total_credits: '5000.00',
  rows: [
    {
      voucher_id: 'v1111111-1111-1111-1111-111111111111',
      voucher_type: 'RECEIPT',
      voucher_date: '2026-04-05',
      series: 'RC/2526',
      number: '0010',
      description: 'Cash receipt — Anjali',
      narration: null,
      debit: '12500.00',
      credit: '0.00',
      balance: '22500.00',
    },
    {
      voucher_id: 'v2222222-2222-2222-2222-222222222222',
      voucher_type: 'PAYMENT',
      voucher_date: '2026-04-20',
      series: 'PY/2526',
      number: '0007',
      description: 'Office rent',
      narration: null,
      debit: '0.00',
      credit: '5000.00',
      balance: '17500.00',
    },
  ],
};

describe('ReportsHub Ledger statement — live-mode integration', () => {
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
      if (u.includes('/ledgers') && !u.includes('/reports/') && method === 'GET') {
        return jsonResponse(200, sampleLedgerList);
      }
      if (u.includes('/reports/ledger/') && method === 'GET') {
        return jsonResponse(200, stmtBody);
      }
      return jsonResponse(404, {});
    });
  }

  it('Ledger statement tab shows a ledger picker populated from GET /ledgers', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ledger/i }));

    await waitFor(() => expect(screen.getByLabelText(/ledger/i)).toBeInTheDocument());
    // The picker is rendered as a <select>; the second option is the
    // Sundry Debtors ledger. Wait for the ledgers list fetch to land.
    await waitFor(() => expect(screen.getByText(/Sundry Debtors LIVE/i)).toBeInTheDocument());
  });

  it('issues GET /reports/ledger/{id} after the user picks a ledger', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ledger/i }));

    await waitFor(() => expect(screen.getByText(/Sundry Debtors LIVE/i)).toBeInTheDocument());

    const select = screen.getByLabelText(/ledger/i) as HTMLSelectElement;
    fireEvent.change(select, {
      target: { value: 'l1111111-1111-1111-1111-111111111111' },
    });

    await waitFor(() =>
      expect(
        urlsHit.some(
          (u) =>
            u.startsWith('GET ') &&
            /\/reports\/ledger\/l1111111-1111-1111-1111-111111111111/.test(u),
        ),
      ).toBe(true),
    );
  });

  it('renders the statement rows + running balance after selection', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ledger/i }));

    await waitFor(() => expect(screen.getByText(/Sundry Debtors LIVE/i)).toBeInTheDocument());

    const select = screen.getByLabelText(/ledger/i) as HTMLSelectElement;
    fireEvent.change(select, {
      target: { value: 'l1111111-1111-1111-1111-111111111111' },
    });

    await waitFor(() => expect(screen.getByText(/Cash receipt — Anjali/i)).toBeInTheDocument());
    // Both rows render
    expect(screen.getByText(/Office rent/i)).toBeInTheDocument();
    // Running balance column shows the closing balance row value.
    // 17500 rupees → compact INR (17.5 K).
    expect(screen.getAllByText(/17\.\d\s*K|17,500/i).length).toBeGreaterThan(0);
  });

  it('renders an empty-state when no ledger is selected', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ledger/i }));

    // The empty-state copy distinguishes itself from the picker's
    // "— Choose a ledger —" option by mentioning the statement.
    await waitFor(() => expect(screen.getByText(/pick a ledger to view/i)).toBeInTheDocument());
  });

  it('appends from/to query params when the user changes the date range', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ledger/i }));

    await waitFor(() => expect(screen.getByText(/Sundry Debtors LIVE/i)).toBeInTheDocument());

    const select = screen.getByLabelText(/ledger/i) as HTMLSelectElement;
    fireEvent.change(select, {
      target: { value: 'l1111111-1111-1111-1111-111111111111' },
    });

    const fromInput = screen.getByLabelText(/from date/i);
    fireEvent.change(fromInput, { target: { value: '2026-04-01' } });
    const toInput = screen.getByLabelText(/to date/i);
    fireEvent.change(toInput, { target: { value: '2026-04-30' } });

    await waitFor(() =>
      expect(
        urlsHit.some((u) =>
          /\/reports\/ledger\/l1111111-1111-1111-1111-111111111111\?.*from=2026-04-01.*to=2026-04-30/.test(
            u,
          ),
        ),
      ).toBe(true),
    );
  });
});
