import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import PartyDetail from '@/pages/masters/PartyDetail';
import PartyList from '@/pages/masters/PartyList';

function renderMasters(initial = '/masters/parties') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/masters/parties" element={<PartyList />} />
          <Route path="/masters/parties/:id" element={<PartyDetail />} />
          <Route path="/sales/invoices/:id" element={<div>INVOICE_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Parties list + detail', () => {
  it('lists parties and routes to detail with khata KPIs', async () => {
    renderMasters();
    await waitFor(() => expect(screen.getByText('Anjali Saree Centre')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('link', { name: /Anjali Saree Centre/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: /Anjali Saree Centre/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/total billed/i)).toBeInTheDocument();
    expect(screen.getAllByText(/outstanding/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/overdue/i).length).toBeGreaterThanOrEqual(1);
  });

  it('filters parties by Suppliers pill', async () => {
    renderMasters();
    await waitFor(() => expect(screen.getByText('Anjali Saree Centre')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /^Suppliers$/i }));
    expect(screen.queryByText('Anjali Saree Centre')).not.toBeInTheDocument();
  });
});
