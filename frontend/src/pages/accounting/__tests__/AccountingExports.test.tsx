import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AccountingHub from '@/pages/accounting/AccountingHub';

/**
 * TASK-CUT-501b — bank-accounts + cheques tabs grow Export buttons.
 *
 * Mirrors `frontend/src/pages/sales/__tests__/InvoiceListExport.test.tsx`:
 * tests run in mock mode (`VITE_API_MODE=mock`), so clicking Export
 * surfaces the "set VITE_API_MODE=live" hint instead of calling the
 * backend. Confirms the button is wired into the live-export plumbing
 * rather than a `useComingSoon` dialog.
 */

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

describe('AccountingHub — Export buttons (TASK-CUT-501b)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('Bank accounts tab shows Export CSV + Export Excel buttons', async () => {
    renderAccounts();
    // Wait for first render on Receipts tab.
    await waitFor(() => expect(screen.getByText('RC/25-26/0001')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: /bank accounts/i }));

    const csvButton = screen.getByRole('button', { name: /export bank-accounts to CSV/i });
    const xlsxButton = screen.getByRole('button', { name: /export bank-accounts to Excel/i });
    expect(csvButton).toBeInTheDocument();
    expect(xlsxButton).toBeInTheDocument();

    // Click Export CSV — mock mode surfaces the "live backend" hint, not
    // a coming-soon dialog. Confirms the button is wired to the export
    // pipeline rather than `useComingSoon`.
    fireEvent.click(csvButton);
    expect(screen.queryByText(/click-dummy/i)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/live backend/i);
    });
  });

  it('Cheques tab shows Export CSV + Export Excel buttons', async () => {
    renderAccounts();
    await waitFor(() => expect(screen.getByText('RC/25-26/0001')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: /^cheques$/i }));

    const csvButton = screen.getByRole('button', { name: /export cheques to CSV/i });
    const xlsxButton = screen.getByRole('button', { name: /export cheques to Excel/i });
    expect(csvButton).toBeInTheDocument();
    expect(xlsxButton).toBeInTheDocument();
    // Mock mode + no bank-account list resolves to disabled buttons (mock
    // returns []). That's fine — the test asserts the buttons exist and
    // are not a `useComingSoon` dialog.
    expect(screen.queryByText(/click-dummy/i)).not.toBeInTheDocument();
  });
});
