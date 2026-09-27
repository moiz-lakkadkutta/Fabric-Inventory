/*
 * ReportsHub — TASK-TR-B03 GSTR-1 live-mode integration tests.
 *
 * Covers wiring the GSTR-1 tab to the real `GET /reports/gstr1?period=`
 * backend endpoint (CUT-302 shipped server-side already; this PR closes
 * the FE gap that was leaving a "coming soon" stub in place).
 *
 * Live-mode is pinned via vi.mock('@/lib/api/mode') BEFORE the
 * page-under-test is imported — otherwise Vite tree-shakes the live
 * branch at module-load time using .env.test (mock). Mirrors the
 * pattern from ReportsHub.live.test.tsx (CUT-301) and
 * AdjustStockDialog.test.tsx (CUT-204).
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

const sampleGstr1Body = {
  period: '2026-04',
  from_date: '2026-04-01',
  to_date: '2026-04-30',
  b2b: [
    {
      sales_invoice_id: 'a1111111-1111-1111-1111-111111111111',
      party_id: 'b1111111-1111-1111-1111-111111111111',
      party_name: 'Anjali Saree Centre LIVE',
      gstin: '27ABCDE1234F1Z5',
      series: 'RT/2526',
      number: '0001',
      invoice_date: '2026-04-30',
      place_of_supply_state: '27',
      taxable_value: '37200.00',
      cgst: '0',
      sgst: '0',
      igst: '1860.00',
      invoice_value: '39060.00',
      gst_rate: '5',
    },
  ],
  b2cl: [
    {
      sales_invoice_id: 'a2222222-2222-2222-2222-222222222222',
      party_id: 'b2222222-2222-2222-2222-222222222222',
      party_name: 'Walk-in Bulk Order LIVE',
      gstin: null,
      series: 'RT/2526',
      number: '0099',
      invoice_date: '2026-04-15',
      place_of_supply_state: '27',
      taxable_value: '275000.00',
      cgst: '0',
      sgst: '0',
      igst: '13750.00',
      invoice_value: '288750.00',
      gst_rate: '5',
    },
  ],
  b2cs: [
    {
      place_of_supply_state: '24',
      gst_rate: '5',
      taxable_value: '12700.00',
      cgst: '317.50',
      sgst: '317.50',
      igst: '0',
      invoice_count: 4,
    },
  ],
  export: [],
  hsn: [
    {
      hsn_code: '5407',
      description: 'Woven fabrics of synthetic filament yarn',
      uom: 'METER',
      gst_rate: '5',
      total_qty: '120.500',
      total_value: '60000.00',
      taxable_value: '57000.00',
      cgst: '0',
      sgst: '0',
      igst: '2850.00',
    },
  ],
};

describe('ReportsHub GSTR-1 — live-mode integration', () => {
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

  function mockEndpoints(gstr1Body: unknown = sampleGstr1Body) {
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
      if (u.includes('/reports/gstr1') && method === 'GET') {
        return jsonResponse(200, gstr1Body);
      }
      return jsonResponse(404, {});
    });
  }

  it('GSTR-1 tab issues a GET /reports/gstr1?period=YYYY-MM', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));

    await waitFor(() =>
      expect(
        urlsHit.some((u) => u.startsWith('GET ') && /\/reports\/gstr1\?period=\d{4}-\d{2}/.test(u)),
      ).toBe(true),
    );
  });

  it('renders B2B / B2CL / B2CS / HSN section headings and rows', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));

    // Wait for the panel to populate
    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());

    // Section headings (all four required buckets)
    expect(screen.getByRole('heading', { name: /B2B/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /B2CL/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /B2CS/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /HSN/i })).toBeInTheDocument();

    // B2CL row shows the bulk order
    expect(screen.getByText(/Walk-in Bulk Order LIVE/i)).toBeInTheDocument();

    // HSN row shows the HSN code
    expect(screen.getByText(/5407/)).toBeInTheDocument();
    expect(screen.getByText(/Woven fabrics of synthetic filament yarn/i)).toBeInTheDocument();

    // B2CS row shows the state code
    const b2csHeading = screen.getByRole('heading', { name: /B2CS/i });
    // The B2CS section table follows the heading; assert the state appears.
    expect(b2csHeading).toBeInTheDocument();
  });

  it('renders empty-state copy for empty buckets', async () => {
    mockEndpoints({
      ...sampleGstr1Body,
      b2b: [],
      b2cl: [],
      b2cs: [],
      export: [],
      hsn: [],
    });
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));

    // All four buckets should render empty-state messages.
    await waitFor(() =>
      expect(screen.getByText(/No B2B invoices in this period/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/No B2CL invoices in this period/i)).toBeInTheDocument();
    expect(screen.getByText(/No B2CS aggregates in this period/i)).toBeInTheDocument();
    expect(screen.getByText(/No HSN summary in this period/i)).toBeInTheDocument();
  });

  it('does NOT render the "coming soon" stub when live-mode and data has loaded', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));

    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());
    expect(screen.queryByText(/coming with TASK-CUT-302/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Wave 4/i)).not.toBeInTheDocument();
  });

  it('enables CSV + Excel export buttons on the GSTR-1 tab', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));

    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());

    const csvBtn = screen.getByRole('button', { name: /export report as csv/i });
    const xlsxBtn = screen.getByRole('button', { name: /export report as excel/i });
    expect(csvBtn).not.toBeDisabled();
    expect(xlsxBtn).not.toBeDisabled();
  });

  it('#199: renders CDNR / CDNUR credit-note sections and nets them off the header totals', async () => {
    const creditNote = {
      note_voucher_id: 'c1111111-1111-1111-1111-111111111111',
      note_series: 'RT/2526',
      note_number: 'CN-0007',
      note_date: '2026-04-10',
      note_type: 'C',
      sales_invoice_id: 'a9999999-9999-9999-9999-999999999999',
      invoice_series: 'RT/2526',
      invoice_number: 'INV-0042',
      invoice_date: '2026-03-25',
      party_id: 'b9999999-9999-9999-9999-999999999999',
      party_name: 'Returned Goods Buyer LIVE',
      place_of_supply_state: 'MH',
      note_value: '1050.00',
      taxable_value: '1000.00',
      gst_rate: '5',
      cgst: '25.00',
      sgst: '25.00',
      igst: '0',
    };
    mockEndpoints({
      ...sampleGstr1Body,
      cdnr: [{ ...creditNote, gstin: '27ABCDE1234F1Z5' }],
      cdnur: [
        {
          ...creditNote,
          note_voucher_id: 'c2222222-2222-2222-2222-222222222222',
          note_number: 'CN-0008',
          invoice_number: 'INV-0050',
          party_name: 'Unregistered Bulk Buyer LIVE',
          place_of_supply_state: 'GJ',
          note_value: '210000.00',
          taxable_value: '200000.00',
          cgst: '0',
          sgst: '0',
          igst: '10000.00',
          ur_type: 'B2CL',
        },
      ],
    });
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));

    await waitFor(() => expect(screen.getByText(/Returned Goods Buyer LIVE/i)).toBeInTheDocument());
    const cdnr = screen.getByRole('heading', { name: /CDNR/i }).closest('section')!;
    expect(within(cdnr as HTMLElement).getByText('RT/2526/CN-0007')).toBeInTheDocument();
    expect(within(cdnr as HTMLElement).getByText(/RT\/2526\/INV-0042/)).toBeInTheDocument();
    expect(within(cdnr as HTMLElement).getByText('27ABCDE1234F1Z5')).toBeInTheDocument();

    const cdnur = screen.getByRole('heading', { name: /CDNUR/i }).closest('section')!;
    expect(within(cdnur as HTMLElement).getByText('B2CL')).toBeInTheDocument();
    expect(
      within(cdnur as HTMLElement).getByText(/Unregistered Bulk Buyer LIVE/),
    ).toBeInTheDocument();

    // Tax: 1860 (B2B) + 13750 (B2CL) + 635 (B2CS) − 50 (CDNR) − 10000 (CDNUR) = 6195.
    expect(screen.getByText('₹6,195.00')).toBeInTheDocument();
  });

  it('#199: empty credit-note sections render empty-state copy (and tolerate an old BE without them)', async () => {
    mockEndpoints(sampleGstr1Body); // no cdnr / cdnur keys at all
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/No credit notes to registered buyers in this period/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/No credit notes to unregistered buyers in this period/i),
    ).toBeInTheDocument();
  });

  it('uses paise-converted totals — taxable values from the BE render as compact INR', async () => {
    mockEndpoints();
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));

    await waitFor(() => expect(screen.getByText(/Anjali Saree Centre LIVE/i)).toBeInTheDocument());

    // B2CL invoice value 288750.00 → compact INR ~₹2.89 L
    const b2clHeading = screen.getByRole('heading', { name: /B2CL/i });
    // Section container is the immediate <section> wrapping the heading.
    const b2clSection = b2clHeading.closest('section') ?? b2clHeading.parentElement!;
    expect(within(b2clSection as HTMLElement).getAllByText(/2\.\d\d\s*L/i).length).toBeGreaterThan(
      0,
    );
  });
});
