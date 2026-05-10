/*
 * Sales Order detail page (TASK-CUT-203).
 *
 * Shows the SO header + lines, with Confirm + Cancel lifecycle buttons
 * that hit /sales-orders/{id}/confirm and /cancel respectively. The
 * pill updates as the BE returns the new status.
 */

import { ArrowLeft, Ban, Check, Truck } from 'lucide-react';
import * as React from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useItems } from '@/lib/queries/items';
import { useParties } from '@/lib/queries/parties';
import {
  useCancelSo,
  useConfirmSo,
  useSalesOrder,
  type SalesOrder,
} from '@/lib/queries/sales-orders';
import { formatDateShort, formatINRCompact } from '@/lib/format';
import type { components } from '@/types/api';

type SalesOrderStatus = components['schemas']['SalesOrderStatus'];

const STATUS_PILL: Record<SalesOrderStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  CONFIRMED: { kind: 'finalized', label: 'Confirmed' },
  PARTIAL_DC: { kind: 'due', label: 'Partial DC' },
  FULLY_DISPATCHED: { kind: 'paid', label: 'Dispatched' },
  INVOICED: { kind: 'paid', label: 'Invoiced' },
  CANCELLED: { kind: 'scrap', label: 'Cancelled' },
};

export default function SalesOrderDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const soQuery = useSalesOrder(id);
  const partiesQuery = useParties();
  const itemsQuery = useItems();
  const confirmSo = useConfirmSo();
  const cancelSo = useCancelSo();
  const confirmKey = useIdempotencyKey();
  const cancelKey = useIdempotencyKey();
  const [error, setError] = React.useState<string | null>(null);

  if (soQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width="40%" height={28} />
        <Skeleton width="100%" height={300} radius={8} />
      </div>
    );
  }

  const so = soQuery.data;
  if (!so) {
    return (
      <div className="p-8 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        Sales order not found.
      </div>
    );
  }

  const partyName = partiesQuery.data?.find((p) => p.party_id === so.party_id)?.name ?? '—';
  const itemNameMap = new Map(itemsQuery.data?.map((i) => [i.item_id, i] as const) ?? []);
  const pill = STATUS_PILL[so.status] ?? STATUS_PILL.DRAFT;

  const handleError = (e: unknown) => {
    if (e instanceof ApiError) {
      setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
    } else if (e instanceof Error) {
      setError(e.message);
    } else {
      setError('Lifecycle transition failed.');
    }
  };

  const onConfirm = async () => {
    setError(null);
    try {
      await confirmSo.mutateAsync({ soId: so.sales_order_id, idempotencyKey: confirmKey.key });
      confirmKey.reset();
    } catch (e) {
      confirmKey.reset();
      handleError(e);
    }
  };

  const onCancel = async () => {
    setError(null);
    try {
      await cancelSo.mutateAsync({ soId: so.sales_order_id, idempotencyKey: cancelKey.key });
      cancelKey.reset();
    } catch (e) {
      cancelKey.reset();
      handleError(e);
    }
  };

  const canConfirm = so.status === 'DRAFT';
  const canCancel = so.status === 'DRAFT' || so.status === 'CONFIRMED';
  // Build a DC against this SO once it's at-or-past CONFIRMED.
  const canBuildDc = so.status === 'CONFIRMED' || so.status === 'PARTIAL_DC';

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/sales/orders"
          aria-label="Back to sales orders"
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
          {so.display_number}
        </h1>
        <Pill kind={pill.kind}>{pill.label}</Pill>
        <div className="ml-auto flex items-center gap-2">
          {canBuildDc && (
            <Button
              variant="outline"
              onClick={() => navigate(`/sales/delivery-challans/new?so_id=${so.sales_order_id}`)}
            >
              <Truck size={14} />
              Build DC
            </Button>
          )}
          {canConfirm && (
            <Button onClick={onConfirm} disabled={confirmSo.isPending}>
              <Check size={14} />
              {confirmSo.isPending ? 'Confirming…' : 'Confirm'}
            </Button>
          )}
          {canCancel && (
            <Button variant="outline" onClick={onCancel} disabled={cancelSo.isPending}>
              <Ban size={14} />
              {cancelSo.isPending ? 'Cancelling…' : 'Cancel'}
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
            <Meta label="SO date" value={formatDateShort(so.so_date)} />
            <Meta
              label="Delivery date"
              value={so.delivery_date ? formatDateShort(so.delivery_date) : '—'}
            />
            <Meta label="Notes" value={so.notes ?? '—'} />
          </div>

          <table className="w-full text-left">
            <thead>
              <tr style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>
                <Th>Item</Th>
                <Th align="right">Qty</Th>
                <Th align="right">Dispatched</Th>
                <Th align="right">Rate</Th>
                <Th align="right">Amount</Th>
              </tr>
            </thead>
            <tbody>
              {so.lines.map((l, i) => {
                const item = itemNameMap.get(l.item_id);
                return (
                  <tr key={l.so_line_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td className="px-2 py-2.5" style={{ fontSize: 13.5, fontWeight: 500 }}>
                      {item?.name ?? `Line ${i + 1}`}
                    </td>
                    <td className="num px-2 py-2.5" style={{ textAlign: 'right' }}>
                      {l.qty_ordered} {item?.primary_uom ?? ''}
                    </td>
                    <td
                      className="num px-2 py-2.5"
                      style={{ textAlign: 'right', color: 'var(--text-secondary)' }}
                    >
                      {l.qty_dispatched}
                    </td>
                    <td className="num px-2 py-2.5" style={{ textAlign: 'right' }}>
                      {formatINRCompact(l.price)}
                    </td>
                    <td
                      className="num px-2 py-2.5"
                      style={{ textAlign: 'right', fontSize: 13.5, fontWeight: 500 }}
                    >
                      {formatINRCompact(l.line_amount)}
                    </td>
                  </tr>
                );
              })}
              {so.lines.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
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
          <Row label="Subtotal" value={formatINRCompact(so.total_amount)} big />
          <p
            style={{
              fontSize: 12,
              color: 'var(--text-tertiary)',
              marginTop: 4,
            }}
          >
            GST is computed on the invoice. SOs hold pre-tax line totals.
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

// Re-export the SO type (used by tests + sibling files for type narrowing).
export type { SalesOrder };
