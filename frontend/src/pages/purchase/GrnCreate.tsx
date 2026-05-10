import { ArrowLeft } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import type { BackendGrnCreateBody, BackendGrnLineCreateBody } from '@/lib/api/grn';
import { useConfirmedPosForGrnForm, useCreateGrn, useLivePo } from '@/lib/queries/grn';

interface DraftLine {
  po_line_id: string;
  item_id: string;
  qty_ordered: string;
  qty_received: string;
  rate: string;
  lot_number: string;
  line_sequence: number;
}

function todayISO(): string {
  // Asia/Kolkata-aligned at the YYYY-MM-DD level: UTC +05:30 means the
  // local date matches when called close to noon UTC. For the click-dummy
  // we use the user's local Date and toISOString slice — close enough
  // for a default the user can change.
  return new Date().toISOString().slice(0, 10);
}

export default function GrnCreate() {
  const navigate = useNavigate();
  const idem = useIdempotencyKey();
  const pos = useConfirmedPosForGrnForm();
  const [poId, setPoId] = useState<string>('');
  const po = useLivePo(poId || undefined);
  const createGrn = useCreateGrn();

  const [grnDate, setGrnDate] = useState<string>(todayISO());
  const [series, setSeries] = useState<string>('GRN/25-26');
  const [notes, setNotes] = useState<string>('');
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [error, setError] = useState<string | null>(null);

  // When PO loads, default each line's received qty to ordered qty.
  useEffect(() => {
    if (!po.data) return;
    setLines(
      po.data.lines.map((l, idx) => ({
        po_line_id: l.po_line_id,
        item_id: l.item_id,
        qty_ordered: String(l.qty_ordered),
        qty_received: stripTrailingZeros(String(l.qty_ordered)),
        rate: String(l.rate),
        lot_number: '',
        line_sequence: l.line_sequence ?? idx + 1,
      })),
    );
  }, [po.data]);

  const partyId = po.data?.party_id;
  const firmId = po.data?.firm_id;

  const canSubmit = useMemo(() => {
    return Boolean(
      poId &&
      partyId &&
      firmId &&
      grnDate &&
      series.trim() &&
      lines.length > 0 &&
      lines.every((l) => Number(l.qty_received) > 0),
    );
  }, [poId, partyId, firmId, grnDate, series, lines]);

  const updateLine = (idx: number, patch: Partial<DraftLine>) => {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  };

  const submit = async () => {
    setError(null);
    if (!canSubmit || !partyId || !firmId) {
      setError('Pick a PO with at least one line and a positive received qty.');
      return;
    }
    const body: BackendGrnCreateBody = {
      firm_id: firmId,
      party_id: partyId,
      purchase_order_id: poId,
      grn_date: grnDate,
      series: series.trim(),
      notes: notes.trim() || null,
      lines: lines.map<BackendGrnLineCreateBody>((l) => ({
        item_id: l.item_id,
        po_line_id: l.po_line_id,
        qty_received: l.qty_received,
        rate: l.rate || null,
        lot_number: l.lot_number.trim() || null,
        line_sequence: l.line_sequence,
      })),
    };
    try {
      const created = await createGrn.mutateAsync({ body, idempotencyKey: idem.key });
      idem.reset();
      navigate(`/purchase/grns/${created.grn_id}`);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create GRN.');
      }
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/purchase/grns"
          aria-label="Back to GRNs"
          className="inline-flex h-8 items-center gap-1 rounded-md px-2"
          style={{ color: 'var(--text-secondary)', fontSize: 13 }}
        >
          <ArrowLeft size={14} />
          GRNs
        </Link>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>New GRN</h1>
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
          <Field label="Source purchase order" htmlFor="grn-po" required>
            <select
              id="grn-po"
              aria-label="Source purchase order"
              value={poId}
              onChange={(e) => setPoId(e.target.value)}
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
              <option value="">Pick a confirmed PO…</option>
              {(pos.data ?? []).map((p) => (
                <option key={p.purchase_order_id} value={p.purchase_order_id}>
                  {p.number} ({p.status})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Series" htmlFor="grn-series" required>
            <Input
              id="grn-series"
              aria-label="GRN series"
              value={series}
              onChange={(e) => setSeries(e.target.value)}
              placeholder="GRN/25-26"
            />
          </Field>
          <Field label="Receipt date" htmlFor="grn-date" required>
            <Input
              id="grn-date"
              aria-label="GRN date"
              type="date"
              value={grnDate}
              onChange={(e) => setGrnDate(e.target.value)}
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
                  <Th align="right">Ordered</Th>
                  <Th align="right">Received</Th>
                  <Th>Lot #</Th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line, idx) => (
                  <tr key={line.po_line_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td className="px-3 py-2.5">
                      <span
                        className="mono"
                        style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
                      >
                        {line.item_id.slice(0, 8)}…
                      </span>
                    </td>
                    <td className="num px-3 py-2.5" style={{ textAlign: 'right', fontSize: 13 }}>
                      {line.qty_ordered}
                    </td>
                    <td className="px-3 py-2.5" style={{ textAlign: 'right' }}>
                      <input
                        aria-label={`Line ${idx + 1} qty received`}
                        value={line.qty_received}
                        onChange={(e) => updateLine(idx, { qty_received: e.target.value })}
                        inputMode="decimal"
                        style={{
                          width: 96,
                          height: 32,
                          borderRadius: 6,
                          border: '1px solid var(--border-default)',
                          background: 'var(--bg-surface)',
                          color: 'var(--text-primary)',
                          padding: '0 8px',
                          fontSize: 13,
                          textAlign: 'right',
                        }}
                      />
                    </td>
                    <td className="px-3 py-2.5">
                      <input
                        aria-label={`Line ${idx + 1} lot number`}
                        value={line.lot_number}
                        onChange={(e) => updateLine(idx, { lot_number: e.target.value })}
                        style={{
                          width: 140,
                          height: 32,
                          borderRadius: 6,
                          border: '1px solid var(--border-default)',
                          background: 'var(--bg-surface)',
                          color: 'var(--text-primary)',
                          padding: '0 8px',
                          fontSize: 13,
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Field label="Notes" htmlFor="grn-notes">
          <Input
            id="grn-notes"
            aria-label="GRN notes"
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
            <Link to="/purchase/grns">Cancel</Link>
          </Button>
          <Button onClick={submit} disabled={!canSubmit || createGrn.isPending}>
            {createGrn.isPending ? 'Creating…' : 'Create GRN'}
          </Button>
        </div>
      </div>
    </div>
  );
}

function stripTrailingZeros(s: string): string {
  // BE returns "50.000" — fine to send back, but the input is friendlier
  // when we trim trailing zeros so the user doesn't see "50.000".
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
