/*
 * Bank-account picker for customer receipts (#201).
 *
 * Once a firm has at least one bank account, the backend rejects a BANK/UPI
 * receipt without `bank_account_id` (422) so every bank movement lands on a
 * reconcilable sub-ledger. Firms with no bank accounts keep the legacy
 * fallback to the 1100 control ledger, so the field is hidden for them.
 *
 * Shared by NewReceiptDialog and InvoiceDetail's "Record payment" form.
 */

import * as React from 'react';

import { Field } from '@/components/ui/field';
import { useBankAccounts, type BankAccountView, type ReceiptMode } from '@/lib/queries/accounts';

export interface ReceiptBankAccount {
  accounts: BankAccountView[];
  /** True when the current mode needs an account and the firm has one. */
  required: boolean;
  bankAccountId: string;
  setBankAccountId: (id: string) => void;
  /** The id to send on POST /receipts (undefined for CASH or no accounts). */
  payloadId: string | undefined;
}

export function useReceiptBankAccount(mode: ReceiptMode): ReceiptBankAccount {
  const bankAccounts = useBankAccounts();
  const accounts = React.useMemo(() => bankAccounts.data ?? [], [bankAccounts.data]);
  const [bankAccountId, setBankAccountId] = React.useState('');
  const required = mode !== 'CASH' && accounts.length > 0;

  // One account → pick it; nothing to choose.
  React.useEffect(() => {
    if (accounts.length === 1 && !bankAccountId) {
      setBankAccountId(accounts[0].bank_account_id);
    }
  }, [accounts, bankAccountId]);

  return {
    accounts,
    required,
    bankAccountId,
    setBankAccountId,
    payloadId: required && bankAccountId ? bankAccountId : undefined,
  };
}

function accountLabel(a: BankAccountView): string {
  const last4 = a.account_number.slice(-4);
  return last4 ? `${a.bank_name} ••${last4}` : a.bank_name || 'Bank account';
}

interface ReceiptBankAccountFieldProps {
  state: ReceiptBankAccount;
  height?: 'h-9' | 'h-10';
}

export function ReceiptBankAccountField({ state, height = 'h-10' }: ReceiptBankAccountFieldProps) {
  if (!state.required) return null;
  return (
    <Field label="Bank account" htmlFor="receipt-bank-account" required>
      <select
        id="receipt-bank-account"
        value={state.bankAccountId}
        onChange={(e) => state.setBankAccountId(e.target.value)}
        className={`${height} w-full rounded-md px-2`}
        style={{
          border: '1px solid var(--border-default)',
          background: 'var(--bg-surface)',
          fontSize: 13,
        }}
      >
        <option value="">— Select —</option>
        {state.accounts.map((a) => (
          <option key={a.bank_account_id} value={a.bank_account_id}>
            {accountLabel(a)}
          </option>
        ))}
      </select>
    </Field>
  );
}
