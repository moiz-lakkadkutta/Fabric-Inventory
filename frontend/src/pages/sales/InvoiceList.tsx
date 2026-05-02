import { FileText, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill, type PillKind } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { useInvoices } from '@/lib/queries/invoices';
import { formatAgeing, formatDateShort, formatINRCompact } from '@/lib/mock';
import type { Invoice, InvoiceStatus } from '@/lib/mock/types';

type FilterKey = 'all' | InvoiceStatus;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'DRAFT', label: 'Drafts' },
  { key: 'FINALIZED', label: 'Finalized' },
  { key: 'PARTIALLY_PAID', label: 'Part-paid' },
  { key: 'OVERDUE', label: 'Overdue' },
  { key: 'PAID', label: 'Paid' },
];

const STATUS_PILL: Record<Invoice['status'], { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  FINALIZED: { kind: 'finalized', label: 'Finalized' },
  PAID: { kind: 'paid', label: 'Paid' },
  PARTIALLY_PAID: { kind: 'due', label: 'Part-paid' },
  OVERDUE: { kind: 'overdue', label: 'Overdue' },
  CANCELLED: { kind: 'scrap', label: 'Cancelled' },
};

export default function InvoiceList() {
  const [filter, setFilter] = useState<FilterKey>('all');
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const invoicesQuery = useInvoices();
  const exportCsv = useComingSoon({
    feature: 'Export invoices to CSV',
    task: 'TASK-046 (Reports → CSV/PDF)',
  });

  const allRows = useMemo(() => invoicesQuery.data ?? [], [invoicesQuery.data]);

  const rows = useMemo(() => {
    return allRows.filter((i) => {
      if (filter !== 'all' && i.status !== filter) return false;
      if (query) {
        const q = query.toLowerCase();
        return i.number.toLowerCase().includes(q) || i.party_name.toLowerCase().includes(q);
      }
      return true;
    });
  }, [allRows, filter, query]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Sales invoices</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {invoicesQuery.isPending ? '—' : `${rows.length} of ${allRows.length}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="default" {...exportCsv.triggerProps}>
            Export CSV
          </Button>
          <Button size="default" onClick={() => navigate('/sales/invoices/new')}>
            <Plus />
            New invoice
          </Button>
        </div>
      </header>
      {exportCsv.dialog}

      {/* Filters + search */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className="inline-flex h-8 items-center rounded-full px-3"
                style={{
                  fontSize: 12.5,
                  fontWeight: active ? 600 : 500,
                  background: active ? 'var(--accent-subtle)' : 'transparent',
                  color: active ? 'var(--accent)' : 'var(--text-secondary)',
                  border: active
                    ? '1px solid var(--accent-subtle)'
                    : '1px solid var(--border-default)',
                }}
              >
                {f.label}
              </button>
            );
          })}
        </div>
        <div
          className="ml-auto inline-flex h-9 w-72 items-center gap-2 rounded-md px-3"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
          }}
        >
          <Search size={14} color="var(--text-tertiary)" />
          <input
            type="search"
            name="invoice-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search invoice # or party"
            className="flex-1 bg-transparent outline-none"
            style={{ fontSize: 13 }}
          />
        </div>
      </div>

      {/* Table */}
      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        {invoicesQuery.isError ? (
          <QueryError onRetry={() => invoicesQuery.refetch()} />
        ) : invoicesQuery.isPending ? (
          <ListSkeleton rows={10} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={FileText}
            title={
              query
                ? `No invoices match "${query}"`
                : filter === 'all'
                  ? 'No invoices yet'
                  : 'No invoices in this filter'
            }
            body={
              query || filter !== 'all'
                ? 'Try clearing the filter or searching by party name.'
                : 'Create your first invoice to start the books.'
            }
            cta={
              query || filter !== 'all'
                ? {
                    label: 'Clear filter',
                    onClick: () => {
                      setFilter('all');
                      setQuery('');
                    },
                  }
                : { label: 'New invoice', onClick: () => navigate('/sales/invoices/new') }
            }
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 760 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Invoice #</Th>
                <Th>Date</Th>
                <Th>Party</Th>
                <Th>Status</Th>
                <Th align="right">Amount</Th>
                <Th align="right">Paid</Th>
                <Th>Ageing</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((inv) => {
                const pill = STATUS_PILL[inv.status];
                const overdue = inv.ageing_days > 0 && inv.status !== 'PAID';
                return (
                  <tr
                    key={inv.invoice_id}
                    style={{ borderTop: '1px solid var(--border-subtle)' }}
                    className="hover:bg-(--bg-sunken)/40"
                  >
                    <Td>
                      <Link
                        to={`/sales/invoices/${inv.invoice_id}`}
                        className="mono"
                        style={{
                          fontSize: 12.5,
                          fontWeight: 500,
                          color: 'var(--accent)',
                        }}
                      >
                        {inv.number}
                      </Link>
                    </Td>
                    <Td>
                      <span style={{ fontSize: 13, whiteSpace: 'nowrap' }} className="num">
                        {formatDateShort(inv.date)}
                      </span>
                    </Td>
                    <Td>
                      <span
                        className="block max-w-[18rem] truncate"
                        style={{ fontSize: 13.5, fontWeight: 500 }}
                      >
                        {inv.party_name}
                      </span>
                    </Td>
                    <Td>
                      <Pill kind={pill.kind}>{pill.label}</Pill>
                    </Td>
                    <Td align="right">
                      <span className="num" style={{ fontSize: 13.5, fontWeight: 500 }}>
                        {formatINRCompact(inv.total)}
                      </span>
                    </Td>
                    <Td align="right">
                      <span
                        className="num"
                        style={{
                          fontSize: 13,
                          color:
                            inv.paid === inv.total
                              ? 'var(--success-text)'
                              : inv.paid > 0
                                ? 'var(--text-secondary)'
                                : 'var(--text-tertiary)',
                        }}
                      >
                        {formatINRCompact(inv.paid)}
                      </span>
                    </Td>
                    <Td>
                      <span
                        style={{
                          fontSize: 12,
                          color: overdue ? 'var(--danger)' : 'var(--text-tertiary)',
                          fontWeight: overdue ? 500 : 400,
                        }}
                      >
                        {formatAgeing(inv.ageing_days, inv.status)}
                      </span>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
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

function Td({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <td className="px-3 py-3" style={{ textAlign: align, verticalAlign: 'middle' }}>
      {children}
    </td>
  );
}

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div role="status" aria-label="Loading invoices" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={88} height={14} />
          <Skeleton width={56} height={14} />
          <Skeleton width="32%" height={14} />
          <Skeleton width={72} height={20} radius={10} />
          <div className="flex-1" />
          <Skeleton width={84} height={14} />
          <Skeleton width={64} height={14} />
        </div>
      ))}
    </div>
  );
}
