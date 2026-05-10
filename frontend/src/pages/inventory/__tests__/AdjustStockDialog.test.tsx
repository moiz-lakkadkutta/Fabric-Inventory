/*
 * AdjustStockDialog — TASK-CUT-204 integration test.
 *
 * Verifies the live-mode behavior end-to-end:
 *   1. Clicking "Adjust stock" on InventoryList opens the dialog.
 *   2. The dialog lists locations from GET /locations and items from GET /items.
 *   3. Submitting POSTs to /stock-adjustments with an Idempotency-Key header.
 *   4. On 201, the dialog closes and the SOH query is refetched.
 *
 * Live-mode pin must happen via vi.mock('@/lib/api/mode') BEFORE the
 * page-under-test is imported. Otherwise IS_LIVE is captured at module
 * load from the .env.test default (`mock`), and Vite tree-shakes the
 * live branch away — defeating the test.
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

describe('AdjustStockDialog (live-mode integration)', () => {
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
      permissions: ['inventory.adjustment.create', 'inventory.stock.read'],
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

  it('opens the dialog, posts a stock adjustment, and refetches SOH on success', async () => {
    let postPayload: Record<string, unknown> | null = null;
    let postIdempotencyKey: string | null = null;
    let itemsCallCount = 0;

    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();

      if (u.includes('/items') && method === 'GET') {
        itemsCallCount += 1;
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
        postIdempotencyKey =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
        postPayload = JSON.parse((init?.body as string) ?? '{}');
        return jsonResponse(201, {
          stock_adjustment_id: '33333333-3333-3333-3333-333333333333',
          org_id: 'o',
          firm_id: 'f',
          item_id: '11111111-1111-1111-1111-111111111111',
          lot_id: null,
          location_id: '22222222-2222-2222-2222-222222222222',
          qty_change: '5',
          reason: 'cycle count',
          requires_approval: false,
          approved_by: null,
          approved_at: null,
          created_by: 'u',
          created_at: '2026-05-10T11:00:00Z',
        });
      }
      return jsonResponse(404, {});
    });

    renderInventory();

    // Wait for the items to load (proves the live-mode SOH query ran).
    await waitFor(() => expect(itemsCallCount).toBeGreaterThan(0));

    // Open the dialog from the "Adjust stock" CTA.
    fireEvent.click(screen.getByRole('button', { name: /adjust stock/i }));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /adjust stock/i })).toBeInTheDocument(),
    );

    // Form fields are present.
    const itemSelect = screen.getByLabelText(/^item/i) as HTMLSelectElement;
    const directionSelect = screen.getByLabelText(/direction/i) as HTMLSelectElement;
    const qtyInput = screen.getByLabelText(/quantity/i) as HTMLInputElement;
    const reasonInput = screen.getByLabelText(/reason/i) as HTMLInputElement;

    // Wait for items + locations to populate.
    await waitFor(() => expect(itemSelect.options.length).toBeGreaterThan(1));

    // Pick the item, increase by 5 units, reason "cycle count".
    fireEvent.change(itemSelect, { target: { value: '11111111-1111-1111-1111-111111111111' } });
    fireEvent.change(directionSelect, { target: { value: 'INCREASE' } });
    fireEvent.change(qtyInput, { target: { value: '5' } });
    fireEvent.change(reasonInput, { target: { value: 'cycle count' } });

    fireEvent.click(screen.getByRole('button', { name: /save adjustment/i }));

    // Dialog closes on success.
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /adjust stock/i })).not.toBeInTheDocument(),
    );

    // Assert the POST happened with the right shape + an Idempotency-Key.
    expect(postPayload).toMatchObject({
      firm_id: 'f',
      item_id: '11111111-1111-1111-1111-111111111111',
      location_id: '22222222-2222-2222-2222-222222222222',
      direction: 'INCREASE',
      qty: '5',
      reason: 'cycle count',
    });
    expect(postIdempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);

    // SOH query refetched after success — items endpoint hit at least
    // twice (initial render + invalidation after the mutation).
    await waitFor(() => expect(itemsCallCount).toBeGreaterThanOrEqual(2));
  });
});
