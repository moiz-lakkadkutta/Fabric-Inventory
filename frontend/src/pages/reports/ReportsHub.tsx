import { Download, Printer } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useDaybook,
  useGstr1,
  usePnL,
  useStockReport,
  useTrialBalance,
} from '@/lib/queries/reports';
import { formatINRCompact } from '@/lib/mock';
import type { GstrSection, PnlRow } from '@/lib/mock/reports';

type Tab = 'pnl' | 'tb' | 'gstr1' | 'stock' | 'daybook';

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'pnl', label: 'P&L' },
  { id: 'tb', label: 'Trial balance' },
  { id: 'gstr1', label: 'GSTR-1' },
  { id: 'stock', label: 'Stock' },
  { id: 'daybook', label: 'Daybook' },
];

const PERIOD = 'Apr 2026 · FY 2025-26';
const COMPARE = 'vs Mar 2026';

export default function ReportsHub() {
  const [tab, setTab] = useState<Tab>('pnl');
  const print = useComingSoon({
    feature: 'Print report (PDF)',
    task: 'TASK-046 (Reports → CSV/PDF)',
  });
  const exportR = useComingSoon({
    feature: 'Export report (CSV / Excel)',
    task: 'TASK-046 (Reports → CSV/PDF)',
  });

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Reports</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {PERIOD} · {COMPARE}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" {...print.triggerProps}>
            <Printer size={14} />
            Print
          </Button>
          <Button variant="outline" {...exportR.triggerProps}>
            <Download size={14} />
            Export
          </Button>
        </div>
      </header>
      {print.dialog}
      {exportR.dialog}

      <nav
        role="tablist"
        aria-label="Reports"
        className="flex flex-wrap gap-1"
        style={{ borderBottom: '1px solid var(--border-default)' }}
      >
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={active}
              onClick={() => setTab(t.id)}
              className="inline-flex h-9 items-center px-4"
              style={{
                fontSize: 13.5,
                fontWeight: active ? 600 : 500,
                color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
                marginBottom: -1,
              }}
            >
              {t.label}
            </button>
          );
        })}
      </nav>

      {tab === 'pnl' && <PnLPanel />}
      {tab === 'tb' && <TrialBalancePanel />}
      {tab === 'gstr1' && <Gstr1Panel />}
      {tab === 'stock' && <StockPanel />}
      {tab === 'daybook' && <DaybookPanel />}
    </div>
  );
}

function PnLPanel() {
  const q = usePnL();
  if (q.isPending) return <Skeleton width="100%" height={400} radius={8} />;
  const rows = q.data ?? [];
  const totalIncome = rows.find((r) => r.label === 'Total income');
  const cogs = rows.find((r) => r.label === 'Cost of goods sold');
  const grossProfit = rows.find((r) => r.label === 'Gross profit');
  const netProfit = rows.find((r) => r.label === 'Net profit');

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Total income" row={totalIncome} />
        <KpiCard label="COGS" row={cogs} negate />
        <KpiCard label="Gross profit" row={grossProfit} accent />
        <KpiCard label="Net profit" row={netProfit} accent />
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
              <Th>Account</Th>
              <Th align="right">Apr 2026</Th>
              <Th align="right">Mar 2026</Th>
              <Th align="right">Δ</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const delta = r.current - r.previous;
              const pct = r.previous === 0 ? 100 : (delta / r.previous) * 100;
              return (
                <tr
                  key={i}
                  style={{
                    borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                    background: r.bold ? 'var(--bg-sunken)' : 'transparent',
                  }}
                >
                  <td
                    className="px-3 py-2.5"
                    style={{
                      fontSize: r.bold ? 13.5 : 13,
                      fontWeight: r.bold ? 600 : 400,
                      paddingLeft: r.bold ? 12 : 28,
                    }}
                  >
                    {r.label}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{
                      textAlign: 'right',
                      fontWeight: r.bold ? 600 : 500,
                    }}
                  >
                    {formatINRCompact(r.current)}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{
                      textAlign: 'right',
                      color: 'var(--text-tertiary)',
                    }}
                  >
                    {formatINRCompact(r.previous)}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{
                      textAlign: 'right',
                      fontSize: 12.5,
                      color: delta >= 0 ? 'var(--success-text)' : 'var(--danger)',
                    }}
                  >
                    {delta >= 0 ? '+' : ''}
                    {pct.toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function KpiCard({
  label,
  row,
  accent,
  negate,
}: {
  label: string;
  row?: PnlRow;
  accent?: boolean;
  negate?: boolean;
}) {
  if (!row) return null;
  const value = negate ? -row.current : row.current;
  const prev = negate ? -row.previous : row.previous;
  const delta = value - prev;
  const pct = prev === 0 ? 100 : (delta / Math.abs(prev)) * 100;
  return (
    <article
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        padding: 14,
      }}
    >
      <div
        className="uppercase"
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div
        className="num mt-1.5"
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: accent ? 'var(--accent)' : 'var(--text-primary)',
        }}
      >
        {formatINRCompact(value)}
      </div>
      <div
        className="num mt-0.5"
        style={{
          fontSize: 11.5,
          color: delta >= 0 ? 'var(--success-text)' : 'var(--danger)',
          fontWeight: 500,
        }}
      >
        {delta >= 0 ? '+' : ''}
        {pct.toFixed(1)}% vs prev
      </div>
    </article>
  );
}

