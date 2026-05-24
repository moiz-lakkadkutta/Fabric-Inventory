/*
 * CostCentresList — TASK-TR-E1-COSTCENTRES.
 *
 * Master-data list for manufacturing cost centres. Lives under the
 * Manufacturing nav rather than Masters because the only consumers are
 * operation masters / MO rollups — the trial customer's textile flow
 * never references a CC from a sales / purchase document.
 *
 * Live-only: there is no click-dummy seed for cost centres in the FE
 * mocks today. When IS_LIVE is false the hook returns an empty array
 * and the UI renders the empty state, which is the right zero-config
 * affordance for design-mode demos.
 *
 * The list page surfaces 5 states (idle/loading/error/empty/filtered-empty)
 * and the breadcrumb reads "Masters › Cost centres" per the design spec.
 * The BE has no `description` column today; the column renders an em-dash
 * until the schema lands. Ops-linked count is also a future field (needs
 * a JOIN with operation_master) — for now we show "—" + a label that
 * makes the missing data legible.
 */

import { Plus, Search, Wallet } from 'lucide-react';
import { useMemo, useState } from 'react';
import { ChevronRight } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { useCostCentres, type BackendCostCentre } from '@/lib/queries/manufacturing';

import { NewCostCentreDialog } from './NewCostCentreDialog';

type FilterKey = 'all' | 'active' | 'inactive';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'inactive', label: 'Inactive' },
];

export default function CostCentresList() {
  const [filter, setFilter] = useState<FilterKey>('all');
  const [query, setQuery] = useState('');
  const [newOpen, setNewOpen] = useState(false);

  // Always fetch all rows (BE caps at 200; the trial customer has <20
  // cost centres). Filter on the client so chip counts stay accurate —
  // pushing `is_active` to the BE would hide the inactive-count badge.
  const ccQuery = useCostCentres({});

  const allRows = useMemo(() => ccQuery.data ?? [], [ccQuery.data]);

  const activeCount = useMemo(() => allRows.filter((cc) => cc.is_active).length, [allRows]);
  const inactiveCount = allRows.length - activeCount;

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allRows.filter((cc) => {
      if (filter === 'active' && !cc.is_active) return false;
      if (filter === 'inactive' && cc.is_active) return false;
      if (!q) return true;
      return cc.code.toLowerCase().includes(q) || cc.name.toLowerCase().includes(q);
    });
  }, [allRows, filter, query]);

  const filtered = filter !== 'all' || Boolean(query.trim());

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <nav
        aria-label="Breadcrumb"
        className="flex items-center gap-1.5"
        style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
      >
        <span>Masters</span>
        <ChevronRight size={12} aria-hidden />
        <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>Cost centres</span>
      </nav>

      {/* Header */}
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Cost centres</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {ccQuery.isPending
            ? '—'
            : `${allRows.length} cost ${allRows.length === 1 ? 'centre' : 'centres'} · ${activeCount} active`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button onClick={() => setNewOpen(true)} aria-label="New cost centre">
            <Plus />
            New cost centre
          </Button>
        </div>
      </header>

      <NewCostCentreDialog open={newOpen} onClose={() => setNewOpen(false)} />

      {/* Filter chips + search */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            const count =
              f.key === 'all' ? allRows.length : f.key === 'active' ? activeCount : inactiveCount;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                aria-pressed={active}
                className="inline-flex h-8 items-center gap-1.5 rounded-full px-3"
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
                <span>{f.label}</span>
                {!ccQuery.isPending && (
                  <span
                    className="num"
                    style={{
                      fontSize: 11,
                      color: active ? 'var(--accent)' : 'var(--text-tertiary)',
                    }}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div
          className="ml-auto inline-flex h-9 items-center gap-2 rounded-md px-3"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            width: 280,
          }}
        >
          <Search size={14} color="var(--text-tertiary)" />
          <input
            type="search"
            name="cost-centre-search"
            aria-label="Search cost centres"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by code, name…"
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
        {ccQuery.isError ? (
          <QueryError error={ccQuery.error} onRetry={() => ccQuery.refetch()} />
        ) : ccQuery.isPending ? (
          <ListSkeleton rows={6} />
        ) : allRows.length === 0 ? (
          <EmptyState
            icon={Wallet}
            title="Track where work happens"
            body={
              'A cost centre is a bucket like "In-house stitching" or "Karigar — Rashid Tailors". ' +
              'Operation masters point at them, and MOs roll labour costs up against each one.'
            }
            cta={{ label: 'New cost centre', onClick: () => setNewOpen(true) }}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Wallet}
            title={
              query
                ? `No cost centres match "${query}"`
                : `No ${filter === 'inactive' ? 'inactive' : 'active'} cost centres`
            }
            body="Try a different filter, or clear the search to see all cost centres."
            cta={
              filtered
                ? {
                    label: 'Clear filter',
                    onClick: () => {
                      setFilter('all');
                      setQuery('');
                    },
                  }
                : undefined
            }
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 820 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th>Description</Th>
                <Th align="right">Ops linked</Th>
                <Th>Status</Th>
                <Th>Updated</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((cc) => (
                <CostCentreRow key={cc.cost_centre_id} cc={cc} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function CostCentreRow({ cc }: { cc: BackendCostCentre }) {
  const active = cc.is_active !== false;
  return (
    <tr
      style={{
        borderTop: '1px solid var(--border-subtle)',
        opacity: active ? 1 : 0.6,
      }}
    >
      <Td>
        <span className="mono" style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>
          {cc.code}
        </span>
      </Td>
      <Td>
        <span style={{ fontSize: 13.5, fontWeight: 500 }}>{cc.name}</span>
      </Td>
      <Td>
        {/* The BE response has no `description` column today (see queries
            module comment). Render an em-dash placeholder so the column
            doesn't collapse — when the schema lands, we'll swap to a
            real value without changing the layout. */}
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>—</span>
      </Td>
      <Td align="right">
        <span className="num" style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          —
        </span>
      </Td>
      <Td>{active ? <Pill kind="paid">Active</Pill> : <Pill kind="scrap">Inactive</Pill>}</Td>
      <Td>
        <span
          className="num"
          style={{ fontSize: 12.5, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}
        >
          {formatDate(cc.updated_at)}
        </span>
      </Td>
    </tr>
  );
}

function formatDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
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
    <div role="status" aria-label="Loading cost centres" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={110} height={14} />
          <Skeleton width="22%" height={14} />
          <Skeleton width="34%" height={14} />
          <div className="flex-1" />
          <Skeleton width={36} height={14} />
          <Skeleton width={64} height={20} radius={10} />
          <Skeleton width={88} height={14} />
        </div>
      ))}
    </div>
  );
}
