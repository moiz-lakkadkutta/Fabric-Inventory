import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as dcQueries from '@/lib/queries/delivery-challans';
import * as invoiceQueries from '@/lib/queries/invoices';
import * as itemsModule from '@/lib/queries/items';
import * as partiesModule from '@/lib/queries/parties';
import InvoiceCreate from '@/pages/sales/InvoiceCreate';

/*
 * DEBT-02 — "Create invoice" from an issued delivery challan opens
 * /sales/invoices/new?dc=<id>. The form is prefilled from the challan
 * (customer locked, lines = challan items + qty) and the create payload
 * carries delivery_challan_id so the BE posts COGS from the challan
 * instead of relieving stock a second time.
 */

afterEach(() => {
  vi.restoreAllMocks();
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const queryResult = (data: unknown, isPending = false): any => ({ data, isPending }) as unknown;

describe('InvoiceCreate from a delivery challan', () => {
  it('prefills from ?dc= and sends delivery_challan_id', async () => {
    vi.spyOn(partiesModule, 'useCustomers').mockReturnValue(
      queryResult([
        { party_id: 'p0', name: 'Someone Else', state_code: 'MH' },
        { party_id: 'p1', name: 'ACME', state_code: 'MH' },
      ]),
    );
    vi.spyOn(itemsModule, 'useItems').mockReturnValue(
      queryResult([
        { item_id: 'i0', name: 'Other', primary_uom: 'METER', gst_rate: 12 },
        { item_id: 'i1', name: 'Chiffon', primary_uom: 'METER', gst_rate: 5 },
      ]),
    );
    vi.spyOn(dcQueries, 'useDc').mockReturnValue(
      queryResult({
        delivery_challan_id: 'dc-1',
        display_number: 'DC/2526/0007',
        party_id: 'p1',
        status: 'ISSUED',
        lines: [
          {
            dc_line_id: 'l1',
            delivery_challan_id: 'dc-1',
            item_id: 'i1',
            lot_id: null,
            qty_dispatched: 12,
            price: 25_000,
            sequence: 1,
          },
        ],
      }),
    );
    const mutateAsync = vi.fn().mockResolvedValue({ invoice_id: 'inv-1' });
    vi.spyOn(invoiceQueries, 'useCreateDraftInvoice').mockReturnValue({
      mutateAsync,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/sales/invoices/new?dc=dc-1']}>
          <InvoiceCreate />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId('dc-billing-note')).toHaveTextContent('DC/2526/0007');
    const customer = screen.getByLabelText('Customer') as HTMLSelectElement;
    await waitFor(() => expect(customer.value).toBe('p1'));
    expect(customer).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /save draft/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const { draft } = mutateAsync.mock.calls[0][0];
    expect(draft.delivery_challan_id).toBe('dc-1');
    expect(draft.party_id).toBe('p1');
    expect(draft.lines).toHaveLength(1);
    expect(draft.lines[0]).toMatchObject({ item_id: 'i1', qty: 12, rate: 25_000, gst_pct: 5 });
  });

  it('sends no challan link on a plain new invoice', async () => {
    vi.spyOn(partiesModule, 'useCustomers').mockReturnValue(
      queryResult([{ party_id: 'p1', name: 'ACME', state_code: 'MH' }]),
    );
    vi.spyOn(itemsModule, 'useItems').mockReturnValue(
      queryResult([{ item_id: 'i1', name: 'Chiffon', primary_uom: 'METER', gst_rate: 5 }]),
    );
    const mutateAsync = vi.fn().mockResolvedValue({ invoice_id: 'inv-2' });
    vi.spyOn(invoiceQueries, 'useCreateDraftInvoice').mockReturnValue({
      mutateAsync,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/sales/invoices/new']}>
          <InvoiceCreate />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId('dc-billing-note')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /save draft/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(mutateAsync.mock.calls[0][0].draft.delivery_challan_id).toBeNull();
  });
});
