/*
 * JobWorkOverview (TASK-CUT-401)
 *
 * Live job-work tracker. Replaces the Wave-design click-dummy with
 * GET /job-work-orders + the new SendOut / ReceiveBack dialogs.
 *
 * Layout:
 *   - Header with "+ Send out" CTA
 *   - KarigarCards (per-karigar rollup tiles)
 *   - Active jobs table (JWOs whose status is not CLOSED/CANCELLED) —
 *     each row has a "Receive back" affordance that opens the dialog
 *     pre-targeted at that JWO.
 */

import { Plus } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useJobWorkOrders,
  useKarigars,
  type JobWorkOrder,
  type JobWorkOrderStatus,
} from '@/lib/queries/jobwork';
import { useMe } from '@/store/auth';

import { KarigarCards } from './KarigarCards';
import { ReceiveBackDialog } from './ReceiveBackDialog';
import { SendOutDialog } from './SendOutDialog';

const STATUS_PILL: Record<JobWorkOrderStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  SENT: { kind: 'karigar', label: 'Sent' },
  PARTIAL_RECEIVED: { kind: 'due', label: 'Partial' },
  CLOSED: { kind: 'paid', label: 'Closed' },
  CANCELLED: { kind: 'overdue', label: 'Cancelled' },
};

export default function JobWorkOverview() {
  const me = useMe();
  const ordersQuery = useJobWorkOrders({ firmId: me?.firm_id ?? null });
  const karigarsQuery = useKarigars();

  const [sendOpen, setSendOpen] = React.useState(false);
  const [receiveTarget, setReceiveTarget] = React.useState<JobWorkOrder | null>(null);

  const orders = ordersQuery.data ?? [];
  const karigarCount = karigarsQuery.data?.length ?? 0;
  const openOrders = orders.filter((o) => o.status !== 'CLOSED' && o.status !== 'CANCELLED');
  const karigarNameById = new Map<string, string>(
    (karigarsQuery.data ?? []).map((k) => [k.party_id, k.name]),
  );

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Job work</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {ordersQuery.isPending || karigarsQuery.isPending
            ? '—'
            : `${karigarCount} karigars · ${openOrders.length} active jobs`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button onClick={() => setSendOpen(true)}>
            <Plus />
            Send out
          </Button>
        </div>
      </header>

      <SendOutDialog open={sendOpen} onClose={() => setSendOpen(false)} />
      <ReceiveBackDialog
        open={receiveTarget !== null}
        onClose={() => setReceiveTarget(null)}
        jwo={receiveTarget}
      />

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
        <KarigarCards orders={orders} />
      </section>

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
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Active jobs</h2>
        </header>
        <div className="overflow-x-auto">
          {ordersQuery.isPending ? (
            <Skeleton width="100%" height={240} />
          ) : openOrders.length === 0 ? (
            <div className="px-4 py-8" style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
              No active job-work orders. Click <strong>Send out</strong> above to dispatch fabric to
              a karigar.
            </div>
          ) : (
            <table className="w-full text-left" style={{ minWidth: 980 }}>
              <thead style={{ background: 'var(--bg-sunken)' }}>
                <tr style={{ color: 'var(--text-tertiary)' }}>
                  <Th>Challan #</Th>
                  <Th>Karigar</Th>
                  <Th>Operation</Th>
                  <Th align="right">Sent</Th>
                  <Th align="right">Received</Th>
                  <Th align="right">Wastage</Th>
                  <Th>Status</Th>
                  <Th align="right">Action</Th>
                </tr>
              </thead>
              <tbody>
                {openOrders.map((order) => {
                  const totals = sumOrderLines(order);
                  const pill = STATUS_PILL[order.status];
                  return (
                    <tr
                      key={order.job_work_order_id}
                      style={{ borderTop: '1px solid var(--border-subtle)' }}
                    >
                      <td className="px-3 py-3">
                        <span className="mono" style={{ fontSize: 12.5, fontWeight: 500 }}>
                          {order.number}
                        </span>
                      </td>
                      <td className="px-3 py-3" style={{ fontSize: 13, fontWeight: 500 }}>
                        {karigarNameById.get(order.karigar_party_id) ??
                          shortenId(order.karigar_party_id)}
                      </td>
                      <td
                        className="px-3 py-3"
                        style={{ fontSize: 13, color: 'var(--text-secondary)' }}
                      >
                        {order.operation ?? '—'}
                      </td>
                      <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                        {totals.sent} {totals.uom}
                      </td>
                      <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                        {totals.received} {totals.uom}
                      </td>
                      <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                        {totals.wastage} {totals.uom}
                      </td>
                      <td className="px-3 py-3">
                        <Pill kind={pill.kind}>{pill.label}</Pill>
                      </td>
                      <td className="px-3 py-3" style={{ textAlign: 'right' }}>
                        <Button variant="outline" onClick={() => setReceiveTarget(order)}>
                          Receive back
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </section>
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

function sumOrderLines(order: JobWorkOrder): {
  sent: string;
  received: string;
  wastage: string;
  uom: string;
} {
  let sent = 0;
  let received = 0;
  let wastage = 0;
  let uom = '';
  for (const line of order.lines ?? []) {
    sent += parseFloat(line.qty_sent ?? '0') || 0;
    received += parseFloat(line.qty_received ?? '0') || 0;
    wastage += parseFloat(line.qty_wastage ?? '0') || 0;
    // First non-empty UOM wins; if a JWO has mixed UOMs the BE would
    // have rejected it on send-out so this is safe.
    if (!uom && line.uom) uom = line.uom;
  }
  return {
    sent: formatQty(sent),
    received: formatQty(received),
    wastage: formatQty(wastage),
    uom,
  };
}

function formatQty(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
}

function shortenId(id: string): string {
  return id.slice(0, 8) + '…';
}
