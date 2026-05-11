/*
 * ReceiveBackDialog (TASK-CUT-401)
 *
 * Records the goods coming back from a karigar against an existing JWO.
 * For each open line we render one row capturing finished qty + wastage
 * (both default to 0). On submit we POST to /job-work-orders/{id}/receive.
 *
 * Client-side invariant (per the CUT-305 retro pre-FE checklist item #3):
 * `qty_received + qty_wastage <= line's open qty`. The BE will 422 on
 * overrun anyway; the client check just spares a round trip.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import {
  useReceiveJobWork,
  type JobWorkOrder,
  type JobWorkReceiptLineRequest,
} from '@/lib/queries/jobwork';

interface ReceiveBackDialogProps {
  open: boolean;
  onClose: () => void;
  jwo: JobWorkOrder | null;
}

interface LineState {
  job_work_order_line_id: string;
  line_no: number;
  uom: string;
  open_qty: number;
  qty_received: string;
  qty_wastage: string;
}

const TODAY = (): string => new Date().toISOString().slice(0, 10);

function buildLineState(jwo: JobWorkOrder | null): LineState[] {
  if (!jwo) return [];
  return (jwo.lines ?? []).map((line) => {
    const sent = parseFloat(line.qty_sent ?? '0') || 0;
    const rcv = parseFloat(line.qty_received ?? '0') || 0;
    const wst = parseFloat(line.qty_wastage ?? '0') || 0;
    return {
      job_work_order_line_id: line.job_work_order_line_id,
      line_no: line.line_no,
      uom: line.uom,
      open_qty: Math.max(0, sent - rcv - wst),
      qty_received: '',
      qty_wastage: '',
    } satisfies LineState;
  });
}

export function ReceiveBackDialog({ open, onClose, jwo }: ReceiveBackDialogProps) {
  const receive = useReceiveJobWork();
  const idem = useIdempotencyKey();

  const [receiptDate, setReceiptDate] = React.useState(TODAY());
  const [notes, setNotes] = React.useState('');
  const [lines, setLines] = React.useState<LineState[]>(() => buildLineState(jwo));
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setReceiptDate(TODAY());
      setNotes('');
      setLines(buildLineState(jwo));
      setError(null);
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, jwo]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!jwo) {
      setError('No JWO selected.');
      return;
    }

    // Build the request body. Skip lines where both qtys are empty/zero
    // so we don't waste BE work on no-op rows. At least one non-zero
    // entry is required (the BE will 422 on an all-zero receipt anyway).
    const bodyLines: JobWorkReceiptLineRequest[] = [];
    for (const ls of lines) {
      const rcv = ls.qty_received.trim();
      const wst = ls.qty_wastage.trim();
      const rcvNum = parseFloat(rcv);
      const wstNum = parseFloat(wst);
      const hasRcv = Number.isFinite(rcvNum) && rcvNum > 0;
      const hasWst = Number.isFinite(wstNum) && wstNum > 0;
      if (!hasRcv && !hasWst) continue;
      if ((hasRcv ? rcvNum : 0) + (hasWst ? wstNum : 0) > ls.open_qty + 1e-9) {
        setError(
          `Line ${ls.line_no}: received + wastage (${(hasRcv ? rcvNum : 0) + (hasWst ? wstNum : 0)}) exceeds open qty (${ls.open_qty}).`,
        );
        return;
      }
      bodyLines.push({
        job_work_order_line_id: ls.job_work_order_line_id,
        qty_received: hasRcv ? rcv : '0',
        qty_wastage: hasWst ? wst : '0',
        notes: null,
      });
    }
    if (bodyLines.length === 0) {
      setError('Enter a finished or wastage qty on at least one line.');
      return;
    }

    receive.mutate(
      {
        jwoId: jwo.job_work_order_id,
        body: {
          receipt_date: receiptDate,
          notes: notes.trim() || null,
          lines: bodyLines,
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
          setError(err instanceof Error ? err.message : 'Could not save receipt.');
        },
      },
    );
  };

  const updateLine = (idx: number, patch: Partial<LineState>) => {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Receive back"
      description={
        jwo
          ? `Record fabric coming back from karigar against ${jwo.number}.`
          : 'No job-work order selected.'
      }
      width={560}
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="receive-back-form" disabled={receive.isPending || !jwo}>
            {receive.isPending ? 'Saving…' : 'Save receipt'}
          </Button>
        </>
      }
    >
      <form id="receive-back-form" onSubmit={onSubmit} className="flex flex-col gap-3">
        <Field label="Receipt date" htmlFor="rb-date" required>
          <Input
            id="rb-date"
            type="date"
            value={receiptDate}
            onChange={(e) => setReceiptDate(e.target.value)}
          />
        </Field>

        <div className="flex flex-col gap-3">
          {lines.map((ls, idx) => (
            <div
              key={ls.job_work_order_line_id}
              className="rounded-md p-3"
              style={{
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-subtle)',
              }}
            >
              <div
                className="mb-2 flex items-baseline justify-between"
                style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
              >
                <span>Line {ls.line_no}</span>
                <span className="num">
                  Open: {ls.open_qty} {ls.uom}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label={`Finished (${ls.uom})`} htmlFor={`rb-rcv-${idx}`} required>
                  <Input
                    id={`rb-rcv-${idx}`}
                    aria-label={`Finished line ${ls.line_no}`}
                    type="number"
                    inputMode="decimal"
                    step="0.001"
                    min="0"
                    value={ls.qty_received}
                    onChange={(e) => updateLine(idx, { qty_received: e.target.value })}
                    placeholder="0"
                  />
                </Field>
                <Field label={`Wastage (${ls.uom})`} htmlFor={`rb-wst-${idx}`}>
                  <Input
                    id={`rb-wst-${idx}`}
                    aria-label={`Wastage line ${ls.line_no}`}
                    type="number"
                    inputMode="decimal"
                    step="0.001"
                    min="0"
                    value={ls.qty_wastage}
                    onChange={(e) => updateLine(idx, { qty_wastage: e.target.value })}
                    placeholder="0"
                  />
                </Field>
              </div>
            </div>
          ))}
        </div>

        <Field label="Notes" htmlFor="rb-notes">
          <Input
            id="rb-notes"
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
