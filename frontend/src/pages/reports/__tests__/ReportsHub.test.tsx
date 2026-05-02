import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import ReportsHub from '@/pages/reports/ReportsHub';

function renderReports() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ReportsHub />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ReportsHub', () => {
  it('opens on the P&L tab and shows Total income / Net profit rows', async () => {
    renderReports();
    await waitFor(() => expect(screen.getAllByText(/total income/i).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/net profit/i).length).toBeGreaterThan(0);
  });

  it('switches to Trial balance and shows the balanced banner', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /trial balance/i }));
    await waitFor(() => expect(screen.getByText(/balanced/i)).toBeInTheDocument());
    // Sundry debtors is one of the asset rows.
    expect(screen.getByText(/sundry debtors/i)).toBeInTheDocument();
  });

  it('switches to GSTR-1 and shows the validation summary', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));
    await waitFor(() => expect(screen.getAllByText(/B2B/i).length).toBeGreaterThan(0));
    expect(screen.getByText(/to review|all OK/i)).toBeInTheDocument();
  });

  it('switches to Stock and shows the total stock value', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /^stock$/i }));
    await waitFor(() => expect(screen.getByText(/total stock value/i)).toBeInTheDocument());
  });

  it('switches to Daybook and shows recent vouchers', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /daybook/i }));
    await waitFor(() => expect(screen.getByText(/RC\/25-26\/0001/)).toBeInTheDocument());
  });
});
