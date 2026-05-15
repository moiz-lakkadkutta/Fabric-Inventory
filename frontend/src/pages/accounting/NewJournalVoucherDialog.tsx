/*
 * NewJournalVoucherDialog (TASK-TR-C01) — replaces the previous
 * `useComingSoon('v2 — journal vouchers')` on the AccountingHub
 * "+ New voucher" CTA. Posts a balanced bundle of DR/CR lines to
 * POST /vouchers/journal via `useCreateJournalVoucher`.
 *
 * UX:
 *   - Date picker + narration (optional) up top.
 *   - Dynamic list of lines, each with ledger select / DR-CR toggle /
 *     amount input + per-row remove. Add Row button at the bottom.
 *   - Live DR / CR totals + balance Δ at the foot of the form.
 *   - Submit disabled until >= 2 lines AND Σ DR == Σ CR (and > 0).
 *   - Server-side rejection (e.g. cross-firm ledger) surfaces as an
 *     inline error; the dialog stays open so the user can correct.
 */

import { Plus, Trash2 } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { formatINRCompact } from '@/lib/format';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import {
  type JournalLineDraft,
  type LedgerPickerItem,
  useCreateJournalVoucher,
  useLedgers,
} from '@/lib/queries/accounts';
import { useMe } from '@/store/auth';

interface NewJournalVoucherDialogProps {
  open: boolean;
  onClose: () => void;
}

interface LineDraft {
  id: string; // local row key
  ledger_id: string;
  line_type: 'DR' | 'CR';
  amount: string; // rupees, raw input
  description: string;
}

const TODAY = (): string => new Date().toISOString().slice(0, 10);

const blankLine = (line_type: 'DR' | 'CR'): LineDraft => ({
  id: `row_${Math.random().toString(36).slice(2, 10)}`,
  ledger_id: '',
  line_type,
  amount: '',
  description: '',
});

function parseRupees(s: string): number {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : NaN;
}

function lineAmountPaise(line: LineDraft): number {
  const v = parseRupees(line.amount);
  if (!Number.isFinite(v) || v <= 0) return 0;
  return Math.round(v * 100);
}

