import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import InventoryList from '@/pages/inventory/InventoryList';
import LotDetail from '@/pages/inventory/LotDetail';

function renderInventory(initial = '/inventory') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/inventory" element={<InventoryList />} />
          <Route path="/inventory/lots/:id" element={<LotDetail />} />
          {/* TASK-TR-B05: "New GRN" routes to the real GRN create flow */}
          <Route
            path="/purchase/grns/new"
            element={<div data-testid="grn-create-page">GRN create page</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Inventory list + Lot detail', () => {
  it('shows a loading skeleton then SKU rows', async () => {
    renderInventory();
    expect(screen.getByLabelText(/loading inventory/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Silk Georgette 60"')).toBeInTheDocument());
  });

  it('navigates to the lot detail and renders the StagesTimeline', async () => {
    renderInventory();
    const link = await screen.findByRole('link', { name: /Silk Georgette 60/ });
    fireEvent.click(link);
    await waitFor(() => expect(screen.getByText(/journey of this lot/i)).toBeInTheDocument());
    // Active stage card should be present.
    expect(screen.getByRole('button', { name: /At embroidery/ })).toBeInTheDocument();
  });

  it('filters SKUs by search query', async () => {
    renderInventory();
    await waitFor(() => expect(screen.getByText('Silk Georgette 60"')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/search SKUs/i), {
      target: { value: 'kanchipuram' },
    });
    expect(screen.getByText('Kanchipuram Pattu')).toBeInTheDocument();
    expect(screen.queryByText('Silk Georgette 60"')).not.toBeInTheDocument();
  });

  it('routes "+ New GRN" to the real GRN create flow (TASK-TR-B05)', async () => {
    renderInventory();
    // Wait for the page to finish loading so the header is rendered.
    await waitFor(() => expect(screen.getByText('Silk Georgette 60"')).toBeInTheDocument());

    const newGrn = screen.getByRole('link', { name: /new grn/i });
    expect(newGrn).toHaveAttribute('href', '/purchase/grns/new');

    fireEvent.click(newGrn);
    await waitFor(() => expect(screen.getByTestId('grn-create-page')).toBeInTheDocument());
    // The old ComingSoon dialog should not appear.
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
  });
});
