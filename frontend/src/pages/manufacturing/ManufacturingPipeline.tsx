import { Plus } from 'lucide-react';
import { useMemo } from 'react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useManufacturingOrders } from '@/lib/queries/manufacturing';
import { KANBAN_COLUMNS, type ManufacturingOrder, type MoStage } from '@/lib/mock/manufacturing';

export default function ManufacturingPipeline() {
  const moQuery = useManufacturingOrders();

  const grouped = useMemo(() => {
    const out = new Map<MoStage, ManufacturingOrder[]>();
    KANBAN_COLUMNS.forEach((c) => out.set(c.id, []));
    (moQuery.data ?? []).forEach((mo) => {
      out.get(mo.stage)?.push(mo);
    });
    return out;
  }, [moQuery.data]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Manufacturing</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {moQuery.isPending ? '—' : `${moQuery.data?.length ?? 0} active orders in pipeline`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline">View list</Button>
          <Button>
            <Plus />
            New MO
          </Button>
        </div>
      </header>

      {moQuery.isPending ? (
        <Skeleton width="100%" height={520} radius={8} />
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {KANBAN_COLUMNS.map((col) => {
            const items = grouped.get(col.id) ?? [];
            return (
              <section
                key={col.id}
                aria-label={col.label}
                className="flex flex-col"
                style={{
                  background: 'var(--bg-sunken)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 8,
                  minHeight: 480,
                }}
              >
                <header
                  className="flex items-center justify-between px-3 py-2.5"
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                >
                  <span
                    className="uppercase"
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      letterSpacing: '0.06em',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {col.label}
                  </span>
                  <span className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                    {items.length}
                  </span>
                </header>
                <div className="flex flex-1 flex-col gap-2 p-2">
                  {items.length === 0 ? (
                    <div
                      className="flex flex-1 items-center justify-center text-center"
                      style={{
                        fontSize: 11,
                        color: 'var(--text-tertiary)',
                        fontStyle: 'italic',
                        padding: 8,
                      }}
                    >
                      No orders here.
                    </div>
                  ) : (
                    items.map((mo) => <KanbanCard key={mo.mo_id} mo={mo} />)
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function KanbanCard({ mo }: { mo: ManufacturingOrder }) {
  const breach = mo.days_in_stage > mo.std_days_in_stage;
  return (
    <article
      style={{
        background: 'var(--bg-surface)',
        border: `1px solid ${breach ? 'var(--warning)' : 'var(--border-subtle)'}`,
        borderRadius: 8,
        padding: 10,
        boxShadow: 'var(--shadow-1)',
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <span
          className="mono"
          style={{ fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 500 }}
        >
          {mo.number}
        </span>
        {breach && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: 'var(--warning-text)',
              padding: '1px 5px',
              borderRadius: 3,
              background: 'var(--warning-subtle)',
            }}
          >
            +{mo.days_in_stage - mo.std_days_in_stage}d
          </span>
        )}
      </div>
      <div className="mt-1" style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.3 }}>
        {mo.product}
      </div>
      <div className="mt-1.5" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
        {mo.qty} {mo.uom.toLowerCase()} · {mo.customer}
      </div>
      <div className="mt-2.5">
        <div
          className="h-1.5 w-full overflow-hidden rounded-full"
          style={{ background: 'var(--bg-sunken)' }}
        >
          <div
            style={{
              width: `${mo.progress_pct}%`,
              height: '100%',
              background: breach ? 'var(--warning)' : 'var(--accent)',
            }}
          />
        </div>
        <div
          className="mt-1 flex justify-between"
          style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}
        >
          <span>{mo.progress_pct}%</span>
          <span>Due {mo.due_date}</span>
        </div>
      </div>
    </article>
  );
}
