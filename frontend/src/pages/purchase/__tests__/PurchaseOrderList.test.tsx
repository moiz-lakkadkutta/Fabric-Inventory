import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import PurchaseOrderList from '@/pages/purchase/PurchaseOrderList';

function renderPO() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PurchaseOrderList />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('PurchaseOrderList', () => {
  it('shows skeleton then PO rows with 3-way match tags', async () => {
    renderPO();
    expect(screen.getByLabelText(/loading purchase orders/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('PO/25-26/0001')).toBeInTheDocument());
    // Each row carries the PO/GRN/PI mini-tag triple.
    expect(screen.getAllByText('PO').length).toBeGreaterThan(1);
    expect(screen.getAllByText('GRN').length).toBeGreaterThan(1);
    expect(screen.getAllByText('PI').length).toBeGreaterThan(1);
  });
});
