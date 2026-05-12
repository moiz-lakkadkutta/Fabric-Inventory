/*
 * CUT-QA-07b (B23) — Receive-back dialog renders per-line inputs.
 *
 * Before: opening "Receive back" against an active JWO showed only the
 * Date + Notes fields. The dialog's submit handler then failed with
 * "Enter a finished or wastage qty on at least one line" because there
 * was no per-line input to read from.
 *
 * Root cause: ``buildLineState`` derives the per-line rows from
 * ``jwo.lines``. The JWO came from the list query, and the BE list
 * endpoint did not eager-load lines, so the dialog had nothing to render.
 * Fixed in 7a by bulk-loading lines on the list endpoint. This test
 * pins the dialog's rendering so a future regression on either side
 * (BE shape or FE conditional) trips a known assertion instead of the
 * cryptic validator error the user saw.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: JobWorkOverview } = await import('@/pages/jobwork/JobWorkOverview');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const KARIGAR_ID = 'k0000000-0000-0000-0000-000000000001';
const ITEM_ID = 'i0000000-0000-0000-0000-000000000001';
const JWO_ID = 'j0000000-0000-0000-0000-000000000001';
const JWO_LINE_ID = 'l0000000-0000-0000-0000-000000000001';

function renderJobWork() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobWorkOverview />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function karigarParty() {
  return {
    party_id: KARIGAR_ID,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    code: 'IMRAN',
    name: 'Imran Khan',
    legal_name: 'Imran Khan',
    is_customer: false,
    is_supplier: false,
    is_karigar: true,
    is_transporter: false,
    tax_status: 'UNREGISTERED',
    gstin: null,
    pan: null,
    phone: null,
    email: null,
    state_code: '24',
    credit_limit: null,
    credit_days: null,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function jwoWithOpenLine() {
  return {
    job_work_order_id: JWO_ID,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    karigar_party_id: KARIGAR_ID,
    series: 'JW/2026-27',
    number: 'JW/2026-27/0001',
    challan_date: '2026-05-01',
    status: 'SENT',
    operation: 'Stitching',
    expected_return_date: '2026-05-20',
    notes: null,
    from_location_id: 'loc_main',
    to_location_id: 'loc_jobwork',
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    lines: [
      {
        job_work_order_line_id: JWO_LINE_ID,
        line_no: 1,
        item_id: ITEM_ID,
        lot_id: null,
        qty_sent: '10',
        qty_received: '0',
        qty_wastage: '0',
        uom: 'PIECE',
        notes: null,
      },
    ],
  };
}

describe('CUT-QA-07b — ReceiveBackDialog per-line inputs (B23)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    authStore.reset();
    authStore.setAccessToken('test-token');
    authStore.setMe({
      user_id: 'u',
      org_id: ORG_ID,
      firm_id: FIRM_ID,
      email: 'u@example.com',
      permissions: [
        'jobwork.order.create',
        'jobwork.order.read',
        'masters.party.read',
        'masters.item.read',
      ],
      flags: {},
      available_firms: [{ firm_id: FIRM_ID, code: 'F1', name: 'F1' }],
      token_expires_at: '2099-01-01T00:00:00Z',
    });
  });

  afterEach(() => {
    cleanup();
    globalThis.fetch = originalFetch;
    authStore.reset();
    vi.restoreAllMocks();
  });

  it('renders Finished + Wastage inputs per JWO line when opened', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/job-work-orders') && !u.includes('/receive')) {
        return jsonResponse(200, {
          items: [jwoWithOpenLine()],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/parties')) {
        return jsonResponse(200, { items: [karigarParty()], count: 1, limit: 200, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderJobWork();

    const rcvBtn = await screen.findByRole('button', { name: /receive back/i });
    fireEvent.click(rcvBtn);

    const dialog = await screen.findByRole('dialog', { name: /receive back/i });

    // Per-line inputs MUST be present — the validator already expects them.
    expect(within(dialog).getByLabelText(/finished line 1/i)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/wastage line 1/i)).toBeInTheDocument();
    // Open-qty label confirms the line state is sourced from the JWO.
    expect(within(dialog).getByText(/Open: 10/i)).toBeInTheDocument();
  });
});
