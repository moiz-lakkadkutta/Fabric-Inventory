/*
 * Live-path integration tests — TASK-CUT-201.
 *
 * Tests exercise the live branch by mocking globalThis.fetch directly
 * (same posture as `client.test.ts` and `accounts.live.test.ts`). They
 * call into the live wrapper functions exposed via `__live`, not
 * through the React-Query hooks (which short-circuit to mock mode in
 * Vitest because IS_LIVE is read at module-load from VITE_API_MODE).
 *
 * Coverage:
 *   - list renders from a mocked GET /purchase-orders response
 *   - create posts the right body (firm_id, party_id, paise→rupees)
 *     with an Idempotency-Key header
 *   - approve hits POST /purchase-orders/{id}/approve and surfaces the
 *     transitioned status
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { authStore } from '@/store/auth';

import { __live, _internal, type CreatePoInput } from '@/lib/queries/purchase-orders';

const SAMPLE_BE_PO = {
  purchase_order_id: '11111111-1111-1111-1111-111111111111',
  org_id: 'o',
  firm_id: 'f',
  series: 'PO/25-26',
  number: '0001',
  party_id: '22222222-2222-2222-2222-222222222222',
  po_date: '2026-04-12',
  delivery_date: '2026-04-20',
  status: 'DRAFT',
  total_amount: '5000.00',
  notes: null,
  lines: [
    {
      po_line_id: 'l1',
      item_id: '33333333-3333-3333-3333-333333333333',
      qty_ordered: '10.000',
      qty_received: '0.000',
      rate: '500.00',
      line_amount: '5000.00',
      line_sequence: 1,
      taxes_applicable: null,
      notes: null,
    },
  ],
  created_at: '2026-04-12T00:00:00Z',
  updated_at: '2026-04-12T00:00:00Z',
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  authStore.reset();
  authStore.setAccessToken('test-token');
  authStore.setMe({
    user_id: 'u',
    email: 'e@example.com',
    org_id: 'o',
    firm_id: 'f',
    permissions: [],
    flags: {},
    available_firms: [],
    token_expires_at: '2026-12-31T00:00:00Z',
  });
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  authStore.reset();
});

describe('live PO list', () => {
  it('GET /purchase-orders maps the BE list into FE PurchaseOrders', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { items: [SAMPLE_BE_PO], limit: 200, offset: 0, count: 1 }),
    );

    const list = await __live.liveListPos();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('/purchase-orders?limit=200');
    expect(list).toHaveLength(1);
    expect(list[0].po_id).toBe(SAMPLE_BE_PO.purchase_order_id);
    expect(list[0].number).toBe('PO/25-26/0001');
    expect(list[0].total).toBe(500000);
    expect(list[0].status).toBe('DRAFT');
  });
});

describe('live PO create', () => {
  it('POSTs the right body and Idempotency-Key', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(201, SAMPLE_BE_PO));

    const input: CreatePoInput = {
      idempotencyKey: 'idem-create-1',
      draft: {
        supplier_id: '22222222-2222-2222-2222-222222222222',
        po_date: '2026-04-12',
        expected_date: '2026-04-20',
        lines: [
          {
            item_id: '33333333-3333-3333-3333-333333333333',
            qty: 10,
            rate: 50000,
            gst_pct: 0,
          },
        ],
      },
    };

    const created = await __live.liveCreatePo(input);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/purchase-orders');
    expect(init.method).toBe('POST');
    const headers = init.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBe('idem-create-1');
    expect(headers['Authorization']).toBe('Bearer test-token');
    const sentBody = JSON.parse(init.body as string);
    expect(sentBody.firm_id).toBe('f');
    expect(sentBody.party_id).toBe('22222222-2222-2222-2222-222222222222');
    expect(sentBody.lines).toHaveLength(1);
    expect(sentBody.lines[0].qty_ordered).toBe('10');
    expect(sentBody.lines[0].rate).toBe('500.00');
    expect(sentBody.series).toBe(_internal.DEFAULT_SERIES);

    expect(created.po_id).toBe(SAMPLE_BE_PO.purchase_order_id);
    expect(created.status).toBe('DRAFT');
  });
});

describe('live PO lifecycle: approve / confirm / cancel', () => {
  it('approve hits POST /purchase-orders/{id}/approve and maps APPROVED → OPEN', async () => {
    const approved = { ...SAMPLE_BE_PO, status: 'APPROVED' };
    fetchMock.mockResolvedValueOnce(jsonResponse(200, approved));

    const out = await __live.liveLifecycle('approve', {
      poId: SAMPLE_BE_PO.purchase_order_id,
      idempotencyKey: 'idem-approve-1',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain(`/purchase-orders/${SAMPLE_BE_PO.purchase_order_id}/approve`);
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Idempotency-Key']).toBe('idem-approve-1');
    expect(out.status).toBe('OPEN'); // BE APPROVED collapses to FE OPEN
  });

  it('confirm hits POST .../confirm and maps CONFIRMED → OPEN', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ...SAMPLE_BE_PO, status: 'CONFIRMED' }));

    const out = await __live.liveLifecycle('confirm', {
      poId: SAMPLE_BE_PO.purchase_order_id,
      idempotencyKey: 'idem-confirm-1',
    });

    expect(fetchMock.mock.calls[0][0]).toContain(
      `/purchase-orders/${SAMPLE_BE_PO.purchase_order_id}/confirm`,
    );
    expect(out.status).toBe('OPEN');
  });

  it('cancel hits POST .../cancel and maps CANCELLED → CANCELLED', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ...SAMPLE_BE_PO, status: 'CANCELLED' }));

    const out = await __live.liveLifecycle('cancel', {
      poId: SAMPLE_BE_PO.purchase_order_id,
      idempotencyKey: 'idem-cancel-1',
    });

    expect(fetchMock.mock.calls[0][0]).toContain(
      `/purchase-orders/${SAMPLE_BE_PO.purchase_order_id}/cancel`,
    );
    expect(out.status).toBe('CANCELLED');
  });
});
