import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { downloadExport } from '@/lib/api/download';
import { IS_LIVE } from '@/lib/api/mode';
import {
  type BankAccountView,
  type ChequeView,
  useBankAccounts,
  useCheques,
  useReceipts,
  useVouchers,
} from '@/lib/queries/accounts';
import { formatINRCompact } from '@/lib/format';
import type {
  Receipt,
  ReceiptStatus,
  Voucher,
  VoucherKind,
  VoucherTypeRaw,
} from '@/lib/mock/accounts';

import { NewBankAccountDialog } from './NewBankAccountDialog';
import { NewChequeDialog } from './NewChequeDialog';
import { NewJournalVoucherDialog } from './NewJournalVoucherDialog';
import { NewReceiptDialog } from './NewReceiptDialog';

type Tab = 'receipts' | 'vouchers' | 'bank-accounts' | 'cheques';

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

// Display label per backend voucher_type — keeps the live Vouchers tab
// honest about whether a row is a RECEIPT vs PAYMENT etc., even though
// they collapse to the same `kind` palette today.
const VOUCHER_TYPE_LABEL: Record<VoucherTypeRaw, string> = {
  SALES_INVOICE: 'Sales invoice',
  PURCHASE_INVOICE: 'Purchase invoice',
  PAYMENT: 'Payment',
  RECEIPT: 'Receipt',
  JOURNAL: 'Journal',
  CONTRA: 'Contra',
  DEBIT_NOTE: 'Debit note',
  CREDIT_NOTE: 'Credit note',
  OPENING_BAL: 'Opening balance',
};

