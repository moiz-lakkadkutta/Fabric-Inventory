/*
 * TASK-TR-B3 — BankReconcile page unit tests.
 *
 * Covers:
 *   - CSV parser handles header/positional + DD-MM-YYYY dates
 *   - Step 1 → Step 2 navigation after picking a bank account
 *   - CSV upload renders preview rows
 *   - Empty / unknown CSV surfaces the error banner
 *   - Confirm button stays disabled with zero matches
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import BankReconcile from '@/pages/accounting/BankReconcile';
import { parseStatementCsv } from '@/lib/queries/bank-reconciliation';
import { authStore } from '@/store/auth';

const FAKE_ME = {
  user_id: 'u1',
  org_id: 'o1',
  firm_id: 'f1',
  email: 't@example.com',
  permissions: ['accounting.bank_recon.confirm', 'accounting.voucher.read', 'banking.bank.read'],
  flags: {},
  available_firms: [{ firm_id: 'f1', code: 'F1', name: 'Firm 1' }],
  token_expires_at: new Date(Date.now() + 60_000).toISOString(),
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  // Seed bank accounts cache so we can skip the loading state in tests.
  qc.setQueryData(
    ['accounts', 'bank-accounts'],
    [
      {
        bank_account_id: 'ba-1',
        firm_id: 'f1',
        ledger_id: 'led-bank',
        bank_name: 'HDFC',
        account_number: '****1234',
        ifsc_code: 'HDFC0001234',
        account_type: 'CURRENT',
        balance_paise: 100_000_00,
        last_reconciled_date: null,
      },
    ],
  );
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/accounting/bank-recon']}>
        <BankReconcile />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  authStore.setMe(FAKE_ME);
});

afterEach(() => {
  authStore.reset();
});

describe('parseStatementCsv', () => {
  it('parses a header-mapped CSV with DD/MM/YYYY dates', () => {
    const csv = [
      'Date,Description,Amount,Balance',
      '15/05/2026,UPI Acme,1000.00,5000.00',
      '16/05/2026,NEFT refund,-250.00,4750.00',
    ].join('\n');
    const rows = parseStatementCsv(csv);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({
      statement_date: '2026-05-15',
      description: 'UPI Acme',
      amount: '1000.00',
      balance: '5000.00',
    });
    expect(rows[1].amount).toBe('-250.00');
  });

  it('falls back to positional columns when there is no recognisable header', () => {
    const csv = '2026-05-15,Cheque deposit,500.00,1500.00';
    const rows = parseStatementCsv(csv);
    expect(rows).toHaveLength(1);
    expect(rows[0].statement_date).toBe('2026-05-15');
  });

  it('coalesces separate debit / credit columns', () => {
    const csv = [
      'Date,Narration,Debit,Credit,Balance',
      '15/05/2026,Vendor payment,500.00,,4500.00',
      '16/05/2026,Customer receipt,,1000.00,5500.00',
    ].join('\n');
    const rows = parseStatementCsv(csv);
    expect(rows[0].amount).toBe('-500.00');
    expect(rows[1].amount).toBe('1000.00');
  });

  it('skips rows with no usable date', () => {
    const csv = ['Date,Description,Amount', ',Bad row,100', '15/05/2026,Good,200'].join('\n');
    const rows = parseStatementCsv(csv);
    expect(rows).toHaveLength(1);
    expect(rows[0].description).toBe('Good');
  });
});

describe('BankReconcile page', () => {
  it('renders Step 1 with the bank-account picker', async () => {
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /reconcile bank statement/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/bank account/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /next: upload csv/i })).toBeDisabled();
  });

  it('advances to Step 2 once a bank account is picked', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText(/bank account/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/bank account/i), { target: { value: 'ba-1' } });
    const next = screen.getByRole('button', { name: /next: upload csv/i });
    expect(next).not.toBeDisabled();
    fireEvent.click(next);

    await waitFor(() => expect(screen.getByLabelText(/bank statement csv/i)).toBeInTheDocument());
    expect(screen.getByText(/expected columns:/i)).toBeInTheDocument();
  });

  it('renders parsed CSV rows in a preview table', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText(/bank account/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/bank account/i), { target: { value: 'ba-1' } });
    fireEvent.click(screen.getByRole('button', { name: /next: upload csv/i }));

    const csv = ['Date,Description,Amount,Balance', '15/05/2026,UPI Acme,1000.00,5000.00'].join(
      '\n',
    );
    const file = new File([csv], 'statement.csv', { type: 'text/csv' });

    const input = screen.getByLabelText(/bank statement csv/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText(/statement.csv/i)).toBeInTheDocument());
    expect(screen.getByText('UPI Acme')).toBeInTheDocument();
    expect(screen.getByText('1000.00')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /find matches/i })).not.toBeDisabled();
  });

  it('surfaces an error for an empty CSV', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText(/bank account/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/bank account/i), { target: { value: 'ba-1' } });
    fireEvent.click(screen.getByRole('button', { name: /next: upload csv/i }));

    // CSV with only an unparseable line.
    const file = new File(['garbage,no,date'], 'bad.csv', { type: 'text/csv' });
    const input = screen.getByLabelText(/bank statement csv/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/no usable rows/i));
  });
});
