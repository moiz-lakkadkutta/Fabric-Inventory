/*
 * Delivery Challan detail page (TASK-CUT-203).
 *
 * Shows DC header + lines and surfaces the Issue button (DRAFT → ISSUED).
 * Issuing posts stock removal on the BE and advances the linked SO's
 * status — handled server-side; the FE just re-fetches.
 */

import { ArrowLeft, Send } from 'lucide-react';
import * as React from 'react';
import { Link, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useDc, useIssueDc } from '@/lib/queries/delivery-challans';
import { useItems } from '@/lib/queries/items';
import { useParties } from '@/lib/queries/parties';
import { formatDateShort, formatINRCompact } from '@/lib/format';
import type { components } from '@/types/api';

type DCStatus = components['schemas']['DCStatus'];

const STATUS_PILL: Record<DCStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  ISSUED: { kind: 'finalized', label: 'Issued' },
  ACKNOWLEDGED: { kind: 'paid', label: 'Acknowledged' },
  IN_PROCESS: { kind: 'karigar', label: 'In process' },
  RETURNED: { kind: 'due', label: 'Returned' },
  CLOSED: { kind: 'paid', label: 'Closed' },
};

export default function DeliveryChallanDetail() {
  const { id } = useParams<{ id: string }>();
  const dcQuery = useDc(id);
  const partiesQuery = useParties();
  const itemsQuery = useItems();
  const issueDc = useIssueDc();
  const issueKey = useIdempotencyKey();
  const [error, setError] = React.useState<string | null>(null);

  if (dcQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width="40%" height={28} />
        <Skeleton width="100%" height={300} radius={8} />
      </div>
    );
  }

  const dc = dcQuery.data;
  if (!dc) {
    return (
      <div className="p-8 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        Delivery challan not found.
      </div>
    );
  }

  const partyName = partiesQuery.data?.find((p) => p.party_id === dc.party_id)?.name ?? '—';
  const itemMap = new Map(itemsQuery.data?.map((i) => [i.item_id, i] as const) ?? []);
  const pill = STATUS_PILL[dc.status] ?? STATUS_PILL.DRAFT;

  const onIssue = async () => {
    setError(null);
    try {
      await issueDc.mutateAsync({ dcId: dc.delivery_challan_id, idempotencyKey: issueKey.key });
      issueKey.reset();
    } catch (e) {
      issueKey.reset();
      if (e instanceof ApiError) {
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not issue delivery challan.');
      }
    }
  };

  const canIssue = dc.status === 'DRAFT';

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/sales/delivery-challans"
          aria-label="Back to delivery challans"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <h1 className="mono" style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.012em' }}>
          {dc.display_number}
        </h1>
        <Pill kind={pill.kind}>{pill.label}</Pill>
        <div className="ml-auto flex items-center gap-2">
          {canIssue && (
            <Button onClick={onIssue} disabled={issueDc.isPending}>
              <Send size={14} />
              {issueDc.isPending ? 'Issuing…' : 'Issue'}
            </Button>
          )}
        </div>
      </header>

      {error && (
        <div
          role="alert"
          style={{
            padding: '8px 10px',
            border: '1px solid var(--danger)',
            borderRadius: 6,
            background: 'rgba(181,49,30,.06)',
            color: 'var(--danger)',
            fontSize: 12.5,
          }}
        >
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div
          className="space-y-4 p-4"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <Meta label="Customer" value={partyName} />
            <Meta label="Dispatch date" value={formatDateShort(dc.dispatch_date)} />
            <Meta label="Place of supply" value={dc.place_of_supply_state ?? '—'} />
            <Meta label="Linked SO" value={dc.sales_order_id ? 'Yes' : 'Free-form'} />
          </div>

          <table className="w-full text-left">
            <thead>
              <tr style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>
                <Th>Item</Th>
                <Th align="right">Qty</Th>
                <Th align="right">Rate</Th>
                <Th align="right">Amount</Th>
              </tr>
            </thead>
            <tbody>
              {dc.lines.map((l, i) => {
                const item = itemMap.get(l.item_id);
                const amount = (l.price ?? 0) * l.qty_dispatched;
                return (
                  <tr key={l.dc_line_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td className="px-2 py-2.5" style={{ fontSize: 13.5, fontWeight: 500 }}>
                      {item?.name ?? `Line ${i + 1}`}
                    </td>
                    <td className="num px-2 py-2.5" style={{ textAlign: 'right' }}>
                      {l.qty_dispatched} {item?.primary_uom ?? ''}
                    </td>
                    <td className="num px-2 py-2.5" style={{ textAlign: 'right' }}>
                      {l.price !== null ? formatINRCompact(l.price) : '—'}
                    </td>
                    <td
                      className="num px-2 py-2.5"
                      style={{ textAlign: 'right', fontSize: 13.5, fontWeight: 500 }}
                    >
                      {l.price !== null ? formatINRCompact(amount) : '—'}
                    </td>
                  </tr>
                );
              })}
              {dc.lines.length === 0 && (
                <tr>
                  <td
                    colSpan={4}
                    className="px-2 py-8 text-center"
                    style={{ color: 'var(--text-tertiary)', fontSize: 13 }}
                  >
                    No line items.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <aside
          className="space-y-3 p-4"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
            alignSelf: 'start',
          }}
        >
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Totals</h2>
          <Row label="Total qty" value={String(dc.total_qty)} />
          <Row label="Indicative amount" value={formatINRCompact(dc.total_amount)} big />
          <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>
            DC posts stock removal only. Tax flows on the invoice issued against this DC.
          </p>
        </aside>
      </div>
    </div>
  );
}

function Th({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      className="px-2 py-2"
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

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        className="uppercase"
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
          letterSpacing: '.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div className="mt-0.5" style={{ fontSize: 14, fontWeight: 500 }}>
        {value}
      </div>
    </div>
  );
}

function Row({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div className="flex items-baseline justify-between">
      <span
        style={{
          fontSize: big ? 13 : 12.5,
          color: big ? 'var(--text-primary)' : 'var(--text-secondary)',
          fontWeight: big ? 600 : 500,
        }}
      >
        {label}
      </span>
      <span className="num" style={{ fontSize: big ? 18 : 13, fontWeight: big ? 600 : 500 }}>
        {value}
      </span>
    </div>
  );
}
