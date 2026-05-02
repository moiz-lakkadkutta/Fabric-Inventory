import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { resetInvoiceStore } from '@/lib/queries/invoices';
import InvoiceCreate from '@/pages/sales/InvoiceCreate';
import InvoiceDetail from '@/pages/sales/InvoiceDetail';
import InvoiceList from '@/pages/sales/InvoiceList';

function renderFlow(initial = '/sales/invoices/new') {
  resetInvoiceStore();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/sales/invoices" element={<InvoiceList />} />
          <Route path="/sales/invoices/new" element={<InvoiceCreate />} />
          <Route path="/sales/invoices/:id" element={<InvoiceDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function waitForCreateReady() {
  await waitFor(() =>
    expect(screen.getByRole('button', { name: /save draft/i })).not.toBeDisabled(),
  );
}

describe('Invoice flow: Create -> Finalize -> Detail', () => {
  it('renders the create page with at least one editable line', async () => {
    renderFlow();
    expect(screen.getByRole('heading', { level: 1, name: /new invoice/i })).toBeInTheDocument();
    await waitForCreateReady();
    expect(screen.getAllByRole('spinbutton', { name: /qty/i }).length).toBeGreaterThan(0);
  });

  it('updates the live total when a line qty changes', async () => {
    renderFlow();
    await waitForCreateReady();
    const qtyInput = screen.getAllByRole('spinbutton', { name: /qty/i })[0];
    fireEvent.change(qtyInput, { target: { value: '10' } });
    expect(screen.getByLabelText(/grand total/i).textContent).toMatch(/₹/);
  });

  it('saves a draft, routes to detail, and shows DRAFT status', async () => {
    renderFlow();
    await waitForCreateReady();
    fireEvent.click(screen.getByRole('button', { name: /save draft/i }));
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^RT\/2526\//),
    );
    expect(screen.getByText(/^Draft$/)).toBeInTheDocument();
  });

  it('finalizes a new invoice and shows FINALIZED status on the detail page', async () => {
    renderFlow();
    await waitForCreateReady();
    fireEvent.click(screen.getByRole('button', { name: /finalize/i }));
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^RT\/2526\//),
    );
    await waitFor(() => expect(screen.getByText(/^Finalized$/)).toBeInTheDocument());
  });

  it('finalizes an existing draft from the detail page', async () => {
    renderFlow('/sales/invoices/inv_1001');
    await waitFor(() => expect(screen.getByText(/^Draft$/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /finalize/i }));
    await waitFor(() => expect(screen.getByText(/^Finalized$/)).toBeInTheDocument());
  });
});
