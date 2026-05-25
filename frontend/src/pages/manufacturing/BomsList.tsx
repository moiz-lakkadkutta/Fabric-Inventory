/*
 * BomsList — TASK-TR-E1-BOMS.
 *
 * Live list of /boms grouped by design. Each design header is followed
 * by its version rows; the active version carries an "Active" pill and
 * full opacity, superseded versions render at reduced opacity.
 *
 * Pattern: copy of `PartyList.tsx` chrome (header, filter chips, 280px
 * search, table card) with a grouped-tbody for the design → versions
 * relationship. Filters: All / Active only / By design (popover-ish
 * select). The "+ New BOM" CTA routes to `/manufacturing/boms/new`.
 *
 * BE shape: `BomResponse` carries `design_id` but no design name or
 * finished item name. We resolve them client-side via `useDesigns()`
 * and `useItems()`. The cost per unit lives nowhere on the wire today
 * (the BE doesn't roll up line costs), so the column displays "—"
 * until a follow-up adds a per-BOM cost endpoint. Lines count comes
 * straight from `bom.lines.length`.
 */

import { ListChecks, Plus, Search } from 'lucide-react';
import * as React from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pill } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateShort } from '@/lib/format';
import { useBoms, useDesigns, type BackendBomResponse } from '@/lib/queries/manufacturing';
import { useItems } from '@/lib/queries/items';

type FilterKey = 'all' | 'active' | 'design';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active only' },
  { key: 'design', label: 'By design' },
];

interface DesignGroup {
  design_id: string;
  design_name: string;
  design_code: string;
  versions: BackendBomResponse[];
}

