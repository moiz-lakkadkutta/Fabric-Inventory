import { ArrowLeft, AlertCircle, Check, IndianRupee, Printer } from 'lucide-react';
import * as React from 'react';
import { Link, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError, apiBlob } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { IS_LIVE } from '@/lib/api/mode';
import { usePostReceipt, type ReceiptMode } from '@/lib/queries/accounts';
import { useFinalizeInvoice, useInvoice } from '@/lib/queries/invoices';
import { formatDateShort, formatINRCompact } from '@/lib/format';
import type { Invoice } from '@/lib/mock/types';

const STATUS_PILL: Record<Invoice['status'], { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  FINALIZED: { kind: 'finalized', label: 'Finalized' },
  PAID: { kind: 'paid', label: 'Paid' },
  PARTIALLY_PAID: { kind: 'due', label: 'Part-paid' },
  OVERDUE: { kind: 'overdue', label: 'Overdue' },
  CANCELLED: { kind: 'scrap', label: 'Cancelled' },
};

export default function InvoiceDetail() {
  const { id } = useParams<{ id: string }>();
  const invoiceQuery = useInvoice(id);
  const finalize = useFinalizeInvoice();
  const postReceipt = usePostReceipt();
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const receiptKey = useIdempotencyKey();
  const [staleError, setStaleError] = React.useState<string | null>(null);
  const [recordOpen, setRecordOpen] = React.useState(false);
  const [recordAmount, setRecordAmount] = React.useState('');
  const [recordMode, setRecordMode] = React.useState<ReceiptMode>('CASH');
  const [recordRef, setRecordRef] = React.useState('');
  const [recordError, setRecordError] = React.useState<string | null>(null);
  const [printError, setPrintError] = React.useState<string | null>(null);
  const [printPending, setPrintPending] = React.useState(false);

  if (invoiceQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width="40%" height={28} />
        <Skeleton width="100%" height={300} radius={8} />
      </div>
    );
  }

  const inv = invoiceQuery.data;
  if (!inv) {
    return (
      <div className="p-8 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        Invoice not found.
      </div>
    );
  }

  const pill = STATUS_PILL[inv.status];

  const onFinalize = () => {
    finalize.mutate(
      { invoiceId: inv.invoice_id, idempotencyKey },
      {
        onSuccess: () => {
          resetKey();
        },
        onError: (err) => {
          resetKey();
          // Backend reuses InvoiceStateError → INVOICE_STATE_ERROR (409)
          // when this invoice already moved past DRAFT. The detail page
          // is therefore stale; show the refresh affordance.
          if (err instanceof ApiError && err.code === 'INVOICE_STATE_ERROR') {
            setStaleError(
              'This invoice was already finalized in another session. Refresh to see the latest state.',
            );
          } else {
            setStaleError(err.message);
          }
        },
      },
    );
  };

  const onRefresh = () => {
    setStaleError(null);
    invoiceQuery.refetch();
  };

  // CUT-205: hit GET /invoices/:id/pdf, turn the Blob into an object URL,
  // and trigger a download via a synthetic anchor click. Authorization
  // headers don't carry on plain `<a href>` so apiBlob() does the auth
  // dance and hands us bytes. Click-dummy mode falls back to the disabled
  // path with a clear message — there's no PDF without a backend.
  const onPrint = async () => {
    setPrintError(null);
    if (!IS_LIVE) {
      setPrintError('Live mode required to download a GST-compliant PDF.');
      return;
    }
    setPrintPending(true);
    try {
      const blob = await apiBlob(`/invoices/${inv.invoice_id}/pdf`);
      const url = URL.createObjectURL(blob);
      try {
        const a = document.createElement('a');
        a.href = url;
        a.download = `${inv.number.replace(/\//g, '_')}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } finally {
        // Defer revoke so Safari has a tick to start the download.
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `${err.code}: ${err.detail || err.title}`
          : err instanceof Error
            ? err.message
            : 'Could not download the PDF.';
      setPrintError(msg);
    } finally {
      setPrintPending(false);
    }
  };

  const outstandingPaise = Math.max(inv.total - inv.paid, 0);
  const canRecordPayment =
    inv.status === 'FINALIZED' || inv.status === 'PARTIALLY_PAID' || inv.status === 'OVERDUE';

  const onSubmitReceipt = (e: React.FormEvent) => {
    e.preventDefault();
    setRecordError(null);
    const amountRupees = parseFloat(recordAmount);
    if (!Number.isFinite(amountRupees) || amountRupees <= 0) {
      setRecordError('Enter a positive amount.');
      return;
    }
    postReceipt.mutate(
      {
        partyId: inv.party_id,
        partyName: inv.party_name,
        amountPaise: Math.round(amountRupees * 100),
        receiptDate: new Date().toISOString().slice(0, 10),
        mode: recordMode,
        reference: recordRef || undefined,
        idempotencyKey: receiptKey.key,
      },
      {
        onSuccess: () => {
          receiptKey.reset();
          setRecordAmount('');
          setRecordRef('');
          setRecordOpen(false);
          // useInvoice cache is invalidated by usePostReceipt's onSuccess.
        },
        onError: (err) => {
          receiptKey.reset();
          setRecordError(err instanceof Error ? err.message : 'Could not record payment.');
        },
      },
    );
  };

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
        <h1 className="mono" style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.012em' }}>
          {inv.number}
        </h1>
        <Pill kind={pill.kind}>{pill.label}</Pill>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            onClick={onPrint}
            disabled={printPending || inv.status === 'DRAFT'}
            title={
              inv.status === 'DRAFT' ? 'Finalize the invoice before printing the PDF.' : undefined
            }
          >
            <Printer size={14} />
            {printPending ? 'Preparing…' : 'Print'}
          </Button>
          {inv.status === 'DRAFT' && (
            <Button onClick={onFinalize} disabled={finalize.isPending}>
              <Check size={14} />
              Finalize
            </Button>
          )}
          {canRecordPayment && (
            <Button onClick={() => setRecordOpen((v) => !v)}>
              <IndianRupee size={14} />
              {recordOpen ? 'Cancel' : 'Record payment'}
            </Button>
          )}
        </div>
      </header>

      {recordOpen && canRecordPayment && (
        <form
          onSubmit={onSubmitReceipt}
          className="flex flex-col gap-3 p-4"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
          }}
        >
          <div className="flex items-baseline gap-2">
            <span style={{ fontSize: 14, fontWeight: 600 }}>Record payment</span>
            <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
              Outstanding: {formatINRCompact(outstandingPaise)}
            </span>
          </div>
          <div className="flex flex-wrap gap-3">
            <div style={{ flex: '1 1 160px' }}>
              <Field label="Amount (₹)" htmlFor="receipt-amount">
                <Input
                  id="receipt-amount"
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  min="0"
                  value={recordAmount}
                  onChange={(e) => setRecordAmount(e.target.value)}
                  placeholder={(outstandingPaise / 100).toFixed(2)}
                />
              </Field>
            </div>
            <div style={{ flex: '0 0 140px' }}>
              <Field label="Mode" htmlFor="receipt-mode">
                <select
                  id="receipt-mode"
                  value={recordMode}
                  onChange={(e) => setRecordMode(e.target.value as ReceiptMode)}
                  className="h-9 w-full rounded-md px-2"
                  style={{
                    border: '1px solid var(--border-default)',
                    background: 'var(--bg-surface)',
                    fontSize: 13,
                  }}
                >
                  <option value="CASH">Cash</option>
                  <option value="BANK">Bank</option>
                  <option value="UPI">UPI</option>
                </select>
              </Field>
            </div>
            <div style={{ flex: '2 1 200px' }}>
              <Field label="Reference (optional)" htmlFor="receipt-ref">
                <Input
                  id="receipt-ref"
                  value={recordRef}
                  onChange={(e) => setRecordRef(e.target.value)}
                  placeholder="NEFT id, cheque #, etc."
                />
              </Field>
            </div>
          </div>
          {recordError && (
            <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 12.5 }}>
              {recordError}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" type="button" onClick={() => setRecordOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={postReceipt.isPending}>
              Save receipt
            </Button>
          </div>
        </form>
      )}

      {staleError && (
        <div
          role="alert"
          className="flex items-start gap-2"
          style={{
            padding: '10px 12px',
            background: 'var(--danger-subtle)',
            color: 'var(--danger-text)',
            borderRadius: 6,
            fontSize: 12.5,
          }}
        >
          <AlertCircle size={14} color="var(--danger)" />
          <span style={{ flex: 1 }}>{staleError}</span>
          <Button variant="outline" onClick={onRefresh}>
            Refresh
          </Button>
        </div>
      )}

      {printError && (
        <div
          role="alert"
          className="flex items-start gap-2"
          style={{
            padding: '10px 12px',
            background: 'var(--danger-subtle)',
            color: 'var(--danger-text)',
            borderRadius: 6,
            fontSize: 12.5,
          }}
        >
          <AlertCircle size={14} color="var(--danger)" />
          <span style={{ flex: 1 }}>{printError}</span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div
          className="space-y-4 p-4"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <Meta label="Customer" value={inv.party_name} />
            <Meta label="Document type" value={prettyDocType(inv.doc_type)} />
            <Meta label="Issue date" value={formatDateShort(inv.date)} />
            <Meta label="Due date" value={formatDateShort(inv.due_date)} />
          </div>

          <table className="w-full text-left">
            <thead>
              <tr style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>
                <Th>Item</Th>
                <Th align="right">Qty</Th>
                <Th align="right">Rate</Th>
                <Th align="right">GST</Th>
                <Th align="right">Amount</Th>
              </tr>
            </thead>
            <tbody>
              {inv.lines.map((l, i) => (
                <tr
                  key={`${l.item_id}-${i}`}
                  style={{ borderTop: '1px solid var(--border-subtle)' }}
                >
                  <td className="px-2 py-2.5" style={{ fontSize: 13.5, fontWeight: 500 }}>
                    {l.item_name}
                  </td>
                  <td className="num px-2 py-2.5" style={{ textAlign: 'right' }}>
                    {l.qty} {l.uom}
                  </td>
                  <td className="num px-2 py-2.5" style={{ textAlign: 'right' }}>
                    {formatINRCompact(l.rate)}
                  </td>
                  <td className="num px-2 py-2.5" style={{ textAlign: 'right' }}>
                    {l.gst_pct}%
                  </td>
                  <td
                    className="num px-2 py-2.5"
                    style={{ textAlign: 'right', fontSize: 13.5, fontWeight: 500 }}
                  >
                    {formatINRCompact(l.amount + l.gst_amount)}
                  </td>
                </tr>
              ))}
              {inv.lines.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-2 py-8 text-center"
                    style={{ color: 'var(--text-tertiary)', fontSize: 13 }}
                  >
                    No line items.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
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
          <Row label="Subtotal" value={formatINRCompact(inv.subtotal)} />
          <Row label="GST" value={formatINRCompact(inv.gst_total)} />
          <hr style={{ border: 0, borderTop: '1px solid var(--border-subtle)' }} />
          <Row label="Grand total" value={formatINRCompact(inv.total)} big />
          <Row label="Paid" value={formatINRCompact(inv.paid)} />
          <Row label="Outstanding" value={formatINRCompact(inv.total - inv.paid)} />
        </aside>
      </div>
    </div>
  );
}

function prettyDocType(t: Invoice['doc_type']) {
  return {
    TAX_INVOICE: 'Tax invoice',
    BILL_OF_SUPPLY: 'Bill of supply',
    CASH_MEMO: 'Cash memo',
    ESTIMATE: 'Estimate',
  }[t];
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

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        className="uppercase"
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
          letterSpacing: '.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div className="mt-0.5" style={{ fontSize: 14, fontWeight: 500 }}>
        {value}
      </div>
    </div>
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
      <span
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
