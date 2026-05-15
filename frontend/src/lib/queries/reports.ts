/*
 * reports.ts — live wiring for the 5 ReportsHub tabs.
 *
 * All five endpoints (CUT-105 + CUT-302) are live:
 *   GET /reports/pnl?from=&to=
 *   GET /reports/tb?as_of=
 *   GET /reports/daybook?date=
 *   GET /reports/stock-summary?as_of=
 *   GET /reports/gstr1?period=YYYY-MM           [TASK-TR-B03]
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
type BackendGstr1Response = components['schemas']['Gstr1Response'];
type BackendGstr1InvoiceRow = components['schemas']['Gstr1InvoiceRow'];
type BackendGstr1B2csRow = components['schemas']['Gstr1B2csRow'];
type BackendGstr1HsnRow = components['schemas']['Gstr1HsnRow'];

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
// GSTR-1 mappers + hook (TASK-TR-B03)
//
// BE envelope shape (Gstr1Response):
//   b2b:    per-counterparty invoices (GSTIN-present)
//   b2cl:   inter-state B2C invoices > ₹2.5L
//   b2cs:   aggregated B2C below threshold, grouped by (state, gst_rate)
//   export: zero-rated overseas / SEZ / EOU sales
//   hsn:    per-HSN aggregation across taxable lines
//
// Money is rupees-decimal-string on the wire; we convert to integer
// paise here so the panel formats with `formatINRCompact` like the
// other tabs.
// ──────────────────────────────────────────────────────────────────────

export interface Gstr1InvoiceVM {
  sales_invoice_id: string;
  party_id: string;
  party_name: string;
  gstin: string | null;
  series: string;
  number: string;
  invoice_date: string;
  place_of_supply_state: string | null;
  gst_rate: string | null;
  taxable_value: number; // paise
  cgst: number; // paise
  sgst: number; // paise
  igst: number; // paise
  invoice_value: number; // paise
}

export interface Gstr1B2csVM {
  place_of_supply_state: string;
  gst_rate: string;
  invoice_count: number;
  taxable_value: number; // paise
  cgst: number; // paise
  sgst: number; // paise
  igst: number; // paise
}

export interface Gstr1HsnVM {
  hsn_code: string;
  description: string | null;
  uom: string;
  total_qty: number; // bare count (not money) — display tolerates float
  total_value: number; // paise
  taxable_value: number; // paise
  cgst: number; // paise
  sgst: number; // paise
  igst: number; // paise
}

export interface Gstr1VM {
  period: string;
  from_date: string;
  to_date: string;
  b2b: Gstr1InvoiceVM[];
  b2cl: Gstr1InvoiceVM[];
  b2cs: Gstr1B2csVM[];
  export: Gstr1InvoiceVM[];
  hsn: Gstr1HsnVM[];
}

function mapGstr1Invoice(b: BackendGstr1InvoiceRow): Gstr1InvoiceVM {
  return {
    sales_invoice_id: b.sales_invoice_id,
    party_id: b.party_id,
    party_name: b.party_name,
    gstin: b.gstin,
    series: b.series,
    number: b.number,
    invoice_date: b.invoice_date,
    place_of_supply_state: b.place_of_supply_state,
    gst_rate: b.gst_rate,
    taxable_value: rupeesToPaise(b.taxable_value),
    cgst: rupeesToPaise(b.cgst),
    sgst: rupeesToPaise(b.sgst),
    igst: rupeesToPaise(b.igst),
    invoice_value: rupeesToPaise(b.invoice_value),
  };
}

function mapGstr1B2cs(b: BackendGstr1B2csRow): Gstr1B2csVM {
  return {
    place_of_supply_state: b.place_of_supply_state,
    gst_rate: b.gst_rate,
    invoice_count: b.invoice_count,
    taxable_value: rupeesToPaise(b.taxable_value),
    cgst: rupeesToPaise(b.cgst),
    sgst: rupeesToPaise(b.sgst),
    igst: rupeesToPaise(b.igst),
  };
}

function mapGstr1Hsn(b: BackendGstr1HsnRow): Gstr1HsnVM {
  return {
    hsn_code: b.hsn_code,
    description: b.description,
    uom: b.uom,
    total_qty: parseFloat(b.total_qty || '0'),
    total_value: rupeesToPaise(b.total_value),
    taxable_value: rupeesToPaise(b.taxable_value),
    cgst: rupeesToPaise(b.cgst),
    sgst: rupeesToPaise(b.sgst),
    igst: rupeesToPaise(b.igst),
  };
}

function mapGstr1Response(r: BackendGstr1Response): Gstr1VM {
  return {
    period: r.period,
    from_date: r.from_date,
    to_date: r.to_date,
    b2b: r.b2b.map(mapGstr1Invoice),
    b2cl: r.b2cl.map(mapGstr1Invoice),
    b2cs: r.b2cs.map(mapGstr1B2cs),
    export: r.export.map(mapGstr1Invoice),
    hsn: r.hsn.map(mapGstr1Hsn),
  };
}

async function liveListGstr1(period: string): Promise<Gstr1VM> {
  const data = await api<BackendGstr1Response>(
    `/reports/gstr1?period=${encodeURIComponent(period)}`,
  );
  return mapGstr1Response(data);
}

/**
 * Build a click-dummy GSTR-1 view-model from the existing `gstrRows`
 * mock fixture. Keeps mock-mode tests (and the click-dummy demo)
 * working with the new live-shape panel.
 */
function mockGstr1ViewModel(period: string): Gstr1VM {
  const b2bRows = gstrRows.filter((r) => r.section === 'B2B');
  return {
    period,
    from_date: `${period}-01`,
    to_date: `${period}-30`,
    b2b: b2bRows.map((r, i) => ({
      sales_invoice_id: `mock-b2b-${i}`,
      party_id: `mock-party-${i}`,
      party_name: r.party,
      gstin: r.gstin,
      series: r.invoice.split('/').slice(0, 2).join('/'),
      number: r.invoice.split('/').pop() ?? r.invoice,
      invoice_date: r.date,
      place_of_supply_state: null,
      gst_rate: '5',
      taxable_value: r.taxable,
      cgst: r.cgst,
      sgst: r.sgst,
      igst: r.igst,
      invoice_value: r.total,
    })),
    b2cl: [],
    b2cs: [],
    export: [],
    hsn: [],
  };
}

/**
 * Pulls the GSTR-1 envelope for the given period (`YYYY-MM`). The
 * panel reads the four BE buckets (B2B / B2CL / B2CS / HSN) plus an
 * export bucket; money is integer paise after mapping.
 */
export function useGstr1(period: string) {
  return useQuery({
    queryKey: ['reports', 'gstr1', period],
    queryFn: () => (IS_LIVE ? liveListGstr1(period) : mockResolve(mockGstr1ViewModel(period))),
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
  mapGstr1Response,
  mapGstr1Invoice,
  mapGstr1B2cs,
  mapGstr1Hsn,
};
