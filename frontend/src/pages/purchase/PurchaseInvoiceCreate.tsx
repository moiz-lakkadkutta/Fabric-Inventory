import { ArrowLeft } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import type { BackendPiCreateBody, BackendPiLineCreateBody } from '@/lib/api/purchase-invoices';
import { useGrn, useGrns } from '@/lib/queries/grn';
import { useCreatePurchaseInvoice } from '@/lib/queries/purchase-invoices';

interface DraftLine {
  item_id: string;
  qty: string;
  rate: string;
  gst_rate: string;
  line_sequence: number;
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function PurchaseInvoiceCreate() {
  const navigate = useNavigate();
  const idem = useIdempotencyKey();
  const grns = useGrns();
  const [grnId, setGrnId] = useState<string>('');
  const grn = useGrn(grnId || undefined);
  const create = useCreatePurchaseInvoice();

  const [invoiceDate, setInvoiceDate] = useState<string>(todayISO());
  const [series, setSeries] = useState<string>('PI/25-26');
  const [notes, setNotes] = useState<string>('');
  const [rcm, setRcm] = useState<boolean>(false);
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [error, setError] = useState<string | null>(null);

  // When GRN loads, pre-fill the lines from its received qty.
  useEffect(() => {
    if (!grn.data) return;
    setLines(
      grn.data.lines.map((l, idx) => ({
        item_id: l.item_id,
        qty: stripTrailingZeros(String(l.qty_received)),
        rate: l.rate ? String(l.rate) : '0',
        gst_rate: '5',
        line_sequence: l.line_sequence ?? idx + 1,
      })),
    );
  }, [grn.data]);

  const partyId = grn.data?.party_id;
  const firmId = grn.data?.firm_id;

  const canSubmit = useMemo(() => {
    return Boolean(
      grnId &&
      partyId &&
      firmId &&
      invoiceDate &&
      series.trim() &&
      lines.length > 0 &&
      lines.every((l) => Number(l.qty) > 0 && Number(l.rate) >= 0),
    );
  }, [grnId, partyId, firmId, invoiceDate, series, lines]);

  const updateLine = (idx: number, patch: Partial<DraftLine>) => {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  };

  const submit = async () => {
    setError(null);
    if (!canSubmit || !partyId || !firmId) {
      setError('Pick a GRN with at least one line.');
      return;
    }
    const body: BackendPiCreateBody = {
      firm_id: firmId,
      party_id: partyId,
      grn_id: grnId,
      invoice_date: invoiceDate,
      series: series.trim(),
      rcm_applicable: rcm,
      notes: notes.trim() || null,
      lines: lines.map<BackendPiLineCreateBody>((l) => ({
        item_id: l.item_id,
        qty: l.qty,
        rate: l.rate,
        gst_rate: l.gst_rate || null,
        line_sequence: l.line_sequence,
      })),
    };
    try {
      const created = await create.mutateAsync({ body, idempotencyKey: idem.key });
      idem.reset();
      navigate(`/purchase/invoices/${created.purchase_invoice_id}`);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create purchase invoice.');
      }
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/purchase/invoices"
          aria-label="Back to purchase invoices"
          className="inline-flex h-8 items-center gap-1 rounded-md px-2"
          style={{ color: 'var(--text-secondary)', fontSize: 13 }}
        >
          <ArrowLeft size={14} />
          Purchase invoices
        </Link>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>
          New purchase invoice
        </h1>
      </header>

      <div
        className="space-y-4 p-4"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Source GRN" htmlFor="pi-grn" required>
            <select
              id="pi-grn"
              aria-label="Source GRN"
              value={grnId}
              onChange={(e) => setGrnId(e.target.value)}
              style={{
                width: '100%',
                height: 40,
                borderRadius: 6,
                border: '1px solid var(--border-default)',
                background: 'var(--bg-surface)',
                color: 'var(--text-primary)',
                padding: '0 12px',
                fontSize: 14,
              }}
            >
              <option value="">Pick a GRN…</option>
              {(grns.data ?? []).map((g) => (
                <option key={g.grn_id} value={g.grn_id}>
                  {g.number} ({g.status})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Series" htmlFor="pi-series" required>
            <Input
              id="pi-series"
              aria-label="PI series"
              value={series}
              onChange={(e) => setSeries(e.target.value)}
              placeholder="PI/25-26"
            />
          </Field>
          <Field label="Invoice date" htmlFor="pi-date" required>
            <Input
              id="pi-date"
              aria-label="Invoice date"
              type="date"
              value={invoiceDate}
              onChange={(e) => setInvoiceDate(e.target.value)}
            />
          </Field>
        </div>

        {lines.length > 0 && (
          <div
            className="overflow-x-auto"
            style={{
              borderRadius: 8,
              border: '1px solid var(--border-default)',
            }}
          >
            <table className="w-full text-left" style={{ minWidth: 640 }}>
              <thead style={{ background: 'var(--bg-sunken)' }}>
                <tr style={{ color: 'var(--text-tertiary)' }}>
                  <Th>Item</Th>
                  <Th align="right">Qty</Th>
                  <Th align="right">Rate (₹)</Th>
                  <Th align="right">GST %</Th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line, idx) => (
                  <tr key={idx} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td className="px-3 py-2.5">
                      <span
                        className="mono"
                        style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
                      >
                        {line.item_id.slice(0, 8)}…
                      </span>
                    </td>
                    <td className="px-3 py-2.5" style={{ textAlign: 'right' }}>
                      <input
                        aria-label={`PI line ${idx + 1} qty`}
                        value={line.qty}
                        onChange={(e) => updateLine(idx, { qty: e.target.value })}
                        inputMode="decimal"
                        style={inputCellStyle}
                      />
                    </td>
                    <td className="px-3 py-2.5" style={{ textAlign: 'right' }}>
                      <input
                        aria-label={`PI line ${idx + 1} rate`}
                        value={line.rate}
                        onChange={(e) => updateLine(idx, { rate: e.target.value })}
                        inputMode="decimal"
                        style={inputCellStyle}
                      />
                    </td>
                    <td className="px-3 py-2.5" style={{ textAlign: 'right' }}>
                      <input
                        aria-label={`PI line ${idx + 1} GST percent`}
                        value={line.gst_rate}
                        onChange={(e) => updateLine(idx, { gst_rate: e.target.value })}
                        inputMode="decimal"
                        style={{ ...inputCellStyle, width: 72 }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center gap-3">
          <label
            className="inline-flex items-center gap-2"
            style={{ fontSize: 13, color: 'var(--text-secondary)' }}
          >
            <input
              type="checkbox"
              aria-label="RCM applicable"
              checked={rcm}
              onChange={(e) => setRcm(e.target.checked)}
            />
            RCM applicable
          </label>
        </div>

        <Field label="Notes" htmlFor="pi-notes">
          <Input
            id="pi-notes"
            aria-label="PI notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional"
          />
        </Field>

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

        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" asChild>
            <Link to="/purchase/invoices">Cancel</Link>
          </Button>
          <Button onClick={submit} disabled={!canSubmit || create.isPending}>
            {create.isPending ? 'Creating…' : 'Create PI'}
          </Button>
        </div>
      </div>
    </div>
  );
}

const inputCellStyle: React.CSSProperties = {
  width: 96,
  height: 32,
  borderRadius: 6,
  border: '1px solid var(--border-default)',
  background: 'var(--bg-surface)',
  color: 'var(--text-primary)',
  padding: '0 8px',
  fontSize: 13,
  textAlign: 'right',
};

function stripTrailingZeros(s: string): string {
  if (!s.includes('.')) return s;
  return s.replace(/\.?0+$/, '');
}

function Th({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      className="px-3 py-2.5"
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
