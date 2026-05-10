import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as dcQueries from '@/lib/queries/delivery-challans';
import * as soQueries from '@/lib/queries/sales-orders';
import * as partiesQueries from '@/lib/queries/parties';
import * as itemsQueries from '@/lib/queries/items';
import DeliveryChallanCreate from '@/pages/sales/DeliveryChallanCreate';
import DeliveryChallanDetail from '@/pages/sales/DeliveryChallanDetail';
import DeliveryChallanList from '@/pages/sales/DeliveryChallanList';
import { authStore } from '@/store/auth';

/*
 * TASK-CUT-203 — Delivery Challan happy-path FE flow.
 *
 *   1. List page renders rows from useDeliveryChallans().
 *   2. Create page submits via useCreateDc().
 *   3. Detail page Issue button calls useIssueDc and the mutation
 *      payload includes the dc id + a fresh idempotency key.
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

describe('DeliveryChallanList', () => {
  it('renders rows + maps party name from useParties', () => {
    vi.spyOn(dcQueries, 'useDeliveryChallans').mockReturnValue(
      queryResult([
        {
          delivery_challan_id: 'dc-1',
          org_id: 'o',
          firm_id: 'f',
          series: 'DC/2526',
          number: '0001',
          display_number: 'DC/2526/0001',
          sales_order_id: 'so-1',
          party_id: 'p1',
          bill_to_address: null,
          ship_to_address: null,
          place_of_supply_state: 'MH',
          dispatch_date: '2026-05-01',
          status: 'DRAFT',
          total_qty: 3,
          total_amount: 150_000,
          lines: [],
          created_at: '2026-05-01T00:00:00Z',
          updated_at: '2026-05-01T00:00:00Z',
        },
      ]),
    );
    vi.spyOn(partiesQueries, 'useParties').mockReturnValue(
      queryResult([{ party_id: 'p1', name: 'ACME Pvt' }]),
    );

    renderRoute('/sales/delivery-challans', <DeliveryChallanList />, '/sales/delivery-challans');

    expect(
      screen.getByRole('heading', { level: 1, name: /delivery challans/i }),
    ).toBeInTheDocument();
    expect(screen.getByText('DC/2526/0001')).toBeInTheDocument();
    expect(screen.getByText('ACME Pvt')).toBeInTheDocument();
    // "Draft" appears in both filter pill + status pill; >0 is enough.
    expect(screen.getAllByText('Draft').length).toBeGreaterThan(0);
  });
});

describe('DeliveryChallanCreate', () => {
  it('submits a create payload via useCreateDc when Save is clicked', async () => {
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
      queryResult([{ item_id: 'i1', name: 'Cotton', primary_uom: 'PIECE', gst_rate: 5 }]),
    );
    // Free-form mode: no SO selected; we keep the SO list empty.
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
    // Set qty to a positive value (default is 1, line item auto-fills).
    fireEvent.click(screen.getByRole('button', { name: /save dc/i }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const payload = mutateAsync.mock.calls[0][0];
    expect(payload.firm_id).toBe('firm-1');
    expect(payload.party_id).toBe('p1');
    expect(payload.sales_order_id).toBeUndefined();
    expect(payload.lines).toHaveLength(1);
    expect(payload.lines[0].item_id).toBe('i1');
    expect(payload.idempotencyKey).toBeTruthy();
  });
});

describe('DeliveryChallanDetail', () => {
  it('renders Issue button for DRAFT and calls useIssueDc on click', async () => {
    vi.spyOn(dcQueries, 'useDc').mockReturnValue(
      queryResult({
        delivery_challan_id: 'dc-1',
        org_id: 'o',
        firm_id: 'f',
        series: 'DC/2526',
        number: '0001',
        display_number: 'DC/2526/0001',
        sales_order_id: null,
        party_id: 'p1',
        bill_to_address: null,
        ship_to_address: null,
        place_of_supply_state: 'MH',
        dispatch_date: '2026-05-01',
        status: 'DRAFT',
        total_qty: 3,
        total_amount: 150_000,
        lines: [],
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
      }),
    );
    vi.spyOn(partiesQueries, 'useParties').mockReturnValue(queryResult([]));
    vi.spyOn(itemsQueries, 'useItems').mockReturnValue(queryResult([]));

    const issueMutate = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(dcQueries, 'useIssueDc').mockReturnValue({
      mutateAsync: issueMutate,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderRoute(
      '/sales/delivery-challans/:id',
      <DeliveryChallanDetail />,
      '/sales/delivery-challans/dc-1',
    );

    expect(screen.getByText('DC/2526/0001')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^issue$/i }));
    await waitFor(() => expect(issueMutate).toHaveBeenCalledTimes(1));
    expect(issueMutate.mock.calls[0][0].dcId).toBe('dc-1');
    expect(issueMutate.mock.calls[0][0].idempotencyKey).toBeTruthy();
  });

  it('hides the Issue button once the DC is past DRAFT', () => {
    vi.spyOn(dcQueries, 'useDc').mockReturnValue(
      queryResult({
        delivery_challan_id: 'dc-1',
        org_id: 'o',
        firm_id: 'f',
        series: 'DC/2526',
        number: '0001',
        display_number: 'DC/2526/0001',
        sales_order_id: null,
        party_id: 'p1',
        bill_to_address: null,
        ship_to_address: null,
        place_of_supply_state: 'MH',
        dispatch_date: '2026-05-01',
        status: 'ISSUED',
        total_qty: 3,
        total_amount: 150_000,
        lines: [],
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
      }),
    );
    vi.spyOn(partiesQueries, 'useParties').mockReturnValue(queryResult([]));
    vi.spyOn(itemsQueries, 'useItems').mockReturnValue(queryResult([]));
    vi.spyOn(dcQueries, 'useIssueDc').mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderRoute(
      '/sales/delivery-challans/:id',
      <DeliveryChallanDetail />,
      '/sales/delivery-challans/dc-1',
    );

    expect(screen.queryByRole('button', { name: /^issue$/i })).not.toBeInTheDocument();
    expect(screen.getByText('Issued')).toBeInTheDocument();
  });
});
