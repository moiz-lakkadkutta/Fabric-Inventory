/*
 * Delivery Challan create page (TASK-CUT-203).
 *
 * Two flows:
 *   1. Free-form DC: pick a customer + items + qty.
 *   2. SO-linked DC: pick a confirmed SO; lines pre-fill from the SO's
 *      remaining (qty_ordered - qty_dispatched) per line. The user can
 *      reduce qty per line before issuing (partial DC).
 *
 * Selecting an SO disables the customer dropdown (the BE enforces same
 * party). `?so_id=...` query-string preselects an SO so the SalesOrder-
 * Detail "Build DC" button can deep-link straight here.
 */

import { ArrowLeft, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useItems } from '@/lib/queries/items';
import { useCustomers } from '@/lib/queries/parties';
import { useCreateDc, type CreateDcLineInput } from '@/lib/queries/delivery-challans';
import { useSalesOrders, useSalesOrder } from '@/lib/queries/sales-orders';
import { formatINRCompact } from '@/lib/format';
import { authStore } from '@/store/auth';

interface DraftLine {
  line_id: string;
  item_id: string | null;
  qty: number;
  rate: number; // paise (optional on wire; sent only if > 0)
}

let lineSeq = 0;
function nextLineId() {
  lineSeq += 1;
  return `dl_${lineSeq}`;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function DeliveryChallanCreate() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialSoId = searchParams.get('so_id') ?? '';

  const customersQuery = useCustomers();
  const itemsQuery = useItems();
  // Only confirmed-or-partial SOs are eligible for a DC build-from path.
  // We list everything and filter client-side; the picker stays simple
  // (no extra refetch when the user cycles between filters).
  const sosQuery = useSalesOrders();
  const createDc = useCreateDc();
  const idem = useIdempotencyKey();

  const [soId, setSoId] = useState<string>(initialSoId);
  const [partyId, setPartyId] = useState<string>('');
  const [dispatchDate, setDispatchDate] = useState<string>(todayIso);
  const [shipState, setShipState] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<DraftLine[]>(() => [
    { line_id: nextLineId(), item_id: null, qty: 1, rate: 0 },
  ]);

  // Pull the chosen SO so we can pre-fill lines + lock the customer.
  const selectedSoQuery = useSalesOrder(soId || undefined);

  const customers = useMemo(() => customersQuery.data ?? [], [customersQuery.data]);
  const items = useMemo(() => itemsQuery.data ?? [], [itemsQuery.data]);
  const eligibleSos = useMemo(() => {
    return (sosQuery.data ?? []).filter(
      (so) => so.status === 'CONFIRMED' || so.status === 'PARTIAL_DC',
    );
  }, [sosQuery.data]);

  // When the SO selection changes, replace local state with the SO's
  // party + remaining lines. User can edit qty before issuing.
  useEffect(() => {
    const so = selectedSoQuery.data;
    if (!so) return;
    setPartyId(so.party_id);
    const remaining: DraftLine[] = so.lines
      .map((l) => {
        const open = Math.max(l.qty_ordered - l.qty_dispatched, 0);
        return {
          line_id: nextLineId(),
          item_id: l.item_id,
          qty: open,
          rate: l.price,
        };
      })
      .filter((l) => l.qty > 0);
    if (remaining.length > 0) setLines(remaining);
  }, [selectedSoQuery.data]);

  // Default the customer to the first one in the list when no SO is set.
  useEffect(() => {
    if (soId) return;
    if (!partyId && customers.length > 0) setPartyId(customers[0].party_id);
  }, [soId, partyId, customers]);

  // Default the first line item once items load (free-form mode only).
  useEffect(() => {
    if (soId) return;
    if (items.length === 0) return;
    setLines((ls) => {
      if (ls.some((l) => l.item_id !== null)) return ls;
      return ls.map((l, i) =>
        i === 0 && l.item_id === null ? { ...l, item_id: items[0].item_id } : l,
      );
    });
  }, [soId, items]);

  const updateLine = (id: string, patch: Partial<DraftLine>) => {
    setLines((ls) => ls.map((l) => (l.line_id === id ? { ...l, ...patch } : l)));
  };

  const onItemPick = (id: string, itemId: string) => {
    updateLine(id, { item_id: itemId });
  };

  const addLine = () =>
    setLines((ls) => [...ls, { line_id: nextLineId(), item_id: null, qty: 1, rate: 0 }]);

  const removeLine = (id: string) =>
    setLines((ls) => (ls.length === 1 ? ls : ls.filter((l) => l.line_id !== id)));

  const totalQty = useMemo(() => lines.reduce((s, l) => s + l.qty, 0), [lines]);
  const totalAmt = useMemo(() => lines.reduce((s, l) => s + l.qty * l.rate, 0), [lines]);

  const onSave = async () => {
    setError(null);
    const me = authStore.get().me;
    if (!me?.firm_id) {
      setError('No active firm in this session — switch to a firm first.');
      return;
    }
    if (!partyId) {
      setError('Select a customer.');
      return;
    }
    const valid: CreateDcLineInput[] = lines
      .filter((l) => l.item_id && l.qty > 0)
      .map((l, idx) => ({
        item_id: l.item_id as string,
        qty_dispatched: l.qty,
        price: l.rate > 0 ? l.rate : undefined,
        sequence: idx + 1,
      }));
    if (valid.length === 0) {
      setError('Add at least one line with an item and a positive quantity.');
      return;
    }
    try {
      const dc = await createDc.mutateAsync({
        firm_id: me.firm_id,
        party_id: partyId,
        dispatch_date: dispatchDate,
        sales_order_id: soId || undefined,
        place_of_supply_state: shipState || undefined,
        lines: valid,
        idempotencyKey: idem.key,
      });
      idem.reset();
      navigate(`/sales/delivery-challans/${dc.delivery_challan_id}`);
    } catch (e) {
      idem.reset();
      if (e instanceof ApiError) {
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create delivery challan.');
      }
    }
  };

  const loading = customersQuery.isPending || itemsQuery.isPending;
  const submitting = createDc.isPending;
  const partyLocked = soId !== '';
  const canSubmit = !loading && !submitting && partyId !== '';

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/sales/delivery-challans"
          aria-label="Back to delivery challans"
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
          New delivery challan
        </h1>
        <Pill kind="draft">Draft</Pill>
        <div className="ml-auto flex items-center gap-2">
          <Button disabled={!canSubmit} onClick={onSave}>
            {submitting ? 'Saving…' : 'Save DC'}
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
              <Field label="Source SO (optional)" htmlFor="dc-so">
                <select
                  id="dc-so"
                  aria-label="Source SO"
                  value={soId}
                  onChange={(e) => setSoId(e.target.value)}
                  className="h-10 w-full rounded-md px-3"
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-default)',
                    fontSize: 13.5,
                  }}
                >
                  <option value="">Free-form (no linked SO)</option>
                  {eligibleSos.map((so) => (
                    <option key={so.sales_order_id} value={so.sales_order_id}>
                      {so.display_number}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Customer" htmlFor="dc-party">
                <select
                  id="dc-party"
                  aria-label="Customer"
                  value={partyId}
                  onChange={(e) => setPartyId(e.target.value)}
                  disabled={partyLocked}
                  className="h-10 w-full rounded-md px-3"
                  style={{
                    background: partyLocked ? 'var(--bg-sunken)' : 'var(--bg-surface)',
                    border: '1px solid var(--border-default)',
                    fontSize: 13.5,
                  }}
                >
                  <option value="">Select customer…</option>
                  {customers.map((c) => (
                    <option key={c.party_id} value={c.party_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Dispatch date" htmlFor="dc-date">
                <Input
                  id="dc-date"
                  type="date"
                  value={dispatchDate}
                  onChange={(e) => setDispatchDate(e.target.value)}
                />
              </Field>
              <Field label="Place of supply state" htmlFor="dc-state">
                <Input
                  id="dc-state"
                  value={shipState}
                  onChange={(e) => setShipState(e.target.value.toUpperCase())}
                  maxLength={2}
                  placeholder="MH"
                />
              </Field>
            </div>

            {customers.length === 0 && (
              <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                No customers in your firm yet.{' '}
                <Link
                  to="/masters/parties"
                  style={{ color: 'var(--accent)', textDecoration: 'underline' }}
                >
                  Add a customer
                </Link>{' '}
                before you build a DC.
              </p>
            )}

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
                    <Th align="right">Rate (optional)</Th>
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
                            value={String((l.rate / 100).toFixed(2))}
                            onChange={(e) =>
                              updateLine(l.line_id, {
                                rate: Math.round(Number(e.target.value) * 100) || 0,
                              })
                            }
                            style={{ width: 96, textAlign: 'right' }}
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
            <Row label="Total qty" value={String(totalQty)} />
            <Row label="Indicative amount" value={formatINRCompact(totalAmt)} />
            <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>
              DCs do not post tax — pricing carries through to the invoice issued against this DC.
            </p>
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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span style={{ fontSize: 12.5, color: 'var(--text-secondary)', fontWeight: 500 }}>
        {label}
      </span>
      <span className="num" style={{ fontSize: 13, fontWeight: 500 }}>
        {value}
      </span>
    </div>
  );
}
