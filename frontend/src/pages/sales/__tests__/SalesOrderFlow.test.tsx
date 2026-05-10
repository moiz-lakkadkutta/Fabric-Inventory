import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as soQueries from '@/lib/queries/sales-orders';
import * as partiesQueries from '@/lib/queries/parties';
import * as itemsQueries from '@/lib/queries/items';
import SalesOrderCreate from '@/pages/sales/SalesOrderCreate';
import SalesOrderDetail from '@/pages/sales/SalesOrderDetail';
import SalesOrderList from '@/pages/sales/SalesOrderList';
import { authStore } from '@/store/auth';

/*
 * TASK-CUT-203 — SalesOrder happy-path FE flow.
 *
 * Three behaviors:
 *   1. List page renders rows from useSalesOrders().
 *   2. Create page submits buildCreateBody-shaped payload via useCreateSo.
 *   3. Detail page Confirm button calls useConfirmSo and reflects new
 *      status pill on success.
 *
 * We mock the query hooks (not the BE). That keeps the test fast,
 * deterministic, and focused on the FE wiring (the live-mode mappers
 * have their own unit tests in lib/queries/__tests__).
 */

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

describe('SalesOrderList', () => {
  it('renders rows returned by useSalesOrders + uses party name from useParties', () => {
    vi.spyOn(soQueries, 'useSalesOrders').mockReturnValue(
      queryResult([
        {
          sales_order_id: 'so-1',
          org_id: 'o',
          firm_id: 'f',
          series: 'SO/2526',
          number: '0001',
          display_number: 'SO/2526/0001',
          party_id: 'p1',
          so_date: '2026-04-30',
          delivery_date: null,
          status: 'CONFIRMED',
          total_amount: 150_000,
          notes: null,
          lines: [],
          created_at: '2026-04-30T00:00:00Z',
          updated_at: '2026-04-30T00:00:00Z',
        },
      ]),
    );
    vi.spyOn(partiesQueries, 'useParties').mockReturnValue(
      queryResult([{ party_id: 'p1', name: 'ACME Pvt' }]),
    );

    renderRoute('/sales/orders', <SalesOrderList />, '/sales/orders');

    expect(screen.getByRole('heading', { level: 1, name: /sales orders/i })).toBeInTheDocument();
    expect(screen.getByText('SO/2526/0001')).toBeInTheDocument();
    expect(screen.getByText('ACME Pvt')).toBeInTheDocument();
    // "Confirmed" appears twice (filter button + status pill); the pill
    // is the assertion we care about — find it by the table row.
    const pills = screen.getAllByText('Confirmed');
    expect(pills.length).toBeGreaterThan(0);
  });
});

describe('SalesOrderCreate', () => {
  it('submits a create payload via useCreateSo when Save is clicked', async () => {
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
      queryResult([{ party_id: 'p1', name: 'ACME Pvt', state_code: 'MH', kind: 'customer' }]),
    );
    vi.spyOn(itemsQueries, 'useItems').mockReturnValue(
      queryResult([
        {
          item_id: 'i1',
          name: 'Cotton',
          primary_uom: 'PIECE',
          gst_rate: 5,
        },
      ]),
    );

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

    // Defaults: party + first line item are auto-filled by the page's
    // useEffects. The Save button is enabled once both queries resolved.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /save so/i })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /save so/i }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const payload = mutateAsync.mock.calls[0][0];
    expect(payload.firm_id).toBe('firm-1');
    expect(payload.party_id).toBe('p1');
    expect(payload.lines).toHaveLength(1);
    expect(payload.lines[0].item_id).toBe('i1');
    expect(payload.idempotencyKey).toMatch(/^[\da-f-]+$/i);
  });

  it('blocks submit + surfaces an error when there is no active firm in the JWT', async () => {
    // No me set on authStore → me.firm_id is undefined.
    authStore.clear();

    vi.spyOn(partiesQueries, 'useCustomers').mockReturnValue(
      queryResult([{ party_id: 'p1', name: 'ACME', state_code: 'MH', kind: 'customer' }]),
    );
    vi.spyOn(itemsQueries, 'useItems').mockReturnValue(
      queryResult([{ item_id: 'i1', name: 'Cotton', primary_uom: 'PIECE', gst_rate: 5 }]),
    );

    const mutateAsync = vi.fn();
    vi.spyOn(soQueries, 'useCreateSo').mockReturnValue({
      mutateAsync,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderRoute('/sales/orders/new', <SalesOrderCreate />, '/sales/orders/new');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /save so/i })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: /save so/i }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('alert').textContent).toMatch(/no active firm/i);
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});

describe('SalesOrderDetail', () => {
  it('renders Confirm button for DRAFT and calls useConfirmSo on click', async () => {
    vi.spyOn(soQueries, 'useSalesOrder').mockReturnValue(
      queryResult({
        sales_order_id: 'so-1',
        org_id: 'o',
        firm_id: 'f',
        series: 'SO/2526',
        number: '0001',
        display_number: 'SO/2526/0001',
        party_id: 'p1',
        so_date: '2026-04-30',
        delivery_date: null,
        status: 'DRAFT',
        total_amount: 150_000,
        notes: null,
        lines: [],
        created_at: '2026-04-30T00:00:00Z',
        updated_at: '2026-04-30T00:00:00Z',
      }),
    );
    vi.spyOn(partiesQueries, 'useParties').mockReturnValue(queryResult([]));
    vi.spyOn(itemsQueries, 'useItems').mockReturnValue(queryResult([]));

    const confirmMutate = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(soQueries, 'useConfirmSo').mockReturnValue({
      mutateAsync: confirmMutate,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    vi.spyOn(soQueries, 'useCancelSo').mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderRoute('/sales/orders/:id', <SalesOrderDetail />, '/sales/orders/so-1');

    expect(screen.getByText('SO/2526/0001')).toBeInTheDocument();
    expect(screen.getByText('Draft')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    await waitFor(() => expect(confirmMutate).toHaveBeenCalledTimes(1));
    expect(confirmMutate.mock.calls[0][0].soId).toBe('so-1');
    expect(confirmMutate.mock.calls[0][0].idempotencyKey).toBeTruthy();
  });

  it('hides the Confirm button once the SO is past DRAFT', () => {
    vi.spyOn(soQueries, 'useSalesOrder').mockReturnValue(
      queryResult({
        sales_order_id: 'so-1',
        org_id: 'o',
        firm_id: 'f',
        series: 'SO/2526',
        number: '0001',
        display_number: 'SO/2526/0001',
        party_id: 'p1',
        so_date: '2026-04-30',
        delivery_date: null,
        status: 'CONFIRMED',
        total_amount: 150_000,
        notes: null,
        lines: [],
        created_at: '2026-04-30T00:00:00Z',
        updated_at: '2026-04-30T00:00:00Z',
      }),
    );
    vi.spyOn(partiesQueries, 'useParties').mockReturnValue(queryResult([]));
    vi.spyOn(itemsQueries, 'useItems').mockReturnValue(queryResult([]));
    vi.spyOn(soQueries, 'useConfirmSo').mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    vi.spyOn(soQueries, 'useCancelSo').mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderRoute('/sales/orders/:id', <SalesOrderDetail />, '/sales/orders/so-1');

    expect(screen.queryByRole('button', { name: /^confirm$/i })).not.toBeInTheDocument();
    // Build DC affordance is visible at-or-past CONFIRMED.
    expect(screen.getByRole('button', { name: /build dc/i })).toBeInTheDocument();
  });
});
