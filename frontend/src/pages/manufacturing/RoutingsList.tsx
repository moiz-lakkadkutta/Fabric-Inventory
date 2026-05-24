/*
 * RoutingsList — TASK-TR-E1-ROUTINGS list view.
 *
 * Rows are grouped by design (design header row + version rows beneath)
 * to keep the "v1 / v2 / v3 of the same DAG" lineage visible.  The
 * BE list endpoint doesn't surface design name or operation labels, so
 * we resolve both client-side via useDesigns() + useOperationMasters().
 *
 * Operations preview = a compact "Cut → Embroidery → Stitch → QC →
 * Pack" trail built from the routing's edges (start nodes → end nodes,
 * topological order, falls back to the unique op list when branching).
 */

import { ChevronRight, Cog, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateShort } from '@/lib/format';
import {
  useDesigns,
  useOperationMasters,
  useRoutings,
  type BackendRoutingResponse,
} from '@/lib/queries/manufacturing';

type FilterKey = 'all' | 'active' | 'multi';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active only' },
  { key: 'multi', label: 'Multi-version designs' },
];

/**
 * Order a routing's operations into a linear preview. Walks from any
 * node with no incoming edges, following next-of map. If the graph
 * branches (>1 outgoing from any node) we return the unique op list
 * unsorted — good enough for a compact preview pill row.
 */
function orderRoutingOps(routing: BackendRoutingResponse): string[] {
  if (routing.edges.length === 0) return [];
  const allOps = new Set<string>();
  const incoming = new Map<string, number>();
  const next = new Map<string, string>();
  let branching = false;
  for (const e of routing.edges) {
    allOps.add(e.from_operation_id);
    allOps.add(e.to_operation_id);
    incoming.set(e.to_operation_id, (incoming.get(e.to_operation_id) ?? 0) + 1);
    if (next.has(e.from_operation_id)) branching = true;
    else next.set(e.from_operation_id, e.to_operation_id);
  }
  if (branching) return Array.from(allOps);
  const root = Array.from(allOps).find((op) => !incoming.has(op));
  if (!root) return Array.from(allOps);
  const ordered: string[] = [];
  let cur: string | undefined = root;
  const guard = new Set<string>();
  while (cur && !guard.has(cur)) {
    ordered.push(cur);
    guard.add(cur);
    cur = next.get(cur);
  }
  return ordered;
}