export default function AccountingHub() {
  const [tab, setTab] = useState<Tab>('receipts');
  const [receiptOpen, setReceiptOpen] = useState(false);
  const [voucherOpen, setVoucherOpen] = useState(false);
  const [bankAccountOpen, setBankAccountOpen] = useState(false);
  const [chequeOpen, setChequeOpen] = useState(false);
  const [selectedBankAccountId, setSelectedBankAccountId] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const receipts = useReceipts();
  const vouchers = useVouchers();
  const bankAccounts = useBankAccounts();
  // Cheques is keyed on the selected bank account; first account selected
  // by default once the list resolves.
  const effectiveBankAccountId =
    selectedBankAccountId ?? bankAccounts.data?.[0]?.bank_account_id ?? null;
  const cheques = useCheques(effectiveBankAccountId);

  const handleExport = async (format: 'csv' | 'xlsx') => {
    if (!IS_LIVE) {
      setExportError('Export is wired to the live backend (set VITE_API_MODE=live).');
      return;
    }
    // Map current tab → BE endpoint. Bank accounts + cheques learnt
    // `?format=` in TASK-CUT-501b; cheques is filtered per bank account
    // so we forward the selected account in the query string.
    let endpoint: string | null = null;
    if (tab === 'receipts') endpoint = '/receipts';
    else if (tab === 'vouchers') endpoint = '/vouchers';
    else if (tab === 'bank-accounts') endpoint = '/bank-accounts';
    else if (tab === 'cheques') {
      if (!effectiveBankAccountId) {
        setExportError('Pick a bank account first.');
        return;
      }
      endpoint = `/cheques?bank_account_id=${effectiveBankAccountId}`;
    }
    if (!endpoint) {
      setExportError('This tab is not exportable yet.');
      return;
    }
    setExportError(null);
    setIsExporting(true);
    try {
      await downloadExport({
        path: endpoint,
        format,
        fallbackFilename: `${tab}-${new Date().toISOString().slice(0, 10)}.${format}`,
      });
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Could not export.');
    } finally {
      setIsExporting(false);
    }
  };

  const reconcile = useComingSoon({
    feature: 'Bank reconciliation',
    task: 'TASK-CUT-v2 (Bank statement match)',
  });

  let cta: React.ReactNode = null;
  if (tab === 'receipts') {
    cta = (
      <Button onClick={() => setReceiptOpen(true)}>
        <Plus />
        New receipt
      </Button>
    );
  } else if (tab === 'vouchers') {
    cta = (
      <Button onClick={() => setVoucherOpen(true)}>
        <Plus />
        New voucher
      </Button>
    );
  } else if (tab === 'bank-accounts') {
    cta = (
      <Button onClick={() => setBankAccountOpen(true)}>
        <Plus />
        New bank account
      </Button>
    );
  } else if (tab === 'cheques') {
    cta = (
      <Button onClick={() => setChequeOpen(true)} disabled={!effectiveBankAccountId}>
        <Plus />
        New cheque
      </Button>
    );
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Accounts</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {receipts.isPending
            ? '—'
            : `${receipts.data?.length ?? 0} receipts · ${vouchers.data?.length ?? 0} vouchers · ${
                bankAccounts.data?.length ?? 0
              } bank accounts`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" {...reconcile.triggerProps}>
            Reconcile bank
          </Button>
          <Button
            variant="outline"
            onClick={() => handleExport('csv')}
            disabled={isExporting || (tab === 'cheques' && !effectiveBankAccountId)}
            aria-label={`Export ${tab} to CSV`}
          >
            {isExporting ? 'Exporting…' : 'Export CSV'}
          </Button>
          <Button
            variant="outline"
            onClick={() => handleExport('xlsx')}
            disabled={isExporting || (tab === 'cheques' && !effectiveBankAccountId)}
            aria-label={`Export ${tab} to Excel`}
          >
            Export Excel
          </Button>
          {cta}
        </div>
      </header>
      {reconcile.dialog}
      {exportError && (
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
          {exportError}
        </div>
      )}

      <NewReceiptDialog open={receiptOpen} onClose={() => setReceiptOpen(false)} />
      <NewJournalVoucherDialog open={voucherOpen} onClose={() => setVoucherOpen(false)} />
      <NewBankAccountDialog open={bankAccountOpen} onClose={() => setBankAccountOpen(false)} />
      <NewChequeDialog
        open={chequeOpen}
        onClose={() => setChequeOpen(false)}
        bankAccountId={effectiveBankAccountId}
      />

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
        <TabButton active={tab === 'bank-accounts'} onClick={() => setTab('bank-accounts')}>
          Bank accounts
        </TabButton>
        <TabButton active={tab === 'cheques'} onClick={() => setTab('cheques')}>
          Cheques
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
        {tab === 'receipts' &&
          (receipts.isPending ? (
            <ListSkeleton rows={8} label="Loading receipts" />
          ) : (
            <ReceiptTable rows={receipts.data ?? []} />
          ))}
        {tab === 'vouchers' &&
          (vouchers.isPending ? (
            <ListSkeleton rows={6} label="Loading vouchers" />
          ) : (
            <VoucherTable rows={vouchers.data ?? []} />
          ))}
        {tab === 'bank-accounts' &&
          (bankAccounts.isPending ? (
            <ListSkeleton rows={4} label="Loading bank accounts" />
          ) : (
            <BankAccountTable rows={bankAccounts.data ?? []} />
          ))}
        {tab === 'cheques' && (
          <ChequePanel
            bankAccounts={bankAccounts.data ?? []}
            selectedBankAccountId={effectiveBankAccountId}
            onSelectBankAccount={setSelectedBankAccountId}
            cheques={cheques.data ?? []}
            isPending={
              bankAccounts.isPending || (Boolean(effectiveBankAccountId) && cheques.isPending)
            }
          />
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
  if (rows.length === 0) {
    return <EmptyTable label="No receipts yet. Click + New receipt to record one." />;
  }
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
  if (rows.length === 0) {
    return (
      <EmptyTable label="No vouchers posted yet — receipts and other postings will appear here." />
    );
  }
  return (
    <table className="w-full text-left" style={{ minWidth: 980 }}>
      <thead style={{ background: 'var(--bg-sunken)' }}>
        <tr style={{ color: 'var(--text-tertiary)' }}>
          <Th>Voucher #</Th>
          <Th>Date</Th>
          <Th>Type</Th>
          <Th>Narration</Th>
          <Th align="right">Debit</Th>
          <Th align="right">Credit</Th>
          <Th>Balanced</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((v) => {
          const pill = VOUCHER_KIND_PILL[v.kind];
          const typeLabel = v.voucher_type ? VOUCHER_TYPE_LABEL[v.voucher_type] : pill.label;
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
                <Pill kind={pill.kind}>{typeLabel}</Pill>
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
                    Balanced
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

function BankAccountTable({ rows }: { rows: BankAccountView[] }) {
  if (rows.length === 0) {
    return <EmptyTable label="No bank accounts. Click + New bank account to add your first." />;
  }
  return (
    <table className="w-full text-left" style={{ minWidth: 920 }}>
      <thead style={{ background: 'var(--bg-sunken)' }}>
        <tr style={{ color: 'var(--text-tertiary)' }}>
          <Th>Bank</Th>
          <Th>Account #</Th>
          <Th>IFSC</Th>
          <Th>Type</Th>
          <Th align="right">Balance</Th>
          <Th>Last reconciled</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.bank_account_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
            <td className="px-3 py-3" style={{ fontSize: 13.5, fontWeight: 500 }}>
              {a.bank_name || '—'}
            </td>
            <td
              className="mono px-3 py-3"
              style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
            >
              {a.account_number || '—'}
            </td>
            <td
              className="mono px-3 py-3"
              style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
            >
              {a.ifsc_code || '—'}
            </td>
            <td className="px-3 py-3" style={{ fontSize: 12.5 }}>
              {a.account_type || '—'}
            </td>
            <td className="num px-3 py-3" style={{ textAlign: 'right', fontWeight: 500 }}>
              {formatINRCompact(a.balance_paise)}
            </td>
            <td className="num px-3 py-3" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
              {a.last_reconciled_date || '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ChequePanel({
  bankAccounts,
  selectedBankAccountId,
  onSelectBankAccount,
  cheques,
  isPending,
}: {
  bankAccounts: BankAccountView[];
  selectedBankAccountId: string | null;
  onSelectBankAccount: (id: string) => void;
  cheques: ChequeView[];
  isPending: boolean;
}) {
  if (bankAccounts.length === 0) {
    return <EmptyTable label="Add a bank account first — cheques are tracked per account." />;
  }
  return (
    <div className="flex flex-col">
      <div
        className="flex items-center gap-2 border-b px-3 py-2"
        style={{ borderColor: 'var(--border-subtle)' }}
      >
        <label
          htmlFor="cheque-bank-account"
          style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}
        >
          Bank account
        </label>
        <select
          id="cheque-bank-account"
          value={selectedBankAccountId ?? ''}
          onChange={(e) => onSelectBankAccount(e.target.value)}
          className="h-8 rounded-md px-2"
          style={{
            border: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            fontSize: 13,
          }}
        >
          {bankAccounts.map((a) => (
            <option key={a.bank_account_id} value={a.bank_account_id}>
              {a.bank_name || a.account_number || a.bank_account_id.slice(0, 8)}
            </option>
          ))}
        </select>
      </div>
      {isPending ? (
        <ListSkeleton rows={4} label="Loading cheques" />
      ) : cheques.length === 0 ? (
        <EmptyTable label="No cheques on this account yet." />
      ) : (
        <table className="w-full text-left" style={{ minWidth: 920 }}>
          <thead style={{ background: 'var(--bg-sunken)' }}>
            <tr style={{ color: 'var(--text-tertiary)' }}>
              <Th>Cheque #</Th>
              <Th>Date</Th>
              <Th>Payee</Th>
              <Th align="right">Amount</Th>
              <Th>Status</Th>
              <Th>Cleared</Th>
            </tr>
          </thead>
          <tbody>
            {cheques.map((c) => (
              <tr key={c.cheque_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td className="px-3 py-3">
                  <span className="mono" style={{ fontSize: 12.5, fontWeight: 500 }}>
                    {c.cheque_number}
                  </span>
                </td>
                <td
                  className="num px-3 py-3"
                  style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                >
                  {c.cheque_date}
                </td>
                <td className="px-3 py-3" style={{ fontSize: 13.5, fontWeight: 500 }}>
                  {c.payee_name || '—'}
                </td>
                <td className="num px-3 py-3" style={{ textAlign: 'right', fontWeight: 500 }}>
                  {formatINRCompact(c.amount_paise)}
                </td>
                <td className="px-3 py-3">
                  <Pill kind={chequePillKind(c.status)}>{prettyChequeStatus(c.status)}</Pill>
                </td>
                <td
                  className="num px-3 py-3"
                  style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}
                >
                  {c.clearing_date || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function chequePillKind(status: string): PillKind {
  switch (status) {
    case 'CLEARED':
      return 'paid';
    case 'BOUNCED':
      return 'overdue';
    case 'CANCELLED':
      return 'scrap';
    case 'ISSUED':
    default:
      return 'draft';
  }
}

function prettyChequeStatus(status: string): string {
  return status.charAt(0) + status.slice(1).toLowerCase();
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

function EmptyTable({ label }: { label: string }) {
  return (
    <div
      role="status"
      className="px-4 py-12 text-center"
      style={{ fontSize: 13, color: 'var(--text-tertiary)' }}
    >
      {label}
    </div>
  );
}
