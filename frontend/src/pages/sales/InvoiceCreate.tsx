import { ArrowLeft, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { useItems } from '@/lib/queries/items';
import { useCustomers } from '@/lib/queries/parties';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useCreateDraftInvoice, useFinalizeInvoice } from '@/lib/queries/invoices';
import { formatINRCompact } from '@/lib/mock';
import type { Invoice, InvoiceLine } from '@/lib/mock/types';

interface DraftLine {
  line_id: string;
  item_id: string | null;
  qty: number;
  rate: number; // paise
  gst_pct: number;
}

let lineSeq = 0;
function nextLineId() {
  lineSeq += 1;
  return `dl_${lineSeq}`;
}

export default function InvoiceCreate() {
  const navigate = useNavigate();
  const customersQuery = useCustomers();
  const itemsQuery = useItems();
  const createDraft = useCreateDraftInvoice();
  const finalize = useFinalizeInvoice();
  const createKey = useIdempotencyKey();
  const finalizeKey = useIdempotencyKey();

  const [partyId, setPartyId] = useState<string>('');
  const [docType, setDocType] = useState<Invoice['doc_type']>('TAX_INVOICE');
  const [lines, setLines] = useState<DraftLine[]>(() => [
    { line_id: nextLineId(), item_id: null, qty: 1, rate: 0, gst_pct: 5 },
  ]);

  const customers = useMemo(() => customersQuery.data ?? [], [customersQuery.data]);
  const items = useMemo(() => itemsQuery.data ?? [], [itemsQuery.data]);

  // Default party + first line item to first customer/item once loaded.
  useEffect(() => {
    if (!partyId && customers.length > 0) {
      setPartyId(customers[0].party_id);
    }
  }, [partyId, customers]);

  useEffect(() => {
    if (items.length === 0) return;
    setLines((ls) => {
      if (ls.some((l) => l.item_id !== null)) return ls;
      const first = items[0];
      return ls.map((l, i) =>
        i === 0 && l.item_id === null ? { ...l, item_id: first.item_id, rate: first.rate } : l,
      );
    });
  }, [items]);

  const updateLine = (id: string, patch: Partial<DraftLine>) => {
    setLines((ls) => ls.map((l) => (l.line_id === id ? { ...l, ...patch } : l)));
  };

  const onItemPick = (id: string, itemId: string) => {
    const item = items.find((i) => i.item_id === itemId);
    if (!item) return;
    updateLine(id, { item_id: itemId, rate: item.rate });
  };

  const addLine = () =>
    setLines((ls) => [
      ...ls,
      { line_id: nextLineId(), item_id: null, qty: 1, rate: 0, gst_pct: 5 },
    ]);

  const removeLine = (id: string) =>
    setLines((ls) => (ls.length === 1 ? ls : ls.filter((l) => l.line_id !== id)));

  const totals = useMemo(() => {
    const subtotal = lines.reduce((s, l) => s + l.qty * l.rate, 0);
    const gst = lines.reduce((s, l) => s + Math.round((l.qty * l.rate * l.gst_pct) / 100), 0);
    return { subtotal, gst, total: subtotal + gst };
  }, [lines]);

  const buildDraft = () => {
    const party = customers.find((c) => c.party_id === partyId);
    if (!party) throw new Error('Select a party');
    const today = '2026-04-30';
    const due = '2026-05-30';
    const invoiceLines: InvoiceLine[] = lines
      .filter((l) => l.item_id)
      .map((l) => {
        const item = items.find((i) => i.item_id === l.item_id);
        const amount = l.qty * l.rate;
        return {
          item_id: l.item_id ?? '',
          item_name: item?.name ?? '—',
          qty: l.qty,
          uom: item?.uom ?? 'PIECE',
          rate: l.rate,
          amount,
          gst_pct: l.gst_pct,
          gst_amount: Math.round((amount * l.gst_pct) / 100),
        };
      });

    return {
      date: today,
      due_date: due,
      party_id: party.party_id,
      party_name: party.name,
      party_state: party.state_code,
      subtotal: totals.subtotal,
      gst_total: totals.gst,
      total: totals.total,
      paid: 0,
      ageing_days: -30,
      lines: invoiceLines,
      doc_type: docType,
    };
  };

  const onSaveDraft = async () => {
    const created = await createDraft.mutateAsync({
      draft: buildDraft(),
      idempotencyKey: createKey.key,
    });
    createKey.reset();
    navigate(`/sales/invoices/${created.invoice_id}`);
  };

  const onFinalize = async () => {
    const created = await createDraft.mutateAsync({
      draft: buildDraft(),
      idempotencyKey: createKey.key,
    });
    createKey.reset();
    await finalize.mutateAsync({
      invoiceId: created.invoice_id,
      idempotencyKey: finalizeKey.key,
    });
    finalizeKey.reset();
    navigate(`/sales/invoices/${created.invoice_id}`);
  };

  const loading = customersQuery.isPending || itemsQuery.isPending;
  const submitting = createDraft.isPending || finalize.isPending;
  const canSubmit = !loading && !submitting && partyId !== '';

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/sales/invoices"
          aria-label="Back to invoices"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.012em' }}>New invoice</h1>
        <Pill kind="draft">Draft</Pill>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" disabled={!canSubmit} onClick={onSaveDraft}>
            Save draft
          </Button>
          <Button disabled={!canSubmit} onClick={onFinalize}>
            Finalize
          </Button>
        </div>
      </header>

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
              <Field label="Customer" htmlFor="party">
                <select
                  id="party"
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
              <Field label="Document type" htmlFor="doc-type">
                <select
                  id="doc-type"
                  value={docType}
                  onChange={(e) => setDocType(e.target.value as Invoice['doc_type'])}
                  className="h-10 w-full rounded-md px-3"
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-default)',
                    fontSize: 13.5,
                  }}
                >
                  <option value="TAX_INVOICE">Tax invoice</option>
                  <option value="BILL_OF_SUPPLY">Bill of supply</option>
                  <option value="CASH_MEMO">Cash memo</option>
                  <option value="ESTIMATE">Estimate</option>
                </select>
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
                            value={String((l.rate / 100).toFixed(2))}
                            onChange={(e) =>
                              updateLine(l.line_id, {
                                rate: Math.round(Number(e.target.value) * 100) || 0,
                              })
                            }
                            style={{ width: 96, textAlign: 'right' }}
                          />
                        </td>
                        <td className="px-2 py-2" style={{ textAlign: 'right' }}>
                          <Input
                            aria-label="GST %"
                            name={`line-${l.line_id}-gst`}
                            value={String(l.gst_pct)}
                            onChange={(e) =>
                              updateLine(l.line_id, {
                                gst_pct: Number(e.target.value) || 0,
                              })
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
            <Row
              label="Grand total"
              labelId="grand-total"
              value={formatINRCompact(totals.total)}
              big
            />
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

interface RowProps {
  label: string;
  value: string;
  labelId?: string;
  big?: boolean;
}

function Row({ label, value, labelId, big }: RowProps) {
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
      <span
        aria-label={labelId === 'grand-total' ? 'Grand total' : undefined}
        className="num"
        style={{
          fontSize: big ? 18 : 13,
          fontWeight: big ? 600 : 500,
        }}
      >
        {value}
      </span>
    </div>
  );
}
