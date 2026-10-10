/*
 * InvoiceDetail — "Download credit note" (#216).
 *
 * A CANCELLED invoice whose cancel was a CGST §34 credit note (the backend
 * sets `credit_note` on the detail payload) offers a download of the
 * Rule 53(1A) credit-note PDF from GET /invoices/<id>/credit-note/pdf,
 * mirroring the Print (invoice PDF) pattern. A same-period cancellation
 * (`credit_note: null`) and every non-cancelled invoice show no such action.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

function pdfResponse(): Response {
  // Minimal valid-PDF preamble. Production responses are kilobytes; one
  // page suffices for the assertion.
  const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37, 0x0a, 0x25, 0xe2]);
  return new Response(bytes, {
    status: 200,
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': 'attachment; filename="RT_2526-0042.pdf"',
    },
  });
}

function detailPayload(overrides: Record<string, unknown>) {
  return {
    sales_invoice_id: 'inv-uuid-1',
    org_id: 'org1',
    firm_id: 'firm1',
    series: 'RT/2526',
    number: '0042',
    party_id: 'p1',
    party_name: 'Anjali Saree Centre',
    delivery_challan_id: null,
    salesperson_id: null,
    invoice_date: '2026-04-30',
    bill_to_address: null,
    ship_to_address: null,
    place_of_supply_state: 'MH',
    invoice_type: 'TAX_INVOICE',
    invoice_amount: '10500.00',
    gst_amount: '500.00',
    paid_amount: '0.00',
    due_date: '2026-05-15',
    lifecycle_status: 'CANCELLED',
    finalized_at: '2026-05-01T05:00:00Z',
    tax_type: 'CGST_SGST',
    round_off: '0.00',
    notes: null,
    lines: [],
    created_at: '2026-04-30T05:00:00Z',
    updated_at: '2026-04-30T05:00:00Z',
    credit_note: {
      voucher_id: 'cn-uuid-1',
      number: 'CN/26-27/0001',
      note_date: '2026-05-10',
    },
    ...overrides,
  };
}

function renderDetail(id = 'inv-uuid-1') {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/sales/invoices/${id}`]}>
        <Routes>
          <Route path="/sales/invoices/:id" element={<InvoiceDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InvoiceDetail — Download credit note (#216)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;
  let createObjectURLSpy: ReturnType<typeof vi.fn>;
  let anchorClickSpy: ReturnType<typeof vi.fn>;
  let downloadNames: string[];
  let detail: Record<string, unknown>;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    authStore.reset();
    authStore.setAccessToken('token-abc');
    authStore.setMe({
      user_id: 'u1',
      org_id: 'org1',
      firm_id: 'firm1',
      email: 'm@example.com',
      permissions: ['sales.invoice.read'],
      flags: {},
      available_firms: [],
      token_expires_at: new Date(Date.now() + 60_000).toISOString(),
    });
    detail = detailPayload({});

    fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : ((input as Request).url ?? String(input));
      if (url.endsWith('/invoices/inv-uuid-1')) {
        return jsonResponse(200, detail);
      }
      if (url.endsWith('/invoices/inv-uuid-1/credit-note/pdf')) {
        return pdfResponse();
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    createObjectURLSpy = vi.fn().mockReturnValue('blob:http://localhost/cn');
    Object.defineProperty(URL, 'createObjectURL', {
      value: createObjectURLSpy,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: vi.fn(),
      writable: true,
      configurable: true,
    });

    anchorClickSpy = vi.fn();
    downloadNames = [];
    const realCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag.toLowerCase() === 'a') {
        Object.defineProperty(el, 'click', {
          value: () => {
            downloadNames.push((el as HTMLAnchorElement).download);
            anchorClickSpy();
          },
          writable: true,
          configurable: true,
        });
      }
      return el;
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    authStore.reset();
    vi.restoreAllMocks();
  });

  it('downloads the credit-note PDF for a cancelled invoice that has one', async () => {
    renderDetail();
    await waitFor(() => expect(screen.getByText(/Cancelled/i)).toBeInTheDocument());
    expect(screen.getByText(/CN\/26-27\/0001/)).toBeInTheDocument();

    const btn = screen.getByRole('button', { name: /download credit note/i });
    fireEvent.click(btn);
    await waitFor(() => expect(createObjectURLSpy).toHaveBeenCalledTimes(1));

    const call = (fetchMock.mock.calls as unknown[][]).find((args) =>
      String(args[0]).endsWith('/invoices/inv-uuid-1/credit-note/pdf'),
    );
    expect(call, 'expected a fetch to /invoices/<id>/credit-note/pdf').toBeTruthy();
    const headers = (call![1] as RequestInit).headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer token-abc');
    expect(anchorClickSpy).toHaveBeenCalledTimes(1);
    expect(downloadNames).toEqual(['CN_26-27_0001.pdf']);
  });

  it('shows no credit-note action for a same-period cancellation', async () => {
    detail = detailPayload({ credit_note: null });
    renderDetail();
    await waitFor(() => expect(screen.getByText(/Cancelled/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /download credit note/i })).toBeNull();
  });

  it('shows no credit-note action on a finalized invoice', async () => {
    detail = detailPayload({ lifecycle_status: 'FINALIZED', credit_note: null });
    renderDetail();
    await waitFor(() => expect(screen.getByText(/Finalized/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /download credit note/i })).toBeNull();
  });
});
