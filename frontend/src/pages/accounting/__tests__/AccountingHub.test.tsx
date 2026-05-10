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

  it('exposes Bank accounts and Cheques tabs (CUT-103)', async () => {
    renderAccounts();
    await waitFor(() => expect(screen.getByText('RC/25-26/0001')).toBeInTheDocument());
    // Bank accounts tab
    fireEvent.click(screen.getByRole('tab', { name: /bank accounts/i }));
    await waitFor(() => expect(screen.getByText(/no bank accounts/i)).toBeInTheDocument());
    // Cheques tab
    fireEvent.click(screen.getByRole('tab', { name: /^cheques$/i }));
    await waitFor(() =>
      expect(screen.getByText(/add a bank account first|no cheques/i)).toBeInTheDocument(),
    );
  });

  it('"+ New receipt" opens a dialog (replaces TASK-042 coming-soon)', async () => {
    renderAccounts();
    await waitFor(() => expect(screen.getByText('RC/25-26/0001')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /new receipt/i }));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /new receipt/i })).toBeInTheDocument(),
    );
    // Form has the required fields per acceptance criteria.
    expect(screen.getByLabelText(/customer/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/amount \(₹\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^mode/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^date/i)).toBeInTheDocument();
  });

  it('"+ New bank account" opens the bank-account form', async () => {
    renderAccounts();
    await waitFor(() => expect(screen.getByText('RC/25-26/0001')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: /bank accounts/i }));
    fireEvent.click(screen.getByRole('button', { name: /new bank account/i }));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /new bank account/i })).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/bank name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/account number/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/ifsc/i)).toBeInTheDocument();
  });

  it('"+ New voucher" still opens a coming-soon (v2 — journal vouchers)', async () => {
    renderAccounts();
    await waitFor(() => expect(screen.getByText('RC/25-26/0001')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: /vouchers/i }));
    fireEvent.click(screen.getByRole('button', { name: /new voucher/i }));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /new journal voucher/i })).toBeInTheDocument(),
    );
    expect(screen.getByText(/v2 — journal vouchers/i)).toBeInTheDocument();
  });
});
