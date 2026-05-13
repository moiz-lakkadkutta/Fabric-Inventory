/*
 * Sales Order create page (TASK-CUT-203).
 *
 * Mirrors InvoiceCreate layout: customer dropdown, line items, totals
 * sidebar. POSTs to /sales-orders with an Idempotency-Key, then routes
 * to the detail page so the user can confirm.
 */

import { ArrowLeft, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useItems } from '@/lib/queries/items';
import { useCustomers } from '@/lib/queries/parties';
import { useCreateSo, type CreateSoLineInput } from '@/lib/queries/sales-orders';
import { formatINRCompact } from '@/lib/format';
import { authStore } from '@/store/auth';

interface DraftLine {
  line_id: string;
  item_id: string | null;
  qty: number;
  rate: number; // paise
  /**
   * Raw editing text for the rate input.
   *
   * The rate field is keystroke-edited in rupees (e.g. "500", "500.5",
   * "500.50") but stored as integer paise. If we re-derive the input
   * value from `rate` every render (formatting via `(rate/100).toFixed(2)`),
   * partial typing like "5" gets parsed as 0.05 rupees, snaps the
   * display to "0.05", and the next keystroke sees "0.055" — every
   * subsequent digit just appends more decimals. That's the B13 10,000×
   * drift: 500 typed → 1 paisa stored.
   *
   * Solution: track the user's literal text here while the field is
   * being edited, and only re-format on blur. `rate` (paise) is the
   * canonical source for totals and the wire payload.
   */
  rate_text: string;
  gst_pct: number;
}

let lineSeq = 0;
function nextLineId() {
  lineSeq += 1;
  return `dl_${lineSeq}`;
}

/** Parse a rupees-as-text input into integer paise. NaN-safe. */
function parseRupeesToPaise(text: string): number {
  const n = Number(text);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.round(n * 100);
}

