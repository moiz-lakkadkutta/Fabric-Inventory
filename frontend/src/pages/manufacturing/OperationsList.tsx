/*
 * OperationsList — TASK-TR-E1-OPERATIONS.
 *
 * Lists all operation masters with code-coloured `OpTypePill` per row,
 * filter chips (All / Active / Inactive + per-type popover), a 280px
 * search box, breadcrumb "Masters › Operations" and a "+ New operation"
 * CTA that opens the create dialog. Mirrors `PartyList.tsx` spacing /
 * filter pattern + the design spec at
 * docs/design/phase6/phase6-operations.jsx.
 *
 * All five list states (Full / Loading / Error / Empty / FilteredEmpty)
 * render through the same code path — choice is data-driven, no
 * separate state components.
 */

import { Cog, ListFilter, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { OpTypePill, type OperationType } from '@/components/manufacturing/OpTypePill';
import { useClickOutside } from '@/hooks/useClickOutside';
import { useOperationMasters } from '@/lib/queries/manufacturing';

import { NewOperationDialog } from './NewOperationDialog';

type ActiveFilter = 'all' | 'active' | 'inactive';

const ALL_TYPES: OperationType[] = [
  'WEAVING',
  'DYEING',
  'EMBROIDERY',
  'STITCHING',
  'QC',
  'PACKING',
  'OTHER',
];

const TYPE_LABEL: Record<OperationType, string> = {
  WEAVING: 'Weaving',
  DYEING: 'Dyeing',
  EMBROIDERY: 'Embroidery',
  STITCHING: 'Stitching',
  QC: 'QC',
  PACKING: 'Packing',
  OTHER: 'Other',
};

/**
 * Format the BE-returned default_duration_mins (decimal string) as a
 * compact "Nh Mm" / "N min" label. Returns em-dash when null.
 * Mirrors the design spec's `durFmt`.
 */
function formatDuration(raw: string | null | undefined): string {
  if (raw == null) return '—';
  const num = parseFloat(raw);
  if (!Number.isFinite(num)) return '—';
  const mins = Math.round(num);
  if (mins <= 0) return '—';
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export default function OperationsList() {
  // TASK-TR-E1: BE returns `is_active=true` by default; we ask for both
  // so the "Inactive" chip can filter client-side without a refetch.
  const opsQuery = useOperationMasters({ is_active: undefined });
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>('all');
  const [typeFilter, setTypeFilter] = useState<Set<OperationType>>(() => new Set());
  const [query, setQuery] = useState('');
  const [newOpen, setNewOpen] = useState(false);
  const [typePopoverOpen, setTypePopoverOpen] = useState(false);
  const typePopoverRef = useClickOutside<HTMLDivElement>(typePopoverOpen, () =>
    setTypePopoverOpen(false),
  );

  const rows = useMemo(() => {
    const all = opsQuery.data ?? [];
    return all.filter((op) => {
      if (activeFilter === 'active' && !op.is_active) return false;
      if (activeFilter === 'inactive' && op.is_active) return false;
      if (typeFilter.size > 0) {
        const t = (op.operation_type ?? 'OTHER') as OperationType;
        if (!typeFilter.has(t)) return false;
      }
      if (query) {
        const q = query.toLowerCase();
        const matches = op.code.toLowerCase().includes(q) || op.name.toLowerCase().includes(q);
        if (!matches) return false;
      }
      return true;
    });
  }, [opsQuery.data, activeFilter, typeFilter, query]);

  const totalLoaded = opsQuery.data?.length ?? 0;
  const hasActiveFilter = activeFilter !== 'all' || typeFilter.size > 0 || query.trim().length > 0;

  const toggleType = (t: OperationType) => {
    setTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  };

  const clearAllFilters = () => {
    setActiveFilter('all');
    setTypeFilter(new Set());
    setQuery('');
  };

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
        <span>Masters</span>
        <span style={{ padding: '0 6px' }} aria-hidden>
          ›
        </span>
        <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Operations</span>
      </nav>

      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Operations</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {opsQuery.isPending ? '—' : `${rows.length} of ${totalLoaded}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button onClick={() => setNewOpen(true)}>
            <Plus />
            New operation
          </Button>
        </div>
      </header>

      <NewOperationDialog open={newOpen} onClose={() => setNewOpen(false)} />

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by active status">
          {(
            [
              { key: 'all', label: 'All' },
              { key: 'active', label: 'Active' },
              { key: 'inactive', label: 'Inactive' },
            ] as { key: ActiveFilter; label: string }[]
          ).map((f) => {
            const active = activeFilter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setActiveFilter(f.key)}
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

          <div className="relative" ref={typePopoverRef}>
            <button
              type="button"
              onClick={() => setTypePopoverOpen((v) => !v)}
              aria-expanded={typePopoverOpen}
              aria-haspopup="dialog"
              className="inline-flex h-8 items-center gap-1.5 rounded-full px-3"
              style={{
                fontSize: 12.5,
                fontWeight: typeFilter.size > 0 ? 600 : 500,
                background: typeFilter.size > 0 ? 'var(--accent-subtle)' : 'transparent',
                color: typeFilter.size > 0 ? 'var(--accent)' : 'var(--text-secondary)',
                border:
                  typeFilter.size > 0
                    ? '1px solid var(--accent-subtle)'
                    : '1px solid var(--border-default)',
              }}
            >
              <ListFilter size={12} />
              {typeFilter.size > 0 ? `By type · ${typeFilter.size}` : 'By type'}
            </button>
            {typePopoverOpen && (
              <div
                role="dialog"
                aria-label="Filter by operation type"
                className="absolute z-30"
                style={{
                  top: 36,
                  left: 0,
                  width: 220,
                  background: 'var(--bg-elevated)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 8,
                  boxShadow: 'var(--shadow-3)',
                  padding: 8,
                }}
              >
                <div className="flex items-center justify-between px-2 py-1">
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: 'var(--text-tertiary)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                    }}
                  >
                    Operation type
                  </span>
                  {typeFilter.size > 0 && (
                    <button
                      type="button"
                      onClick={() => setTypeFilter(new Set())}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        cursor: 'pointer',
                        fontSize: 11,
                        color: 'var(--accent)',
                        padding: 0,
                      }}
                    >
                      Clear
                    </button>
                  )}
                </div>
                <div className="flex flex-col">
                  {ALL_TYPES.map((t) => {
                    const checked = typeFilter.has(t);
                    return (
                      <label
                        key={t}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-(--bg-sunken)"
                        style={{ fontSize: 12.5 }}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleType(t)}
                          aria-label={TYPE_LABEL[t]}
                        />
                        <OpTypePill type={t} />
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
        <div
          className="ml-auto inline-flex h-9 items-center gap-2 rounded-md px-3"
          style={{
            width: 280,
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
          }}
        >
          <Search size={14} color="var(--text-tertiary)" />
          <input
            type="search"
            name="operations-search"
            aria-label="Search operations"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by code, name"
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
        {opsQuery.isError ? (
          <QueryError error={opsQuery.error} onRetry={() => opsQuery.refetch()} />
        ) : opsQuery.isPending ? (
          <ListSkeleton rows={8} />
        ) : totalLoaded === 0 ? (
          <EmptyState
            icon={Cog}
            title="Define your manufacturing steps"
            body="Operations are reusable steps like Cutting, Aari embroidery, or Quality check. Wire them into a routing for each design — they decide the kanban columns lots move through."
            cta={{ label: 'New operation', onClick: () => setNewOpen(true) }}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Cog}
            title={query ? `No operations match "${query}"` : 'No operations match this filter'}
            body="Try a different type or clear the search to see everyone."
            cta={hasActiveFilter ? { label: 'Clear filter', onClick: clearAllFilters } : undefined}
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 820 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th>Operation type</Th>
                <Th align="right">Default duration</Th>
                <Th>Cost centre</Th>
                <Th>Active</Th>
                <Th>Updated</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((op) => (
                <tr
                  key={op.operation_master_id}
                  style={{
                    borderTop: '1px solid var(--border-subtle)',
                    opacity: op.is_active ? 1 : 0.55,
                  }}
                >
                  <Td>
                    <span
                      className="mono"
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: 'var(--accent)',
                      }}
                    >
                      {op.code}
                    </span>
                  </Td>
                  <Td>
                    <span style={{ fontSize: 13.5, fontWeight: 500 }}>{op.name}</span>
                  </Td>
                  <Td>
                    <OpTypePill type={(op.operation_type ?? 'OTHER') as OperationType} />
                  </Td>
                  <Td align="right">
                    <span className="num" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                      {formatDuration(op.default_duration_mins)}
                    </span>
                  </Td>
                  <Td>
                    <span
                      style={{
                        fontSize: 12.5,
                        color: op.cost_centre_id ? 'var(--text-secondary)' : 'var(--text-tertiary)',
                      }}
                    >
                      {op.cost_centre_id ? (
                        <span className="mono" style={{ fontSize: 11.5 }}>
                          {op.cost_centre_id.slice(0, 8)}…
                        </span>
                      ) : (
                        '—'
                      )}
                    </span>
                  </Td>
                  <Td>
                    {op.is_active ? (
                      <Pill kind="paid">Active</Pill>
                    ) : (
                      <Pill kind="scrap">Inactive</Pill>
                    )}
                  </Td>
                  <Td>
                    <span
                      className="num"
                      style={{
                        fontSize: 12.5,
                        color: 'var(--text-tertiary)',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {op.updated_at.slice(0, 10)}
                    </span>
                  </Td>
                </tr>
              ))}
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
    <div role="status" aria-label="Loading operations" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={110} height={14} />
          <Skeleton width="32%" height={14} />
          <Skeleton width={100} height={20} radius={10} />
          <div className="flex-1" />
          <Skeleton width={60} height={14} />
          <Skeleton width={70} height={20} radius={10} />
        </div>
      ))}
    </div>
  );
}
