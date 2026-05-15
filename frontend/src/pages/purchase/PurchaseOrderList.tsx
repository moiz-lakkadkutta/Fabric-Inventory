import { Plus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { formatINRCompact } from '@/lib/format';
import type { MatchStatus, PoStatus, PurchaseOrder } from '@/lib/mock/purchase';
import { useParties } from '@/lib/queries/parties';
import { usePurchaseOrders } from '@/lib/queries/purchase-orders';

const STATUS_PILL: Record<PoStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  OPEN: { kind: 'finalized', label: 'Open' },
  GRN_RECEIVED: { kind: 'karigar', label: 'GRN received' },
  INVOICED: { kind: 'paid', label: 'Invoiced' },
  CLOSED: { kind: 'paid', label: 'Closed' },
  CANCELLED: { kind: 'scrap', label: 'Cancelled' },
};

export default function PurchaseOrderList() {
  const navigate = useNavigate();
  const poQuery = usePurchaseOrders();
  // Resolve supplier names from the parties cache (the BE PO list doesn't
  // include supplier_name on the wire — use party_id + the parties list
  // to render the column).
  const partiesQuery = useParties();
  const supplierLookup = new Map<string, string>(
    (partiesQuery.data ?? []).map((p) => [p.party_id, p.name]),
  );

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Purchase</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {poQuery.isPending
            ? '—'
            : `${poQuery.data?.length ?? 0} POs · 3-way match status per row`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" onClick={() => navigate('/purchase/grns/new')}>
            Receive GRN
          </Button>
          <Button onClick={() => navigate('/purchase/new')}>
            <Plus />
            New PO
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
        {poQuery.isPending ? (
          <ListSkeleton rows={8} />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 920 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>PO #</Th>
                <Th>Date</Th>
                <Th>Supplier</Th>
                <Th align="right">Total</Th>
                <Th>Status</Th>
                <Th>3-way match</Th>
                <Th>Expected</Th>
              </tr>
            </thead>
            <tbody>
              {(poQuery.data ?? []).map((po) => (
                <PoRow
                  key={po.po_id}
                  po={po}
                  supplierName={po.supplier_name || supplierLookup.get(po.supplier_id) || '—'}
                  onClick={() => navigate(`/purchase/${po.po_id}`)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function PoRow({
  po,
  supplierName,
  onClick,
}: {
  po: PurchaseOrder;
  supplierName: string;
  onClick: () => void;
}) {
  const pill = STATUS_PILL[po.status];
  return (
    <tr
      style={{ borderTop: '1px solid var(--border-subtle)', cursor: 'pointer' }}
      onClick={onClick}
    >
      <td className="px-3 py-3">
        <span className="mono" style={{ fontSize: 12.5, fontWeight: 500 }}>
          {po.number}
        </span>
      </td>
      <td className="num px-3 py-3" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
        {po.date}
      </td>
      <td className="px-3 py-3" style={{ fontSize: 13.5, fontWeight: 500 }}>
        {supplierName}
      </td>
      <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
        {formatINRCompact(po.total)}
      </td>
      <td className="px-3 py-3">
        <Pill kind={pill.kind}>{pill.label}</Pill>
      </td>
      <td className="px-3 py-3">
        <ThreeWayMatch po={po.po_match} grn={po.grn_match} pi={po.pi_match} />
      </td>
      <td className="num px-3 py-3" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
        {po.expected_date}
      </td>
    </tr>
  );
}

function ThreeWayMatch({ po, grn, pi }: { po: MatchStatus; grn: MatchStatus; pi: MatchStatus }) {
  return (
    <div className="inline-flex items-center gap-1">
      <Tag label="PO" status={po} />
      <Connector />
      <Tag label="GRN" status={grn} />
      <Connector />
      <Tag label="PI" status={pi} />
    </div>
  );
}

function Tag({ label, status }: { label: string; status: MatchStatus }) {
  const color =
    status === 'matched'
      ? { bg: 'var(--success-subtle)', fg: 'var(--success-text)' }
      : status === 'mismatched'
        ? { bg: 'var(--danger-subtle)', fg: 'var(--danger-text)' }
        : { bg: 'var(--bg-sunken)', fg: 'var(--text-tertiary)' };
  return (
    <span
      className="inline-flex items-center"
      style={{
        height: 18,
        padding: '0 6px',
        borderRadius: 3,
        fontSize: 10.5,
        fontWeight: 600,
        letterSpacing: '0.04em',
        background: color.bg,
        color: color.fg,
      }}
    >
      {label}
    </span>
  );
}

function Connector() {
  return <span aria-hidden style={{ width: 8, height: 1, background: 'var(--border-default)' }} />;
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
    <div role="status" aria-label="Loading purchase orders" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={88} height={14} />
          <Skeleton width={56} height={14} />
          <Skeleton width="28%" height={14} />
          <div className="flex-1" />
          <Skeleton width={90} height={14} />
          <Skeleton width={120} height={14} />
        </div>
      ))}
    </div>
  );
}