/** Format integer paise as a rupees string for the input (e.g. 50000 → "500.00"). */
function formatPaiseForInput(paise: number): string {
  return (paise / 100).toFixed(2);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function SalesOrderCreate() {
  const navigate = useNavigate();
  const customersQuery = useCustomers();
  const itemsQuery = useItems();
  const createSo = useCreateSo();
  const idem = useIdempotencyKey();

  const [partyId, setPartyId] = useState<string>('');
  const [soDate, setSoDate] = useState<string>(todayIso);
  const [deliveryDate, setDeliveryDate] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<DraftLine[]>(() => [
    { line_id: nextLineId(), item_id: null, qty: 1, rate: 0, rate_text: '', gst_pct: 5 },
  ]);

  const customers = useMemo(() => customersQuery.data ?? [], [customersQuery.data]);
  const items = useMemo(() => itemsQuery.data ?? [], [itemsQuery.data]);

  useEffect(() => {
    if (!partyId && customers.length > 0) setPartyId(customers[0].party_id);
  }, [partyId, customers]);

  useEffect(() => {
    if (items.length === 0) return;
    setLines((ls) => {
      if (ls.some((l) => l.item_id !== null)) return ls;
      const first = items[0];
      return ls.map((l, i) =>
        i === 0 && l.item_id === null
          ? { ...l, item_id: first.item_id, gst_pct: first.gst_rate || 5 }
          : l,
      );
    });
  }, [items]);

  const updateLine = (id: string, patch: Partial<DraftLine>) => {
    setLines((ls) => ls.map((l) => (l.line_id === id ? { ...l, ...patch } : l)));
  };

  const onItemPick = (id: string, itemId: string) => {
    const item = items.find((i) => i.item_id === itemId);
    if (!item) return;
    updateLine(id, { item_id: itemId, gst_pct: item.gst_rate || 5 });
  };

  const addLine = () =>
    setLines((ls) => [
      ...ls,
      { line_id: nextLineId(), item_id: null, qty: 1, rate: 0, rate_text: '', gst_pct: 5 },
    ]);

  const removeLine = (id: string) =>
    setLines((ls) => (ls.length === 1 ? ls : ls.filter((l) => l.line_id !== id)));

  const totals = useMemo(() => {
    const subtotal = lines.reduce((s, l) => s + l.qty * l.rate, 0);
    const gst = lines.reduce((s, l) => s + Math.round((l.qty * l.rate * l.gst_pct) / 100), 0);
    return { subtotal, gst, total: subtotal + gst };
  }, [lines]);

  const onSave = async () => {
    setError(null);
    const me = authStore.get().me;
    if (!me?.firm_id) {
      setError('No active firm in this session — switch to a firm first.');
      return;
    }
    const validLines: CreateSoLineInput[] = lines
      .filter((l) => l.item_id && l.qty > 0)
      .map((l, idx) => ({
        item_id: l.item_id as string,
        qty_ordered: l.qty,
        price: l.rate,
        gst_pct: l.gst_pct,
        sequence: idx + 1,
      }));
    if (validLines.length === 0) {
      setError('Add at least one line with an item and a positive quantity.');
      return;
    }
    try {
      const so = await createSo.mutateAsync({
        firm_id: me.firm_id,
        party_id: partyId,
        so_date: soDate,
        delivery_date: deliveryDate || undefined,
        notes: notes || undefined,
        lines: validLines,
        idempotencyKey: idem.key,
      });
      idem.reset();
      navigate(`/sales/orders/${so.sales_order_id}`);
    } catch (e) {
      idem.reset();
      if (e instanceof ApiError) {
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create sales order.');
      }
    }
  };

  const loading = customersQuery.isPending || itemsQuery.isPending;
  const submitting = createSo.isPending;
  const canSubmit = !loading && !submitting && partyId !== '';

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/sales/orders"
          aria-label="Back to sales orders"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.012em' }}>
          New sales order
        </h1>
        <Pill kind="draft">Draft</Pill>
        <div className="ml-auto flex items-center gap-2">
          <Button disabled={!canSubmit} onClick={onSave}>
            {submitting ? 'Saving…' : 'Save SO'}
          </Button>
        </div>
      </header>

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

      {loading ? (
        <Skeleton width="100%" height={400} radius={8} />
      ) : customers.length === 0 || items.length === 0 ? (
        <EmptyMastersCard hasCustomers={customers.length > 0} hasItems={items.length > 0} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
          <div
            className="space-y-4 p-4"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-default)',
              borderRadius: 8,
            }}
          >
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <Field label="Customer" htmlFor="so-party">
                <select
                  id="so-party"
                  aria-label="Customer"
                  value={partyId}
                  onChange={(e) => setPartyId(e.target.value)}
                  className="h-10 w-full rounded-md px-3"
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-default)',
                    fontSize: 13.5,
                  }}
                >
                  {customers.map((c) => (
                    <option key={c.party_id} value={c.party_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="SO date" htmlFor="so-date">
                <Input
                  id="so-date"
                  type="date"
                  value={soDate}
                  onChange={(e) => setSoDate(e.target.value)}
                />
              </Field>
              <Field label="Expected delivery" htmlFor="so-delivery">
                <Input
                  id="so-delivery"
                  type="date"
                  value={deliveryDate}
                  onChange={(e) => setDeliveryDate(e.target.value)}
                />
              </Field>
              <Field label="Notes" htmlFor="so-notes">
                <Input
                  id="so-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Internal note (optional)"
                />
              </Field>
            </div>

            <div>
              <div
                className="mb-2 flex items-center justify-between"
                style={{ fontSize: 13, color: 'var(--text-secondary)', fontWeight: 500 }}
              >
                <span>Line items</span>
                <Button variant="ghost" size="sm" onClick={addLine}>
                  <Plus size={12} /> Add line
                </Button>
              </div>
              <table className="w-full text-left">
                <thead>
                  <tr style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>
                    <Th>Item</Th>
                    <Th align="right">Qty</Th>
                    <Th align="right">Rate</Th>
                    <Th align="right">GST %</Th>
                    <Th align="right">Amount</Th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l) => {
                    const amount = l.qty * l.rate;
                    return (
                      <tr key={l.line_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                        <td className="px-2 py-2">
                          <select
                            aria-label="Item"
                            name={`line-${l.line_id}-item`}
                            value={l.item_id ?? ''}
                            onChange={(e) => onItemPick(l.line_id, e.target.value)}
                            className="h-9 w-full rounded-md px-2"
                            style={{
                              background: 'var(--bg-surface)',
                              border: '1px solid var(--border-default)',
                              fontSize: 13,
                            }}
                          >
                            <option value="">Select item…</option>
                            {items.map((i) => (
                              <option key={i.item_id} value={i.item_id}>
                                {i.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-2 py-2" style={{ textAlign: 'right' }}>
                          <input
                            type="number"
                            aria-label="Qty"
                            name={`line-${l.line_id}-qty`}
                            min={0}
                            value={l.qty}
                            onChange={(e) =>
                              updateLine(l.line_id, { qty: Number(e.target.value) || 0 })
                            }
                            className="num h-9 w-20 rounded-md px-2 text-right"
                            style={{
                              background: 'var(--bg-surface)',
                              border: '1px solid var(--border-default)',
                              fontSize: 13,
                            }}
                          />
                        </td>
                        <td className="px-2 py-2" style={{ textAlign: 'right' }}>
                          <Input
                            aria-label="Rate"
                            name={`line-${l.line_id}-rate`}
                            inputMode="decimal"
                            placeholder="0.00"
                            value={l.rate_text}
                            onChange={(e) => {
                              const text = e.target.value;
                              // Don't reformat mid-edit — keep the raw text so the
                              // user can finish typing (e.g. "500" → "500.50").
                              updateLine(l.line_id, {
                                rate_text: text,
                                rate: parseRupeesToPaise(text),
                              });
                            }}
                            onBlur={() => {
                              // On blur, snap the visible text to the canonical
                              // 2-decimal form derived from the stored paise.
                              updateLine(l.line_id, { rate_text: formatPaiseForInput(l.rate) });
                            }}
                            style={{ width: 96, textAlign: 'right' }}
                          />
                        </td>
                        <td className="px-2 py-2" style={{ textAlign: 'right' }}>
                          <Input
                            aria-label="GST %"
                            name={`line-${l.line_id}-gst`}
                            value={String(l.gst_pct)}
                            onChange={(e) =>
                              updateLine(l.line_id, { gst_pct: Number(e.target.value) || 0 })
                            }
                            style={{ width: 64, textAlign: 'right' }}
                          />
                        </td>
                        <td
                          className="num px-2 py-2"
                          style={{ textAlign: 'right', fontSize: 13.5, fontWeight: 500 }}
                        >
                          {formatINRCompact(amount)}
                        </td>
                        <td className="px-2 py-2" style={{ textAlign: 'right' }}>
                          <button
                            type="button"
                            aria-label={`Remove line ${l.line_id}`}
                            onClick={() => removeLine(l.line_id)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md"
                            style={{ color: 'var(--text-tertiary)' }}
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <aside
            className="space-y-3 p-4"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-default)',
              borderRadius: 8,
              alignSelf: 'start',
            }}
          >
            <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Totals</h2>
            <Row label="Subtotal" value={formatINRCompact(totals.subtotal)} />
            <Row label="GST" value={formatINRCompact(totals.gst)} />
            <hr style={{ border: 0, borderTop: '1px solid var(--border-subtle)' }} />
            <Row label="Grand total" value={formatINRCompact(totals.total)} big />
          </aside>
        </div>
      )}
    </div>
  );
}

function Th({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      className="px-2 py-2"
      style={{
        textAlign: align,
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {children}
    </th>
  );
}

function Row({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div className="flex items-baseline justify-between">
      <span
        style={{
          fontSize: big ? 13 : 12.5,
          color: big ? 'var(--text-primary)' : 'var(--text-secondary)',
          fontWeight: big ? 600 : 500,
        }}
      >
        {label}
      </span>
      <span className="num" style={{ fontSize: big ? 18 : 13, fontWeight: big ? 600 : 500 }}>
        {value}
      </span>
    </div>
  );
}

interface EmptyMastersCardProps {
  hasCustomers: boolean;
  hasItems: boolean;
}

function EmptyMastersCard({ hasCustomers, hasItems }: EmptyMastersCardProps) {
  return (
    <div
      className="space-y-4 p-6"
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
      }}
    >
      <h2 style={{ fontSize: 16, fontWeight: 600 }}>
        {!hasCustomers && !hasItems ? 'Set up your masters' : 'One more master to add'}
      </h2>
      {!hasCustomers && (
        <div className="space-y-1">
          <p style={{ fontSize: 13.5, color: 'var(--text-secondary)' }}>
            No customers yet. Add at least one customer to take this order.
          </p>
          <Link
            to="/masters/parties"
            style={{ fontSize: 13.5, color: 'var(--accent)', textDecoration: 'underline' }}
          >
            Add a customer →
          </Link>
        </div>
      )}
      {!hasItems && (
        <div className="space-y-1">
          <p style={{ fontSize: 13.5, color: 'var(--text-secondary)' }}>
            No items yet. Add at least one item to put on a line.
          </p>
          <Link
            to="/masters/items"
            style={{ fontSize: 13.5, color: 'var(--accent)', textDecoration: 'underline' }}
          >
            Add an item →
          </Link>
        </div>
      )}
    </div>
  );
}
