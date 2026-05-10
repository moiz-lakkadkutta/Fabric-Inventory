/*
 * NewReceiptDialog (TASK-CUT-103) — replaces the previous
 * `useComingSoon('TASK-042')` on `/accounting`. Posts to /receipts via
 * `usePostReceipt` (which is also used by InvoiceDetail's "Record
 * payment").
 *
 * Required fields: party (typeahead from /parties customers), amount,
 * mode (CASH/BANK/UPI), date, optional reference. The form mirrors the
 * existing InvoiceDetail receipt form so the visual feel is consistent.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useCustomerParties, usePostReceipt, type ReceiptMode } from '@/lib/queries/accounts';

interface NewReceiptDialogProps {
  open: boolean;
  onClose: () => void;
}

const TODAY = (): string => new Date().toISOString().slice(0, 10);

export function NewReceiptDialog({ open, onClose }: NewReceiptDialogProps) {
  const customers = useCustomerParties();
  const postReceipt = usePostReceipt();
  const idem = useIdempotencyKey();
  const [partyId, setPartyId] = React.useState('');
  const [amount, setAmount] = React.useState('');
  const [mode, setMode] = React.useState<ReceiptMode>('CASH');
  const [reference, setReference] = React.useState('');
  const [date, setDate] = React.useState<string>(TODAY());
  const [error, setError] = React.useState<string | null>(null);

  // Reset on open so the dialog never shows stale state from a previous
  // submission.
  React.useEffect(() => {
    if (open) {
      setPartyId('');
      setAmount('');
      setMode('CASH');
      setReference('');
      setDate(TODAY());
      setError(null);
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!partyId) {
      setError('Pick a customer.');
      return;
    }
    const amountRupees = parseFloat(amount);
    if (!Number.isFinite(amountRupees) || amountRupees <= 0) {
      setError('Enter a positive amount.');
      return;
    }
    const partyName = customers.data?.find((c) => c.party_id === partyId)?.name ?? '';
    postReceipt.mutate(
      {
        partyId,
        partyName,
        amountPaise: Math.round(amountRupees * 100),
        receiptDate: date,
        mode,
        reference: reference || undefined,
        idempotencyKey: idem.key,
      },
      {
        onSuccess: () => {
          idem.reset();
          onClose();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Could not record receipt.');
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New receipt"
      description="Record an incoming customer payment. Allocates FIFO across open invoices."
      width={520}
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="new-receipt-form" disabled={postReceipt.isPending}>
            Save receipt
          </Button>
        </>
      }
    >
      <form id="new-receipt-form" onSubmit={onSubmit} className="flex flex-col gap-3">
        <Field label="Customer" htmlFor="receipt-party" required>
          <select
            id="receipt-party"
            value={partyId}
            onChange={(e) => setPartyId(e.target.value)}
            className="h-10 w-full rounded-md px-2"
            style={{
              border: '1px solid var(--border-default)',
              background: 'var(--bg-surface)',
              fontSize: 13,
            }}
          >
            <option value="">— Select —</option>
            {(customers.data ?? []).map((c) => (
              <option key={c.party_id} value={c.party_id}>
                {c.name} ({c.code})
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount (₹)" htmlFor="receipt-amount" required>
            <Input
              id="receipt-amount"
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
            />
          </Field>
          <Field label="Mode" htmlFor="receipt-mode" required>
            <select
              id="receipt-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as ReceiptMode)}
              className="h-10 w-full rounded-md px-2"
              style={{
                border: '1px solid var(--border-default)',
                background: 'var(--bg-surface)',
                fontSize: 13,
              }}
            >
              <option value="CASH">Cash</option>
              <option value="BANK">Bank</option>
              <option value="UPI">UPI</option>
            </select>
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date" htmlFor="receipt-date" required>
            <Input
              id="receipt-date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </Field>
          <Field label="Reference (optional)" htmlFor="receipt-ref">
            <Input
              id="receipt-ref"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="NEFT id, cheque #, …"
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
