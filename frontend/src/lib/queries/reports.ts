/*
 * reports.ts — TASK-CUT-301 live wiring for the 5 ReportsHub tabs.
 *
 * Four endpoints from CUT-105 are live in this PR:
 *   GET /reports/pnl?from=&to=
 *   GET /reports/tb?as_of=
 *   GET /reports/daybook?date=
 *   GET /reports/stock-summary?as_of=
 *
 * GSTR-1 is still on mock fixtures; the BE endpoint lands in CUT-302
 * (Wave 4 sibling). Once it ships, swap useGstr1's live branch in the
 * same shape as the four above.
 *
 * Money on the wire is rupees-as-Decimal-string (per CLAUDE.md). All
 * mappers convert to integer paise before handing data to the React
 * components — never floats for money. Indian-grouping formatting
 * stays in `@/lib/format` (formatINRCompact).
 *
 * Firm scope: the BE derives firm_id from the session token, so no
 * firm_id query param is appended FE-side. RLS still gates the call.
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import {
  daybookEntries,
  gstrRows,
  pnlRows,
  stockRows,
  tbRows,
  type DaybookEntry,
  type PnlRow,
  type StockRow,
  type TrialBalanceRow,
} from '@/lib/mock/reports';
import type { components } from '@/types/api';

// CUT-301 retires the mock fixture-delay helper from this module so
// the reports path is live-first; mock mode still resolves inline so
// the click-dummy keeps working. Existing ReportsHub mock-mode tests
// don't depend on a loading frame, so a synchronous resolve is fine.
const mockResolve = <T>(value: T): Promise<T> => Promise.resolve(value);

type BackendPnlResponse = components['schemas']['PnlResponse'];
type BackendPnlGroupRow = components['schemas']['PnlGroupRow'];
type BackendTbResponse = components['schemas']['TbResponse'];
type BackendTbRow = components['schemas']['TbRow'];
type BackendDaybookResponse = components['schemas']['DaybookResponse'];
type BackendDaybookVoucher = components['schemas']['DaybookVoucher'];
type BackendStockSummaryResponse = components['schemas']['StockSummaryResponse'];
type BackendStockSummaryRow = components['schemas']['StockSummaryRow'];

// ──────────────────────────────────────────────────────────────────────
// Money helpers — rupees-decimal-string → integer paise.
// ──────────────────────────────────────────────────────────────────────

/**
 * Convert a rupees-decimal string (the BE wire format) to integer paise.
 * Multiplies by 100 then rounds to avoid float accumulation errors —
 * "1234.56" → 123456 paise. Empty / nullable inputs collapse to 0.
 */
function rupeesToPaise(s: string | null | undefined): number {
  if (s === null || s === undefined || s === '') return 0;
  // Use Math.round on the explicit multiplication, NOT parseFloat alone —
  // 0.1 + 0.2 round-tripped through paise must stay 30, not 29.9999999.
  return Math.round(parseFloat(s) * 100);
}

// ──────────────────────────────────────────────────────────────────────
// P&L mapper
//
// The BE returns aggregates (`total_income`, `cogs`, `gross_profit`,
// `expenses`, `net_profit`) plus a flat list of by-ledger-group rows
// each tagged with a group_type of INCOME | COGS | EXPENSE. The
// component (PnLPanel in ReportsHub) consumes the legacy click-dummy
// shape: a flat array of PnlRow with `bold` flags marking subtotals
// and labels matching specific strings ("Total income",
// "Cost of goods sold", "Gross profit", "Net profit"). We construct
// that array from the envelope so the component diff stays minimal.
// ──────────────────────────────────────────────────────────────────────

