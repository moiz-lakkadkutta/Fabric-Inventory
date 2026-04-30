import { invoices } from './invoices';
import { lowStockItems } from './items';
import { parties } from './parties';
import type { ActivityItem, Kpi } from './types';

const outstandingReceivables = invoices
  .filter((i) => i.status !== 'PAID' && i.status !== 'CANCELLED')
  .reduce((s, i) => s + (i.total - i.paid), 0);

const overdueReceivables = invoices
  .filter((i) => i.status === 'OVERDUE')
  .reduce((s, i) => s + (i.total - i.paid), 0);

const salesToday = invoices
  .filter((i) => i.date === '2026-04-30' && i.status !== 'CANCELLED')
  .reduce((s, i) => s + i.total, 0);

const salesMtd = invoices
  .filter((i) => i.date.startsWith('2026-04') && i.status !== 'CANCELLED')
  .reduce((s, i) => s + i.total, 0);

const supplierPayables = parties
  .filter((p) => p.outstanding < 0)
  .reduce((s, p) => s + Math.abs(p.outstanding), 0);

export const kpis: Kpi[] = [
  {
    key: 'outstanding',
    label: 'Outstanding receivables',
    value: outstandingReceivables,
    unit: '₹',
    delta_pct: 8.4,
    delta_kind: 'negative', // up = bad for receivables
    spark: [88, 92, 87, 95, 102, 108, 112, 118, 121, 124],
  },
  {
    key: 'overdue',
    label: 'Overdue (>0d past due)',
    value: overdueReceivables,
    unit: '₹',
    delta_pct: -3.1,
    delta_kind: 'positive',
    spark: [42, 48, 51, 49, 52, 47, 44, 41, 39, 38],
  },
  {
    key: 'sales_today',
    label: 'Sales today',
    value: salesToday,
    unit: '₹',
    delta_pct: 12.7,
    delta_kind: 'positive',
    spark: [3, 5, 4, 7, 6, 9, 8, 11, 12, 14],
  },
  {
    key: 'sales_mtd',
    label: 'Sales · Apr MTD',
    value: salesMtd,
    unit: '₹',
    delta_pct: 5.2,
    delta_kind: 'positive',
    spark: [180, 185, 192, 198, 203, 211, 218, 224, 231, 238],
  },
  {
    key: 'low_stock',
    label: 'Low-stock SKUs',
    value: lowStockItems.length,
    unit: 'count',
    delta_pct: 2,
    delta_kind: 'negative',
    spark: [3, 3, 3, 3, 4, 4, 4, 4, 4, 4],
  },
  {
    key: 'payables',
    label: 'Supplier payables',
    value: supplierPayables,
    unit: '₹',
    delta_pct: -1.4,
    delta_kind: 'positive',
    spark: [62, 60, 58, 60, 56, 55, 53, 52, 51, 50],
  },
];

export const activity: ActivityItem[] = [
  {
    id: 'a_1',
    ts: '2026-04-30T11:42:00Z',
    kind: 'invoice_finalized',
    title: 'Invoice RT/2526/0004 finalized',
    detail: 'Anjali Saree Centre · ₹2.54 L',
    amount: 2_54_100_00,
    party: 'Anjali Saree Centre',
  },
  {
    id: 'a_2',
    ts: '2026-04-30T10:18:00Z',
    kind: 'payment_received',
    title: 'Payment received from Lakshmi Suit House',
    detail: '₹2.00 L · NEFT · against RT/2526/0011',
    amount: 2_00_000_00,
    party: 'Lakshmi Suit House',
  },
  {
    id: 'a_3',
    ts: '2026-04-30T09:51:00Z',
    kind: 'low_stock',
    title: 'Chiffon Silk 44" below reorder',
    detail: '85m on hand · reorder at 100m',
  },
  {
    id: 'a_4',
    ts: '2026-04-29T18:04:00Z',
    kind: 'po_approved',
    title: 'PO/2526/0042 approved',
    detail: 'Surat Silk Mills · ₹3.40 L',
    amount: 3_40_000_00,
    party: 'Surat Silk Mills',
  },
  {
    id: 'a_5',
    ts: '2026-04-29T16:30:00Z',
    kind: 'invoice_finalized',
    title: 'Invoice RT/2526/0007 finalized',
    detail: 'Sangeeta Traders · ₹3.18 L',
    amount: 3_18_200_00,
    party: 'Sangeeta Traders',
  },
  {
    id: 'a_6',
    ts: '2026-04-28T14:12:00Z',
    kind: 'gst_filed',
    title: 'GSTR-1 filed for March 2026',
    detail: '47 invoices · ₹18.4 L turnover',
  },
];
