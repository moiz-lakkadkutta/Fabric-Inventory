import { useNavigate, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { ApiError } from '@/lib/api/client';
import { formatINR } from '@/lib/format';
import { useParty } from '@/lib/queries/parties';
import {
  canApprove,
  canCancel,
  canConfirm,
  useApprovePo,
  useCancelPo,
  useConfirmPo,
  usePurchaseOrder,
} from '@/lib/queries/purchase-orders';
import type { PoStatus } from '@/lib/mock/purchase';
import { useState } from 'react';

const STATUS_PILL: Record<PoStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  OPEN: { kind: 'finalized', label: 'Open' },
  GRN_RECEIVED: { kind: 'karigar', label: 'GRN received' },
  INVOICED: { kind: 'paid', label: 'Invoiced' },
  CLOSED: { kind: 'paid', label: 'Closed' },
  CANCELLED: { kind: 'scrap', label: 'Cancelled' },
};

export default function PurchaseOrderDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const poQuery = usePurchaseOrder(id);
  const supplierQuery = useParty(poQuery.data?.supplier_id);

  const approve = useApprovePo();
  const confirm = useConfirmPo();
  const cancel = useCancelPo();
  const approveIdem = useIdempotencyKey();
  const confirmIdem = useIdempotencyKey();
  const cancelIdem = useIdempotencyKey();

  const [error, setError] = useState<string | null>(null);

  if (poQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width={240} height={28} />
        <Skeleton width="100%" height={120} />
      </div>
    );
  }

  if (poQuery.isError) {
    return (
      <QueryError
        title="Couldn't load this purchase order"
        error={poQuery.error}
        onRetry={() => poQuery.refetch()}
      />
    );
  }

  const po = poQuery.data;
  if (!po) {
    return (
      <QueryError
        title="Purchase order not found"
        error={new Error('not_found')}
        onRetry={() => navigate('/purchase')}
      />
    );
  }

  const pill = STATUS_PILL[po.status];
  const supplierName = po.supplier_name || supplierQuery.data?.name || '—';

  const runLifecycle = async (label: string, fn: () => Promise<unknown>, reset: () => void) => {
    setError(null);
    try {
      await fn();
      reset();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`${label} failed — ${e.detail || e.title}`);
      } else if (e instanceof Error) {
        setError(`${label} failed — ${e.message}`);
      } else {
        setError(`${label} failed.`);
      }
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>{po.number}</h1>
        <Pill kind={pill.kind}>{pill.label}</Pill>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {po.date}
          {po.expected_date ? ` · expected ${po.expected_date}` : ''}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            disabled={!canApprove(po.status) || approve.isPending}
            onClick={() =>
              runLifecycle(
                'Approve',
                () => approve.mutateAsync({ poId: po.po_id, idempotencyKey: approveIdem.key }),
                approveIdem.reset,
              )
            }
          >
            {approve.isPending ? 'Approving…' : 'Approve'}
          </Button>
          <Button
            disabled={!canConfirm(po.status) || confirm.isPending}
            onClick={() =>
              runLifecycle(
                'Confirm',
                () => confirm.mutateAsync({ poId: po.po_id, idempotencyKey: confirmIdem.key }),
                confirmIdem.reset,
              )
            }
          >
            {confirm.isPending ? 'Confirming…' : 'Confirm'}
          </Button>
          <Button
            variant="outline"
            disabled={!canCancel(po.status) || cancel.isPending}
            onClick={() =>
              runLifecycle(
                'Cancel',
                () => cancel.mutateAsync({ poId: po.po_id, idempotencyKey: cancelIdem.key }),
                cancelIdem.reset,
              )
            }
          >
            {cancel.isPending ? 'Cancelling…' : 'Cancel PO'}
          </Button>
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

      <div
        className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <Field label="Supplier" value={supplierName} />
        <Field label="PO date" value={po.date} />
        <Field label="Expected" value={po.expected_date || '—'} />
      </div>

      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <table className="w-full text-left" style={{ minWidth: 720 }}>
          <thead style={{ background: 'var(--bg-sunken)' }}>
            <tr style={{ color: 'var(--text-tertiary)' }}>
              <Th>Item</Th>
              <Th align="right">Qty</Th>
              <Th align="right">Rate</Th>
              <Th align="right">Amount</Th>
            </tr>
          </thead>
          <tbody>
            {(po.lines ?? []).map((l, idx) => (
              <tr key={idx} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td className="mono px-3 py-3" style={{ fontSize: 12.5 }}>
                  {l.item_name || l.item_id.slice(0, 8)}
                </td>
                <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                  {l.qty}
                </td>
                <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                  {formatINR(l.rate)}
                </td>
                <td className="num px-3 py-3" style={{ textAlign: 'right', fontWeight: 500 }}>
                  {formatINR(l.amount)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr style={{ borderTop: '1px solid var(--border-default)' }}>
              <td colSpan={3} className="px-3 py-3" style={{ textAlign: 'right' }}>
                <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>Total</span>
              </td>
              <td
                className="num px-3 py-3"
                style={{ textAlign: 'right', fontWeight: 600, fontSize: 14 }}
              >
                {formatINR(po.total)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
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
      <div style={{ fontSize: 13.5, fontWeight: 500, marginTop: 2 }}>{value}</div>
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