function mapPnlResponseToRows(r: BackendPnlResponse): PnlRow[] {
  const rows: PnlRow[] = [];

  const incomeGroups = r.by_ledger_group.filter((g) => g.group_type === 'INCOME');
  const cogsGroups = r.by_ledger_group.filter((g) => g.group_type === 'COGS');
  const expenseGroups = r.by_ledger_group.filter((g) => g.group_type === 'EXPENSE');

  for (const g of incomeGroups) {
    rows.push(groupToRow('Income', g));
  }
  rows.push({
    group: 'Income',
    label: 'Total income',
    current: rupeesToPaise(r.total_income),
    previous: incomeGroups.reduce((s, g) => s + rupeesToPaise(g.prior_period_amount), 0),
    bold: true,
    divider: true,
  });

  for (const g of cogsGroups) {
    rows.push(groupToRow('COGS', g));
  }
  rows.push({
    group: 'COGS',
    label: 'Cost of goods sold',
    current: rupeesToPaise(r.cogs),
    previous: cogsGroups.reduce((s, g) => s + rupeesToPaise(g.prior_period_amount), 0),
    bold: true,
    divider: true,
  });

  rows.push({
    group: 'GP',
    label: 'Gross profit',
    current: rupeesToPaise(r.gross_profit),
    previous:
      incomeGroups.reduce((s, g) => s + rupeesToPaise(g.prior_period_amount), 0) -
      cogsGroups.reduce((s, g) => s + rupeesToPaise(g.prior_period_amount), 0),
    bold: true,
    divider: true,
  });

  for (const g of expenseGroups) {
    rows.push(groupToRow('Expenses', g));
  }
  if (expenseGroups.length > 0) {
    rows.push({
      group: 'Expenses',
      label: 'Total expenses',
      current: rupeesToPaise(r.expenses),
      previous: expenseGroups.reduce((s, g) => s + rupeesToPaise(g.prior_period_amount), 0),
      bold: true,
      divider: true,
    });
  }

  rows.push({
    group: 'NP',
    label: 'Net profit',
    current: rupeesToPaise(r.net_profit),
    previous:
      incomeGroups.reduce((s, g) => s + rupeesToPaise(g.prior_period_amount), 0) -
      cogsGroups.reduce((s, g) => s + rupeesToPaise(g.prior_period_amount), 0) -
      expenseGroups.reduce((s, g) => s + rupeesToPaise(g.prior_period_amount), 0),
    bold: true,
  });

  return rows;
}

function groupToRow(group: string, g: BackendPnlGroupRow): PnlRow {
  return {
    group,
    label: g.group_name,
    current: rupeesToPaise(g.current_period_amount),
    previous: rupeesToPaise(g.prior_period_amount),
  };
}

async function liveListPnL(): Promise<PnlRow[]> {
  // BE defaults: `from` → FY start; `to` → today. Leaving the query
  // params empty produces a sensible YTD P&L (matches the spike doc's
  // expectations and CUT-105's defaults).
  const data = await api<BackendPnlResponse>('/reports/pnl');
  return mapPnlResponseToRows(data);
}

