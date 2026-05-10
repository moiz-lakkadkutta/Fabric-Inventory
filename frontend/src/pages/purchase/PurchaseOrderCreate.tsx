import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { ApiError } from '@/lib/api/client';
import { formatINR } from '@/lib/format';
import { useItems } from '@/lib/queries/items';
import { useSuppliers } from '@/lib/queries/parties';
import { useCreatePo, type CreatePoLineInput } from '@/lib/queries/purchase-orders';

interface DraftLine extends CreatePoLineInput {
  // Used purely as a stable React key while the row is unsaved.
  uid: string;
}

const today = (): string => new Date().toISOString().slice(0, 10);

function blankLine(): DraftLine {
  return {
    uid: crypto.randomUUID(),
    item_id: '',
    qty: 1,
    rate: 0,
    gst_pct: 0,
  };
}

export default function PurchaseOrderCreate() {
  const navigate = useNavigate();
  const suppliersQuery = useSuppliers();
  const itemsQuery = useItems();
  const createPo = useCreatePo();
  const idem = useIdempotencyKey();

  const [supplierId, setSupplierId] = useState('');
  const [poDate, setPoDate] = useState(today());
  const [expectedDate, setExpectedDate] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<DraftLine[]>([blankLine()]);
  const [error, setError] = useState<string | null>(null);

  const totalPaise = lines.reduce((acc, l) => acc + (l.qty || 0) * (l.rate || 0), 0);

  const setLine = (uid: string, patch: Partial<DraftLine>) => {
    setLines((prev) => prev.map((l) => (l.uid === uid ? { ...l, ...patch } : l)));
  };

  const addLine = () => setLines((prev) => [...prev, blankLine()]);
  const removeLine = (uid: string) => setLines((prev) => prev.filter((l) => l.uid !== uid));

  const submit = async () => {
    setError(null);
    if (!supplierId) {
      setError('Pick a supplier.');
      return;
    }
    const usableLines = lines.filter((l) => l.item_id && l.qty > 0);
    if (usableLines.length === 0) {
      setError('Add at least one line with item + quantity.');
      return;
    }
    try {
      const created = await createPo.mutateAsync({
        draft: {
          supplier_id: supplierId,
          po_date: poDate,
          expected_date: expectedDate,
          notes: notes.trim() || undefined,
          lines: usableLines.map((l) => ({
            item_id: l.item_id,
            qty: l.qty,
            rate: l.rate,
            gst_pct: l.gst_pct,
          })),
        },
        idempotencyKey: idem.key,
      });
      idem.reset();
      navigate(`/purchase/${created.po_id}`);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create purchase order.');
      }
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>
          New purchase order
        </h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          Send to a supplier · DRAFT until approved
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" onClick={() => navigate(-1)} disabled={createPo.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={createPo.isPending}>
            {createPo.isPending ? 'Saving…' : 'Save draft'}
          </Button>
        </div>
      </header>

      <div
        className="space-y-4 p-5"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Supplier" htmlFor="po-supplier" required>
            <select
              id="po-supplier"
              aria-label="Supplier"
              value={supplierId}
              onChange={(e) => setSupplierId(e.target.value)}
              className="h-9 w-full rounded-md px-2"
              style={{
                fontSize: 13,
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-default)',
              }}
            >
              <option value="">{suppliersQuery.isPending ? 'Loading…' : 'Select supplier'}</option>
              {(suppliersQuery.data ?? []).map((s) => (
                <option key={s.party_id} value={s.party_id}>
                  {s.name}
                  {s.code ? ` (${s.code})` : ''}
                </option>
              ))}
            </select>
          </Field>
          <Field label="PO date" htmlFor="po-date" required>
            <Input
              id="po-date"
              aria-label="PO date"
              type="date"
              value={poDate}
              onChange={(e) => setPoDate(e.target.value)}
            />
          </Field>
          <Field label="Expected date" htmlFor="po-expected">
            <Input
              id="po-expected"
              aria-label="Expected date"
              type="date"
              value={expectedDate}
              onChange={(e) => setExpectedDate(e.target.value)}
            />
          </Field>
        </div>

        <Field label="Notes" htmlFor="po-notes">
          <Input
            id="po-notes"
            aria-label="Notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional"
          />
        </Field>

        <div className="space-y-2">
          <header className="flex items-center justify-between">
            <h2 style={{ fontSize: 14, fontWeight: 600 }}>Lines</h2>
            <Button variant="outline" onClick={addLine} disabled={createPo.isPending}>
              <Plus />
              Add line
            </Button>
          </header>
          <table className="w-full text-left" style={{ fontSize: 13 }}>
            <thead style={{ color: 'var(--text-tertiary)' }}>
              <tr>
                <th
                  className="px-2 py-2"
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  Item
                </th>
                <th
                  className="px-2 py-2"
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                    width: 100,
                  }}
                >
                  Qty
                </th>
                <th
                  className="px-2 py-2"
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                    width: 140,
                    textAlign: 'right',
                  }}
                >
                  Rate (₹)
                </th>
                <th
                  className="num px-2 py-2"
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                    width: 140,
                    textAlign: 'right',
                  }}
                >
                  Amount
                </th>
                <th style={{ width: 36 }} />
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => {
                const amountPaise = (line.qty || 0) * (line.rate || 0);
                return (
                  <tr key={line.uid} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td className="px-2 py-2">
                      <select
                        aria-label="Item"
                        value={line.item_id}
                        onChange={(e) => {
                          const id = e.target.value;
                          const it = (itemsQuery.data ?? []).find((i) => i.item_id === id);
                          setLine(line.uid, {
                            item_id: id,
                            gst_pct: it?.gst_rate ?? 0,
                          });
                        }}
                        className="h-9 w-full rounded-md px-2"
                        style={{
                          fontSize: 13,
                          background: 'var(--bg-elevated)',
                          border: '1px solid var(--border-default)',
                        }}
                      >
                        <option value="">
                          {itemsQuery.isPending ? 'Loading…' : 'Select item'}
                        </option>
                        {(itemsQuery.data ?? []).map((i) => (
                          <option key={i.item_id} value={i.item_id}>
                            {i.name}
                            {i.code ? ` (${i.code})` : ''}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <Input
                        aria-label="Qty"
                        type="number"
                        min={0}
                        step="0.001"
                        value={line.qty}
                        onChange={(e) =>
                          setLine(line.uid, { qty: parseFloat(e.target.value) || 0 })
                        }
                      />
                    </td>
                    <td className="px-2 py-2">
                      <Input
                        aria-label="Rate"
                        type="number"
                        min={0}
                        step="0.01"
                        value={(line.rate / 100).toString()}
                        onChange={(e) =>
                          setLine(line.uid, {
                            rate: Math.round((parseFloat(e.target.value) || 0) * 100),
                          })
                        }
                      />
                    </td>
                    <td
                      className="num px-2 py-2"
                      style={{ textAlign: 'right', color: 'var(--text-secondary)' }}
                    >
                      {formatINR(amountPaise)}
                    </td>
                    <td className="px-2 py-2" style={{ textAlign: 'right' }}>
                      <button
                        type="button"
                        aria-label="Remove line"
                        onClick={() => removeLine(line.uid)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md"
                        style={{
                          background: 'transparent',
                          border: '1px solid transparent',
                          color: 'var(--text-tertiary)',
                        }}
                        disabled={lines.length === 1}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr style={{ borderTop: '1px solid var(--border-default)' }}>
                <td colSpan={3} className="px-2 py-3" style={{ textAlign: 'right' }}>
                  <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>Total</span>
                </td>
                <td
                  className="num px-2 py-3"
                  style={{ textAlign: 'right', fontWeight: 600, fontSize: 14 }}
                >
                  {formatINR(totalPaise)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>

        {error && (
          <div
            role="alert"
            style={{
              padding: '8px 10px',
              border: '1px solid var(--danger)',
              borderRadius: 6,
              background: 'rgba(181,49,30,.06)',
              color: 'var(--danger)',
              fontSize: 12.5,
            }}
          >
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
