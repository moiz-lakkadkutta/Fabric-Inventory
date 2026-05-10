/*
 * Sales Orders list page (TASK-CUT-203).
 *
 * Replaces the <Placeholder> route at /sales/orders. Lists SOs from the
 * live BE (`GET /sales-orders`), with status pills + a "+ New SO" button
 * that routes to /sales/orders/new.
 */

import { ClipboardList, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill, type PillKind } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { useParties } from '@/lib/queries/parties';
import { useSalesOrders } from '@/lib/queries/sales-orders';
import { formatDateShort, formatINRCompact } from '@/lib/format';
import type { components } from '@/types/api';

type SalesOrderStatus = components['schemas']['SalesOrderStatus'];

const STATUS_PILL: Record<SalesOrderStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  CONFIRMED: { kind: 'finalized', label: 'Confirmed' },
  PARTIAL_DC: { kind: 'due', label: 'Partial DC' },
  FULLY_DISPATCHED: { kind: 'paid', label: 'Dispatched' },
  INVOICED: { kind: 'paid', label: 'Invoiced' },
  CANCELLED: { kind: 'scrap', label: 'Cancelled' },
};

type FilterKey = 'all' | SalesOrderStatus;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'DRAFT', label: 'Drafts' },
  { key: 'CONFIRMED', label: 'Confirmed' },
  { key: 'PARTIAL_DC', label: 'Partial' },
  { key: 'FULLY_DISPATCHED', label: 'Dispatched' },
  { key: 'CANCELLED', label: 'Cancelled' },
];

export default function SalesOrderList() {
  const navigate = useNavigate();
  const sosQuery = useSalesOrders();
  const partiesQuery = useParties();
  const [filter, setFilter] = useState<FilterKey>('all');
  const [query, setQuery] = useState('');

  const partyName = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of partiesQuery.data ?? []) map.set(p.party_id, p.name);
    return map;
  }, [partiesQuery.data]);

  const allRows = useMemo(() => sosQuery.data ?? [], [sosQuery.data]);
  const rows = useMemo(() => {
    return allRows.filter((so) => {
      if (filter !== 'all' && so.status !== filter) return false;
      if (query) {
        const q = query.toLowerCase();
        const name = partyName.get(so.party_id) ?? '';
        return so.display_number.toLowerCase().includes(q) || name.toLowerCase().includes(q);
      }
      return true;
    });
  }, [allRows, filter, query, partyName]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Sales orders</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {sosQuery.isPending ? '—' : `${rows.length} of ${allRows.length}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button onClick={() => navigate('/sales/orders/new')}>
            <Plus />
            New SO
          </Button>
        </div>
      </header>

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
            name="so-search"
            aria-label="Search sales orders"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search SO # or party"
            className="flex-1 bg-transparent outline-none"
            style={{ fontSize: 13 }}
          />
        </div>
      </div>

      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        {sosQuery.isError ? (
          <QueryError error={sosQuery.error} onRetry={() => sosQuery.refetch()} />
        ) : sosQuery.isPending ? (
          <ListSkeleton rows={6} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={ClipboardList}
            title={
              query
                ? `No sales orders match "${query}"`
                : filter === 'all'
                  ? 'No sales orders yet'
                  : 'No sales orders in this filter'
            }
            body={
              query || filter !== 'all'
                ? 'Try clearing the filter, or create one.'
                : 'Create the first SO to track a customer commitment before delivery.'
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
                : { label: 'New SO', onClick: () => navigate('/sales/orders/new') }
            }
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 760 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>SO #</Th>
                <Th>Date</Th>
                <Th>Party</Th>
                <Th>Status</Th>
                <Th align="right">Total</Th>
                <Th>Delivery</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((so) => {
                const pill = STATUS_PILL[so.status] ?? STATUS_PILL.DRAFT;
                return (
                  <tr
                    key={so.sales_order_id}
                    style={{ borderTop: '1px solid var(--border-subtle)' }}
                  >
                    <Td>
                      <Link
                        to={`/sales/orders/${so.sales_order_id}`}
                        className="mono"
                        style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--accent)' }}
                      >
                        {so.display_number}
                      </Link>
                    </Td>
                    <Td>
                      <span className="num" style={{ fontSize: 13 }}>
                        {formatDateShort(so.so_date)}
                      </span>
                    </Td>
                    <Td>
                      <span style={{ fontSize: 13.5, fontWeight: 500 }}>
                        {partyName.get(so.party_id) ?? '—'}
                      </span>
                    </Td>
                    <Td>
                      <Pill kind={pill.kind}>{pill.label}</Pill>
                    </Td>
                    <Td align="right">
                      <span className="num" style={{ fontSize: 13.5, fontWeight: 500 }}>
                        {formatINRCompact(so.total_amount)}
                      </span>
                    </Td>
                    <Td>
                      <span
                        className="num"
                        style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}
                      >
                        {so.delivery_date ? formatDateShort(so.delivery_date) : '—'}
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
    <div role="status" aria-label="Loading sales orders" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={88} height={14} />
          <Skeleton width={56} height={14} />
          <Skeleton width="32%" height={14} />
          <Skeleton width={72} height={20} radius={10} />
          <div className="flex-1" />
          <Skeleton width={84} height={14} />
        </div>
      ))}
    </div>
  );
}
