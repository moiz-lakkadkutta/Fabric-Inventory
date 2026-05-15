/*
 * InventoryList live-mode integration tests — TASK-TR-B01.
 *
 * Verifies the InventoryList page is wired to the real
 * `GET /reports/stock-summary` endpoint:
 *   1. Renders on-hand qty from the backend envelope (not zero stubs).
 *   2. Renders the lots count and "X SKUs" subtitle from the same payload.
 *   3. After a successful POST /stock-adjustments the SKU list refetches
 *      so the visible on-hand updates.
 *
 * Live-mode pin happens via vi.mock('@/lib/api/mode') BEFORE the
 * page-under-test is imported (see AdjustStockDialog.test.tsx for the
 * pattern — without it Vite tree-shakes the live branch away under
 * the .env.test VITE_API_MODE=mock default).
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
const { default: InventoryList } = await import('@/pages/inventory/InventoryList');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stockSummaryEnvelope(rows: Array<Record<string, unknown>>) {
  return {
    as_of: '2026-05-15',
    total_value: '12345.67',
    rows,
  };
}

function renderInventory() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/inventory']}>
        <InventoryList />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InventoryList — live-mode stock-summary wiring', () => {
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
      org_id: 'o',
      firm_id: 'f',
      email: 'u@example.com',
      permissions: [
        'accounting.report.view',
        'inventory.adjustment.create',
        'inventory.stock.read',
      ],
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

  it('renders on-hand qty from the live /reports/stock-summary payload', async () => {
    let stockSummaryHits = 0;
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/reports/stock-summary')) {
        stockSummaryHits += 1;
        return jsonResponse(
          200,
          stockSummaryEnvelope([
            {
              item_id: '11111111-1111-1111-1111-111111111111',
              item_code: 'SLK-GEO-60',
              item_name: 'Silk Georgette 60"',
              sku_id: null,
              sku_code: null,
              uom: 'METER',
              on_hand_qty: '12.5',
              avg_cost: '180.00',
              valuation: '2250.00',
            },
          ]),
        );
      }
      return jsonResponse(404, {});
    });

    renderInventory();

    // Wait for the live query to fire.
    await waitFor(() => expect(stockSummaryHits).toBeGreaterThan(0));

    // The row's on-hand should be the real "12.5", not the old "0" stub.
    await waitFor(() => expect(screen.getByText('Silk Georgette 60"')).toBeInTheDocument());
    // 12.5 is formatted with the user's locale; allow either "12.5" or "12.50" rendering.
    expect(screen.getByText(/12\.5/)).toBeInTheDocument();
  });

  it('renders the SKU count from the live payload (subtitle reflects real rows)', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/reports/stock-summary')) {
        return jsonResponse(
          200,
          stockSummaryEnvelope([
            {
              item_id: '11111111-1111-1111-1111-111111111111',
              item_code: 'A',
              item_name: 'Item A',
              sku_id: null,
              sku_code: null,
              uom: 'METER',
              on_hand_qty: '10',
              avg_cost: '0',
              valuation: '0',
            },
            {
              item_id: '22222222-2222-2222-2222-222222222222',
              item_code: 'B',
              item_name: 'Item B',
              sku_id: null,
              sku_code: null,
              uom: 'PIECE',
              on_hand_qty: '5',
              avg_cost: '0',
              valuation: '0',
            },
          ]),
        );
      }
      return jsonResponse(404, {});
    });

    renderInventory();

    // Header subtitle reads "2 SKUs · …".
    await waitFor(() => expect(screen.getByText(/2 SKUs/)).toBeInTheDocument());
  });

  it('refetches the SKU list after AdjustStockDialog success so on-hand updates', async () => {
    let stockSummaryHits = 0;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();

      if (u.includes('/reports/stock-summary')) {
        stockSummaryHits += 1;
        // First call: 5 on hand. After the adjustment: 8 on hand.
        const qty = stockSummaryHits === 1 ? '5' : '8';
        return jsonResponse(
          200,
          stockSummaryEnvelope([
            {
              item_id: '11111111-1111-1111-1111-111111111111',
              item_code: 'COTSUIT',
              item_name: 'Cotton Suit',
              sku_id: null,
              sku_code: null,
              uom: 'PIECE',
              on_hand_qty: qty,
              avg_cost: '0',
              valuation: '0',
            },
          ]),
        );
      }
      if (u.includes('/items') && method === 'GET') {
        return jsonResponse(200, {
          items: [
            {
              item_id: '11111111-1111-1111-1111-111111111111',
              org_id: 'o',
              firm_id: 'f',
              code: 'COTSUIT',
              name: 'Cotton Suit',
              description: null,
              category: null,
              item_type: 'FINISHED',
              primary_uom: 'PIECE',
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
          limit: 200,
          offset: 0,
          count: 1,
        });
      }
      if (u.includes('/locations') && method === 'GET') {
        return jsonResponse(200, {
          items: [
            {
              location_id: '22222222-2222-2222-2222-222222222222',
              org_id: 'o',
              firm_id: 'f',
              code: 'MAIN',
              name: 'Main Warehouse',
              location_type: 'WAREHOUSE',
              is_active: true,
            },
          ],
          count: 1,
        });
      }
      if (u.includes('/stock-adjustments') && method === 'POST') {
        return jsonResponse(201, {
          stock_adjustment_id: '33333333-3333-3333-3333-333333333333',
          org_id: 'o',
          firm_id: 'f',
          item_id: '11111111-1111-1111-1111-111111111111',
          lot_id: null,
          location_id: '22222222-2222-2222-2222-222222222222',
          qty_change: '3',
          reason: 'cycle count',
          requires_approval: false,
          approved_by: null,
          approved_at: null,
          created_by: 'u',
          created_at: '2026-05-15T11:00:00Z',
        });
      }
      return jsonResponse(404, {});
    });

    renderInventory();

    // Initial render: on_hand 5.
    await waitFor(() => expect(screen.getByText('Cotton Suit')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/^5$/)).toBeInTheDocument());

    // Open the AdjustStockDialog, fill it, submit.
    fireEvent.click(screen.getByRole('button', { name: /adjust stock/i }));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /adjust stock/i })).toBeInTheDocument(),
    );

    const itemSelect = screen.getByLabelText(/^item/i) as HTMLSelectElement;
    await waitFor(() => expect(itemSelect.options.length).toBeGreaterThan(1));
    fireEvent.change(itemSelect, { target: { value: '11111111-1111-1111-1111-111111111111' } });
    fireEvent.change(screen.getByLabelText(/direction/i), { target: { value: 'INCREASE' } });
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'cycle count' } });

    fireEvent.click(screen.getByRole('button', { name: /save adjustment/i }));

    // Dialog closes on 201.
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /adjust stock/i })).not.toBeInTheDocument(),
    );

    // The SKU list refetched — on-hand now reads 8.
    await waitFor(() => expect(stockSummaryHits).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(screen.getByText(/^8$/)).toBeInTheDocument());
  });
});