export function usePnL() {
  return useQuery({
    queryKey: ['reports', 'pnl'],
    queryFn: () => (IS_LIVE ? liveListPnL() : mockResolve([...pnlRows])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Trial Balance mapper
// ──────────────────────────────────────────────────────────────────────

/**
 * Map the BE Trial Balance ledger row to the click-dummy TbRow shape.
 * The click-dummy uses a `group` string (free-form, e.g. "Asset",
 * "Liability"); the BE uses `group_code` (e.g. "ASSETS", "REVENUE"),
 * which is what we surface. The visible label stays the BE group_code
 * — once we add a separate group-name field, this can map nicely.
 */
function mapTbRow(b: BackendTbRow): TrialBalanceRow {
  return {
    account: b.ledger_name,
    group: b.group_code ?? '—',
    debit: rupeesToPaise(b.debit),
    credit: rupeesToPaise(b.credit),
  };
}

async function liveListTb(): Promise<TrialBalanceRow[]> {
  const data = await api<BackendTbResponse>('/reports/tb');
  return data.rows.map(mapTbRow);
}

export function useTrialBalance() {
  return useQuery({
    queryKey: ['reports', 'tb'],
    queryFn: () => (IS_LIVE ? liveListTb() : mockResolve([...tbRows])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// GSTR-1 (still on mock — CUT-302 will land the BE endpoint and this
// hook should mirror the four above)
// ──────────────────────────────────────────────────────────────────────

export function useGstr1() {
  return useQuery({
    queryKey: ['reports', 'gstr1'],
    // TODO(CUT-302): once `GET /reports/gstr1?period=YYYY-MM` ships in
    // Wave 4, swap the live branch to hit it; for now live mode returns
    // an empty array because the tab's component renders a coming-soon
    // panel that ignores `q.data`. Mock mode keeps the click-dummy
    // fixture so existing mock-mode tests pass unchanged.
    queryFn: () => (IS_LIVE ? mockResolve([]) : mockResolve([...gstrRows])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Stock summary mapper
// ──────────────────────────────────────────────────────────────────────

function mapStockRow(b: BackendStockSummaryRow): StockRow {
  // on_hand_qty is a decimal-string (the BE preserves precision for
  // fabric metres). parseFloat is safe here because qty is a count,
  // not money — display tolerates rounding. avg_cost and valuation
  // are money and convert via rupeesToPaise (integer paise).
  return {
    code: b.item_code,
    name: b.item_name,
    uom: b.uom,
    on_hand: parseFloat(b.on_hand_qty || '0'),
    rate: rupeesToPaise(b.avg_cost),
    value: rupeesToPaise(b.valuation),
  };
}

async function liveListStock(): Promise<StockRow[]> {
  const data = await api<BackendStockSummaryResponse>('/reports/stock-summary');
  return data.rows.map(mapStockRow);
}

export function useStockReport() {
  return useQuery({
    queryKey: ['reports', 'stock'],
    queryFn: () => (IS_LIVE ? liveListStock() : mockResolve([...stockRows])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Daybook mapper
//
// The BE returns one row per voucher with totals already aggregated
// across that voucher's lines (so a sales-invoice's DR-debtors and
// CR-revenue collapse to a single total_debit + total_credit pair).
// That matches the click-dummy DaybookEntry exactly — one row per
// voucher, voucher_type drives the `kind` column.
// ──────────────────────────────────────────────────────────────────────

const VOUCHER_TYPE_TO_KIND: Record<string, DaybookEntry['kind']> = {
  SALES_INVOICE: 'Sales',
  PURCHASE_INVOICE: 'Purchase',
  RECEIPT: 'Receipt',
  PAYMENT: 'Payment',
  JOURNAL: 'Journal',
  CONTRA: 'Journal',
  DEBIT_NOTE: 'Journal',
  CREDIT_NOTE: 'Journal',
  OPENING_BAL: 'Journal',
};

function mapDaybookVoucher(b: BackendDaybookVoucher, asOfDate: string): DaybookEntry {
  const kind = VOUCHER_TYPE_TO_KIND[b.voucher_type] ?? 'Journal';
  const narration =
    b.narration ??
    (b.party_name ? `${kind} — ${b.party_name}` : `${kind} — ${b.series}/${b.number}`);
  return {
    date: asOfDate,
    voucher: `${b.series}/${b.number}`,
    kind,
    narration,
    debit: rupeesToPaise(b.total_debit),
    credit: rupeesToPaise(b.total_credit),
  };
}

async function liveListDaybook(): Promise<DaybookEntry[]> {
  const data = await api<BackendDaybookResponse>('/reports/daybook');
  return data.vouchers.map((v) => mapDaybookVoucher(v, data.date));
}

export function useDaybook() {
  return useQuery({
    queryKey: ['reports', 'daybook'],
    queryFn: () => (IS_LIVE ? liveListDaybook() : mockResolve([...daybookEntries])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Test-only exports
// ──────────────────────────────────────────────────────────────────────

export const _internal = {
  rupeesToPaise,
  mapPnlResponseToRows,
  mapTbRow,
  mapStockRow,
  mapDaybookVoucher,
};
