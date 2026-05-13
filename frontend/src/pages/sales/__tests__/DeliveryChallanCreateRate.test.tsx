/*
 * TASK-CUT-QA-02c (B13 sibling) — DC rate input correctly stores paise.
 *
 * Same root cause as SalesOrderCreate (see SalesOrderCreateRate.test.tsx):
 * the optional Rate column on DeliveryChallanCreate used the same
 * formatted-input → reparse pattern, so typing "500" into the default
 * "0.00" cell stored ₹0.01 instead of ₹500.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as dcQueries from '@/lib/queries/delivery-challans';
import * as soQueries from '@/lib/queries/sales-orders';
import * as partiesQueries from '@/lib/queries/parties';
import * as itemsQueries from '@/lib/queries/items';
import DeliveryChallanCreate from '@/pages/sales/DeliveryChallanCreate';
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

function typeAppending(input: HTMLInputElement, text: string) {
  for (const ch of text) {
    const next = (input.value ?? '') + ch;
    fireEvent.change(input, { target: { value: next } });
  }
}

describe('DeliveryChallanCreate — rate input (B13)', () => {
  it('typing "500" in the Rate cell sends price=50000 paise (₹500)', async () => {
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

    vi.spyOn(partiesQueries, 'useCustomers').mockReturnValue(
      queryResult([{ party_id: 'p1', name: 'ACME', state_code: 'MH', kind: 'customer' }]),
    );
    vi.spyOn(itemsQueries, 'useItems').mockReturnValue(
      queryResult([{ item_id: 'i1', name: 'Cotton Suit', primary_uom: 'PIECE', gst_rate: 5 }]),
    );
    vi.spyOn(soQueries, 'useSalesOrders').mockReturnValue(queryResult([]));
    vi.spyOn(soQueries, 'useSalesOrder').mockReturnValue(queryResult(null));

    const mutateAsync = vi.fn().mockResolvedValue({ delivery_challan_id: 'dc-9' });
    vi.spyOn(dcQueries, 'useCreateDc').mockReturnValue({
      mutateAsync,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderRoute(
      '/sales/delivery-challans/new',
      <DeliveryChallanCreate />,
      '/sales/delivery-challans/new',
    );

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /save dc/i })).not.toBeDisabled(),
    );

    const qtyInput = screen.getByLabelText('Qty') as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: '20' } });

    const rateInput = screen.getByLabelText('Rate') as HTMLInputElement;
    typeAppending(rateInput, '500');

    fireEvent.click(screen.getByRole('button', { name: /save dc/i }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const payload = mutateAsync.mock.calls[0][0];
    expect(payload.lines).toHaveLength(1);
    // CreateDcLineInput.price is paise (FE convention). 500 rupees = 50,000 paise.
    expect(payload.lines[0].price).toBe(50_000);
    expect(payload.lines[0].qty_dispatched).toBe(20);
  });
});