export default function BomsList() {
  const [filter, setFilter] = React.useState<FilterKey>('all');
  const [designId, setDesignId] = React.useState<string>('');
  const [query, setQuery] = React.useState<string>('');
  const navigate = useNavigate();

  // include_inactive defaults to true so the list shows the full version
  // history. The "Active only" chip drops to active_only=true.
  const bomsQuery = useBoms({
    active_only: filter === 'active' ? true : undefined,
    design_id: filter === 'design' && designId ? designId : undefined,
  });
  const designsQuery = useDesigns();
  const itemsQuery = useItems();

  const designsById = React.useMemo(() => {
    const m = new Map<string, { name: string; code: string }>();
    for (const d of designsQuery.data ?? []) {
      m.set(d.design_id, { name: d.name, code: d.code });
    }
    return m;
  }, [designsQuery.data]);

  const itemsById = React.useMemo(() => {
    const m = new Map<string, { name: string; code: string }>();
    for (const it of itemsQuery.data ?? []) {
      m.set(it.item_id, { name: it.name, code: it.code });
    }
    return m;
  }, [itemsQuery.data]);

  const allBoms = React.useMemo(() => bomsQuery.data ?? [], [bomsQuery.data]);

  const filtered = React.useMemo(() => {
    if (!query) return allBoms;
    const q = query.toLowerCase();
    return allBoms.filter((b) => {
      const dInfo = designsById.get(b.design_id);
      const iInfo = itemsById.get(b.finished_item_id);
      return (
        dInfo?.name.toLowerCase().includes(q) ||
        dInfo?.code.toLowerCase().includes(q) ||
        iInfo?.name.toLowerCase().includes(q) ||
        iInfo?.code.toLowerCase().includes(q) ||
        b.bom_id.toLowerCase().includes(q)
      );
    });
  }, [allBoms, query, designsById, itemsById]);

  const grouped: DesignGroup[] = React.useMemo(() => {
    const map = new Map<string, DesignGroup>();
    // Sort with active versions first within each design, then by
    // version_number desc so the newest non-active sits just below the
    // active row.
    const sorted = [...filtered].sort((a, b) => {
      if (a.design_id !== b.design_id) return 0;
      if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
      return b.version_number - a.version_number;
    });
    for (const bom of sorted) {
      let g = map.get(bom.design_id);
      if (!g) {
        const info = designsById.get(bom.design_id);
        g = {
          design_id: bom.design_id,
          design_name: info?.name ?? '—',
          design_code: info?.code ?? '—',
          versions: [],
        };
        map.set(bom.design_id, g);
      }
      g.versions.push(bom);
    }
    // Sort design groups by design code A-Z so the list is stable
    // across refetches.
    return Array.from(map.values()).sort((a, b) => a.design_code.localeCompare(b.design_code));
  }, [filtered, designsById]);

  const activeCount = allBoms.filter((b) => b.is_active).length;
  const designCount = new Set(allBoms.map((b) => b.design_id)).size;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>
          Bills of materials
        </h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {bomsQuery.isPending
            ? '—'
            : `${allBoms.length} BOMs across ${designCount} design${designCount === 1 ? '' : 's'} · ${activeCount} active`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button onClick={() => navigate('/manufacturing/boms/new')}>
            <Plus />
            New BOM
          </Button>
        </div>
      </header>

      {/* Filters + search */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter BOMs">
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
          {filter === 'design' && (
            <select
              aria-label="Filter by design"
              value={designId}
              onChange={(e) => setDesignId(e.target.value)}
              className="h-8 rounded-md px-2"
              style={{
                fontSize: 12.5,
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-default)',
              }}
            >
              <option value="">— pick a design —</option>
              {(designsQuery.data ?? []).map((d) => (
                <option key={d.design_id} value={d.design_id}>
                  {d.code} — {d.name}
                </option>
              ))}
            </select>
          )}
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
            name="bom-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by design code, name, item…"
            aria-label="Search BOMs"
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
        {bomsQuery.isError ? (
          <QueryError error={bomsQuery.error} onRetry={() => bomsQuery.refetch()} />
        ) : bomsQuery.isPending ? (
          <ListSkeleton rows={6} />
        ) : grouped.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title={
              query
                ? `No BOMs match "${query}"`
                : filter === 'active'
                  ? 'No active BOMs yet'
                  : 'Build your first bill of materials'
            }
            body={
              query || filter !== 'all'
                ? 'Try clearing the filter or searching by design code.'
                : 'A BOM is the recipe of raw materials per finished unit, versioned per design. Only the active version is consumed by Manufacturing Orders.'
            }
            cta={
              query || filter !== 'all'
                ? {
                    label: 'Clear filter',
                    onClick: () => {
                      setFilter('all');
                      setDesignId('');
                      setQuery('');
                    },
                  }
                : { label: 'New BOM', onClick: () => navigate('/manufacturing/boms/new') }
            }
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 820 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Design</Th>
                <Th width={100}>Version</Th>
                <Th align="right" width={80}>
                  Lines
                </Th>
                <Th align="right" width={140}>
                  Cost / unit
                </Th>
                <Th width={100}>Active</Th>
                <Th width={120}>Updated</Th>
              </tr>
            </thead>
            <tbody>
              {grouped.map((g) => (
                <React.Fragment key={g.design_id}>
                  <tr data-testid="bom-design-header" style={{ background: 'var(--bg-sunken)' }}>
                    <td
                      colSpan={6}
                      style={{
                        padding: '8px 14px',
                        borderBottom: '1px solid var(--border-default)',
                        borderTop: '1px solid var(--border-default)',
                      }}
                    >
                      <div className="flex items-center gap-2.5">
                        <span
                          className="mono"
                          style={{
                            fontSize: 11,
                            color: 'var(--accent)',
                            fontWeight: 700,
                          }}
                        >
                          {g.design_code}
                        </span>
                        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{g.design_name}</span>
                        <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                          · {g.versions.length} version{g.versions.length > 1 ? 's' : ''}
                        </span>
                      </div>
                    </td>
                  </tr>
                  {g.versions.map((bom) => (
                    <BomVersionRow
                      key={bom.bom_id}
                      bom={bom}
                      itemName={itemsById.get(bom.finished_item_id)?.name ?? '—'}
                    />
                  ))}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function BomVersionRow({ bom, itemName }: { bom: BackendBomResponse; itemName: string }) {
  return (
    <tr
      data-testid="bom-version-row"
      style={{
        opacity: bom.is_active ? 1 : 0.62,
        borderTop: '1px solid var(--border-subtle)',
      }}
    >
      <Td>
        <span style={{ paddingLeft: 16, fontSize: 13, fontWeight: bom.is_active ? 500 : 400 }}>
          {itemName}
        </span>
      </Td>
      <Td>
        <span
          className="mono"
          data-testid="version-chip"
          data-active={bom.is_active}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            height: 22,
            padding: '0 8px',
            background: bom.is_active ? 'var(--accent-subtle)' : 'var(--bg-sunken)',
            color: bom.is_active ? 'var(--accent)' : 'var(--text-secondary)',
            borderRadius: 4,
            fontSize: 11.5,
            fontWeight: 700,
            border: '1px solid ' + (bom.is_active ? 'transparent' : 'var(--border-subtle)'),
          }}
        >
          v{bom.version_number}
        </span>
      </Td>
      <Td align="right">
        <span className="num" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          {bom.lines.length}
        </span>
      </Td>
      <Td align="right">
        <span className="num" style={{ fontSize: 13, fontWeight: 500 }}>
          —
        </span>
      </Td>
      <Td>
        {bom.is_active ? <Pill kind="paid">Active</Pill> : <Pill kind="scrap">Superseded</Pill>}
      </Td>
      <Td>
        <span
          className="num"
          style={{ fontSize: 12.5, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}
        >
          {formatDateShort(bom.updated_at)}
        </span>
      </Td>
    </tr>
  );
}

function Th({
  children,
  align = 'left',
  width,
}: {
  children?: React.ReactNode;
  align?: 'left' | 'right';
  width?: number;
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
        width,
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
  children?: React.ReactNode;
  align?: 'left' | 'right';
}) {
  return (
    <td className="px-3 py-3" style={{ textAlign: align, verticalAlign: 'middle' }}>
      {children}
    </td>
  );
}

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div role="status" aria-label="Loading BOMs" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={160} height={14} />
          <Skeleton width={48} height={20} radius={4} />
          <div className="flex-1" />
          <Skeleton width={64} height={14} />
          <Skeleton width={120} height={14} />
          <Skeleton width={88} height={20} radius={10} />
          <Skeleton width={88} height={14} />
        </div>
      ))}
    </div>
  );
}

/* Link is imported for potential row-deep-links; keep the import live. */
void Link;
