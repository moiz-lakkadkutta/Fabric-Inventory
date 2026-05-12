import { ArrowLeft } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useGrn, useReceiveGrn } from '@/lib/queries/grn';

const STATUS_PILL: Record<string, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  ACKNOWLEDGED: { kind: 'finalized', label: 'Received' },
  IN_PROCESS: { kind: 'karigar', label: 'In process' },
  RETURNED: { kind: 'scrap', label: 'Returned' },
  CLOSED: { kind: 'paid', label: 'Closed' },
};

export default function GrnDetail() {
  const { id } = useParams();
  const grn = useGrn(id);
  const receive = useReceiveGrn();
  const idem = useIdempotencyKey();

  if (grn.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width={220} height={24} />
        <Skeleton width="100%" height={140} />
      </div>
    );
  }

  if (grn.error instanceof ApiError && grn.error.code === 'NOT_FOUND') {
    return <p>GRN not found.</p>;
  }
  if (grn.error) {
    return (
      <p role="alert" style={{ color: 'var(--danger)' }}>
        Could not load GRN: {(grn.error as Error).message}
      </p>
    );
  }
  if (!grn.data) return null;

  const g = grn.data;
  const pill = STATUS_PILL[g.status] ?? { kind: 'draft' as PillKind, label: g.status };

  const handleReceive = async () => {
    if (!id) return;
    try {
      await receive.mutateAsync({ grnId: id, idempotencyKey: idem.key });
      idem.reset();
    } catch {
      // The error surfaces via `receive.error`. Keep the UI inline.
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/purchase/grns"
          aria-label="Back to GRNs"
          className="inline-flex h-8 items-center gap-1 rounded-md px-2"
          style={{ color: 'var(--text-secondary)', fontSize: 13 }}
        >
          <ArrowLeft size={14} />
          GRNs
        </Link>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>{g.number}</h1>
        <Pill kind={pill.kind}>{pill.label}</Pill>
        <div className="ml-auto flex items-center gap-2">
          {g.status === 'DRAFT' && (
            <Button onClick={handleReceive} disabled={receive.isPending}>
              {receive.isPending ? 'Receiving…' : 'Receive (post stock)'}
            </Button>
          )}
        </div>
      </header>

      <div
        className="grid grid-cols-2 gap-4 p-4 md:grid-cols-4"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <Stat label="Date" value={g.grn_date} />
        <Stat
          label="Source PO"
          value={
            g.purchase_order_id ? (
              <Link
                to={`/purchase?po=${g.purchase_order_id}`}
                aria-label="Source PO"
                style={{ color: 'var(--accent)' }}
              >
                source PO
              </Link>
            ) : (
              '—'
            )
          }
        />
        <Stat label="Total qty" value={g.total_qty_received ?? '—'} />
        <Stat label="Total amount (₹)" value={g.total_amount ?? '—'} />
      </div>

      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <table className="w-full text-left" style={{ minWidth: 600 }}>
          <thead style={{ background: 'var(--bg-sunken)' }}>
            <tr style={{ color: 'var(--text-tertiary)' }}>
              <Th>#</Th>
              <Th>Item</Th>
              <Th align="right">Qty received</Th>
              <Th align="right">Rate</Th>
              <Th>Lot #</Th>
            </tr>
          </thead>
          <tbody>
            {g.lines.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-3 py-6 text-center"
                  style={{ color: 'var(--text-tertiary)', fontSize: 13 }}
                >
                  No lines on this GRN.
                </td>
              </tr>
            ) : (
              g.lines.map((line) => (
                <tr key={line.grn_line_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td
                    className="num px-3 py-3"
                    style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
                  >
                    {line.line_sequence}
                  </td>
                  <td className="px-3 py-3">
                    {line.item_name ? (
                      <span style={{ fontSize: 13 }}>{line.item_name}</span>
                    ) : (
                      <span
                        className="mono"
                        style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
                      >
                        {line.item_id.slice(0, 8)}…
                      </span>
                    )}
                  </td>
                  <td className="num px-3 py-3" style={{ textAlign: 'right', fontSize: 13 }}>
                    {line.qty_received}
                  </td>
                  <td
                    className="num px-3 py-3"
                    style={{ textAlign: 'right', fontSize: 13, color: 'var(--text-secondary)' }}
                  >
                    {line.rate ?? '—'}
                  </td>
                  <td
                    className="px-3 py-3"
                    style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                  >
                    {line.lot_number ?? '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
          color: 'var(--text-tertiary)',
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 14, color: 'var(--text-primary)', marginTop: 2 }}>{value}</div>
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
