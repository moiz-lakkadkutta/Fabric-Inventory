import { Download, Printer } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { downloadExport, type ExportFormat } from '@/lib/api/download';
import { IS_LIVE } from '@/lib/api/mode';
import {
  useDaybook,
  useGstr1,
  usePnL,
  useStockReport,
  useTrialBalance,
  type Gstr1B2csVM,
  type Gstr1HsnVM,
  type Gstr1InvoiceVM,
  type Gstr1VM,
} from '@/lib/queries/reports';
import { formatINRCompact } from '@/lib/format';
import type { PnlRow } from '@/lib/mock/reports';

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

/**
 * Current YYYY-MM string in local time. Used as the default GSTR-1
 * period; user can change via the period picker. Local time is fine
 * because GSTR-1 is filed per Indian fiscal month — the BE re-validates
 * the format anyway.
 */
function currentPeriod(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function reportExportEndpoint(tab: Tab, gstr1Period: string): { path: string; stem: string } {
  // Reports are firm-scoped on the backend; the BE pulls org_id/firm_id
  // off the JWT, so we don't pass them as query params. Period defaults
  // (FY current month) are resolved server-side too.
  switch (tab) {
    case 'pnl':
      return { path: '/reports/pnl', stem: 'pnl' };
    case 'tb':
      return { path: '/reports/tb', stem: 'tb' };
    case 'gstr1':
      // GSTR-1 needs a period; default to current month (UI picker).
      // BE supports both CSV (flattens to B2B) and XLSX (5-sheet
      // canonical filing).
      return {
        path: `/reports/gstr1?period=${encodeURIComponent(gstr1Period)}`,
        stem: `gstr1-${gstr1Period}`,
      };
    case 'stock':
      return { path: '/reports/stock-summary', stem: 'stock-summary' };
    case 'daybook':
      return { path: '/reports/daybook', stem: 'daybook' };
  }
}

export default function ReportsHub() {
  const [tab, setTab] = useState<Tab>('pnl');
  // GSTR-1 period state, used by both the panel query and the
  // export-button endpoint resolver. Other tabs ignore it.
  const [gstr1Period, setGstr1Period] = useState<string>(currentPeriod());
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const print = useComingSoon({
    feature: 'Print report (PDF)',
    task: 'TASK-046 (Reports → CSV/PDF)',
  });

  const runExport = async (format: ExportFormat) => {
    if (!IS_LIVE) {
      setExportError('Export is wired to the live backend (set VITE_API_MODE=live).');
      return;
    }
    const endpoint = reportExportEndpoint(tab, gstr1Period);
    setExportError(null);
    setIsExporting(true);
    try {
      await downloadExport({
        path: endpoint.path,
        format,
        fallbackFilename: `${endpoint.stem}-${new Date().toISOString().slice(0, 10)}.${format}`,
      });
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Could not export report.');
    } finally {
      setIsExporting(false);
    }
  };

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
          <Button
            variant="outline"
            onClick={() => runExport('csv')}
            disabled={isExporting}
            aria-label="Export report as CSV"
          >
            <Download size={14} />
            {isExporting ? 'Exporting…' : 'Export CSV'}
          </Button>
          <Button
            variant="outline"
            onClick={() => runExport('xlsx')}
            disabled={isExporting}
            aria-label="Export report as Excel"
          >
            <Download size={14} />
            Export Excel
          </Button>
        </div>
      </header>
      {print.dialog}
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
      {tab === 'gstr1' && <Gstr1Panel period={gstr1Period} onPeriodChange={setGstr1Period} />}
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

function Gstr1Panel({
  period,
  onPeriodChange,
}: {
  period: string;
  onPeriodChange: (p: string) => void;
}) {
  // `period` is a YYYY-MM string driven by the panel-local month picker.
  // Other tabs don't care about the picker; this lets the user re-fetch
  // GSTR-1 for any month independently of the page-level "Apr 2026"
  // header (a header-level picker can replace this later — for now the
  // panel-local control is the simplest path to live wiring).
  const q = useGstr1(period);

  return (
    <div className="space-y-4">
      <Gstr1Header
        period={period}
        onPeriodChange={onPeriodChange}
        data={q.data}
        isPending={q.isPending}
      />
      {q.isPending ? (
        <Skeleton width="100%" height={400} radius={8} />
      ) : q.isError ? (
        <Gstr1ErrorState message={(q.error as Error)?.message ?? 'Could not load GSTR-1.'} />
      ) : (
        <>
          <Gstr1B2BSection rows={q.data?.b2b ?? []} />
          <Gstr1B2CLSection rows={q.data?.b2cl ?? []} />
          <Gstr1B2CSSection rows={q.data?.b2cs ?? []} />
          <Gstr1HsnSection rows={q.data?.hsn ?? []} />
        </>
      )}
    </div>
  );
}

function Gstr1Header({
  period,
  onPeriodChange,
  data,
  isPending,
}: {
  period: string;
  onPeriodChange: (p: string) => void;
  data: Gstr1VM | undefined;
  isPending: boolean;
}) {
  const totalTaxable = data
    ? sumTaxable(data.b2b) +
      sumTaxable(data.b2cl) +
      data.b2cs.reduce((s, r) => s + r.taxable_value, 0) +
      sumTaxable(data.export)
    : 0;
  const totalTax = data
    ? sumTax(data.b2b) +
      sumTax(data.b2cl) +
      data.b2cs.reduce((s, r) => s + r.cgst + r.sgst + r.igst, 0) +
      sumTax(data.export)
    : 0;
  const invoiceCount = data
    ? data.b2b.length +
      data.b2cl.length +
      data.b2cs.reduce((s, r) => s + r.invoice_count, 0) +
      data.export.length
    : 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <label
          htmlFor="gstr1-period"
          style={{ fontSize: 12, color: 'var(--text-tertiary)', fontWeight: 500 }}
        >
          Period
        </label>
        <input
          id="gstr1-period"
          type="month"
          value={period}
          onChange={(e) => onPeriodChange(e.target.value)}
          aria-label="GSTR-1 period"
          style={{
            padding: '6px 10px',
            fontSize: 13,
            border: '1px solid var(--border-default)',
            borderRadius: 6,
            background: 'var(--bg-surface)',
            color: 'var(--text-primary)',
          }}
        />
        {data && (
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
            {data.from_date} → {data.to_date}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Invoices" value={isPending ? '—' : String(invoiceCount)} />
        <Stat label="Taxable value" value={isPending ? '—' : formatINRCompact(totalTaxable)} />
        <Stat label="Tax (CGST+SGST+IGST)" value={isPending ? '—' : formatINRCompact(totalTax)} />
        <Stat label="HSN rows" value={isPending ? '—' : String(data?.hsn.length ?? 0)} />
      </div>
    </div>
  );
}

function sumTaxable(rows: Gstr1InvoiceVM[]): number {
  return rows.reduce((s, r) => s + r.taxable_value, 0);
}
function sumTax(rows: Gstr1InvoiceVM[]): number {
  return rows.reduce((s, r) => s + r.cgst + r.sgst + r.igst, 0);
}

function SectionWrapper({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      <header
        className="flex items-baseline gap-2 px-3"
        style={{
          background: 'var(--bg-sunken)',
          borderBottom: '1px solid var(--border-subtle)',
          paddingTop: 8,
          paddingBottom: 8,
        }}
      >
        <h2 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{title}</h2>
        <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          {count} {count === 1 ? 'row' : 'rows'}
        </span>
      </header>
      {children}
    </section>
  );
}

function EmptyRow({ message }: { message: string }) {
  return (
    <div
      style={{
        padding: '20px 12px',
        textAlign: 'center',
        fontSize: 12.5,
        color: 'var(--text-tertiary)',
      }}
    >
      {message}
    </div>
  );
}

function Gstr1B2BSection({ rows }: { rows: Gstr1InvoiceVM[] }) {
  return (
    <SectionWrapper title="B2B" count={rows.length}>
      {rows.length === 0 ? (
        <EmptyRow message="No B2B invoices in this period." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left" style={{ minWidth: 720 }}>
            <thead style={{ background: 'var(--bg-surface)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>GSTIN</Th>
                <Th>Counterparty</Th>
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
              {rows.map((r) => (
                <tr
                  key={r.sales_invoice_id}
                  style={{ borderTop: '1px solid var(--border-subtle)' }}
                >
                  <td
                    className="mono px-3 py-2.5"
                    style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}
                  >
                    {r.gstin ?? '—'}
                  </td>
                  <td className="px-3 py-2.5" style={{ fontSize: 13, fontWeight: 500 }}>
                    {r.party_name}
                  </td>
                  <td className="mono px-3 py-2.5" style={{ fontSize: 12, fontWeight: 500 }}>
                    {r.series}/{r.number}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{ fontSize: 12, color: 'var(--text-secondary)' }}
                  >
                    {r.invoice_date}
                  </td>
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                    {formatINRCompact(r.taxable_value)}
                  </td>
                  <Td value={r.cgst} />
                  <Td value={r.sgst} />
                  <Td value={r.igst} />
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right', fontWeight: 500 }}>
                    {formatINRCompact(r.invoice_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionWrapper>
  );
}

function Gstr1B2CLSection({ rows }: { rows: Gstr1InvoiceVM[] }) {
  return (
    <SectionWrapper title="B2CL" count={rows.length}>
      {rows.length === 0 ? (
        <EmptyRow message="No B2CL invoices in this period." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left" style={{ minWidth: 720 }}>
            <thead style={{ background: 'var(--bg-surface)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Place of supply</Th>
                <Th>Counterparty</Th>
                <Th>Invoice</Th>
                <Th>Date</Th>
                <Th align="right">Taxable</Th>
                <Th align="right">IGST</Th>
                <Th align="right">Total</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.sales_invoice_id}
                  style={{ borderTop: '1px solid var(--border-subtle)' }}
                >
                  <td
                    className="mono px-3 py-2.5"
                    style={{ fontSize: 12, color: 'var(--text-secondary)' }}
                  >
                    {r.place_of_supply_state ?? '—'}
                  </td>
                  <td className="px-3 py-2.5" style={{ fontSize: 13, fontWeight: 500 }}>
                    {r.party_name}
                  </td>
                  <td className="mono px-3 py-2.5" style={{ fontSize: 12, fontWeight: 500 }}>
                    {r.series}/{r.number}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{ fontSize: 12, color: 'var(--text-secondary)' }}
                  >
                    {r.invoice_date}
                  </td>
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                    {formatINRCompact(r.taxable_value)}
                  </td>
                  <Td value={r.igst} />
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right', fontWeight: 500 }}>
                    {formatINRCompact(r.invoice_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionWrapper>
  );
}

function Gstr1B2CSSection({ rows }: { rows: Gstr1B2csVM[] }) {
  return (
    <SectionWrapper title="B2CS" count={rows.length}>
      {rows.length === 0 ? (
        <EmptyRow message="No B2CS aggregates in this period." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left" style={{ minWidth: 720 }}>
            <thead style={{ background: 'var(--bg-surface)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Place of supply</Th>
                <Th>GST rate</Th>
                <Th align="right">Invoices</Th>
                <Th align="right">Taxable</Th>
                <Th align="right">CGST</Th>
                <Th align="right">SGST</Th>
                <Th align="right">IGST</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={`${r.place_of_supply_state}-${r.gst_rate}-${i}`}
                  style={{ borderTop: '1px solid var(--border-subtle)' }}
                >
                  <td
                    className="mono px-3 py-2.5"
                    style={{ fontSize: 12, color: 'var(--text-secondary)' }}
                  >
                    {r.place_of_supply_state}
                  </td>
                  <td
                    className="num px-3 py-2.5"
                    style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                  >
                    {r.gst_rate}%
                  </td>
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                    {r.invoice_count}
                  </td>
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                    {formatINRCompact(r.taxable_value)}
                  </td>
                  <Td value={r.cgst} />
                  <Td value={r.sgst} />
                  <Td value={r.igst} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionWrapper>
  );
}

function Gstr1HsnSection({ rows }: { rows: Gstr1HsnVM[] }) {
  return (
    <SectionWrapper title="HSN summary" count={rows.length}>
      {rows.length === 0 ? (
        <EmptyRow message="No HSN summary in this period." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left" style={{ minWidth: 720 }}>
            <thead style={{ background: 'var(--bg-surface)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>HSN</Th>
                <Th>Description</Th>
                <Th>UQC</Th>
                <Th align="right">Qty</Th>
                <Th align="right">Taxable</Th>
                <Th align="right">CGST</Th>
                <Th align="right">SGST</Th>
                <Th align="right">IGST</Th>
                <Th align="right">Total</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={`${r.hsn_code}-${i}`}
                  style={{
                    borderTop: '1px solid var(--border-subtle)',
                    background: r.hsn_code === '' ? 'var(--warning-subtle)' : 'transparent',
                  }}
                >
                  <td className="mono px-3 py-2.5" style={{ fontSize: 12, fontWeight: 500 }}>
                    {r.hsn_code === '' ? '(missing)' : r.hsn_code}
                  </td>
                  <td className="px-3 py-2.5" style={{ fontSize: 13 }}>
                    {r.description ?? '—'}
                  </td>
                  <td
                    className="px-3 py-2.5"
                    style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
                  >
                    {r.uom.toLowerCase()}
                  </td>
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                    {r.total_qty.toLocaleString('en-IN')}
                  </td>
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right' }}>
                    {formatINRCompact(r.taxable_value)}
                  </td>
                  <Td value={r.cgst} />
                  <Td value={r.sgst} />
                  <Td value={r.igst} />
                  <td className="num px-3 py-2.5" style={{ textAlign: 'right', fontWeight: 500 }}>
                    {formatINRCompact(r.total_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionWrapper>
  );
}

function Td({ value }: { value: number }) {
  return (
    <td
      className="num px-3 py-2.5"
      style={{
        textAlign: 'right',
        color: value > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)',
      }}
    >
      {value > 0 ? formatINRCompact(value) : '—'}
    </td>
  );
}

function Gstr1ErrorState({ message }: { message: string }) {
  return (
    <div
      role="alert"
      style={{
        padding: 16,
        background: 'var(--bg-surface)',
        border: '1px solid var(--danger)',
        borderRadius: 8,
        color: 'var(--danger)',
        fontSize: 13,
      }}
    >
      Could not load GSTR-1: {message}
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
