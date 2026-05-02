import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { resetInvoiceStore } from '@/lib/queries/invoices';
import InvoiceList from '@/pages/sales/InvoiceList';

function renderInvoiceList() {
  resetInvoiceStore();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/sales/invoices']}>
        <Routes>
          <Route path="/sales/invoices" element={<InvoiceList />} />
          <Route path="/sales/invoices/new" element={<div>NEW_INVOICE_REACHED</div>} />
          <Route path="/sales/invoices/:id" element={<div>DETAIL_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InvoiceList', () => {
  it('shows a loading skeleton before mock data resolves', () => {
    renderInvoiceList();
    expect(screen.getByLabelText(/loading invoices/i)).toBeInTheDocument();
  });

  it('renders rows once mock data has resolved and links the New invoice button to /sales/invoices/new', async () => {
    renderInvoiceList();
    await waitFor(() => expect(screen.getByText(/RT\/2526\/0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /new invoice/i }));
    expect(screen.getByText('NEW_INVOICE_REACHED')).toBeInTheDocument();
  });

  it('navigates to the invoice detail when a row is clicked', async () => {
    renderInvoiceList();
    const link = await screen.findByRole('link', { name: /RT\/2526\/0001/ });
    fireEvent.click(link);
    expect(screen.getByText('DETAIL_REACHED')).toBeInTheDocument();
  });

  it('filters rows when the Drafts pill is selected', async () => {
    renderInvoiceList();
    await waitFor(() => expect(screen.getByText(/RT\/2526\/0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /^Drafts$/i }));
    // Only DRAFT invoices remain — the seed data uses RT/2526/0001..0003.
    expect(screen.getByText(/RT\/2526\/0001/)).toBeInTheDocument();
    expect(screen.queryByText(/RT\/2526\/0004/)).not.toBeInTheDocument();
  });
});
