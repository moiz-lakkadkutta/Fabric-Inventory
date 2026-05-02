import { ArrowLeft, Check, Printer } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { useFinalizeInvoice, useInvoice } from '@/lib/queries/invoices';
import { formatDateShort, formatINRCompact } from '@/lib/mock';
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
    finalize.mutate(inv.invoice_id);
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
          <Button variant="outline">
            <Printer size={14} />
            Print
          </Button>
          {inv.status === 'DRAFT' && (
            <Button onClick={onFinalize} disabled={finalize.isPending}>
              <Check size={14} />
              Finalize
            </Button>
          )}
        </div>
      </header>

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
