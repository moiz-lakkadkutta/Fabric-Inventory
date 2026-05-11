/*
 * ReportsHub — TASK-CUT-301 live-mode integration tests.
 *
 * One spec per tab. Each spec asserts that the ReportsHub:
 *   1. Issues a GET against the relevant /reports/* endpoint.
 *   2. Renders real values from the backend envelope (not the mock).
 *
 * Live-mode pin must happen via vi.mock('@/lib/api/mode') BEFORE the
 * page-under-test is imported. Without that, IS_LIVE is captured at
 * module load from .env.test (VITE_API_MODE=mock) and Vite tree-shakes
 * the live branch away. Mirrors the pattern from
 * pages/inventory/__tests__/AdjustStockDialog.test.tsx (CUT-204).
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

describe('ReportsHub — live-mode integration', () => {
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

  it('P&L tab pulls real numbers from GET /reports/pnl', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      urlsHit.push(`${method} ${u}`);
      if (u.includes('/reports/pnl') && method === 'GET') {
        return jsonResponse(200, {
          period: { from_date: '2026-04-01', to_date: '2026-04-30' },
          total_income: '987654.32',
          cogs: '500000.00',
          gross_profit: '487654.32',
          expenses: '100000.00',
          net_profit: '387654.32',
          by_ledger_group: [
            {
              group_code: 'INCOME',
              group_name: 'Sales — Tax invoices',
              group_type: 'INCOME',
              current_period_amount: '987654.32',
              prior_period_amount: '750000.00',
              variance_pct: '31.69',
            },
            {
              group_code: 'COGS',
              group_name: 'Purchases',
              group_type: 'COGS',
              current_period_amount: '500000.00',
              prior_period_amount: '450000.00',
              variance_pct: '11.11',
            },
            {
              group_code: 'EXPENSE',
              group_name: 'Salaries',
              group_type: 'EXPENSE',
              current_period_amount: '100000.00',
              prior_period_amount: '95000.00',
              variance_pct: '5.26',
            },
          ],
        });
      }
      return jsonResponse(404, {});
    });

    renderReports();

    await waitFor(() =>
      expect(urlsHit.some((u) => u.startsWith('GET ') && u.includes('/reports/pnl'))).toBe(true),
    );

    // The "Sales — Tax invoices" group row from the BE payload should appear.
    await waitFor(() => expect(screen.getByText(/Sales — Tax invoices/i)).toBeInTheDocument());
    // The unique total-income value (₹9.88L) renders in compact form.
    await waitFor(() => expect(screen.getAllByText(/9\.88\s*L/i).length).toBeGreaterThan(0));
  });

  it('Trial Balance tab pulls real numbers from GET /reports/tb', async () => {
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
      if (u.includes('/reports/tb') && method === 'GET') {
        return jsonResponse(200, {
          as_of: '2026-04-30',
          total_debits: '150000.00',
          total_credits: '150000.00',
          balanced: true,
          rows: [
            {
              ledger_id: '11111111-1111-1111-1111-111111111111',
              ledger_code: '1100',
              ledger_name: 'Sundry Debtors — Live',
              group_code: 'ASSETS',
              debit: '150000.00',
              credit: '0',
            },
            {
              ledger_id: '22222222-2222-2222-2222-222222222222',
              ledger_code: '4000',
              ledger_name: 'Sales — Tax invoices',
              group_code: 'REVENUE',
              debit: '0',
              credit: '150000.00',
            },
          ],
        });
      }
      return jsonResponse(404, {});
    });

    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /trial balance/i }));

    await waitFor(() =>
      expect(urlsHit.some((u) => u.startsWith('GET ') && u.includes('/reports/tb'))).toBe(true),
    );

    // Real ledger names from the BE payload should render.
    await waitFor(() => expect(screen.getByText(/Sundry Debtors — Live/i)).toBeInTheDocument());
    // Balanced banner shows.
    expect(screen.getByText(/balanced/i)).toBeInTheDocument();
  });

  it('Daybook tab pulls real vouchers from GET /reports/daybook', async () => {
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
      if (u.includes('/reports/daybook') && method === 'GET') {
        return jsonResponse(200, {
          date: '2026-05-10',
          vouchers: [
            {
              voucher_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
              voucher_type: 'SALES_INVOICE',
              series: 'RT/2526',
              number: '0099',
              narration: 'Sale — Live ACME Customer',
              total_debit: '12345.00',
              total_credit: '12345.00',
              party_name: 'Live ACME Customer',
            },
          ],
        });
      }
      return jsonResponse(404, {});
    });

    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /daybook/i }));

    await waitFor(() =>
      expect(urlsHit.some((u) => u.startsWith('GET ') && u.includes('/reports/daybook'))).toBe(
        true,
      ),
    );

    await waitFor(() => expect(screen.getByText(/Live ACME Customer/i)).toBeInTheDocument());
  });

  it('Stock summary tab pulls real rows from GET /reports/stock-summary', async () => {
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
      if (u.includes('/reports/stock-summary') && method === 'GET') {
        return jsonResponse(200, {
          as_of: '2026-04-30',
          total_value: '500000.00',
          rows: [
            {
              sku_id: null,
              item_id: '33333333-3333-3333-3333-333333333333',
              item_code: 'LIVE-FABRIC',
              item_name: 'Live Banarasi Silk',
              sku_code: null,
              on_hand_qty: '100.000',
              uom: 'METER',
              avg_cost: '5000.00',
              valuation: '500000.00',
            },
          ],
        });
      }
      return jsonResponse(404, {});
    });

    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /^stock$/i }));

    await waitFor(() =>
      expect(
        urlsHit.some((u) => u.startsWith('GET ') && u.includes('/reports/stock-summary')),
      ).toBe(true),
    );

    await waitFor(() => expect(screen.getByText(/Live Banarasi Silk/i)).toBeInTheDocument());
    // The total-value strip renders the BE's total (₹5L compact).
    expect(screen.getAllByText(/5\.00\s*L/i).length).toBeGreaterThan(0);
  });
});
