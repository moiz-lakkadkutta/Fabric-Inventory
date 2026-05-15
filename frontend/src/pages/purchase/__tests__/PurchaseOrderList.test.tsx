import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import PurchaseOrderList from '@/pages/purchase/PurchaseOrderList';

function renderPO() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/purchase']}>
        <Routes>
          <Route path="/purchase" element={<PurchaseOrderList />} />
          {/* TASK-TR-B05: "Receive GRN" now navigates to the real GRN
              create flow instead of opening a ComingSoon dialog. */}
          <Route
            path="/purchase/grns/new"
            element={<div data-testid="grn-create-page">GRN create page</div>}
          />
        </Routes>
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

  it('routes "Receive GRN" to the real GRN create flow (TASK-TR-B05)', async () => {
    renderPO();
    await waitFor(() => expect(screen.getByText('PO/25-26/0001')).toBeInTheDocument());

    const receiveBtn = screen.getByRole('button', { name: /receive grn/i });
    fireEvent.click(receiveBtn);

    await waitFor(() => expect(screen.getByTestId('grn-create-page')).toBeInTheDocument());
    // The old ComingSoon dialog should not appear.
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
  });
});
