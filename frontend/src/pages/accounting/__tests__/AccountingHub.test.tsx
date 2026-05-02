import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import AccountingHub from '@/pages/accounting/AccountingHub';

function renderAccounts() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AccountingHub />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AccountingHub', () => {
  it('opens on Receipts tab and shows posted/bounced statuses', async () => {
    renderAccounts();
    await waitFor(() => expect(screen.getByText('RC/25-26/0001')).toBeInTheDocument());
    expect(screen.getAllByText(/posted/i).length).toBeGreaterThan(1);
    expect(screen.getAllByText(/bounced/i).length).toBeGreaterThanOrEqual(1);
  });

  it('switches to Vouchers tab and shows balanced markers', async () => {
    renderAccounts();
    await waitFor(() => expect(screen.getByText('RC/25-26/0001')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: /vouchers/i }));
    await waitFor(() => expect(screen.getByText('JV/25-26/0014')).toBeInTheDocument());
    expect(screen.getAllByText(/balanced/i).length).toBeGreaterThan(1);
  });
});
