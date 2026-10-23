import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Live-mode command palette (fix/live-search-and-placeholders).
 *
 * In live mode the palette's party / item / invoice entries must come
 * from the real list endpoints, not the click-dummy fixtures — otherwise
 * searching surfaces fake records whose detail pages 404.
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { CommandPalette } = await import('@/components/layout/CommandPalette');

const PARTY_ID = '11111111-1111-1111-1111-111111111111';
const ITEM_ID = '33333333-3333-3333-3333-333333333333';
const INVOICE_ID = '44444444-4444-4444-4444-444444444444';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const PARTY = {
  party_id: PARTY_ID,
  org_id: 'o1',
  firm_id: 'f1',
  code: 'ZEN',
  name: 'Zenith Textiles Live',
  legal_name: null,
  is_supplier: false,
  is_customer: true,
  is_karigar: false,
  is_transporter: false,
  tax_status: 'REGULAR',
  gstin: null,
  pan: null,
  phone: null,
  email: null,
  state_code: '27',
  contact_person: null,
  credit_limit: null,
  notes: null,
  is_active: true,
  created_at: '2026-05-10T00:00:00Z',
  updated_at: '2026-05-10T00:00:00Z',
  deleted_at: null,
};

const ITEM = {
  item_id: ITEM_ID,
  org_id: 'o1',
  firm_id: 'f1',
  code: 'LIVE-SILK',
  name: 'Live Banarasi Silk',
  description: null,
  category: null,
  item_type: 'RAW',
  primary_uom: 'METER',
  tracking: 'NONE',
  hsn_code: '5007',
  gst_rate: '5.00',
  has_variants: false,
  has_expiry: false,
  is_active: true,
  created_at: '2026-05-10T00:00:00Z',
  updated_at: '2026-05-10T00:00:00Z',
  deleted_at: null,
};

const INVOICE = {
  sales_invoice_id: INVOICE_ID,
  org_id: 'o1',
  firm_id: 'f1',
  series: 'LV',
  number: '0042',
  invoice_date: '2026-10-01',
  due_date: '2026-10-31',
  party_id: PARTY_ID,
  party_name: 'Zenith Textiles Live',
  place_of_supply_state: '27',
  lifecycle_status: 'FINALIZED',
  invoice_amount: '1180.00',
  gst_amount: '180.00',
  paid_amount: '0.00',
  created_at: '2026-10-01T00:00:00Z',
};

function renderPalette() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<CommandPalette open onClose={() => {}} />} />
          <Route path="/masters/parties/:id" element={<div>PARTY_DETAIL_REACHED</div>} />
          <Route path="/masters/items/:id" element={<div>ITEM_DETAIL_REACHED</div>} />
          <Route path="/sales/invoices/:id" element={<div>INVOICE_DETAIL_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  authStore.setAccessToken('access-token-abc');
  fetchMock = vi.fn(async (url: RequestInfo) => {
    const u = String(url);
    if (u.includes('/parties')) return jsonResponse(200, { items: [PARTY], count: 1 });
    if (u.includes('/items')) return jsonResponse(200, { items: [ITEM], count: 1 });
    if (u.includes('/invoices'))
      return jsonResponse(200, { items: [INVOICE], count: 1, limit: 200, offset: 0 });
    return jsonResponse(404, { title: 'not found' });
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  authStore.reset();
});

function search(value: string) {
  fireEvent.change(screen.getByLabelText(/command palette search/i), { target: { value } });
}

describe('CommandPalette — live mode', () => {
  it('shows real parties and routes to the real party id', async () => {
    renderPalette();
    search('zenith');
    expect(await screen.findByText('Zenith Textiles Live')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText(/command palette search/i), { key: 'Enter' });
    expect(screen.getByText('PARTY_DETAIL_REACHED')).toBeInTheDocument();
  });

  it('does not surface click-dummy mock parties', async () => {
    renderPalette();
    search('zenith');
    await screen.findByText('Zenith Textiles Live');
    search('anjali');
    expect(screen.queryByText('Anjali Saree Centre')).not.toBeInTheDocument();
    expect(screen.getByText(/nothing matches/i)).toBeInTheDocument();
  });

  it('shows real invoices by number and real items', async () => {
    renderPalette();
    search('LV/0042');
    expect(await screen.findByText('LV/0042')).toBeInTheDocument();
    search('banarasi');
    expect(await screen.findByText('Live Banarasi Silk')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Live Banarasi Silk'));
    expect(screen.getByText('ITEM_DETAIL_REACHED')).toBeInTheDocument();
  });

  it('does not fetch list data while closed', () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <CommandPalette open={false} onClose={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
