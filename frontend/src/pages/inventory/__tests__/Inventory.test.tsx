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
});