export default function RoutingsList() {
  const [filter, setFilter] = useState<FilterKey>('all');
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  const routingsQuery = useRoutings({ active_only: filter === 'active' });
  const designsQuery = useDesigns();
  const opMastersQuery = useOperationMasters();

  const designById = useMemo(() => {
    const m = new Map<string, { code: string; name: string }>();
    for (const d of designsQuery.data ?? []) {
      m.set(d.design_id, { code: d.code, name: d.name });
    }
    return m;
  }, [designsQuery.data]);

  const opNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const om of opMastersQuery.data ?? []) m.set(om.operation_master_id, om.name);
    return m;
  }, [opMastersQuery.data]);

  const allRows = useMemo(() => routingsQuery.data ?? [], [routingsQuery.data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allRows.filter((r) => {
      if (filter === 'multi') {
        const versions = allRows.filter((x) => x.design_id === r.design_id);
        if (versions.length <= 1) return false;
      }
      if (!q) return true;
      const design = designById.get(r.design_id);
      const designText = `${design?.code ?? ''} ${design?.name ?? ''}`.toLowerCase();
      const opsText = r.edges
        .flatMap((e) => [
          opNameById.get(e.from_operation_id) ?? '',
          opNameById.get(e.to_operation_id) ?? '',
        ])
        .join(' ')
        .toLowerCase();
      return r.code.toLowerCase().includes(q) || designText.includes(q) || opsText.includes(q);
    });
  }, [allRows, filter, query, designById, opNameById]);

  // Group by design (preserving the BE order — newest version first).
  const grouped = useMemo(() => {
    const map = new Map<string, BackendRoutingResponse[]>();
    for (const r of filtered) {
      if (!map.has(r.design_id)) map.set(r.design_id, []);
      map.get(r.design_id)?.push(r);
    }
    return Array.from(map.entries()).map(([designId, versions]) => ({
      designId,
      versions: [...versions].sort((a, b) => b.version_number - a.version_number),
    }));
  }, [filtered]);

  const activeCount = allRows.filter((r) => r.is_active).length;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Routings</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {routingsQuery.isPending
            ? '—'
            : `${filtered.length} of ${allRows.length} · ${activeCount} active`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button size="default" onClick={() => navigate('/manufacturing/routings/new')}>
            <Plus />
            New routing
          </Button>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter routings">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                aria-pressed={active}
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
            name="routing-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by design, operation…"
            aria-label="Search routings"
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
        {routingsQuery.isError ? (
          <QueryError error={routingsQuery.error} onRetry={() => routingsQuery.refetch()} />
        ) : routingsQuery.isPending ? (
          <ListSkeleton rows={6} />
        ) : grouped.length === 0 ? (
          allRows.length === 0 ? (
            <EmptyState
              icon={Cog}
              title="Wire your first routing"
              body="A routing is the DAG of operations that produces a design — Cut → Embroidery → Stitch → QC → Pack. MOs walk this graph to assign work in the pipeline kanban."
              cta={{
                label: 'New routing',
                onClick: () => navigate('/manufacturing/routings/new'),
              }}
            />
          ) : (
            <EmptyState
              icon={Cog}
              title={query ? `No routings match "${query}"` : 'No routings in this filter'}
              body="Try a different filter, or clear the search to see everyone."
              cta={{
                label: 'Clear filter',
                onClick: () => {
                  setFilter('all');
                  setQuery('');
                },
              }}
            />
          )
        ) : (
          <table className="w-full text-left" style={{ minWidth: 840 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Design / version</Th>
                <Th align="right">Nodes</Th>
                <Th>Operations sequence</Th>
                <Th>Status</Th>
                <Th>Updated</Th>
              </tr>
            </thead>
            <tbody>
              {grouped.map((group, gi) => {
                const design = designById.get(group.designId);
                return (
                  <RoutingGroup
                    key={group.designId}
                    design={design}
                    designId={group.designId}
                    versions={group.versions}
                    opNameById={opNameById}
                    isFirst={gi === 0}
                  />
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function RoutingGroup({
  design,
  designId,
  versions,
  opNameById,
  isFirst,
}: {
  design: { code: string; name: string } | undefined;
  designId: string;
  versions: BackendRoutingResponse[];
  opNameById: Map<string, string>;
  isFirst: boolean;
}) {
  return (
    <>
      <tr style={{ background: 'var(--bg-sunken)' }}>
        <td
          colSpan={5}
          style={{
            padding: '8px 14px',
            borderBottom: '1px solid var(--border-default)',
            borderTop: isFirst ? 'none' : '1px solid var(--border-default)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              className="mono"
              style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700 }}
            >
              {design?.code ?? designId.slice(0, 8)}
            </span>
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>{design?.name ?? '—'}</span>
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
              · {versions.length} version{versions.length > 1 ? 's' : ''}
            </span>
          </div>
        </td>
      </tr>
      {versions.map((r) => {
        const orderedOps = orderRoutingOps(r);
        const nodeCount = new Set(r.edges.flatMap((e) => [e.from_operation_id, e.to_operation_id]))
          .size;
        return (
          <tr
            key={r.routing_id}
            data-testid={`routing-row-${r.routing_id}`}
            style={{
              borderTop: '1px solid var(--border-subtle)',
              opacity: r.is_active ? 1 : 0.7,
            }}
          >
            <Td>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span
                  className="mono"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    height: 22,
                    padding: '0 8px',
                    background: r.is_active ? 'var(--accent-subtle)' : 'var(--bg-sunken)',
                    color: r.is_active ? 'var(--accent)' : 'var(--text-secondary)',
                    borderRadius: 4,
                    fontSize: 11.5,
                    fontWeight: 700,
                    border: r.is_active
                      ? '1px solid transparent'
                      : '1px solid var(--border-subtle)',
                  }}
                >
                  v{r.version_number}
                </span>
                <span style={{ fontSize: 13, fontWeight: 500 }}>{r.code}</span>
              </div>
            </Td>
            <Td align="right">
              <span className="num" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                {nodeCount}
              </span>
            </Td>
            <Td>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  flexWrap: 'wrap',
                }}
              >
                {orderedOps.length === 0 ? (
                  <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>—</span>
                ) : (
                  orderedOps.slice(0, 7).map((opId, j) => (
                    <span key={`${r.routing_id}-${j}`} style={{ display: 'inline-flex' }}>
                      <span
                        style={{
                          fontSize: 11,
                          padding: '2px 7px',
                          borderRadius: 3,
                          background: 'var(--bg-sunken)',
                          color: 'var(--text-secondary)',
                          border: '1px solid var(--border-subtle)',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {opNameById.get(opId) ?? '…'}
                      </span>
                      {j < orderedOps.length - 1 && j < 6 && (
                        <ChevronRight size={11} color="var(--text-tertiary)" />
                      )}
                    </span>
                  ))
                )}
                {orderedOps.length > 7 && (
                  <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                    +{orderedOps.length - 7}
                  </span>
                )}
              </div>
            </Td>
            <Td>
              {r.is_active ? <Pill kind="paid">Active</Pill> : <Pill kind="scrap">Superseded</Pill>}
            </Td>
            <Td>
              <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                {formatDateShort(r.updated_at)}
              </span>
            </Td>
          </tr>
        );
      })}
    </>
  );
}

function Th({
  children,
  align = 'left',
}: {
  children?: React.ReactNode;
  align?: 'left' | 'right';
}) {
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

function Td({
  children,
  align = 'left',
}: {
  children: React.ReactNode;
  align?: 'left' | 'right' | 'center';
}) {
  return (
    <td className="px-3 py-3" style={{ textAlign: align, verticalAlign: 'middle' }}>
      {children}
    </td>
  );
}

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div role="status" aria-label="Loading routings" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={50} height={20} radius={4} />
          <Skeleton width="32%" height={14} />
          <div className="flex-1" />
          <Skeleton width={64} height={14} />
          <Skeleton width={84} height={20} radius={10} />
          <Skeleton width={84} height={14} />
        </div>
      ))}
    </div>
  );
}

export const _internal = { orderRoutingOps };
