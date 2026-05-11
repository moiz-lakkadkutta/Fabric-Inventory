/*
 * SendOutDialog (TASK-CUT-401)
 *
 * Lets the owner send fabric out to a karigar for an operation. Posts a
 * single-line JWO to /job-work-orders. Multi-line is supported by the
 * BE but unnecessary for the v1 dogfood; one fabric item + one
 * operation per challan is the textile-trade reality. Add-line affordance
 * can land in a follow-up if Moiz wants it.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useItems } from '@/lib/queries/items';
import { useCreateJobWorkOrder, useKarigars } from '@/lib/queries/jobwork';
import { useMe } from '@/store/auth';

interface SendOutDialogProps {
  open: boolean;
  onClose: () => void;
}

const TODAY = (): string => new Date().toISOString().slice(0, 10);

export function SendOutDialog({ open, onClose }: SendOutDialogProps) {
  const me = useMe();
  const karigars = useKarigars();
  const items = useItems();
  const create = useCreateJobWorkOrder();
  const idem = useIdempotencyKey();

  const [karigarId, setKarigarId] = React.useState('');
  const [itemId, setItemId] = React.useState('');
  const [qty, setQty] = React.useState('');
  const [uom, setUom] = React.useState('METER');
  const [operation, setOperation] = React.useState('');
  const [challanDate, setChallanDate] = React.useState(TODAY());
  const [expectedReturn, setExpectedReturn] = React.useState('');
  const [notes, setNotes] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  // Reset every open so the dialog never reuses stale state across send-outs.
  React.useEffect(() => {
    if (open) {
      setKarigarId('');
      setItemId('');
      setQty('');
      setUom('METER');
      setOperation('');
      setChallanDate(TODAY());
      setExpectedReturn('');
      setNotes('');
      setError(null);
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // When the user picks an item, pre-fill the UOM from the item's primary_uom
  // so the common case (fabric → METER) is one click less.
  React.useEffect(() => {
    if (!itemId) return;
    const it = (items.data ?? []).find((i) => i.item_id === itemId);
    if (it?.primary_uom) setUom(it.primary_uom);
  }, [itemId, items.data]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!me?.firm_id) {
      setError('No active firm in this session.');
      return;
    }
    if (!karigarId) {
      setError('Pick a karigar.');
      return;
    }
    if (!itemId) {
      setError('Pick an item.');
      return;
    }
    const qtyNum = parseFloat(qty);
    if (!Number.isFinite(qtyNum) || qtyNum <= 0) {
      setError('Quantity must be a positive number.');
      return;
    }
    if (!uom.trim()) {
      setError('UOM is required.');
      return;
    }

    create.mutate(
      {
        body: {
          firm_id: me.firm_id,
          karigar_party_id: karigarId,
          challan_date: challanDate,
          operation: operation.trim() || null,
          expected_return_date: expectedReturn || null,
          notes: notes.trim() || null,
          lines: [
            {
              item_id: itemId,
              qty_sent: qty,
              uom: uom.trim(),
              notes: null,
            },
          ],
        },
        idempotencyKey: idem.key,
      },
      {
        onSuccess: () => {
          idem.reset();
          onClose();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Could not send out.');
        },
      },
    );
  };

  const karigarOptions = karigars.data ?? [];
  const itemOptions = items.data ?? [];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Send out to karigar"
      description="Move fabric / pieces from your warehouse to the karigar. Posts a job-work challan and moves stock MAIN → JOBWORK."
      width={560}
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="send-out-form" disabled={create.isPending}>
            {create.isPending ? 'Saving…' : 'Save send-out'}
          </Button>
        </>
      }
    >
      <form id="send-out-form" onSubmit={onSubmit} className="flex flex-col gap-3">
        <Field label="Karigar" htmlFor="so-karigar" required>
          <select
            id="so-karigar"
            value={karigarId}
            onChange={(e) => setKarigarId(e.target.value)}
            className="h-10 w-full rounded-md px-2"
            style={{
              border: '1px solid var(--border-default)',
              background: 'var(--bg-surface)',
              fontSize: 13,
            }}
          >
            <option value="">— Select karigar —</option>
            {karigarOptions.map((k) => (
              <option key={k.party_id} value={k.party_id}>
                {k.name} ({k.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Item" htmlFor="so-item" required>
          <select
            id="so-item"
            value={itemId}
            onChange={(e) => setItemId(e.target.value)}
            className="h-10 w-full rounded-md px-2"
            style={{
              border: '1px solid var(--border-default)',
              background: 'var(--bg-surface)',
              fontSize: 13,
            }}
          >
            <option value="">— Select item —</option>
            {itemOptions.map((it) => (
              <option key={it.item_id} value={it.item_id}>
                {it.name} ({it.code})
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity" htmlFor="so-qty" required>
            <Input
              id="so-qty"
              type="number"
              inputMode="decimal"
              step="0.001"
              min="0"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              placeholder="0"
            />
          </Field>
          <Field label="UOM" htmlFor="so-uom" required>
            <Input
              id="so-uom"
              value={uom}
              onChange={(e) => setUom(e.target.value)}
              placeholder="METER"
            />
          </Field>
        </div>
        <Field label="Operation" htmlFor="so-operation">
          <Input
            id="so-operation"
            value={operation}
            onChange={(e) => setOperation(e.target.value)}
            placeholder="e.g. Aari embroidery, Stitching, Dyeing"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Challan date" htmlFor="so-date" required>
            <Input
              id="so-date"
              type="date"
              value={challanDate}
              onChange={(e) => setChallanDate(e.target.value)}
            />
          </Field>
          <Field label="Expected return" htmlFor="so-return">
            <Input
              id="so-return"
              type="date"
              value={expectedReturn}
              onChange={(e) => setExpectedReturn(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Notes" htmlFor="so-notes">
          <Input
            id="so-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional"
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
