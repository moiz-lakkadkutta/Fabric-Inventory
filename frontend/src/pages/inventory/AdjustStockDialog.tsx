/*
 * AdjustStockDialog (TASK-CUT-204) — replaces the previous
 * `useComingSoon('TASK-024')` on `/inventory`. Posts to /stock-adjustments
 * via `useCreateStockAdjustment`, then invalidates the SOH query so the
 * row's on-hand refetches without a manual reload.
 *
 * The form mirrors the existing accounting/inventory dialog pattern:
 * locally-controlled fields, idempotency key minted on open, error
 * surface inside the form, dialog closes only on success.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useItems } from '@/lib/queries/items';
import {
  useCreateStockAdjustment,
  useLocations,
  type StockAdjustmentDirection,
} from '@/lib/queries/stock-adjustments';
import { useMe } from '@/store/auth';

interface AdjustStockDialogProps {
  open: boolean;
  onClose: () => void;
  /** Optional pre-selected item — when the dialog is opened from a row. */
  defaultItemId?: string;
}

const TODAY = (): string => new Date().toISOString().slice(0, 10);

export function AdjustStockDialog({ open, onClose, defaultItemId }: AdjustStockDialogProps) {
  const me = useMe();
  const items = useItems();
  const locations = useLocations(me?.firm_id ?? null);
  const create = useCreateStockAdjustment();
  const idem = useIdempotencyKey();

  const [itemId, setItemId] = React.useState<string>(defaultItemId ?? '');
  const [locationId, setLocationId] = React.useState<string>('');
  const [direction, setDirection] = React.useState<StockAdjustmentDirection>('INCREASE');
  const [qty, setQty] = React.useState<string>('');
  const [reason, setReason] = React.useState<string>('');
  const [date, setDate] = React.useState<string>(TODAY());
  const [error, setError] = React.useState<string | null>(null);

  // Reset on open so the dialog never shows stale state.
  React.useEffect(() => {
    if (open) {
      setItemId(defaultItemId ?? '');
      setLocationId('');
      setDirection('INCREASE');
      setQty('');
      setReason('');
      setDate(TODAY());
      setError(null);
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultItemId]);

  // Default to the only location when there's exactly one — saves a click.
  React.useEffect(() => {
    if (!open) return;
    const locs = locations.data ?? [];
    if (locs.length === 1 && !locationId) {
      setLocationId(locs[0].location_id);
    }
  }, [open, locations.data, locationId]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!me?.firm_id) {
      setError('No active firm in this session.');
      return;
    }
    if (!itemId) {
      setError('Pick an item.');
      return;
    }
    if (!locationId) {
      setError(
        (locations.data ?? []).length === 0
          ? 'No warehouse locations exist for this firm yet. Create one before adjusting stock.'
          : 'Pick a location.',
      );
      return;
    }
    const qtyNum = parseFloat(qty);
    if (!Number.isFinite(qtyNum) || qtyNum <= 0) {
      setError('Quantity must be a positive number.');
      return;
    }
    if (!reason.trim()) {
      setError('Reason is required.');
      return;
    }

    create.mutate(
      {
        body: {
          firm_id: me.firm_id,
          item_id: itemId,
          location_id: locationId,
          qty: String(qtyNum),
          direction,
          reason: reason.trim(),
          txn_date: date,
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
          setError(err instanceof Error ? err.message : 'Could not save adjustment.');
        },
      },
    );
  };

  const itemOptions = items.data ?? [];
  const locationOptions = locations.data ?? [];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Adjust stock"
      description="Increase, decrease, or reset on-hand stock at a location. Posts to the stock ledger."
      width={520}
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="adjust-stock-form" disabled={create.isPending}>
            Save adjustment
          </Button>
        </>
      }
    >
      <form id="adjust-stock-form" onSubmit={onSubmit} className="flex flex-col gap-3">
        <Field label="Item" htmlFor="adj-item" required>
          <select
            id="adj-item"
            value={itemId}
            onChange={(e) => setItemId(e.target.value)}
            className="h-10 w-full rounded-md px-2"
            style={{
              border: '1px solid var(--border-default)',
              background: 'var(--bg-surface)',
              fontSize: 13,
            }}
          >
            <option value="">— Select —</option>
            {itemOptions.map((it) => (
              <option key={it.item_id} value={it.item_id}>
                {it.name} ({it.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Location" htmlFor="adj-location" required>
          <select
            id="adj-location"
            value={locationId}
            onChange={(e) => setLocationId(e.target.value)}
            className="h-10 w-full rounded-md px-2"
            style={{
              border: '1px solid var(--border-default)',
              background: 'var(--bg-surface)',
              fontSize: 13,
            }}
          >
            <option value="">— Select —</option>
            {locationOptions.map((loc) => (
              <option key={loc.location_id} value={loc.location_id}>
                {loc.name} ({loc.code})
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Direction" htmlFor="adj-direction" required>
            <select
              id="adj-direction"
              value={direction}
              onChange={(e) => setDirection(e.target.value as StockAdjustmentDirection)}
              className="h-10 w-full rounded-md px-2"
              style={{
                border: '1px solid var(--border-default)',
                background: 'var(--bg-surface)',
                fontSize: 13,
              }}
            >
              <option value="INCREASE">Increase (+)</option>
              <option value="DECREASE">Decrease (−)</option>
              <option value="COUNT_RESET">Count reset</option>
            </select>
          </Field>
          <Field label="Quantity" htmlFor="adj-qty" required>
            <Input
              id="adj-qty"
              type="number"
              inputMode="decimal"
              step="0.001"
              min="0"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              placeholder="0"
            />
          </Field>
        </div>
        <Field label="Reason" htmlFor="adj-reason" required>
          <Input
            id="adj-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. cycle count, damaged, surplus found"
          />
        </Field>
        <Field label="Date" htmlFor="adj-date">
          <Input id="adj-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
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