function TrialBalancePanel() {
  const q = useTrialBalance();
  if (q.isPending) return <Skeleton width="100%" height={400} radius={8} />;
  const rows = q.data ?? [];
  const debit = rows.reduce((s, r) => s + r.debit, 0);
  const credit = rows.reduce((s, r) => s + r.credit, 0);
  const balanced = debit === credit;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span
          style={{
            fontSize: 12.5,
            color: balanced ? 'var(--success-text)' : 'var(--danger)',
            fontWeight: 600,
          }}
        >
          {balanced ? '✓ Balanced' : '✗ Unbalanced'}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          Debit total <span className="num">{formatINRCompact(debit)}</span> · Credit total{' '}
          <span className="num">{formatINRCompact(credit)}</span>
        </span>
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
              <Th>Account</Th>
              <Th>Group</Th>
              <Th align="right">Debit</Th>
              <Th align="right">Credit</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td className="px-3 py-2.5" style={{ fontSize: 13, fontWeight: 500 }}>
                  {r.account}
                </td>
                <td
                  className="px-3 py-2.5"
                  style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}
                >
                  {r.group}
                </td>
                <td
                  className="num px-3 py-2.5"
                  style={{
                    textAlign: 'right',
                    color: r.debit > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)',
                  }}
                >
                  {r.debit > 0 ? formatINRCompact(r.debit) : '—'}
                </td>
                <td
                  className="num px-3 py-2.5"
                  style={{
                    textAlign: 'right',
                    color: r.credit > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)',
                  }}
                >
                  {r.credit > 0 ? formatINRCompact(r.credit) : '—'}
                </td>
              </tr>
            ))}
            <tr
              style={{
                borderTop: '2px solid var(--border-default)',
                background: 'var(--bg-sunken)',
              }}
            >
              <td className="px-3 py-3" style={{ fontWeight: 600 }}>
                Total
              </td>
              <td />
              <td className="num px-3 py-3" style={{ textAlign: 'right', fontWeight: 600 }}>
                {formatINRCompact(debit)}
              </td>
              <td className="num px-3 py-3" style={{ textAlign: 'right', fontWeight: 600 }}>
                {formatINRCompact(credit)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

const SECTION_PILL: Record<GstrSection, { kind: PillKind; label: string }> = {
  B2B: { kind: 'finalized', label: 'B2B' },
  B2C: { kind: 'draft', label: 'B2C' },
  CDNR: { kind: 'overdue', label: 'CDNR' },
  EXP: { kind: 'paid', label: 'Export' },
  NIL: { kind: 'scrap', label: 'Nil' },
};

function Gstr1Panel() {
  const q = useGstr1();
  if (q.isPending) return <Skeleton width="100%" height={400} radius={8} />;
  const rows = q.data ?? [];
  const totalTaxable = rows.reduce((s, r) => s + r.taxable, 0);
  const totalTax = rows.reduce((s, r) => s + r.cgst + r.sgst + r.igst, 0);
  const issues = rows.filter((r) => r.status !== 'OK').length;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Invoices" value={`${rows.length}`} />
        <Stat label="Taxable value" value={formatINRCompact(totalTaxable)} />
        <Stat label="Tax (CGST+SGST+IGST)" value={formatINRCompact(totalTax)} />
        <Stat
          label="Validation"
          value={issues === 0 ? '✓ All OK' : `${issues} to review`}
          color={issues === 0 ? 'var(--success-text)' : 'var(--warning-text)'}
        />
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
              <Th>Section</Th>
              <Th>Party</Th>
              <Th>GSTIN</Th>
              <Th>Invoice</Th>
              <Th>Date</Th>
              <Th align="right">Taxable</Th>
              <Th align="right">CGST</Th>
              <Th align="right">SGST</Th>
              <Th align="right">IGST</Th>
              <Th align="right">Total</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const pill = SECTION_PILL[r.section];
              return (
                <tr
                  key={i}
                  style={{
                    borderTop: '1px solid var(--border-subtle)',
                    background:
                      r.status === 'WARN'
                        ? 'var(--warning-subtle)'
                        : r.status === 'ERROR'
                          ? 'var(--danger-subtle)'
                          : 'transparent',
                  }}
                >
                  <td className="px-3 py-2.5">
                    <Pill kind={pill.kind}>{pill.label}</Pill>
                  </td>
                  <td className="px-3 py-2.5" style={{ fontSize: 13, fontWeight: 500 }}>
                    {r.party}
                  </td>
                  <td
                    className="mono px-3 py-2.5"
                    style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}
                  >
                    {r.gstin}
                  </td>
                  <td className="mono px-3 py-2.5" style={{ fontSize: 12, fontWeight: 500 }}>
                    {r.invoice}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{ fontSize: 12, color: 'var(--text-secondary)' }}
                  >
                    {r.date}
                  </td>
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                    {formatINRCompact(r.taxable)}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{ textAlign: 'right', color: 'var(--text-tertiary)' }}
                  >
                    {r.cgst > 0 ? formatINRCompact(r.cgst) : '—'}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{ textAlign: 'right', color: 'var(--text-tertiary)' }}
                  >
                    {r.sgst > 0 ? formatINRCompact(r.sgst) : '—'}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{ textAlign: 'right', color: 'var(--text-tertiary)' }}
                  >
                    {r.igst > 0 ? formatINRCompact(r.igst) : '—'}
                  </td>
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right', fontWeight: 500 }}>
                    {formatINRCompact(r.total)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StockPanel() {
  const q = useStockReport();
  if (q.isPending) return <Skeleton width="100%" height={400} radius={8} />;
  const rows = q.data ?? [];
  const total = rows.reduce((s, r) => s + r.value, 0);
  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-3">
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>Total stock value</span>
        <span className="num" style={{ fontSize: 22, fontWeight: 600, color: 'var(--accent)' }}>
          {formatINRCompact(total)}
        </span>
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
              <Th>Code</Th>
              <Th>Item</Th>
              <Th>UoM</Th>
              <Th align="right">On hand</Th>
              <Th align="right">Rate</Th>
              <Th align="right">Value</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.code} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td
                  className="mono px-3 py-2.5"
                  style={{ fontSize: 12, color: 'var(--text-secondary)' }}
                >
                  {r.code}
                </td>
                <td className="px-3 py-2.5" style={{ fontSize: 13, fontWeight: 500 }}>
                  {r.name}
                </td>
                <td className="px-3 py-2.5" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                  {r.uom.toLowerCase()}
                </td>
                <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                  {r.on_hand.toLocaleString('en-IN')}
                </td>
                <td
                  className="num px-3 py-2.5"
                  style={{ textAlign: 'right', color: 'var(--text-secondary)' }}
                >
                  {formatINRCompact(r.rate)}
                </td>
                <td className="num px-3 py-2.5" style={{ textAlign: 'right', fontWeight: 500 }}>
                  {formatINRCompact(r.value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DaybookPanel() {
  const q = useDaybook();
  if (q.isPending) return <Skeleton width="100%" height={400} radius={8} />;
  const rows = q.data ?? [];
  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      <table className="w-full text-left">
        <thead style={{ background: 'var(--bg-sunken)' }}>
          <tr style={{ color: 'var(--text-tertiary)' }}>
            <Th>Date</Th>
            <Th>Voucher</Th>
            <Th>Kind</Th>
            <Th>Narration</Th>
            <Th align="right">Debit</Th>
            <Th align="right">Credit</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ borderTop: '1px solid var(--border-subtle)' }}>
              <td
                className="num px-3 py-2.5"
                style={{ fontSize: 12, color: 'var(--text-secondary)' }}
              >
                {r.date}
              </td>
              <td className="mono px-3 py-2.5" style={{ fontSize: 12, fontWeight: 500 }}>
                {r.voucher}
              </td>
              <td className="px-3 py-2.5" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                {r.kind}
              </td>
              <td className="px-3 py-2.5" style={{ fontSize: 13 }}>
                {r.narration}
              </td>
              <td
                className="num px-3 py-2.5"
                style={{
                  textAlign: 'right',
                  color: r.debit > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)',
                }}
              >
                {r.debit > 0 ? formatINRCompact(r.debit) : '—'}
              </td>
              <td
                className="num px-3 py-2.5"
                style={{
                  textAlign: 'right',
                  color: r.credit > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)',
                }}
              >
                {r.credit > 0 ? formatINRCompact(r.credit) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <article
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        padding: 14,
      }}
    >
      <div
        className="uppercase"
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div
        className="num mt-1.5"
        style={{
          fontSize: 18,
          fontWeight: 600,
          color: color ?? 'var(--text-primary)',
        }}
      >
        {value}
      </div>
    </article>
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
