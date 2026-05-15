/*
 * TASK-TR-C01 — NewJournalVoucherDialog unit tests.
 *
 * Runs in mock mode (`VITE_API_MODE=mock`), so the create-JV mutation
 * resolves through the fakeFetch branch and the dialog can validate
 * client-side state machine + UI affordances without a live backend.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { NewJournalVoucherDialog } from '@/pages/accounting/NewJournalVoucherDialog';
import { authStore } from '@/store/auth';

const FAKE_ME = {
  user_id: 'u1',
  org_id: 'o1',
  firm_id: 'f1',
  email: 't@example.com',
  permissions: ['accounting.voucher.post', 'accounting.coa.read'],
  flags: {},
  available_firms: [{ firm_id: 'f1', code: 'F1', name: 'Firm 1' }],
  token_expires_at: new Date(Date.now() + 60_000).toISOString(),
};

function renderDialog() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  // Prime the mock ledgers cache so the picker renders options.
  qc.setQueryData(
    ['accounts', 'ledgers'],
    [
      { ledger_id: 'led-cash', code: '1000', name: 'Cash on Hand', ledger_type: 'CASH' },
      { ledger_id: 'led-sales', code: '4000', name: 'Sales Revenue', ledger_type: 'REVENUE' },
    ],
  );
  return render(
    <QueryClientProvider client={qc}>
      <NewJournalVoucherDialog open={true} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  authStore.setMe(FAKE_ME);
});

afterEach(() => {
  authStore.reset();
});

describe('NewJournalVoucherDialog', () => {
  it('renders with two empty lines by default', () => {
    renderDialog();
    expect(screen.getByLabelText(/line 1 ledger/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/line 2 ledger/i)).toBeInTheDocument();
    // No third line out of the box.
    expect(screen.queryByLabelText(/line 3 ledger/i)).not.toBeInTheDocument();
  });

  it('disables submit while DR and CR totals are zero (no amounts entered)', () => {
    renderDialog();
    const submit = screen.getByRole('button', { name: /post voucher/i });
    expect(submit).toBeDisabled();
  });

  it('disables submit when only one line is filled (single-line guard)', () => {
    renderDialog();
    const submit = screen.getByRole('button', { name: /post voucher/i });

    // Fill only the first line.
    fireEvent.change(screen.getByLabelText(/line 1 ledger/i), { target: { value: 'led-cash' } });
    fireEvent.change(screen.getByLabelText(/line 1 amount/i), { target: { value: '500' } });
    // Submit must remain disabled — Σ DR (500) != Σ CR (0).
    expect(submit).toBeDisabled();
  });

  it('disables submit when DR / CR are unbalanced and surfaces the difference', () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText(/line 1 ledger/i), { target: { value: 'led-cash' } });
    fireEvent.change(screen.getByLabelText(/line 1 amount/i), { target: { value: '1500' } });
    fireEvent.change(screen.getByLabelText(/line 2 ledger/i), { target: { value: 'led-sales' } });
    fireEvent.change(screen.getByLabelText(/line 2 amount/i), { target: { value: '1000' } });
    const submit = screen.getByRole('button', { name: /post voucher/i });
    expect(submit).toBeDisabled();
    // Difference indicator shows a non-zero number; "Balanced" text not present.
    expect(screen.queryByText(/^balanced$/i)).not.toBeInTheDocument();
  });

  it('enables submit when DR == CR and both lines have ledger + amount', async () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText(/line 1 ledger/i), { target: { value: 'led-cash' } });
    fireEvent.change(screen.getByLabelText(/line 1 amount/i), { target: { value: '750' } });
    fireEvent.change(screen.getByLabelText(/line 2 ledger/i), { target: { value: 'led-sales' } });
    fireEvent.change(screen.getByLabelText(/line 2 amount/i), { target: { value: '750' } });

    await waitFor(() => {
      const submit = screen.getByRole('button', { name: /post voucher/i });
      expect(submit).not.toBeDisabled();
    });
    expect(screen.getByText(/^balanced$/i)).toBeInTheDocument();
  });

  it('allows adding and removing lines (remove disabled when only two remain)', () => {
    renderDialog();
    const removeLine1 = screen.getByRole('button', { name: /remove line 1/i });
    expect(removeLine1).toBeDisabled();
    // Add a DR line; remove on first line becomes enabled.
    fireEvent.click(screen.getByRole('button', { name: /add debit line/i }));
    expect(screen.getByLabelText(/line 3 ledger/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove line 1/i })).not.toBeDisabled();
    // Remove the new third line; we're back to two and removal re-disables.
    fireEvent.click(screen.getByRole('button', { name: /remove line 3/i }));
    expect(screen.queryByLabelText(/line 3 ledger/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove line 1/i })).toBeDisabled();
  });
});
