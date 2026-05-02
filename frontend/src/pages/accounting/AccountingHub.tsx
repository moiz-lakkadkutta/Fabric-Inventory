import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { useReceipts, useVouchers } from '@/lib/queries/accounts';
import { formatINRCompact } from '@/lib/mock';
import type { Receipt, ReceiptStatus, Voucher, VoucherKind } from '@/lib/mock/accounts';

type Tab = 'receipts' | 'vouchers';

const RECEIPT_PILL: Record<ReceiptStatus, { kind: PillKind; label: string }> = {
  POSTED: { kind: 'paid', label: 'Posted' },
  PENDING: { kind: 'due', label: 'Pending' },
  BOUNCED: { kind: 'overdue', label: 'Bounced' },
};

const VOUCHER_KIND_PILL: Record<VoucherKind, { kind: PillKind; label: string }> = {
  JOURNAL: { kind: 'finalized', label: 'Journal' },
  PAYMENT: { kind: 'karigar', label: 'Payment' },
  CONTRA: { kind: 'draft', label: 'Contra' },
  EXPENSE: { kind: 'overdue', label: 'Expense' },
};

export default function AccountingHub() {
  const [tab, setTab] = useState<Tab>('receipts');
  const receipts = useReceipts();
  const vouchers = useVouchers();
  const reconcile = useComingSoon({
    feature: 'Bank reconciliation',
    task: 'TASK-045 (Bank statement match)',
  });
  const newEntry = useComingSoon({
    feature: tab === 'receipts' ? 'New receipt' : 'New voucher',
    task: tab === 'receipts' ? 'TASK-042 (Receipt screen)' : 'TASK-044 (Voucher post)',
  });

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Accounts</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {receipts.isPending
            ? '—'
            : `${receipts.data?.length ?? 0} receipts · ${vouchers.data?.length ?? 0} vouchers`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" {...reconcile.triggerProps}>
            Reconcile bank
          </Button>
          <Button {...newEntry.triggerProps}>
            <Plus />
            New {tab === 'receipts' ? 'receipt' : 'voucher'}
          </Button>
        </div>
      </header>
      {reconcile.dialog}
      {newEntry.dialog}

      <div
        className="inline-flex items-center rounded-md p-1"
        style={{ background: 'var(--bg-sunken)' }}
        role="tablist"
      >
        <TabButton active={tab === 'receipts'} onClick={() => setTab('receipts')}>
          Receipts
        </TabButton>
        <TabButton active={tab === 'vouchers'} onClick={() => setTab('vouchers')}>
          Vouchers
        </TabButton>
      </div>

      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        {tab === 'receipts' ? (
          receipts.isPending ? (
            <ListSkeleton rows={8} label="Loading receipts" />
          ) : (
            <ReceiptTable rows={receipts.data ?? []} />
          )
        ) : vouchers.isPending ? (
          <ListSkeleton rows={6} label="Loading vouchers" />
        ) : (
          <VoucherTable rows={vouchers.data ?? []} />
        )}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className="inline-flex h-7 items-center rounded-[5px] px-3"
      style={{
        fontSize: 13,
        fontWeight: active ? 600 : 500,
        background: active ? 'var(--bg-surface)' : 'transparent',
        color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
        boxShadow: active ? 'var(--shadow-1)' : 'none',
      }}
    >
      {children}
    </button>
  );
}

function ReceiptTable({ rows }: { rows: Receipt[] }) {
  return (
    <table className="w-full text-left" style={{ minWidth: 980 }}>
      <thead style={{ background: 'var(--bg-sunken)' }}>
        <tr style={{ color: 'var(--text-tertiary)' }}>
          <Th>Receipt #</Th>
          <Th>Date</Th>
          <Th>Party</Th>
          <Th align="right">Amount</Th>
          <Th>Mode</Th>
          <Th>Reference</Th>
          <Th>Status</Th>
          <Th>Allocated</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const pill = RECEIPT_PILL[r.status];
          return (
            <tr key={r.receipt_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
              <td className="px-3 py-3">
                <span className="mono" style={{ fontSize: 12.5, fontWeight: 500 }}>
                  {r.number}
                </span>
              </td>
              <td
                className="num px-3 py-3"
                style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
              >
                {r.date}
              </td>
              <td className="px-3 py-3" style={{ fontSize: 13.5, fontWeight: 500 }}>
                {r.party_name}
              </td>
              <td className="num px-3 py-3" style={{ textAlign: 'right', fontWeight: 500 }}>
                {formatINRCompact(r.amount)}
              </td>
              <td className="px-3 py-3" style={{ fontSize: 12.5 }}>
                {r.mode.charAt(0) + r.mode.slice(1).toLowerCase()}
              </td>
              <td
                className="mono px-3 py-3"
                style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
              >
                {r.reference}
              </td>
              <td className="px-3 py-3">
                <Pill kind={pill.kind}>{pill.label}</Pill>
              </td>
              <td className="px-3 py-3" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                <span className="mono">{r.allocated_to.join(', ')}</span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function VoucherTable({ rows }: { rows: Voucher[] }) {
  return (
    <table className="w-full text-left" style={{ minWidth: 980 }}>
      <thead style={{ background: 'var(--bg-sunken)' }}>
        <tr style={{ color: 'var(--text-tertiary)' }}>
          <Th>Voucher #</Th>
          <Th>Date</Th>
          <Th>Kind</Th>
          <Th>Narration</Th>
          <Th align="right">Debit</Th>
          <Th align="right">Credit</Th>
          <Th>Balanced</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((v) => {
          const pill = VOUCHER_KIND_PILL[v.kind];
          return (
            <tr key={v.voucher_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
              <td className="px-3 py-3">
                <span className="mono" style={{ fontSize: 12.5, fontWeight: 500 }}>
                  {v.number}
                </span>
              </td>
              <td
                className="num px-3 py-3"
                style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
              >
                {v.date}
              </td>
              <td className="px-3 py-3">
                <Pill kind={pill.kind}>{pill.label}</Pill>
              </td>
              <td className="px-3 py-3" style={{ fontSize: 13 }}>
                {v.narration}
              </td>
              <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                {formatINRCompact(v.debit_total)}
              </td>
              <td className="num px-3 py-3" style={{ textAlign: 'right' }}>
                {formatINRCompact(v.credit_total)}
              </td>
              <td className="px-3 py-3">
                {v.balanced ? (
                  <span style={{ color: 'var(--success-text)', fontSize: 12.5, fontWeight: 500 }}>
                    ✓ Balanced
                  </span>
                ) : (
                  <span style={{ color: 'var(--danger)', fontSize: 12.5, fontWeight: 500 }}>
                    Unbalanced
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
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

function ListSkeleton({ rows, label }: { rows: number; label: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={88} height={14} />
          <Skeleton width={56} height={14} />
          <Skeleton width="28%" height={14} />
          <div className="flex-1" />
          <Skeleton width={100} height={14} />
        </div>
      ))}
    </div>
  );
}
