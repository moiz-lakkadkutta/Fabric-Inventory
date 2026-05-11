/*
 * JobWorkOverview — TASK-CUT-401 live-mode integration tests.
 *
 * Covers four vertical slices:
 *   1. GET /job-work-orders populates the active jobs list + karigar cards.
 *   2. "Send out" dialog POSTs to /job-work-orders with an Idempotency-Key.
 *   3. "Receive back" against an existing JWO POSTs to /receive.
 *   4. Karigar cards group by party_id with per-karigar pending qty.
 *
 * Live-mode pin happens via vi.mock('@/lib/api/mode') BEFORE the
 * page-under-test is imported. Otherwise IS_LIVE is captured at module
 * load from the .env.test default (`mock`), and Vite tree-shakes the
 * live branch away — defeating the test.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
const KARIGAR_IMRAN_ID = 'k0000000-0000-0000-0000-000000000001';
const KARIGAR_NASEEM_ID = 'k0000000-0000-0000-0000-000000000002';
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

interface JwoRowOptions {
  id: string;
  karigarPartyId: string;
  status?: 'SENT' | 'PARTIAL_RECEIVED' | 'CLOSED' | 'CANCELLED' | 'DRAFT';
  number?: string;
  operation?: string | null;
  qtySent?: string;
  qtyReceived?: string;
  qtyWastage?: string;
  uom?: string;
  lineId?: string;
}

function buildJwo({
  id,
  karigarPartyId,
  status = 'SENT',
  number,
  operation = 'Aari embroidery',
  qtySent = '100',
  qtyReceived = '0',
  qtyWastage = '0',
  uom = 'METER',
  lineId = JWO_LINE_ID,
}: JwoRowOptions) {
  return {
    job_work_order_id: id,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    karigar_party_id: karigarPartyId,
    series: 'JW/2026-27',
    number: number ?? `JW/2026-27/${id.slice(-4)}`,
    challan_date: '2026-05-01',
    status,
    operation,
    expected_return_date: '2026-05-20',
    notes: null,
    from_location_id: 'loc_main',
    to_location_id: 'loc_jobwork',
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    lines: [
      {
        job_work_order_line_id: lineId,
        line_no: 1,
        item_id: ITEM_ID,
        lot_id: null,
        qty_sent: qtySent,
        qty_received: qtyReceived,
        qty_wastage: qtyWastage,
        uom,
        notes: null,
      },
    ],
  };
}

function karigarPartyRow(id: string, code: string, name: string) {
  return {
    party_id: id,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    code,
    name,
    legal_name: name,
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

describe('JobWorkOverview (live-mode integration, TASK-CUT-401)', () => {
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

  it('renders the active jobs list from GET /job-work-orders', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/job-work-orders') && !u.includes('/receive')) {
        return jsonResponse(200, {
          items: [
            buildJwo({
              id: JWO_ID,
              karigarPartyId: KARIGAR_IMRAN_ID,
              number: 'JW/2026-27/0001',
              operation: 'Aari embroidery',
            }),
          ],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/parties')) {
        return jsonResponse(200, {
          items: [karigarPartyRow(KARIGAR_IMRAN_ID, 'IMRAN', 'Imran Khan')],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderJobWork();

    await waitFor(() => expect(screen.getByText('JW/2026-27/0001')).toBeInTheDocument());
    expect(screen.getAllByText(/Imran Khan/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Aari embroidery/i)).toBeInTheDocument();
  });

  it('"Send out" dialog POSTs to /job-work-orders with idempotency key', async () => {
    let postPayload: Record<string, unknown> | null = null;
    let postIdempotencyKey: string | null = null;
    let jwoListCallCount = 0;

    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.includes('/job-work-orders') && !u.includes('/receive') && method === 'GET') {
        jwoListCallCount += 1;
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      if (u.includes('/job-work-orders') && method === 'POST' && !u.includes('/receive')) {
        postIdempotencyKey =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
        postPayload = JSON.parse((init?.body as string) ?? '{}');
        return jsonResponse(
          201,
          buildJwo({
            id: JWO_ID,
            karigarPartyId: KARIGAR_IMRAN_ID,
            number: 'JW/2026-27/0001',
          }),
        );
      }
      if (u.includes('/parties')) {
        return jsonResponse(200, {
          items: [karigarPartyRow(KARIGAR_IMRAN_ID, 'IMRAN', 'Imran Khan')],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, {
          items: [
            {
              item_id: ITEM_ID,
              org_id: ORG_ID,
              firm_id: FIRM_ID,
              code: 'COTSUIT',
              name: 'Cotton fabric',
              description: null,
              category: null,
              item_type: 'RAW',
              primary_uom: 'METER',
              tracking: 'NONE',
              hsn_code: '5208',
              gst_rate: '5',
              has_variants: false,
              has_expiry: false,
              is_active: true,
              created_at: '2026-04-30T00:00:00Z',
              updated_at: '2026-04-30T00:00:00Z',
              deleted_at: null,
            },
          ],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    });

    renderJobWork();
    await waitFor(() => expect(jwoListCallCount).toBeGreaterThan(0));

    // Open the send-out dialog.
    fireEvent.click(screen.getByRole('button', { name: /send out/i }));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /send out/i })).toBeInTheDocument(),
    );

    const dialog = screen.getByRole('dialog', { name: /send out/i });
    const karigarSelect = within(dialog).getByLabelText(/karigar/i) as HTMLSelectElement;
    const itemSelect = within(dialog).getByLabelText(/^item/i) as HTMLSelectElement;
    const qtyInput = within(dialog).getByLabelText(/quantity/i) as HTMLInputElement;
    const uomInput = within(dialog).getByLabelText(/uom/i) as HTMLInputElement;
    const operationInput = within(dialog).getByLabelText(/operation/i) as HTMLInputElement;

    await waitFor(() => expect(karigarSelect.options.length).toBeGreaterThan(1));
    await waitFor(() => expect(itemSelect.options.length).toBeGreaterThan(1));

    fireEvent.change(karigarSelect, { target: { value: KARIGAR_IMRAN_ID } });
    fireEvent.change(itemSelect, { target: { value: ITEM_ID } });
    fireEvent.change(qtyInput, { target: { value: '95.5' } });
    fireEvent.change(uomInput, { target: { value: 'METER' } });
    fireEvent.change(operationInput, { target: { value: 'Aari embroidery' } });

    fireEvent.click(within(dialog).getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /send out/i })).not.toBeInTheDocument(),
    );

    expect(postPayload).toMatchObject({
      firm_id: FIRM_ID,
      karigar_party_id: KARIGAR_IMRAN_ID,
      operation: 'Aari embroidery',
      lines: [
        {
          item_id: ITEM_ID,
          qty_sent: '95.5',
          uom: 'METER',
        },
      ],
    });
    expect(postIdempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);
    // List refetched after the POST.
    await waitFor(() => expect(jwoListCallCount).toBeGreaterThanOrEqual(2));
  });

  it('"Receive back" against an existing JWO posts to /receive', async () => {
    let postPayload: Record<string, unknown> | null = null;
    let postIdempotencyKey: string | null = null;
    let receivePath: string | null = null;

    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.includes('/receive') && method === 'POST') {
        receivePath = u;
        postIdempotencyKey =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
        postPayload = JSON.parse((init?.body as string) ?? '{}');
        return jsonResponse(201, {
          job_work_receipt_id: 'rcp_001',
          org_id: ORG_ID,
          firm_id: FIRM_ID,
          job_work_order_id: JWO_ID,
          receipt_date: '2026-05-10',
          status: 'POSTED',
          notes: null,
          created_at: '2026-05-10T00:00:00Z',
          updated_at: '2026-05-10T00:00:00Z',
          lines: [],
        });
      }
      if (u.includes('/job-work-orders') && method === 'GET') {
        return jsonResponse(200, {
          items: [
            buildJwo({
              id: JWO_ID,
              karigarPartyId: KARIGAR_IMRAN_ID,
              number: 'JW/2026-27/0001',
              qtySent: '100',
              qtyReceived: '0',
              qtyWastage: '0',
            }),
          ],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/parties')) {
        return jsonResponse(200, {
          items: [karigarPartyRow(KARIGAR_IMRAN_ID, 'IMRAN', 'Imran Khan')],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderJobWork();
    await waitFor(() => expect(screen.getByText('JW/2026-27/0001')).toBeInTheDocument());

    // Click the "Receive back" CTA on the JWO row.
    const rcvBtns = await screen.findAllByRole('button', { name: /receive back/i });
    fireEvent.click(rcvBtns[0]);

    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /receive back/i })).toBeInTheDocument(),
    );

    const dialog = screen.getByRole('dialog', { name: /receive back/i });
    const finishedInput = within(dialog).getByLabelText(/finished/i) as HTMLInputElement;
    const wastageInput = within(dialog).getByLabelText(/wastage/i) as HTMLInputElement;
    fireEvent.change(finishedInput, { target: { value: '95.5' } });
    fireEvent.change(wastageInput, { target: { value: '4.5' } });

    fireEvent.click(within(dialog).getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /receive back/i })).not.toBeInTheDocument(),
    );

    expect(receivePath).toContain(`/job-work-orders/${JWO_ID}/receive`);
    expect(postPayload).toMatchObject({
      lines: [
        {
          job_work_order_line_id: JWO_LINE_ID,
          qty_received: '95.5',
          qty_wastage: '4.5',
        },
      ],
    });
    expect(postIdempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it('karigar cards group by party_id with per-karigar pending qty', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/job-work-orders')) {
        return jsonResponse(200, {
          items: [
            // Imran: 2 orders. 100 sent, 30 received => 70 pending.
            // + 50 sent, 0 received => 50 pending. Total Imran = 120.
            buildJwo({
              id: 'j1',
              lineId: 'lA',
              karigarPartyId: KARIGAR_IMRAN_ID,
              qtySent: '100',
              qtyReceived: '30',
              qtyWastage: '0',
              uom: 'METER',
              status: 'PARTIAL_RECEIVED',
            }),
            buildJwo({
              id: 'j2',
              lineId: 'lB',
              karigarPartyId: KARIGAR_IMRAN_ID,
              qtySent: '50',
              qtyReceived: '0',
              qtyWastage: '0',
              uom: 'METER',
              status: 'SENT',
            }),
            // Naseem: 1 order. 80 sent, 60 received, 20 wastage => 0 pending.
            buildJwo({
              id: 'j3',
              lineId: 'lC',
              karigarPartyId: KARIGAR_NASEEM_ID,
              qtySent: '80',
              qtyReceived: '60',
              qtyWastage: '20',
              uom: 'PIECE',
              status: 'CLOSED',
            }),
          ],
          count: 3,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/parties')) {
        return jsonResponse(200, {
          items: [
            karigarPartyRow(KARIGAR_IMRAN_ID, 'IMRAN', 'Imran Khan'),
            karigarPartyRow(KARIGAR_NASEEM_ID, 'NASEEM', 'Naseem Begum'),
          ],
          count: 2,
          limit: 200,
          offset: 0,
        });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderJobWork();

    // Both karigar cards render.
    await waitFor(() =>
      expect(screen.getAllByText(/Imran Khan/i).length).toBeGreaterThanOrEqual(1),
    );
    expect(screen.getAllByText(/Naseem Begum/i).length).toBeGreaterThanOrEqual(1);

    // Imran's card surfaces 120 m pending. The orders query resolves
    // independently of the karigars query — wait for the derived
    // rollup to render the pending value.
    await waitFor(() => {
      const card = screen
        .getAllByText(/Imran Khan/i)
        .map((el) => el.closest('[data-testid="karigar-card"]'))
        .find((el): el is HTMLElement => el !== null && el !== undefined);
      expect(card).toBeTruthy();
      expect(within(card!).getByText(/120/)).toBeInTheDocument();
    });
    const imranCard = screen
      .getAllByText(/Imran Khan/i)
      .map((el) => el.closest('[data-testid="karigar-card"]'))
      .find((el): el is HTMLElement => el !== null && el !== undefined);
    expect(imranCard).toBeTruthy();
    expect(within(imranCard!).getByText(/METER/i)).toBeInTheDocument();

    // Naseem's card surfaces 0 pending (all closed).
    const naseemCard = screen
      .getAllByText(/Naseem Begum/i)
      .map((el) => el.closest('[data-testid="karigar-card"]'))
      .find((el): el is HTMLElement => el !== null && el !== undefined);
    expect(naseemCard).toBeTruthy();
    // Either explicit "0" or "—" / "no pending" is acceptable; require
    // that we don't surface a positive pending for Naseem.
    expect(within(naseemCard!).queryByText(/120/)).not.toBeInTheDocument();
  });
});
