import { ArrowLeft } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { Monogram } from '@/components/ui/monogram';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { findParty } from '@/lib/mock/parties';
import { invoices } from '@/lib/mock/invoices';
import { formatINRCompact } from '@/lib/mock';
import { useQuery } from '@tanstack/react-query';

import { fakeFetch } from '@/lib/mock/api';
import type { PartyKind } from '@/lib/mock/types';

const KIND_PILL: Record<PartyKind, { kind: PillKind; label: string }> = {
  customer: { kind: 'finalized', label: 'Customer' },
  supplier: { kind: 'draft', label: 'Supplier' },
  karigar: { kind: 'karigar', label: 'Karigar' },
  transporter: { kind: 'scrap', label: 'Transporter' },
};

function useParty(id: string | undefined) {
  return useQuery({
    queryKey: ['parties', id],
    enabled: id !== undefined,
    queryFn: () => fakeFetch(() => (id ? (findParty(id) ?? null) : null)),
  });
}

export default function PartyDetail() {
  const { id } = useParams<{ id: string }>();
  const partyQuery = useParty(id);

  if (partyQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width="40%" height={28} />
        <Skeleton width="100%" height={400} radius={8} />
      </div>
    );
  }

  const p = partyQuery.data;
  if (!p) {
    return (
      <div className="p-8 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        Party not found.
      </div>
    );
  }

  const initials = p.name
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
  const pill = KIND_PILL[p.kind];

  // Khata KPIs from invoices.
  const partyInvoices = invoices.filter((i) => i.party_id === p.party_id);
  const total = partyInvoices.reduce((s, i) => s + i.total, 0);
  const paid = partyInvoices.reduce((s, i) => s + i.paid, 0);
  const outstanding = total - paid;
  const overdue = partyInvoices
    .filter((i) => i.ageing_days > 0 && i.status !== 'PAID' && i.status !== 'CANCELLED')
    .reduce((s, i) => s + (i.total - i.paid), 0);

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/masters/parties"
          aria-label="Back to parties"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <Monogram initials={initials} size={44} tone="accent" />
        <div className="min-w-0">
          <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em', margin: 0 }}>
            {p.name}
          </h1>
          <div
            className="mt-0.5 flex items-center gap-2"
            style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}
          >
            <span>{p.code}</span>
            <span>·</span>
            <span>{p.city}</span>
            {p.gstin && (
              <>
                <span>·</span>
                <span className="mono">{p.gstin}</span>
              </>
            )}
          </div>
        </div>
        <div className="ml-auto">
          <Pill kind={pill.kind}>{pill.label}</Pill>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KhataKPI label="Total billed" value={formatINRCompact(total)} />
        <KhataKPI label="Received" value={formatINRCompact(paid)} green />
        <KhataKPI label="Outstanding" value={formatINRCompact(outstanding)} />
        <KhataKPI label="Overdue" value={formatINRCompact(overdue)} danger />
      </div>

      <section
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <header
          className="flex items-baseline gap-2 px-4"
          style={{
            paddingTop: 12,
            paddingBottom: 12,
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>
            Khata · invoices &amp; receipts
          </h2>
          <span className="ml-auto" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
            {partyInvoices.length} entries
          </span>
        </header>
        <table className="w-full text-left">
          <thead>
            <tr style={{ color: 'var(--text-tertiary)' }}>
              <Th>Doc</Th>
              <Th>Date</Th>
              <Th>Type</Th>
              <Th align="right">Amount</Th>
              <Th align="right">Paid</Th>
              <Th align="right">Outstanding</Th>
            </tr>
          </thead>
          <tbody>
            {partyInvoices.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-12 text-center"
                  style={{ fontSize: 13, color: 'var(--text-tertiary)' }}
                >
                  No transactions for this party yet.
                </td>
              </tr>
            )}
            {partyInvoices.map((i) => (
              <tr key={i.invoice_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td className="px-3 py-2.5">
                  <Link
                    to={`/sales/invoices/${i.invoice_id}`}
                    className="mono"
                    style={{ fontSize: 12.5, color: 'var(--accent)', fontWeight: 500 }}
                  >
                    {i.number}
                  </Link>
                </td>
                <td className="num px-3 py-2.5" style={{ fontSize: 12.5 }}>
                  {i.date}
                </td>
                <td
                  className="px-3 py-2.5"
                  style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                >
                  Sales invoice
                </td>
                <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                  {formatINRCompact(i.total)}
                </td>
                <td
                  className="num px-3 py-2.5"
                  style={{ textAlign: 'right', color: 'var(--text-secondary)' }}
                >
                  {formatINRCompact(i.paid)}
                </td>
                <td
                  className="num px-3 py-2.5"
                  style={{
                    textAlign: 'right',
                    color: i.total - i.paid > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)',
                    fontWeight: i.total - i.paid > 0 ? 500 : 400,
                  }}
                >
                  {formatINRCompact(i.total - i.paid)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function KhataKPI({
  label,
  value,
  green,
  danger,
}: {
  label: string;
  value: string;
  green?: boolean;
  danger?: boolean;
}) {
  const color = danger ? 'var(--danger)' : green ? 'var(--success-text)' : 'var(--text-primary)';
  return (
    <article
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        padding: 14,
      }}
    >
      <div
        className="uppercase"
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div className="num mt-1.5" style={{ fontSize: 22, fontWeight: 600, color }}>
        {value}
      </div>
    </article>
  );
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
