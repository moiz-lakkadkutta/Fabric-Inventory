/*
 * #201 — NewReceiptDialog sends bank_account_id for BANK/UPI receipts.
 *
 * Once a firm has a bank account the backend 422s a BANK/UPI receipt
 * without one, so the dialog must ask for it (and must not send it for
 * CASH, which the backend also rejects).
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mutate = vi.fn();

vi.mock('@/lib/queries/accounts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/queries/accounts')>();
  return {
    ...actual,
    usePostReceipt: () => ({ mutate, isPending: false }),
  };
});

import { NewReceiptDialog } from '@/pages/accounting/NewReceiptDialog';

const ACCOUNT = (id: string, bank: string, number: string) => ({
  bank_account_id: id,
  firm_id: 'f1',
  ledger_id: `led-${id}`,
  bank_name: bank,
  account_number: number,
  ifsc_code: 'X',
  account_type: 'CURRENT',
  balance_paise: 0,
  last_reconciled_date: null,
});

function renderDialog(accounts: ReturnType<typeof ACCOUNT>[]) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  qc.setQueryData(['accounts', 'bank-accounts'], accounts);
  qc.setQueryData(
    ['accounts', 'customer-parties'],
    [{ party_id: 'p1', code: 'C1', name: 'Silk House' }],
  );
  return render(
    <QueryClientProvider client={qc}>
      <NewReceiptDialog open onClose={() => {}} />
    </QueryClientProvider>,
  );
}

function fillBasics(mode: 'CASH' | 'BANK' | 'UPI') {
  fireEvent.change(screen.getByLabelText(/Customer/), { target: { value: 'p1' } });
  fireEvent.change(screen.getByLabelText(/Amount/), { target: { value: '500' } });
  fireEvent.change(screen.getByLabelText(/Mode/), { target: { value: mode } });
}

const submit = () => fireEvent.click(screen.getByRole('button', { name: 'Save receipt' }));

describe('NewReceiptDialog bank account (#201)', () => {
  beforeEach(() => mutate.mockReset());

  it('requires a bank account for BANK when the firm has several', () => {
    renderDialog([ACCOUNT('ba-1', 'HDFC', '001234'), ACCOUNT('ba-2', 'SBI', '009876')]);
    fillBasics('BANK');

    submit();
    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/bank account/i);

    fireEvent.change(screen.getByLabelText(/Bank account/), { target: { value: 'ba-2' } });
    submit();
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toMatchObject({ mode: 'BANK', bankAccountId: 'ba-2' });
  });

  it('auto-selects the only bank account for UPI', () => {
    renderDialog([ACCOUNT('ba-1', 'HDFC', '001234')]);
    fillBasics('UPI');
    expect(screen.getByLabelText(/Bank account/)).toHaveValue('ba-1');

    submit();
    expect(mutate.mock.calls[0][0]).toMatchObject({ mode: 'UPI', bankAccountId: 'ba-1' });
  });

  it('never sends a bank account for CASH', () => {
    renderDialog([ACCOUNT('ba-1', 'HDFC', '001234')]);
    fillBasics('CASH');
    expect(screen.queryByLabelText(/Bank account/)).toBeNull();

    submit();
    expect(mutate.mock.calls[0][0].bankAccountId).toBeUndefined();
  });

  it('hides the field and sends none when the firm has no bank accounts', () => {
    renderDialog([]);
    fillBasics('BANK');
    expect(screen.queryByLabelText(/Bank account/)).toBeNull();

    submit();
    expect(mutate.mock.calls[0][0]).toMatchObject({ mode: 'BANK' });
    expect(mutate.mock.calls[0][0].bankAccountId).toBeUndefined();
  });
});
