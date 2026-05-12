import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Bug B9 — detail pages must show item_name instead of the raw UUID.
 *
 * Procurement responses (PO/GRN/PI) ship `lines[].item_name` after
 * TASK-CUT-QA-03a. These tests force IS_LIVE=true, stub fetch with a
 * payload that includes `item_name: 'Cotton Suit'`, and assert the
 * rendered cell shows the name (and DOES NOT show the UUID prefix
 * fallback).
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: PurchaseOrderDetail } = await import('@/pages/purchase/PurchaseOrderDetail');
const { default: GrnDetail } = await import('@/pages/purchase/GrnDetail');
const { default: PurchaseInvoiceDetail } = await import('@/pages/purchase/PurchaseInvoiceDetail');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const FIRM_ID = 'f1111111-1111-1111-1111-111111111111';
const PARTY_ID = 'c1111111-1111-1111-1111-111111111111';
const ITEM_ID = '81bc3ff5-1111-1111-1111-111111111111';
const PO_ID = 'a1111111-1111-1111-1111-111111111111';
const PO_LINE_ID = 'a2222222-2222-2222-2222-222222222222';
const GRN_ID = 'd1111111-1111-1111-1111-111111111111';
const PI_ID = 'a3333333-3333-3333-3333-333333333333';

function makeQc() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function renderRoute(initial: string) {
  const qc = makeQc();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/purchase/:id" element={<PurchaseOrderDetail />} />
          <Route path="/purchase/grns/:id" element={<GrnDetail />} />
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
      'purchase.po.read',
      'purchase.po.approve',
      'purchase.grn.read',
      'purchase.grn.approve',
      'purchase.invoice.read',
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

describe('PurchaseOrderDetail — renders item_name (B9)', () => {
  it('shows "Cotton Suit" on the line, not the item UUID prefix', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes(`/purchase-orders/${PO_ID}`)) {
        return jsonResponse(200, {
          purchase_order_id: PO_ID,
          org_id: 'o1',
          firm_id: FIRM_ID,
          series: 'PO/25-26',
          number: 'PO/25-26/0001',
          party_id: PARTY_ID,
          po_date: '2026-05-09',
          delivery_date: null,
          status: 'CONFIRMED',
          total_amount: '50000.00',
          notes: null,
          lines: [
            {
              po_line_id: PO_LINE_ID,
              item_id: ITEM_ID,
              item_name: 'Cotton Suit',
              qty_ordered: '50.000',
              qty_received: '0',
              rate: '1000.00',
              line_amount: '50000.00',
              line_sequence: 1,
              taxes_applicable: null,
              notes: null,
            },
          ],
          created_at: '2026-05-09T00:00:00Z',
          updated_at: '2026-05-09T00:00:00Z',
        });
      }
      if (u.includes(`/parties/${PARTY_ID}`)) {
        return jsonResponse(200, {
          party_id: PARTY_ID,
          name: 'Acme Supplier',
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderRoute(`/purchase/${PO_ID}`);
    await waitFor(() => expect(screen.getByText('Cotton Suit')).toBeInTheDocument());
    expect(screen.queryByText(ITEM_ID.slice(0, 8))).not.toBeInTheDocument();
  });
});

describe('GrnDetail — renders item_name (B9)', () => {
  it('shows "Cotton Suit" on the line, not the item UUID prefix', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes(`/grns/${GRN_ID}`)) {
        return jsonResponse(200, {
          grn_id: GRN_ID,
          org_id: 'o1',
          firm_id: FIRM_ID,
          series: 'GRN/25-26',
          number: 'GRN/25-26/0001',
          party_id: PARTY_ID,
          purchase_order_id: PO_ID,
          grn_date: '2026-05-10',
          status: 'DRAFT',
          total_qty_received: '50.000',
          total_amount: '50000.00',
          notes: null,
          lines: [
            {
              grn_line_id: 'd2222222-2222-2222-2222-222222222222',
              grn_id: GRN_ID,
              item_id: ITEM_ID,
              item_name: 'Cotton Suit',
              po_line_id: PO_LINE_ID,
              qty_received: '50.000',
              rate: '1000.00',
              lot_number: 'LOT-1',
              line_sequence: 1,
            },
          ],
          created_at: '2026-05-10T00:00:00Z',
          updated_at: '2026-05-10T00:00:00Z',
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderRoute(`/purchase/grns/${GRN_ID}`);
    await waitFor(() => expect(screen.getByText('Cotton Suit')).toBeInTheDocument());
    // Fallback prefix (with trailing ellipsis) must not appear.
    expect(screen.queryByText(`${ITEM_ID.slice(0, 8)}…`)).not.toBeInTheDocument();
  });
});

describe('PurchaseInvoiceDetail — renders item_name (B9)', () => {
  it('shows "Cotton Suit" on the line, not the item UUID prefix', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes(`/purchase-invoices/${PI_ID}`)) {
        return jsonResponse(200, {
          purchase_invoice_id: PI_ID,
          org_id: 'o1',
          firm_id: FIRM_ID,
          series: 'PI/25-26',
          number: 'PI/25-26/0001',
          party_id: PARTY_ID,
          grn_id: null,
          invoice_date: '2026-05-11',
          invoice_amount: '50000.00',
          gst_amount: '0.00',
          rcm_applicable: false,
          status: 'DRAFT',
          lifecycle_status: 'DRAFT',
          paid_amount: '0',
          due_date: null,
          notes: null,
          lines: [
            {
              pi_line_id: 'a4444444-4444-4444-4444-444444444444',
              purchase_invoice_id: PI_ID,
              item_id: ITEM_ID,
              item_name: 'Cotton Suit',
              qty: '50.000',
              rate: '1000.00',
              line_amount: '50000.00',
              gst_rate: '0',
              gst_amount: '0.00',
              line_sequence: 1,
            },
          ],
          created_at: '2026-05-11T00:00:00Z',
          updated_at: '2026-05-11T00:00:00Z',
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderRoute(`/purchase/invoices/${PI_ID}`);
    await waitFor(() => expect(screen.getByText('Cotton Suit')).toBeInTheDocument());
    expect(screen.queryByText(`${ITEM_ID.slice(0, 8)}…`)).not.toBeInTheDocument();
  });
});
