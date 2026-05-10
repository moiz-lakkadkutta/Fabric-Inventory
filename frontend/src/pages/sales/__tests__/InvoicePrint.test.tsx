/*
 * InvoiceDetail Print button — TASK-CUT-205 vitest.
 *
 * Verifies the live-mode wiring end-to-end:
 *   1. Render the InvoiceDetail page for a FINALIZED invoice (mocked
 *      backend response).
 *   2. Click "Print".
 *   3. Assert that:
 *      a) GET /invoices/<id>/pdf was hit with `Authorization: Bearer ...`.
 *      b) URL.createObjectURL was called with the returned Blob.
 *      c) An <a download="..."> click was synthesised so the browser
 *         starts a save-as.
 *
 * Live-mode pin must come BEFORE the page is imported, otherwise the
 * IS_LIVE constant gets locked at the .env.test default ('mock') and
 * the live branch is dead code at test time.
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

describe('InvoiceDetail — Print PDF (CUT-205)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;
  let createObjectURLSpy: ReturnType<typeof vi.fn>;
  let revokeObjectURLSpy: ReturnType<typeof vi.fn>;
  let anchorClickSpy: ReturnType<typeof vi.fn>;
  const fakeBlobUrl = 'blob:http://localhost/abcdef';

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

    fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : ((input as Request).url ?? String(input));
      if (url.endsWith('/invoices/inv-uuid-1') && !url.endsWith('/pdf')) {
        return jsonResponse(200, {
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
          lifecycle_status: 'FINALIZED',
          finalized_at: '2026-05-01T05:00:00Z',
          tax_type: 'CGST_SGST',
          round_off: '0.00',
          notes: null,
          lines: [
            {
              si_line_id: 'l1',
              item_id: 'i1',
              item_name: 'Chiffon Silk',
              item_uom: 'METER',
              qty: '10.0000',
              price: '1000.00',
              line_amount: '10000.00',
              gst_rate: '5.00',
              gst_amount: '500.00',
              sequence: 1,
            },
          ],
          created_at: '2026-04-30T05:00:00Z',
          updated_at: '2026-04-30T05:00:00Z',
        });
      }
      if (url.endsWith('/invoices/inv-uuid-1/pdf')) {
        return pdfResponse();
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    createObjectURLSpy = vi.fn().mockReturnValue(fakeBlobUrl);
    revokeObjectURLSpy = vi.fn();
    // jsdom's URL doesn't ship createObjectURL — define it.
    Object.defineProperty(URL, 'createObjectURL', {
      value: createObjectURLSpy,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: revokeObjectURLSpy,
      writable: true,
      configurable: true,
    });

    // Capture <a>.click() so we can assert the download was triggered
    // without a real navigation.
    anchorClickSpy = vi.fn();
    const realCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag.toLowerCase() === 'a') {
        // Override click on this instance only — leaves other anchors alone.
        Object.defineProperty(el, 'click', {
          value: anchorClickSpy,
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

  it('hits the PDF endpoint with auth and triggers a download on click', async () => {
    renderDetail();
    // Wait for the detail payload to render.
    await waitFor(() => expect(screen.getByText(/Finalized/i)).toBeInTheDocument());

    const printBtn = screen.getByRole('button', { name: /print/i });
    expect(printBtn).not.toBeDisabled();
    fireEvent.click(printBtn);

    await waitFor(() => expect(createObjectURLSpy).toHaveBeenCalledTimes(1));

    // The PDF endpoint was hit with the access token.
    const pdfCall = (fetchMock.mock.calls as unknown[][]).find((args) =>
      String(args[0]).endsWith('/invoices/inv-uuid-1/pdf'),
    );
    expect(pdfCall, 'expected a fetch to /invoices/<id>/pdf').toBeTruthy();
    const init = pdfCall![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer token-abc');
    expect(headers['Accept']).toBe('application/pdf');

    // The blob produced an object URL and the synthesised anchor was clicked.
    // Note: undici / jsdom expose Blob through a different realm than the
    // page's `Blob` constructor, so a plain `instanceof Blob` would be a
    // false negative. Duck-type on the structural shape instead.
    const blobArg = createObjectURLSpy.mock.calls[0][0] as Blob;
    expect(blobArg).toBeDefined();
    expect(blobArg.type).toBe('application/pdf');
    expect(blobArg.size).toBeGreaterThan(0);
    expect(anchorClickSpy).toHaveBeenCalledTimes(1);
  });
});
