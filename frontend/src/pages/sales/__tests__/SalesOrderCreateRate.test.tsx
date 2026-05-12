/*
 * TASK-CUT-QA-02 (B13) — rate input correctly stores paise.
 *
 * Repros the 10,000× drift reported in E2E QA 2026-05-12:
 *   - user types "500" (rupees) into the Rate cell of a SO line
 *   - SO posts with price=0.01 (1 paisa) instead of 500.00
 *
 * Root cause: the input was controlled with `value={(rate/100).toFixed(2)}`
 * so each keystroke parsed the *displayed* rupees-with-cents string back as
 * a number. Typing "5" into "0.00" produced "0.005" → 0.5 paise → round to
 * 1 paisa, and the display snapped to "0.01" before the next keystroke.
 *
 * The fix is to track the raw editing string per-line and only re-derive
 * paise on the user's onBlur (or at submit time). This test simulates the
 * exact keystroke pattern from the QA repro by issuing one change event
 * per character against the *currently-rendered* input value — the same
 * way the browser DOM does it.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as soQueries from '@/lib/queries/sales-orders';
import * as partiesQueries from '@/lib/queries/parties';
import * as itemsQueries from '@/lib/queries/items';
import SalesOrderCreate from '@/pages/sales/SalesOrderCreate';
import { authStore } from '@/store/auth';

afterEach(() => {
  vi.restoreAllMocks();
  authStore.clear();
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const queryResult = (data: unknown, isPending = false): any =>
  ({ data, isPending, isError: false, error: null, refetch: vi.fn() }) as unknown;

function renderRoute(path: string, element: React.ReactElement, route: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Simulate the user typing `text` one character at a time at the end of
 * the field's current value. Re-reads `input.value` between keystrokes
 * so any controlled-component reformat is observed — matching the
 * browser's actual behaviour.
 */
function typeAppending(input: HTMLInputElement, text: string) {
  for (const ch of text) {
    const next = (input.value ?? '') + ch;
    fireEvent.change(input, { target: { value: next } });
  }
}

function seedAuth() {
  authStore.setAccessToken('t');
  authStore.setMe({
    user_id: 'u',
    org_id: 'o',
    firm_id: 'firm-1',
    email: 'me@x.com',
    permissions: [],
    flags: {},
    available_firms: [],
    token_expires_at: '2099-01-01',
  });
}

function mockMasters() {
  vi.spyOn(partiesQueries, 'useCustomers').mockReturnValue(
    queryResult([{ party_id: 'p1', name: 'ACME Pvt', state_code: 'MH', kind: 'customer' }]),
  );
  vi.spyOn(itemsQueries, 'useItems').mockReturnValue(
    queryResult([
      {
        item_id: 'i1',
        name: 'Cotton Suit',
        primary_uom: 'PIECE',
        gst_rate: 5,
      },
    ]),
  );
}

describe('SalesOrderCreate — rate input (B13)', () => {
  it('submitsRate500Correctly: typing "500" sends price=50000 paise (₹500), not 1 paisa', async () => {
    seedAuth();
    mockMasters();

    const mutateAsync = vi.fn().mockResolvedValue({
      sales_order_id: 'so-9',
      display_number: 'SO/2526/0009',
    });
    vi.spyOn(soQueries, 'useCreateSo').mockReturnValue({
      mutateAsync,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderRoute('/sales/orders/new', <SalesOrderCreate />, '/sales/orders/new');

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /save so/i })).not.toBeDisabled(),
    );

    // Clear the qty cell of any default 1 so the test asserts purely on
    // the rate field; type qty=20 then rate=500, matching the QA repro.
    const qtyInput = screen.getByLabelText('Qty') as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: '20' } });

    const rateInput = screen.getByLabelText('Rate') as HTMLInputElement;
    // Browsers fire one input event per keystroke; React re-renders the
    // controlled value between them. The bug only repros if we type
    // incrementally — a single fireEvent.change with "500" would mask it.
    typeAppending(rateInput, '500');

    fireEvent.click(screen.getByRole('button', { name: /save so/i }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const payload = mutateAsync.mock.calls[0][0];
    expect(payload.lines).toHaveLength(1);
    // CreateSoInput shape: price is in paise (FE convention, see
    // lib/queries/sales-orders.ts → CreateSoLineInput).
    // 500 rupees = 50,000 paise.
    expect(payload.lines[0].price).toBe(50_000);
    expect(payload.lines[0].qty_ordered).toBe(20);
  });
});
