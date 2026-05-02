import { Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { useSkus } from '@/lib/queries/inventory';
import { lots } from '@/lib/mock/inventory';
import { PHASE_COLOR, STAGE_META, type StageId } from '@/lib/mock/stages';

const ALL_STAGES: StageId[] = [
  'RAW',
  'CUT',
  'AT_EMBROIDERY',
  'QC_PENDING',
  'AT_STITCHING',
  'FINISHED',
  'PACKED',
];

export default function InventoryList() {
  const skusQuery = useSkus();
  const [query, setQuery] = useState('');
  const adjust = useComingSoon({
    feature: 'Adjust stock',
    task: 'TASK-024 (Inventory adjustments)',
  });
  const newGrn = useComingSoon({
    feature: 'New GRN intake',
    task: 'TASK-027 (GRN screen)',
  });

  const rows = useMemo(() => {
    const all = skusQuery.data ?? [];
    if (!query) return all;
    const q = query.toLowerCase();
    return all.filter((r) => r.code.toLowerCase().includes(q) || r.name.toLowerCase().includes(q));
  }, [skusQuery.data, query]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Inventory</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {skusQuery.isPending
            ? '—'
            : `${rows.length} SKUs · ${rows.reduce((s, r) => s + r.lots, 0)} active lots`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" {...adjust.triggerProps}>
            Adjust stock
          </Button>
          <Button {...newGrn.triggerProps}>
            <Plus />
            New GRN
          </Button>
        </div>
      </header>
      {adjust.dialog}
      {newGrn.dialog}

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
          name="sku-search"
          aria-label="Search SKUs"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search SKU code or name"
          className="flex-1 bg-transparent outline-none"
          style={{ fontSize: 13 }}
        />
      </div>

      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        {skusQuery.isPending ? (
          <ListSkeleton rows={8} />
        ) : (
          <table className="w-full text-left">
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th align="right">On hand</Th>
                <Th>Status mix</Th>
                <Th align="right">Lots</Th>
                <Th align="right">Reorder</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const sampleLot = lots.find((l) => l.sku_id === r.sku_id);
                return (
                  <tr key={r.sku_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td className="px-3 py-3">
                      <span
                        className="mono"
                        style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                      >
                        {r.code}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      {sampleLot ? (
                        <Link
                          to={`/inventory/lots/${sampleLot.lot_id}`}
                          style={{
                            fontSize: 13.5,
                            fontWeight: 500,
                            color: 'var(--accent)',
                          }}
                        >
                          {r.name}
                        </Link>
                      ) : (
                        <span style={{ fontSize: 13.5, fontWeight: 500 }}>{r.name}</span>
                      )}
                    </td>
                    <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                      <span style={{ fontSize: 13.5, fontWeight: 500 }}>
                        {r.on_hand.toLocaleString('en-IN')}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: 'var(--text-tertiary)',
                          marginLeft: 4,
                        }}
                      >
                        {r.uom.toLowerCase()}
                      </span>
                    </td>
                    <td className="px-3 py-3" style={{ width: 220 }}>
                      <StatusMixBar mix={r.mix} />
                    </td>
                    <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                      {r.lots}
                    </td>
                    <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                      <span
                        style={{
                          color: r.on_hand < r.reorder ? 'var(--danger)' : 'var(--text-tertiary)',
                          fontSize: 12.5,
                          fontWeight: r.on_hand < r.reorder ? 500 : 400,
                        }}
                      >
                        {r.reorder}
                      </span>
                    </td>
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

function StatusMixBar({ mix }: { mix: Partial<Record<StageId, number>> }) {
  const segments = ALL_STAGES.filter((id) => (mix[id] ?? 0) > 0).map((id) => ({
    id,
    pct: mix[id] ?? 0,
    color: PHASE_COLOR[STAGE_META[id].phase],
  }));
  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="flex h-2 w-full overflow-hidden rounded-full"
        style={{ background: 'var(--bg-sunken)' }}
        aria-label="Status mix"
      >
        {segments.map((seg) => (
          <span
            key={seg.id}
            title={`${STAGE_META[seg.id].label} ${seg.pct}%`}
            style={{
              width: `${seg.pct}%`,
              background: seg.color.fg,
              opacity: 0.85,
            }}
          />
        ))}
      </div>
      <div
        className="flex flex-wrap gap-x-2 gap-y-0.5"
        style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}
      >
        {segments.map((seg) => (
          <span key={seg.id} className="inline-flex items-center gap-1">
            <span
              aria-hidden
              style={{
                width: 6,
                height: 6,
                borderRadius: 999,
                background: seg.color.fg,
                display: 'inline-block',
              }}
            />
            {STAGE_META[seg.id].label} {seg.pct}%
          </span>
        ))}
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

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div role="status" aria-label="Loading inventory" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={88} height={14} />
          <Skeleton width="32%" height={14} />
          <div className="flex-1" />
          <Skeleton width={60} height={14} />
          <Skeleton width={140} height={14} />
        </div>
      ))}
    </div>
  );
}
