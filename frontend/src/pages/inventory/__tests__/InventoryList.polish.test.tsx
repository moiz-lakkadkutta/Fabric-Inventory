/*
 * InventoryList polish tests — TASK-TR-B06.
 *
 * Covers two B02-retro follow-ups:
 *   1. Low-stock visual signal: a "Low stock" pill renders when
 *      `on_hand < reorder` (and reorder > 0); not when stock is
 *      adequate.
 *   2. Permission UX: a 403 PERMISSION_DENIED on /reports/stock-summary
 *      shows a tailored "Ask an admin..." message naming the missing
 *      permission key, and NOT the generic empty-table state.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
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

describe('InventoryList — TASK-TR-B06 polish', () => {
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
      permissions: ['accounting.report.view', 'inventory.stock.read'],
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

  describe('low-stock badge', () => {
    // The /reports/stock-summary response doesn't carry reorder yet
    // (see frontend/src/lib/queries/inventory.ts — `reorder` defaults
    // to 0 on the live mapper). We exercise the page via mock-mode
    // fixtures, which DO carry reorder thresholds, by toggling
    // IS_LIVE back to false for this block.
    it('renders Low stock pill when on_hand < reorder (mock fixture)', async () => {
      // Re-mock mode to mock so the page reads skuRows fixtures that
      // carry reorder thresholds.
      vi.resetModules();
      vi.doMock('@/lib/api/mode', () => ({
        API_MODE: 'mock',
        IS_LIVE: false,
        IS_MOCK: true,
      }));
      const { default: MockInventoryList } = await import('@/pages/inventory/InventoryList');

      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, staleTime: 0 } },
      });
      render(
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/inventory']}>
            <MockInventoryList />
          </MemoryRouter>
        </QueryClientProvider>,
      );

      // Chiffon Silk 44" has on_hand 78 and reorder 100 in the fixture
      // — the badge should render in that row.
      await waitFor(() => expect(screen.getByText('Chiffon Silk 44"')).toBeInTheDocument());
      const lowStockBadges = screen.getAllByLabelText(/low stock/i);
      expect(lowStockBadges.length).toBeGreaterThan(0);

      // Silk Georgette 60" has on_hand 248.5 and reorder 100 — NOT
      // a low-stock row. The text "Silk Georgette 60"" should render
      // but no Low stock pill should sit in that row.
      const georgetteRow = screen.getByText('Silk Georgette 60"').closest('tr');
      expect(georgetteRow).toBeTruthy();
      expect(georgetteRow!.querySelector('[aria-label="Low stock"]')).toBeNull();
    });
  });

  describe('permission UX on 403', () => {
    it('renders a tailored "ask an admin" message naming the missing permission', async () => {
      fetchMock.mockImplementation(async (url: RequestInfo) => {
        const u = String(url);
        if (u.includes('/reports/stock-summary')) {
          return jsonResponse(403, {
            code: 'PERMISSION_DENIED',
            title: 'Forbidden',
            detail: 'Requires permission: accounting.report.view',
            status: 403,
            field_errors: {},
            request_id: 'req-test-403',
          });
        }
        return jsonResponse(404, {});
      });

      renderInventory();

      // Tailored permission-denied state surfaces.
      await waitFor(() => expect(screen.getByTestId('query-error-permission')).toBeInTheDocument());

      // Headline names what's wrong without being shouty.
      expect(screen.getByText(/don't have permission/i)).toBeInTheDocument();

      // The missing key surfaces in the body so a user can copy/paste
      // it into a message to their admin. Use exact-substring matching
      // because both the BE detail string and our copy contain the key.
      expect(screen.getByText(/accounting\.report\.view/)).toBeInTheDocument();

      // Crucially: we did NOT collapse into the generic empty
      // "0 SKUs · 0 active lots" / empty table state.
      expect(screen.queryByText(/^0 SKUs/)).not.toBeInTheDocument();
      expect(screen.queryByTestId('query-error-generic')).not.toBeInTheDocument();
    });
  });
});
