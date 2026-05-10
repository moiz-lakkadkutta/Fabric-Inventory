/*
 * NewBankAccountDialog (TASK-CUT-103) — POST /bank-accounts after first
 * creating the per-bank ASSET ledger via /ledgers (the schema requires
 * `ledger_id` and the BE service does not auto-create one). Both calls
 * happen inside `useCreateBankAccount`'s mutation; the dialog only
 * collects the human-friendly fields.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useCreateBankAccount } from '@/lib/queries/accounts';
import { useMe } from '@/store/auth';

interface NewBankAccountDialogProps {
  open: boolean;
  onClose: () => void;
}

export function NewBankAccountDialog({ open, onClose }: NewBankAccountDialogProps) {
  const me = useMe();
  const create = useCreateBankAccount();
  const idem = useIdempotencyKey();

  const [bankName, setBankName] = React.useState('');
  const [accountNumber, setAccountNumber] = React.useState('');
  const [ifscCode, setIfscCode] = React.useState('');
  const [accountType, setAccountType] = React.useState('CURRENT');
  const [balance, setBalance] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setBankName('');
      setAccountNumber('');
      setIfscCode('');
      setAccountType('CURRENT');
      setBalance('');
      setError(null);
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!me?.firm_id) {
      setError('No active firm in this session.');
      return;
    }
    if (!bankName.trim()) {
      setError('Bank name is required.');
      return;
    }
    const balanceRupees = balance ? parseFloat(balance) : 0;
    if (balance && (!Number.isFinite(balanceRupees) || balanceRupees < 0)) {
      setError('Balance must be a non-negative number.');
      return;
    }
    create.mutate(
      {
        firmId: me.firm_id,
        bankName: bankName.trim(),
        accountNumber: accountNumber.trim(),
        ifscCode: ifscCode.trim().toUpperCase(),
        accountType,
        balancePaise: Math.round(balanceRupees * 100),
        idempotencyKey: idem.key,
      },
      {
        onSuccess: () => {
          idem.reset();
          onClose();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Could not create bank account.');
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New bank account"
      description="Adds a new bank account to this firm. A sub-ledger under 'Bank Accounts' is auto-created."
      width={520}
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="new-bank-form" disabled={create.isPending}>
            Create
          </Button>
        </>
      }
    >
      <form id="new-bank-form" onSubmit={onSubmit} className="flex flex-col gap-3">
        <Field label="Bank name" htmlFor="bank-name" required>
          <Input
            id="bank-name"
            value={bankName}
            onChange={(e) => setBankName(e.target.value)}
            placeholder="e.g. HDFC Bank"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Account number" htmlFor="bank-acc-no">
            <Input
              id="bank-acc-no"
              value={accountNumber}
              onChange={(e) => setAccountNumber(e.target.value)}
              placeholder="00123456789012"
            />
          </Field>
          <Field label="IFSC" htmlFor="bank-ifsc">
            <Input
              id="bank-ifsc"
              value={ifscCode}
              onChange={(e) => setIfscCode(e.target.value)}
              placeholder="HDFC0001234"
            />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Account type" htmlFor="bank-type">
            <select
              id="bank-type"
              value={accountType}
              onChange={(e) => setAccountType(e.target.value)}
              className="h-10 w-full rounded-md px-2"
              style={{
                border: '1px solid var(--border-default)',
                background: 'var(--bg-surface)',
                fontSize: 13,
              }}
            >
              <option value="CURRENT">Current</option>
              <option value="SAVINGS">Savings</option>
              <option value="CC">Cash credit</option>
              <option value="OD">Overdraft</option>
            </select>
          </Field>
          <Field label="Opening balance (₹)" htmlFor="bank-balance">
            <Input
              id="bank-balance"
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0"
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
              placeholder="0.00"
            />
          </Field>
        </div>
        {error && (
          <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 12.5 }}>
            {error}
          </div>
        )}
      </form>
    </Dialog>
  );
}
