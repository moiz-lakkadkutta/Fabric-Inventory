import { Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Monogram } from '@/components/ui/monogram';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { useJobs, useKarigars } from '@/lib/queries/jobwork';
import type { JobStatus } from '@/lib/mock/jobwork';

const JOB_PILL: Record<JobStatus, { kind: PillKind; label: string }> = {
  SENT: { kind: 'draft', label: 'Sent' },
  IN_PROGRESS: { kind: 'karigar', label: 'In progress' },
  PARTIAL_RETURN: { kind: 'due', label: 'Partial return' },
  COMPLETED: { kind: 'paid', label: 'Completed' },
  BREACHED: { kind: 'overdue', label: 'Breached' },
};

export default function JobWorkOverview() {
  const karigarsQuery = useKarigars();
  const jobsQuery = useJobs();
  const receive = useComingSoon({
    feature: 'Receive back from karigar',
    task: 'TASK-034 (Job receive-back)',
  });
  const send = useComingSoon({
    feature: 'Send out to karigar',
    task: 'TASK-032 (Job send-out)',
  });

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Job work</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {karigarsQuery.isPending
            ? '—'
            : `${karigarsQuery.data?.length ?? 0} karigars · ${jobsQuery.data?.length ?? 0} active jobs`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" {...receive.triggerProps}>
            Receive back
          </Button>
          <Button {...send.triggerProps}>
            <Plus />
            Send out
          </Button>
        </div>
      </header>
      {receive.dialog}
      {send.dialog}

      <section
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <header
          className="flex items-baseline gap-2 px-4"
          style={{
            paddingTop: 12,
            paddingBottom: 12,
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Karigars</h2>
        </header>
        {karigarsQuery.isPending ? (
          <CardGridSkeleton />
        ) : (
          <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
            {(karigarsQuery.data ?? []).map((k) => (
              <article
                key={k.karigar_id}
                style={{
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 8,
                  padding: 14,
                  background: 'var(--bg-surface)',
                }}
              >
                <div className="flex items-start gap-3">
                  <Monogram
                    initials={k.name
                      .split(' ')
                      .map((w) => w[0])
                      .slice(0, 2)
                      .join('')}
                    size={36}
                    tone="accent"
                  />
                  <div className="min-w-0 flex-1">
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>{k.name}</div>
                    <div
                      className="truncate"
                      style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}
                    >
                      {k.city} · {k.ops.join(' · ')}
                    </div>
                  </div>
                </div>
                <div
                  className="mt-3 grid grid-cols-3 gap-2 pt-3"
                  style={{ borderTop: '1px solid var(--border-subtle)' }}
                >
                  <SmallStat k="Active" v={k.active_qty} />
                  <SmallStat k="Open" v={`${k.open_orders}`} />
                  <SmallStat
                    k="On-time"
                    v={`${k.on_time_pct}%`}
                    color={k.on_time_pct >= 90 ? 'var(--success-text)' : 'var(--warning-text)'}
                  />
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <header
          className="flex items-baseline gap-2 px-4"
          style={{
            paddingTop: 12,
            paddingBottom: 12,
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Active jobs</h2>
        </header>
        {jobsQuery.isPending ? (
          <Skeleton width="100%" height={240} />
        ) : (
          <table className="w-full text-left">
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Job #</Th>
                <Th>Karigar</Th>
                <Th>Operation</Th>
                <Th align="right">Sent</Th>
                <Th align="right">Returned</Th>
                <Th>Due</Th>
                <Th>Status</Th>
                <Th align="right">Wastage</Th>
              </tr>
            </thead>
            <tbody>
              {(jobsQuery.data ?? []).map((j) => {
                const pill = JOB_PILL[j.status];
                return (
                  <tr key={j.job_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td className="px-3 py-3">
                      <span className="mono" style={{ fontSize: 12.5, fontWeight: 500 }}>
                        {j.number}
                      </span>
                    </td>
                    <td className="px-3 py-3" style={{ fontSize: 13, fontWeight: 500 }}>
                      {j.karigar_name}
                    </td>
                    <td
                      className="px-3 py-3"
                      style={{ fontSize: 13, color: 'var(--text-secondary)' }}
                    >
                      {j.op}
                    </td>
                    <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                      {j.sent_qty}
                    </td>
                    <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                      {j.returned_qty}
                    </td>
                    <td
                      className="num px-3 py-3"
                      style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}
                    >
                      {j.due_date}
                    </td>
                    <td className="px-3 py-3">
                      <Pill kind={pill.kind}>{pill.label}</Pill>
                    </td>
                    <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                      {j.wastage_pct !== undefined ? (
                        <span
                          style={{
                            color:
                              j.wastage_pct > 5
                                ? 'var(--danger)'
                                : j.wastage_pct > 0
                                  ? 'var(--warning-text)'
                                  : 'var(--text-tertiary)',
                            fontSize: 12.5,
                          }}
                        >
                          {j.wastage_pct}%
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-tertiary)' }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function SmallStat({ k, v, color }: { k: string; v: string; color?: string }) {
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
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: color ?? 'var(--text-primary)',
        }}
      >
        {v}
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

function CardGridSkeleton() {
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