export function NewJournalVoucherDialog({ open, onClose }: NewJournalVoucherDialogProps) {
  const me = useMe();
  const ledgers = useLedgers();
  const mutation = useCreateJournalVoucher();
  const idem = useIdempotencyKey();

  const [voucherDate, setVoucherDate] = React.useState<string>(TODAY());
  const [narration, setNarration] = React.useState('');
  const [lines, setLines] = React.useState<LineDraft[]>(() => [blankLine('DR'), blankLine('CR')]);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setVoucherDate(TODAY());
      setNarration('');
      setLines([blankLine('DR'), blankLine('CR')]);
      setError(null);
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const totalDrPaise = lines
    .filter((l) => l.line_type === 'DR')
    .reduce((acc, l) => acc + lineAmountPaise(l), 0);
  const totalCrPaise = lines
    .filter((l) => l.line_type === 'CR')
    .reduce((acc, l) => acc + lineAmountPaise(l), 0);
  const diffPaise = totalDrPaise - totalCrPaise;

  const allLinesValid = lines.every((l) => Boolean(l.ledger_id) && lineAmountPaise(l) > 0);
  const balanced = totalDrPaise > 0 && totalDrPaise === totalCrPaise;
  const canSubmit =
    lines.length >= 2 && allLinesValid && balanced && !mutation.isPending && Boolean(me?.firm_id);

  const updateLine = (id: string, patch: Partial<LineDraft>) => {
    setLines((prev) => prev.map((line) => (line.id === id ? { ...line, ...patch } : line)));
  };
  const removeLine = (id: string) => {
    setLines((prev) => (prev.length <= 2 ? prev : prev.filter((line) => line.id !== id)));
  };
  const addLine = (line_type: 'DR' | 'CR') => {
    setLines((prev) => [...prev, blankLine(line_type)]);
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!me?.firm_id) {
      setError('No active firm in this session.');
      return;
    }
    if (lines.length < 2) {
      setError('At least two lines required.');
      return;
    }
    if (!balanced) {
      setError('Debits and credits must match before posting.');
      return;
    }
    const payload: JournalLineDraft[] = lines.map((line) => ({
      ledger_id: line.ledger_id,
      line_type: line.line_type,
      amount_paise: lineAmountPaise(line),
      description: line.description.trim() || undefined,
    }));
    mutation.mutate(
      {
        firmId: me.firm_id,
        voucherDate,
        narration: narration.trim() || undefined,
        lines: payload,
        idempotencyKey: idem.key,
      },
      {
        onSuccess: () => {
          idem.reset();
          onClose();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Could not post journal voucher.');
        },
      },
    );
  };

  const ledgerOptions: LedgerPickerItem[] = ledgers.data ?? [];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New journal voucher"
      description="Post a manual balanced GL entry. Debits and credits must match before submit."
      width={720}
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="new-jv-form" disabled={!canSubmit}>
            {mutation.isPending ? 'Posting…' : 'Post voucher'}
          </Button>
        </>
      }
    >
      <form id="new-jv-form" onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Voucher date" htmlFor="jv-date" required>
            <Input
              id="jv-date"
              type="date"
              value={voucherDate}
              onChange={(e) => setVoucherDate(e.target.value)}
            />
          </Field>
          <Field label="Narration (optional)" htmlFor="jv-narration">
            <Input
              id="jv-narration"
              value={narration}
              onChange={(e) => setNarration(e.target.value)}
              placeholder="e.g. April depreciation, cost-centre allocation, …"
            />
          </Field>
        </div>

        <div
          className="rounded-md"
          style={{
            border: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            overflow: 'hidden',
          }}
        >
          <table className="w-full text-left" style={{ minWidth: 580 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr
                style={{
                  color: 'var(--text-tertiary)',
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                <th className="px-2 py-2" style={{ width: '38%' }}>
                  Ledger
                </th>
                <th className="px-2 py-2" style={{ width: 96 }}>
                  Type
                </th>
                <th className="px-2 py-2" style={{ width: 130, textAlign: 'right' }}>
                  Amount (₹)
                </th>
                <th className="px-2 py-2">Description</th>
                <th className="px-2 py-2" style={{ width: 40 }} aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {lines.map((line, idx) => (
                <tr key={line.id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td className="px-2 py-2">
                    <select
                      aria-label={`Line ${idx + 1} ledger`}
                      value={line.ledger_id}
                      onChange={(e) => updateLine(line.id, { ledger_id: e.target.value })}
                      className="h-9 w-full rounded-md px-2"
                      style={{
                        border: '1px solid var(--border-default)',
                        background: 'var(--bg-surface)',
                        fontSize: 13,
                      }}
                    >
                      <option value="">— Select ledger —</option>
                      {ledgerOptions.map((l) => (
                        <option key={l.ledger_id} value={l.ledger_id}>
                          {l.code} · {l.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-2">
                    <select
                      aria-label={`Line ${idx + 1} type`}
                      value={line.line_type}
                      onChange={(e) =>
                        updateLine(line.id, { line_type: e.target.value as 'DR' | 'CR' })
                      }
                      className="h-9 w-full rounded-md px-2"
                      style={{
                        border: '1px solid var(--border-default)',
                        background: 'var(--bg-surface)',
                        fontSize: 13,
                      }}
                    >
                      <option value="DR">DR</option>
                      <option value="CR">CR</option>
                    </select>
                  </td>
                  <td className="px-2 py-2">
                    <Input
                      aria-label={`Line ${idx + 1} amount`}
                      type="number"
                      inputMode="decimal"
                      step="0.01"
                      min="0"
                      value={line.amount}
                      onChange={(e) => updateLine(line.id, { amount: e.target.value })}
                      placeholder="0.00"
                      style={{ textAlign: 'right' }}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <Input
                      aria-label={`Line ${idx + 1} description`}
                      value={line.description}
                      onChange={(e) => updateLine(line.id, { description: e.target.value })}
                      placeholder="(optional)"
                    />
                  </td>
                  <td className="px-2 py-2">
                    <button
                      type="button"
                      aria-label={`Remove line ${idx + 1}`}
                      onClick={() => removeLine(line.id)}
                      disabled={lines.length <= 2}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md"
                      style={{
                        background: 'transparent',
                        border: '1px solid transparent',
                        color: lines.length <= 2 ? 'var(--text-tertiary)' : 'var(--text-secondary)',
                        opacity: lines.length <= 2 ? 0.4 : 1,
                        cursor: lines.length <= 2 ? 'not-allowed' : 'pointer',
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div
            className="flex items-center gap-2 px-2 py-2"
            style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-sunken)' }}
          >
            <Button
              type="button"
              variant="outline"
              onClick={() => addLine('DR')}
              aria-label="Add debit line"
            >
              <Plus size={14} />
              Add DR line
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => addLine('CR')}
              aria-label="Add credit line"
            >
              <Plus size={14} />
              Add CR line
            </Button>
          </div>
        </div>

        <div
          className="grid grid-cols-3 gap-3 rounded-md px-3 py-2.5"
          style={{
            background: 'var(--bg-sunken)',
            border: '1px solid var(--border-subtle)',
            fontSize: 13,
          }}
          aria-live="polite"
        >
          <div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>Total debits</div>
            <div className="num" style={{ fontWeight: 600 }}>
              {formatINRCompact(totalDrPaise)}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>Total credits</div>
            <div className="num" style={{ fontWeight: 600 }}>
              {formatINRCompact(totalCrPaise)}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>Difference</div>
            <div
              className="num"
              style={{
                fontWeight: 600,
                color:
                  diffPaise === 0 && totalDrPaise > 0
                    ? 'var(--success-text)'
                    : 'var(--danger-text)',
              }}
            >
              {diffPaise === 0 ? 'Balanced' : formatINRCompact(Math.abs(diffPaise))}
            </div>
          </div>
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
