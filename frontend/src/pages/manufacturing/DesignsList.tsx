/*
 * DesignsList — TASK-TR-E1.
 *
 * Masters › Designs list page. Mirrors PartyList's structure (page
 * header, filter chips, search bar, table) and renders all five list
 * states the design spec calls out:
 *   - Full           — rows with one inactive rendered muted.
 *   - Loading        — skeleton rows.
 *   - Error          — QueryError banner + Retry.
 *   - Empty          — zero rows, CTA opens NewDesignDialog.
 *   - FilteredEmpty  — search returned nothing (distinct from true-empty).
 *
 * Breadcrumb shows the full Masters › Designs path; relying on the
 * page header rather than a separate breadcrumb chrome (matches the
 * existing PartyList convention — the layout shell handles top-bar
 * breadcrumbs).
 */

import { Palette, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateLong } from '@/lib/format';
import { useDesigns, type BackendDesignResponse } from '@/lib/queries/manufacturing';

import { NewDesignDialog } from './NewDesignDialog';

type FilterKey = 'all' | 'active' | 'inactive';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'inactive', label: 'Inactive' },
];

/**
 * A design is "active" when `deleted_at IS NULL`. The BE list endpoint
 * filters soft-deletes server-side by default, so to show inactive rows
 * we'd need a separate include flag the BE doesn't expose yet. For v1
 * the chip is reachable but the inactive bucket will be empty until the
 * BE grows an `include_inactive` query param. Keeping the chip visible
 * matches the design spec and is forward-compatible.
 */
function isActive(d: BackendDesignResponse): boolean {
  return d.deleted_at === null;
}

export default function DesignsList() {
  const designsQuery = useDesigns();
  const [filter, setFilter] = useState<FilterKey>('all');
  const [query, setQuery] = useState('');
  const [newOpen, setNewOpen] = useState(false);

  const all = useMemo(() => designsQuery.data ?? [], [designsQuery.data]);

  const filtered = useMemo(() => {
    return all.filter((d) => {
      if (filter === 'active' && !isActive(d)) return false;
      if (filter === 'inactive' && isActive(d)) return false;
      if (query) {
        const q = query.toLowerCase();
        return (
          d.name.toLowerCase().includes(q) ||
          d.code.toLowerCase().includes(q) ||
          (d.description?.toLowerCase().includes(q) ?? false)
        );
      }
      return true;
    });
  }, [all, filter, query]);

  const activeCount = all.filter(isActive).length;
  const inactiveCount = all.length - activeCount;
  const trueEmpty = !designsQuery.isPending && !designsQuery.isError && all.length === 0;
  const filteredEmpty =
    !designsQuery.isPending && !designsQuery.isError && all.length > 0 && filtered.length === 0;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <div className="flex flex-col">
          <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)', letterSpacing: '0.02em' }}>
            Masters &rsaquo; Designs
          </span>
          <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Designs</h1>
        </div>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {designsQuery.isPending
            ? '—'
            : `${filtered.length} of ${all.length} · ${activeCount} active`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button onClick={() => setNewOpen(true)} aria-label="Create a new design">
            <Plus />
            New design
          </Button>
        </div>
      </header>

      <NewDesignDialog open={newOpen} onClose={() => setNewOpen(false)} />

      {/* Filter chips + search bar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter designs">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            const count =
              f.key === 'all' ? all.length : f.key === 'active' ? activeCount : inactiveCount;
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
                {f.label}
                {!designsQuery.isPending && (
                  <span style={{ color: 'var(--text-tertiary)', fontWeight: 400 }}>{count}</span>
                )}
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
            name="design-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by code, name, description"
            aria-label="Search designs"
            className="flex-1 bg-transparent outline-none"
            style={{ fontSize: 13 }}
          />
        </div>
      </div>

      {/* Table / states */}
      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        {designsQuery.isError ? (
          <QueryError error={designsQuery.error} onRetry={() => designsQuery.refetch()} />
        ) : designsQuery.isPending ? (
          <ListSkeleton rows={8} />
        ) : trueEmpty ? (
          <EmptyState
            icon={Palette}
            title="Create your first design"
            body="A design is a finished product like Anarkali Pink or Sharara Gold. You'll attach a BOM and a Routing to each — the Manufacturing Order wizard pulls from this list."
            cta={{ label: 'New design', onClick: () => setNewOpen(true) }}
          />
        ) : filteredEmpty ? (
          <EmptyState
            icon={Palette}
            title={query ? `No designs match "${query}"` : 'No designs in this filter'}
            body="Try a different filter, or clear the search to see everyone."
            cta={{
              label: 'Clear filter',
              onClick: () => {
                setFilter('all');
                setQuery('');
              },
            }}
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 880 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th>Description</Th>
                <Th align="right">BOM v</Th>
                <Th align="right">Routing v</Th>
                <Th>Active</Th>
                <Th>Updated</Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((d) => (
                <DesignRow key={d.design_id} d={d} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function DesignRow({ d }: { d: BackendDesignResponse }) {
  const active = isActive(d);
  // The list endpoint doesn't surface BOM / routing version counts;
  // those live on the BOM/routing list endpoints and would balloon the
  // payload to N+1 lookups. Until the BE exposes counts on the design
  // shape (a 1-line aggregate), the columns render an em-dash placeholder
  // for now — preserves the spec's column lineup without faking numbers.
  const bomCount = '—';
  const rtgCount = '—';
  return (
    <tr
      style={{
        borderTop: '1px solid var(--border-subtle)',
        opacity: active ? 1 : 0.55,
      }}
    >
      <td className="px-3 py-3">
        <span className="mono" style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>
          {d.code}
        </span>
      </td>
      <td className="px-3 py-3" style={{ fontSize: 13.5, fontWeight: 500 }}>
        {d.name}
      </td>
      <td
        className="px-3 py-3 max-w-[28rem]"
        style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
      >
        <span className="block truncate">{d.description ?? '—'}</span>
      </td>
      <td
        className="num px-3 py-3"
        style={{ textAlign: 'right', fontSize: 13, color: 'var(--text-tertiary)' }}
      >
        {bomCount}
      </td>
      <td
        className="num px-3 py-3"
        style={{ textAlign: 'right', fontSize: 13, color: 'var(--text-tertiary)' }}
      >
        {rtgCount}
      </td>
      <td className="px-3 py-3">
        {active ? <Pill kind="paid">Active</Pill> : <Pill kind="scrap">Inactive</Pill>}
      </td>
      <td
        className="num px-3 py-3"
        style={{ fontSize: 12.5, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}
      >
        {formatDateLong(d.updated_at)}
      </td>
    </tr>
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

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div role="status" aria-label="Loading designs" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={90} height={14} />
          <Skeleton width="22%" height={14} />
          <Skeleton width="34%" height={14} />
          <div className="flex-1" />
          <Skeleton width={50} height={14} />
          <Skeleton width={64} height={20} radius={10} />
          <Skeleton width={80} height={14} />
        </div>
      ))}
    </div>
  );
}
