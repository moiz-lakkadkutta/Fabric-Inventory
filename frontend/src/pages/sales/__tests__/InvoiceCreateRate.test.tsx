import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as invoiceQueries from '@/lib/queries/invoices';
import * as itemsModule from '@/lib/queries/items';
import * as partiesModule from '@/lib/queries/parties';
import InvoiceCreate from '@/pages/sales/InvoiceCreate';

/*
 * Bug found recording the demo films: the line Rate input re-formatted to
 * 2 decimals on every keystroke, so typing "2950" produced ₹2.02. The
 * input must keep the raw typed text while editing and format on blur.
 */

afterEach(() => {
  vi.restoreAllMocks();
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const queryResult = (data: unknown, isPending = false): any => ({ data, isPending }) as unknown;

/** Simulate typing one character at a time, the way a browser would:
 * each keystroke appends to whatever the input currently displays. */
function typeChars(input: HTMLInputElement, chars: string) {
  for (const ch of chars) {
    fireEvent.change(input, { target: { value: input.value + ch } });
  }
}

describe('InvoiceCreate line Rate input', () => {
  it('keeps typed digits while editing and formats to 2 decimals on blur', async () => {
    vi.spyOn(partiesModule, 'useCustomers').mockReturnValue(
      queryResult([{ party_id: 'p1', name: 'ACME', state_code: 'MH' }]),
    );
    vi.spyOn(itemsModule, 'useItems').mockReturnValue(
      queryResult([{ item_id: 'i1', name: 'Chiffon', primary_uom: 'METER', gst_rate: 5 }]),
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
        <MemoryRouter initialEntries={['/sales/invoices/new']}>
          <InvoiceCreate />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const rate = screen.getByLabelText('Rate') as HTMLInputElement;
    expect(rate.value).toBe('0.00');
    fireEvent.focus(rate);
    // User clears the field, then types 2950 digit by digit.
    fireEvent.change(rate, { target: { value: '' } });
    typeChars(rate, '2950');
    expect(rate.value).toBe('2950');

    fireEvent.blur(rate);
    expect(rate.value).toBe('2950.00');

    fireEvent.click(screen.getByRole('button', { name: /save draft/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(mutateAsync.mock.calls[0][0].draft.lines[0].rate).toBe(295_000);
  });
});
