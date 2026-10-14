/*
 * InvoiceDetail — "Discard draft" (DRAFT → DISCARDED).
 *
 * Live mode: a DRAFT invoice shows a "Discard draft" action; it opens a
 * confirmation dialog; confirming POSTs /invoices/<id>/discard with an
 * Idempotency-Key and the page flips to "Discarded". "Keep draft" closes
 * the dialog without a request. Non-draft invoices don't offer the action.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: InvoiceDetail } = await import('@/pages/sales/InvoiceDetail');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function invoiceBody(lifecycle: string) {
  return {
    sales_invoice_id: 'inv-d1',
    org_id: 'org1',
    firm_id: 'firm1',
    series: 'RT/2526',
    number: '0007',
    party_id: 'p1',
    party_name: 'Anjali Saree Centre',
    delivery_challan_id: null,
    salesperson_id: null,
    invoice_date: '2026-05-01',
    bill_to_address: null,
    ship_to_address: null,
    place_of_supply_state: 'MH',
    invoice_type: 'TAX_INVOICE',
    invoice_amount: '1050.00',
    gst_amount: '50.00',
    paid_amount: '0.00',
    due_date: '2026-05-15',
    lifecycle_status: lifecycle,
    finalized_at: null,
    tax_type: 'CGST_SGST',
    round_off: '0.00',
    notes: null,
    lines: [],
    created_at: '2026-05-01T05:00:00Z',
    updated_at: '2026-05-01T05:00:00Z',
  };
}

function renderDetail() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/sales/invoices/inv-d1']}>
        <Routes>
          <Route path="/sales/invoices/:id" element={<InvoiceDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InvoiceDetail — Discard draft', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;
  let lifecycle: string;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    lifecycle = 'DRAFT';
    authStore.reset();
    authStore.setAccessToken('token-abc');
    authStore.setMe({
      user_id: 'u1',
      org_id: 'org1',
      firm_id: 'firm1',
      email: 'm@example.com',
      permissions: ['sales.invoice.read', 'sales.invoice.cancel'],
      flags: {},
      available_firms: [],
      token_expires_at: new Date(Date.now() + 60_000).toISOString(),
    });
    fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : ((input as Request).url ?? String(input));
      if (url.endsWith('/invoices/inv-d1/discard') && init?.method === 'POST') {
        lifecycle = 'DISCARDED';
        return jsonResponse(200, invoiceBody('DISCARDED'));
      }
      if (url.endsWith('/invoices/inv-d1')) return jsonResponse(200, invoiceBody(lifecycle));
      if (url.includes('/invoices?'))
        return jsonResponse(200, { items: [], limit: 200, offset: 0, count: 0 });
      throw new Error(`unexpected fetch ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    authStore.reset();
    vi.restoreAllMocks();
  });

  const discardCalls = () =>
    (fetchMock.mock.calls as unknown[][]).filter((args) =>
      String(args[0]).endsWith('/invoices/inv-d1/discard'),
    );

  it('confirms, POSTs /discard with an Idempotency-Key, and shows Discarded', async () => {
    renderDetail();
    const open = await screen.findByRole('button', { name: /discard draft/i });
    fireEvent.click(open);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/will not be reused/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /discard draft/i }));

    await waitFor(() => expect(discardCalls()).toHaveLength(1));
    const init = discardCalls()[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get('Idempotency-Key')).toBeTruthy();

    await waitFor(() => expect(screen.getByText('Discarded')).toBeInTheDocument());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /discard draft/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /finalize/i })).not.toBeInTheDocument();
  });

  it('"Keep draft" closes the dialog without a request', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: /discard draft/i }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: /keep draft/i }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(discardCalls()).toHaveLength(0);
  });

  it('is not offered for a finalized invoice', async () => {
    lifecycle = 'FINALIZED';
    renderDetail();
    await screen.findByText('Finalized');
    expect(screen.queryByRole('button', { name: /discard draft/i })).not.toBeInTheDocument();
  });
});
