/*
 * Delivery Challans list page (TASK-CUT-203).
 *
 * Replaces the <Placeholder> route at /sales/challans (and the new
 * /sales/delivery-challans alias). Lists DCs from the live BE
 * (`GET /delivery-challans`).
 */

import { Truck, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill, type PillKind } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { useParties } from '@/lib/queries/parties';
import { useDeliveryChallans } from '@/lib/queries/delivery-challans';
import { formatDateShort } from '@/lib/format';
import type { components } from '@/types/api';

type DCStatus = components['schemas']['DCStatus'];

const STATUS_PILL: Record<DCStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  ISSUED: { kind: 'finalized', label: 'Issued' },
  ACKNOWLEDGED: { kind: 'paid', label: 'Acknowledged' },
  IN_PROCESS: { kind: 'karigar', label: 'In process' },
  RETURNED: { kind: 'due', label: 'Returned' },
  CLOSED: { kind: 'paid', label: 'Closed' },
};

type FilterKey = 'all' | DCStatus;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'DRAFT', label: 'Drafts' },
  { key: 'ISSUED', label: 'Issued' },
  { key: 'ACKNOWLEDGED', label: 'Acknowledged' },
];

export default function DeliveryChallanList() {
  const navigate = useNavigate();
  const dcsQuery = useDeliveryChallans();
  const partiesQuery = useParties();
  const [filter, setFilter] = useState<FilterKey>('all');
  const [query, setQuery] = useState('');

  const partyName = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of partiesQuery.data ?? []) map.set(p.party_id, p.name);
    return map;
  }, [partiesQuery.data]);

  const allRows = useMemo(() => dcsQuery.data ?? [], [dcsQuery.data]);
  const rows = useMemo(() => {
    return allRows.filter((dc) => {
      if (filter !== 'all' && dc.status !== filter) return false;
      if (query) {
        const q = query.toLowerCase();
        const name = partyName.get(dc.party_id) ?? '';
        return dc.display_number.toLowerCase().includes(q) || name.toLowerCase().includes(q);
      }
      return true;
    });
  }, [allRows, filter, query, partyName]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>
          Delivery challans
        </h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {dcsQuery.isPending ? '—' : `${rows.length} of ${allRows.length}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button onClick={() => navigate('/sales/delivery-challans/new')}>
            <Plus />
            New DC
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
            name="dc-search"
            aria-label="Search delivery challans"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search DC # or party"
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
        {dcsQuery.isError ? (
          <QueryError error={dcsQuery.error} onRetry={() => dcsQuery.refetch()} />
        ) : dcsQuery.isPending ? (
          <ListSkeleton rows={6} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Truck}
            title={
              query
                ? `No DCs match "${query}"`
                : filter === 'all'
                  ? 'No delivery challans yet'
                  : 'No DCs in this filter'
            }
            body={
              query || filter !== 'all'
                ? 'Try clearing the filter, or create one.'
                : 'A challan tracks a dispatch. Build one against a confirmed SO or stand-alone.'
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
                : { label: 'New DC', onClick: () => navigate('/sales/delivery-challans/new') }
            }
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 760 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>DC #</Th>
                <Th>Date</Th>
                <Th>Party</Th>
                <Th>Status</Th>
                <Th align="right">Qty</Th>
                <Th>Linked SO</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((dc) => {
                const pill = STATUS_PILL[dc.status] ?? STATUS_PILL.DRAFT;
                return (
                  <tr
                    key={dc.delivery_challan_id}
                    style={{ borderTop: '1px solid var(--border-subtle)' }}
                  >
                    <Td>
                      <Link
                        to={`/sales/delivery-challans/${dc.delivery_challan_id}`}
                        className="mono"
                        style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--accent)' }}
                      >
                        {dc.display_number}
                      </Link>
                    </Td>
                    <Td>
                      <span className="num" style={{ fontSize: 13 }}>
                        {formatDateShort(dc.dispatch_date)}
                      </span>
                    </Td>
                    <Td>
                      <span style={{ fontSize: 13.5, fontWeight: 500 }}>
                        {partyName.get(dc.party_id) ?? '—'}
                      </span>
                    </Td>
                    <Td>
                      <Pill kind={pill.kind}>{pill.label}</Pill>
                    </Td>
                    <Td align="right">
                      <span className="num" style={{ fontSize: 13.5 }}>
                        {dc.total_qty}
                      </span>
                    </Td>
                    <Td>
                      <span
                        className="mono"
                        style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
                      >
                        {dc.sales_order_id ? 'linked' : '—'}
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
    <div role="status" aria-label="Loading delivery challans" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={88} height={14} />
          <Skeleton width={56} height={14} />
          <Skeleton width="32%" height={14} />
          <Skeleton width={72} height={20} radius={10} />
          <div className="flex-1" />
          <Skeleton width={50} height={14} />
        </div>
      ))}
    </div>
  );
}
