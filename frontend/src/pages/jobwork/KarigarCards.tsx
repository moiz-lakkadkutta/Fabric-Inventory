/*
 * KarigarCards (TASK-CUT-401)
 *
 * Per-karigar rollup tiles for the JobWorkOverview page.
 *
 * Reads two queries:
 *   - `useKarigars()`     — every party with `is_karigar=true`
 *   - the JWO list  — passed in via props so the parent can share one
 *     fetch between cards + active jobs table
 *
 * Pending qty per karigar = Σ(qty_sent) − Σ(qty_received) − Σ(qty_wastage)
 * across all of that karigar's JWO lines. Bucketed by uom so a karigar
 * handling both fabric (meters) and stitched (pieces) doesn't have
 * apples + oranges added.
 */

import { Monogram } from '@/components/ui/monogram';
import { Skeleton } from '@/components/ui/skeleton';
import {
  groupByKarigar,
  useKarigars,
  type JobWorkOrder,
  type KarigarRollup,
  type KarigarRow,
} from '@/lib/queries/jobwork';

interface KarigarCardsProps {
  orders: JobWorkOrder[] | undefined;
}

export function KarigarCards({ orders }: KarigarCardsProps) {
  const karigarsQuery = useKarigars();
  const karigars = karigarsQuery.data ?? [];

  if (karigarsQuery.isPending) {
    return <KarigarCardsSkeleton />;
  }

  if (karigars.length === 0) {
    return (
      <div className="px-4 py-6" style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
        No karigars on file yet. Add a karigar party from{' '}
        <a href="/masters/parties" style={{ color: 'var(--accent)', textDecoration: 'underline' }}>
          Masters → Parties
        </a>{' '}
        to start sending fabric out.
      </div>
    );
  }

  const rollupByKarigar = new Map<string, KarigarRollup>();
  for (const r of groupByKarigar(orders ?? [])) {
    rollupByKarigar.set(r.karigar_party_id, r);
  }

  return (
    <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
      {karigars.map((k) => (
        <KarigarCard
          key={k.party_id}
          karigar={k}
          rollup={rollupByKarigar.get(k.party_id) ?? null}
        />
      ))}
    </div>
  );
}

function KarigarCard({ karigar, rollup }: { karigar: KarigarRow; rollup: KarigarRollup | null }) {
  const initials = karigar.name
    .split(' ')
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('');
  const pendingEntries = rollup ? Object.entries(rollup.pending_by_uom) : [];
  return (
    <article
      data-testid="karigar-card"
      style={{
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        padding: 14,
        background: 'var(--bg-surface)',
      }}
    >
      <div className="flex items-start gap-3">
        <Monogram initials={initials} size={36} tone="accent" />
        <div className="min-w-0 flex-1">
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{karigar.name}</div>
          <div
            className="truncate"
            style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}
          >
            {karigar.code}
            {karigar.state_code ? ` · ${karigar.state_code}` : ''}
          </div>
        </div>
      </div>
      <div
        className="mt-3 grid grid-cols-2 gap-2 pt-3"
        style={{ borderTop: '1px solid var(--border-subtle)' }}
      >
        <SmallStat k="Open" v={String(rollup?.open_orders ?? 0)} />
        <SmallStat
          k="Pending"
          v={
            pendingEntries.length === 0
              ? '—'
              : pendingEntries.map(([uom, qty]) => `${formatQty(qty)} ${uom}`).join(' · ')
          }
        />
      </div>
    </article>
  );
}

function SmallStat({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div
        className="uppercase"
        style={{
          fontSize: 10,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
          fontWeight: 600,
        }}
      >
        {k}
      </div>
      <div
        className="num mt-0.5"
        style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}
      >
        {v}
      </div>
    </div>
  );
}

function formatQty(n: number): string {
  // Display two decimals if the value isn't a whole number; otherwise
  // an integer. Fabric quantities are typically 0.5m granular.
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
}

function KarigarCardsSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading karigars"
      className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 xl:grid-cols-4"
    >
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} width="100%" height={130} radius={8} />
      ))}
    </div>
  );
}
