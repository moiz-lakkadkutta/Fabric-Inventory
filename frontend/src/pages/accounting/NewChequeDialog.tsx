/*
 * NewChequeDialog (TASK-CUT-103) — POST /cheques. Cheques are scoped
 * per bank account; the parent panel passes in `bankAccountId` from
 * the active selection. Status defaults to ISSUED.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useCreateCheque } from '@/lib/queries/accounts';
import { useMe } from '@/store/auth';

interface NewChequeDialogProps {
  open: boolean;
  onClose: () => void;
  bankAccountId: string | null;
}

const TODAY = (): string => new Date().toISOString().slice(0, 10);

export function NewChequeDialog({ open, onClose, bankAccountId }: NewChequeDialogProps) {
  const me = useMe();
  const create = useCreateCheque();
  const idem = useIdempotencyKey();

  const [chequeNumber, setChequeNumber] = React.useState('');
  const [chequeDate, setChequeDate] = React.useState<string>(TODAY());
  const [payeeName, setPayeeName] = React.useState('');
  const [amount, setAmount] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setChequeNumber('');
      setChequeDate(TODAY());
      setPayeeName('');
      setAmount('');
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
    if (!bankAccountId) {
      setError('Pick a bank account first.');
      return;
    }
    if (!chequeNumber.trim()) {
      setError('Cheque number is required.');
      return;
    }
    const amountRupees = parseFloat(amount);
    if (!Number.isFinite(amountRupees) || amountRupees <= 0) {
      setError('Enter a positive amount.');
      return;
    }
    create.mutate(
      {
        firmId: me.firm_id,
        bankAccountId,
        chequeNumber: chequeNumber.trim(),
        chequeDate,
        payeeName: payeeName.trim(),
        amountPaise: Math.round(amountRupees * 100),
        idempotencyKey: idem.key,
      },
      {
        onSuccess: () => {
          idem.reset();
          onClose();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Could not record cheque.');
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New cheque"
      description="Record a cheque issued from this bank account."
      width={520}
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="new-cheque-form" disabled={create.isPending}>
            Record
          </Button>
        </>
      }
    >
      <form id="new-cheque-form" onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Cheque number" htmlFor="cheque-number" required>
            <Input
              id="cheque-number"
              value={chequeNumber}
              onChange={(e) => setChequeNumber(e.target.value)}
              placeholder="000001"
            />
          </Field>
          <Field label="Date" htmlFor="cheque-date" required>
            <Input
              id="cheque-date"
              type="date"
              value={chequeDate}
              onChange={(e) => setChequeDate(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Payee" htmlFor="cheque-payee">
          <Input
            id="cheque-payee"
            value={payeeName}
            onChange={(e) => setPayeeName(e.target.value)}
            placeholder="e.g. Surat Silk Mills"
          />
        </Field>
        <Field label="Amount (₹)" htmlFor="cheque-amount" required>
          <Input
            id="cheque-amount"
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
          />
        </Field>
        {error && (
          <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 12.5 }}>
            {error}
          </div>
        )}
      </form>
    </Dialog>
  );
}
