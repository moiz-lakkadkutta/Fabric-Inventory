import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as itemsModule from '@/lib/queries/items';
import * as partiesModule from '@/lib/queries/parties';
import InvoiceCreate from '@/pages/sales/InvoiceCreate';

/*
 * CUT-108 — InvoiceCreate must surface an empty-state CTA when the
 * customer or item master is empty. Without it, a fresh-signup user
 * (zero parties, zero items) lands on /sales/invoices/new, sees an
 * empty <select>, and has no path forward — they often stumble into
 * /inventory's "+ New GRN" Coming Soon dialog instead of /masters/items.
 */

function renderCreate() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/sales/invoices/new']}>
        <InvoiceCreate />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

// TanStack Query's UseQueryResult is a discriminated union with 24+
// fields per branch — we only care about `data` and `isPending` for
// these tests, so we coerce through `unknown` rather than constructing
// a fully-shaped result.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const queryResult = (data: unknown, isPending = false): any => ({ data, isPending }) as unknown;

describe('InvoiceCreate empty state', () => {
  it('shows an Add party CTA when there are zero customers', () => {
    vi.spyOn(partiesModule, 'useCustomers').mockReturnValue(queryResult([]));
    vi.spyOn(itemsModule, 'useItems').mockReturnValue(
      queryResult([{ item_id: 'i1', name: 'Cotton', primary_uom: 'PIECE', gst_rate: 5 }]),
    );

    renderCreate();

    expect(screen.getByText(/no customers yet/i)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /add a customer/i });
    expect(link).toHaveAttribute('href', '/masters/parties');
  });

  it('shows an Add item CTA when there are zero items', () => {
    vi.spyOn(partiesModule, 'useCustomers').mockReturnValue(
      queryResult([{ party_id: 'p1', name: 'ACME', state_code: 'MH' }]),
    );
    vi.spyOn(itemsModule, 'useItems').mockReturnValue(queryResult([]));

    renderCreate();

    expect(screen.getByText(/no items yet/i)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /add an item/i });
    expect(link).toHaveAttribute('href', '/masters/items');
  });
});
