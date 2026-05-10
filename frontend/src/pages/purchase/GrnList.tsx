import { Plus } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { useGrns } from '@/lib/queries/grn';

const STATUS_PILL: Record<string, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  ACKNOWLEDGED: { kind: 'finalized', label: 'Received' },
  IN_PROCESS: { kind: 'karigar', label: 'In process' },
  RETURNED: { kind: 'scrap', label: 'Returned' },
  CLOSED: { kind: 'paid', label: 'Closed' },
};

export default function GrnList() {
  const grns = useGrns();

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>GRNs</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {grns.isPending
            ? '—'
            : `${grns.data?.length ?? 0} GRN${(grns.data?.length ?? 0) === 1 ? '' : 's'}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button asChild>
            <Link to="/purchase/grns/new">
              <Plus />
              New GRN
            </Link>
          </Button>
        </div>
      </header>

      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        {grns.isPending ? (
          <ListSkeleton rows={6} />
        ) : (grns.data ?? []).length === 0 ? (
          <div
            className="px-4 py-10 text-center"
            style={{ color: 'var(--text-tertiary)', fontSize: 13 }}
          >
            No GRNs yet. Receive a confirmed PO to create one.
          </div>
        ) : (
          <table className="w-full text-left" style={{ minWidth: 720 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>GRN #</Th>
                <Th>Date</Th>
                <Th>PO</Th>
                <Th>Status</Th>
                <Th align="right">Total qty</Th>
              </tr>
            </thead>
            <tbody>
              {(grns.data ?? []).map((g) => {
                const pill = STATUS_PILL[g.status] ?? {
                  kind: 'draft' as PillKind,
                  label: g.status,
                };
                return (
                  <tr key={g.grn_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td className="px-3 py-3">
                      <Link
                        to={`/purchase/grns/${g.grn_id}`}
                        className="mono"
                        style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--accent)' }}
                      >
                        {g.number}
                      </Link>
                    </td>
                    <td
                      className="num px-3 py-3"
                      style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                    >
                      {g.grn_date}
                    </td>
                    <td className="px-3 py-3" style={{ fontSize: 12.5 }}>
                      {g.purchase_order_id ? (
                        <Link
                          to={`/purchase?po=${g.purchase_order_id}`}
                          style={{ color: 'var(--accent)' }}
                        >
                          source PO
                        </Link>
                      ) : (
                        <span style={{ color: 'var(--text-tertiary)' }}>—</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <Pill kind={pill.kind}>{pill.label}</Pill>
                    </td>
                    <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                      {g.total_qty_received ?? '—'}
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
    <div role="status" aria-label="Loading GRNs" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={88} height={14} />
          <Skeleton width={56} height={14} />
          <Skeleton width="22%" height={14} />
          <div className="flex-1" />
          <Skeleton width={90} height={14} />
        </div>
      ))}
    </div>
  );
}
