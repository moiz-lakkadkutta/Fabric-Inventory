/*
 * MoList — TASK-TR-A14-FU.
 *
 * Live list view of /manufacturing/mo with status filter chips. Drives
 * the new MO entry points exposed from the Manufacturing pipeline page.
 * The "+ New MO" button routes to a stub page; the actual creation form
 * lands in a separate task.
 *
 * Column shape comes from the OpenAPI snapshot's MoListItem — the BE
 * does not surface design name on the list shape, so we resolve it
 * client-side via useDesigns(). MoListItem has no cost_pool field
 * either; that's only on the completion preview, so the list shows the
 * status badge + planned/produced qty and the cost lands on detail.
 */

import { Factory, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill, type PillKind } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateShort } from '@/lib/format';
import { useDesigns, useMos, type BackendMoStatus } from '@/lib/queries/manufacturing';

type FilterKey = 'all' | BackendMoStatus;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'DRAFT', label: 'Draft' },
  { key: 'RELEASED', label: 'Released' },
  { key: 'IN_PROGRESS', label: 'In progress' },
  { key: 'COMPLETED', label: 'Completed' },
  { key: 'CLOSED', label: 'Closed' },
];

const STATUS_PILL: Record<BackendMoStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  RELEASED: { kind: 'finalized', label: 'Released' },
  IN_PROGRESS: { kind: 'karigar', label: 'In progress' },
  COMPLETED: { kind: 'paid', label: 'Completed' },
  CLOSED: { kind: 'scrap', label: 'Closed' },
};

export default function MoList() {
  const [filter, setFilter] = useState<FilterKey>('all');
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  // Push status filter down to the BE — the FE search box stays client
  // side (no `?q=` filter on the BE today; the list is small enough
  // that filter-on-client is fine for v1).
  const mosQuery = useMos(filter === 'all' ? {} : { status: filter });
  const designsQuery = useDesigns();

  const designNameById = useMemo(() => {
    const map = new Map<string, string>();
    (designsQuery.data ?? []).forEach((d) => map.set(d.design_id, d.name));
    return map;
  }, [designsQuery.data]);

  const allRows = useMemo(() => mosQuery.data ?? [], [mosQuery.data]);

  const rows = useMemo(() => {
    if (!query) return allRows;
    const q = query.toLowerCase();
    return allRows.filter((mo) => {
      const number = `${mo.series ? `${mo.series}/` : ''}${mo.number}`.toLowerCase();
      const designName = (designNameById.get(mo.design_id) ?? '').toLowerCase();
      return number.includes(q) || designName.includes(q);
    });
  }, [allRows, query, designNameById]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>
          Manufacturing orders
        </h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {mosQuery.isPending ? '—' : `${rows.length} of ${allRows.length}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="default" onClick={() => navigate('/manufacturing')}>
            Pipeline view
          </Button>
          <Button size="default" onClick={() => navigate('/manufacturing/mo/new')}>
            <Plus />
            New MO
          </Button>
        </div>
      </header>

      {/* Filters + search */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                aria-pressed={active}
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
            name="mo-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search MO # or design"
            aria-label="Search MO number or design"
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
        {mosQuery.isError ? (
          <QueryError error={mosQuery.error} onRetry={() => mosQuery.refetch()} />
        ) : mosQuery.isPending ? (
          <ListSkeleton rows={8} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Factory}
            title={
              query
                ? `No MOs match "${query}"`
                : filter === 'all'
                  ? 'No MOs yet.'
                  : 'No MOs in this filter'
            }
            body={
              query || filter !== 'all'
                ? 'Try clearing the filter or searching by design.'
                : 'Click New MO to create one.'
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
                : { label: 'New MO', onClick: () => navigate('/manufacturing/mo/new') }
            }
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 820 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>MO #</Th>
                <Th>Design</Th>
                <Th align="right">Planned</Th>
                <Th>Status</Th>
                <Th>MO date</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((mo) => {
                const pill = STATUS_PILL[mo.status];
                const moNumber = mo.series ? `${mo.series}/${mo.number}` : mo.number;
                const designName = designNameById.get(mo.design_id) ?? '—';
                return (
                  <tr
                    key={mo.manufacturing_order_id}
                    style={{ borderTop: '1px solid var(--border-subtle)' }}
                    className="hover:bg-(--bg-sunken)/40"
                  >
                    <Td>
                      <Link
                        to={`/manufacturing/mo/${mo.manufacturing_order_id}`}
                        className="mono"
                        style={{
                          fontSize: 12.5,
                          fontWeight: 500,
                          color: 'var(--accent)',
                        }}
                      >
                        {moNumber}
                      </Link>
                    </Td>
                    <Td>
                      <span
                        className="block max-w-[18rem] truncate"
                        style={{ fontSize: 13.5, fontWeight: 500 }}
                      >
                        {designName}
                      </span>
                    </Td>
                    <Td align="right">
                      <span className="num" style={{ fontSize: 13.5, fontWeight: 500 }}>
                        {formatDecimalShort(mo.planned_qty)}
                      </span>
                    </Td>
                    <Td>
                      <Pill kind={pill.kind}>{pill.label}</Pill>
                    </Td>
                    <Td>
                      <span className="num" style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                        {formatDateShort(mo.mo_date)}
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

/**
 * Drop trailing zeros from BE Decimal strings — "100.0000" → "100", "12.5000" → "12.5".
 * Keeps the column tidy for whole-number planned qtys while preserving precision
 * for fractional cases. Pure string work; never coerces to Number for arithmetic.
 */
function formatDecimalShort(s: string): string {
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

function Td({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <td className="px-3 py-3" style={{ textAlign: align, verticalAlign: 'middle' }}>
      {children}
    </td>
  );
}

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div
      role="status"
      aria-label="Loading manufacturing orders"
      className="flex flex-col gap-2 p-4"
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={120} height={14} />
          <Skeleton width="32%" height={14} />
          <div className="flex-1" />
          <Skeleton width={64} height={14} />
          <Skeleton width={88} height={20} radius={10} />
          <Skeleton width={56} height={14} />
        </div>
      ))}
    </div>
  );
}
