/*
 * ReportsHub — TASK-TR-B04 Ageing tab live-mode integration tests.
 *
 * The backend's `GET /reports/ageing` endpoint was already live; this
 * task wires the FE consumer. The panel renders the per-party rows
 * with the five buckets (current / 1-30 / 31-60 / 61-90 / >90) plus
 * the total outstanding banner.
 *
 * Mirrors ReportsHub.gstr1.test.tsx (TASK-TR-B03) for the live-mode
 * pinning, fetch-mock harness, and authStore boilerplate.
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

const sampleAgeing = {
  as_of: '2026-05-15',
  total_outstanding: '125000.00',
  rows: [
    {
      party_id: 'p1111111-1111-1111-1111-111111111111',
      party_name: 'Anjali Saree Centre LIVE',
      outstanding: '85000.00',
      current: '40000.00',
      bucket_1_30: '20000.00',
      bucket_31_60: '15000.00',
      bucket_61_90: '10000.00',
      bucket_over_90: '0.00',
    },
    {
      party_id: 'p2222222-2222-2222-2222-222222222222',
      party_name: 'Walk-in Bulk Order LIVE',
      outstanding: '40000.00',
      current: '0.00',
      bucket_1_30: '0.00',
      bucket_31_60: '0.00',
      bucket_61_90: '0.00',
      bucket_over_90: '40000.00',
    },
  ],
};

describe('ReportsHub Ageing — live-mode integration', () => {
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

  function mockEndpoints(body: unknown = sampleAgeing) {
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
      if (u.includes('/reports/ageing') && method === 'GET') {
        return jsonResponse(200, body);
      }
      return jsonResponse(404, {});
    });
  }

  it('Ageing tab issues a GET /reports/ageing', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ageing/i }));

    await waitFor(() =>
      expect(urlsHit.some((u) => u.startsWith('GET ') && /\/reports\/ageing/.test(u))).toBe(true),
    );
  });

  it('renders party rows with the five buckets', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ageing/i }));

    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());
    expect(screen.getByText(/Walk-in Bulk Order LIVE/i)).toBeInTheDocument();
    // Bucket headers
    expect(screen.getByText(/^Current$/i)).toBeInTheDocument();
    expect(screen.getByText(/1[-–]30/)).toBeInTheDocument();
    expect(screen.getByText(/31[-–]60/)).toBeInTheDocument();
    expect(screen.getByText(/61[-–]90/)).toBeInTheDocument();
    expect(screen.getByText(/>\s*90|over\s*90/i)).toBeInTheDocument();
  });

  it('renders the total outstanding banner from the response', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ageing/i }));

    // Wait for the data to load so the KPI banner switches from '—' to
    // a real INR value. Total outstanding 1.25 L (125000 rupees) →
    // compact INR "₹1.25 L".
    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());
    expect(screen.getByText(/total outstanding/i)).toBeInTheDocument();
    expect(screen.getAllByText(/1\.\d\d\s*L/i).length).toBeGreaterThan(0);
  });

  it('renders empty-state when there are no parties with outstanding balances', async () => {
    mockEndpoints({
      as_of: '2026-05-15',
      total_outstanding: '0.00',
      rows: [],
    });
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ageing/i }));

    await waitFor(() =>
      expect(screen.getByText(/no parties? with outstanding/i)).toBeInTheDocument(),
    );
  });

  it('allows the user to change the as-of date and refetches', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /Ageing/i }));

    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());

    const dateInput = screen.getByLabelText(/as of/i);
    fireEvent.change(dateInput, { target: { value: '2026-04-30' } });

    await waitFor(() =>
      expect(urlsHit.some((u) => /\/reports\/ageing\?as_of=2026-04-30/.test(u))).toBe(true),
    );
  });
});
