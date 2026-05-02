import { findItem } from './items';
import { customers } from './parties';
import type { Invoice, InvoiceLine, InvoiceStatus } from './types';

// Today's anchor for ageing math. Real app pulls from server; here we
// fix a date so screenshots stay stable across environments.
export const TODAY = '2026-04-30';

// Build a deterministic line. Returns paise math.
function line(itemId: string, qty: number, gst_pct: number, rate_override?: number): InvoiceLine {
  const item = findItem(itemId)!;
  const rate = rate_override ?? item.rate;
  const amount = Math.round(rate * qty);
  const gst_amount = Math.round((amount * gst_pct) / 100);
  return {
    item_id: item.item_id,
    item_name: item.name,
    qty,
    uom: item.uom,
    rate,
    amount,
    gst_pct,
    gst_amount,
  };
}

// Build a single invoice from lines + party + date offset.
let seq = 1000;
function inv(opts: {
  daysAgo: number;
  partyIdx: number;
  lines: InvoiceLine[];
  status: InvoiceStatus;
  paid?: number;
  doc_type?: Invoice['doc_type'];
  due_days?: number;
}): Invoice {
  const party = customers[opts.partyIdx % customers.length];
  const subtotal = opts.lines.reduce((s, l) => s + l.amount, 0);
  const gst_total = opts.lines.reduce((s, l) => s + l.gst_amount, 0);
  const total = subtotal + gst_total;
  const todayDate = new Date(TODAY);
  const issueDate = new Date(todayDate);
  issueDate.setDate(todayDate.getDate() - opts.daysAgo);
  const dueDate = new Date(issueDate);
  dueDate.setDate(issueDate.getDate() + (opts.due_days ?? 30));
  const ageing_days = Math.floor((todayDate.getTime() - dueDate.getTime()) / 86_400_000);
  seq += 1;
  return {
    invoice_id: `inv_${seq}`,
    number: `RT/2526/${String(seq - 1000).padStart(4, '0')}`,
    date: issueDate.toISOString().slice(0, 10),
    due_date: dueDate.toISOString().slice(0, 10),
    party_id: party.party_id,
    party_name: party.name,
    party_state: party.state_code,
    status: opts.status,
    subtotal,
    gst_total,
    total,
    paid: opts.paid ?? (opts.status === 'PAID' ? total : 0),
    ageing_days,
    lines: opts.lines,
    doc_type: opts.doc_type ?? 'TAX_INVOICE',
  };
}

// 25 invoices with realistic distribution.
// Statuses: ~3 DRAFT, ~6 FINALIZED (in due window), ~6 PARTIALLY_PAID,
// ~5 PAID, ~4 OVERDUE, 1 CANCELLED.
export const invoices: Invoice[] = [
  // DRAFT — issued today
  inv({
    daysAgo: 0,
    partyIdx: 0,
    status: 'DRAFT',
    lines: [line('i_006', 6, 5), line('i_011', 12, 5)],
  }),
  inv({
    daysAgo: 0,
    partyIdx: 3,
    status: 'DRAFT',
    lines: [line('i_010', 4, 5)],
  }),
  inv({
    daysAgo: 1,
    partyIdx: 6,
    status: 'DRAFT',
    lines: [line('i_009', 2, 5), line('i_012', 3, 5)],
  }),

  // FINALIZED — within due window
  inv({
    daysAgo: 2,
    partyIdx: 0,
    status: 'FINALIZED',
    lines: [line('i_007', 18, 5), line('i_011', 24, 5)],
  }),
  inv({
    daysAgo: 4,
    partyIdx: 1,
    status: 'FINALIZED',
    lines: [line('i_002', 22, 5), line('i_010', 8, 5)],
  }),
  inv({
    daysAgo: 5,
    partyIdx: 2,
    status: 'FINALIZED',
    lines: [line('i_019', 3, 5)],
  }),
  inv({
    daysAgo: 6,
    partyIdx: 7,
    status: 'FINALIZED',
    lines: [line('i_018', 24, 5), line('i_010', 6, 5)],
  }),
  inv({
    daysAgo: 8,
    partyIdx: 5,
    status: 'FINALIZED',
    lines: [line('i_007', 12, 5), line('i_011', 18, 5)],
    doc_type: 'BILL_OF_SUPPLY',
  }),
  inv({
    daysAgo: 10,
    partyIdx: 4,
    status: 'FINALIZED',
    lines: [line('i_010', 6, 5), line('i_018', 12, 5)],
  }),

  // PARTIALLY_PAID
  inv({
    daysAgo: 12,
    partyIdx: 0,
    status: 'PARTIALLY_PAID',
    paid: 100_000_00,
    lines: [line('i_006', 18, 5), line('i_012', 12, 5)],
  }),
  inv({
    daysAgo: 14,
    partyIdx: 2,
    status: 'PARTIALLY_PAID',
    paid: 200_000_00,
    lines: [line('i_009', 8, 5), line('i_019', 4, 5)],
  }),
  inv({
    daysAgo: 18,
    partyIdx: 6,
    status: 'PARTIALLY_PAID',
    paid: 150_000_00,
    lines: [line('i_002', 30, 5), line('i_006', 8, 5)],
  }),
  inv({
    daysAgo: 22,
    partyIdx: 1,
    status: 'PARTIALLY_PAID',
    paid: 80_000_00,
    lines: [line('i_007', 22, 5), line('i_018', 18, 5)],
  }),
  inv({
    daysAgo: 25,
    partyIdx: 3,
    status: 'PARTIALLY_PAID',
    paid: 12_000_00,
    lines: [line('i_010', 8, 5), line('i_011', 6, 5)],
  }),
  inv({
    daysAgo: 28,
    partyIdx: 5,
    status: 'PARTIALLY_PAID',
    paid: 50_000_00,
    lines: [line('i_018', 30, 5), line('i_011', 14, 5)],
  }),

  // PAID
  inv({
    daysAgo: 32,
    partyIdx: 4,
    status: 'PAID',
    lines: [line('i_010', 6, 5), line('i_018', 8, 5)],
  }),
  inv({
    daysAgo: 35,
    partyIdx: 7,
    status: 'PAID',
    lines: [line('i_007', 14, 5)],
  }),
  inv({
    daysAgo: 40,
    partyIdx: 0,
    status: 'PAID',
    lines: [line('i_006', 8, 5), line('i_012', 6, 5)],
  }),
  inv({
    daysAgo: 45,
    partyIdx: 1,
    status: 'PAID',
    lines: [line('i_002', 16, 5)],
  }),
  inv({
    daysAgo: 52,
    partyIdx: 2,
    status: 'PAID',
    lines: [line('i_019', 2, 5)],
  }),

  // OVERDUE
  inv({
    daysAgo: 48,
    partyIdx: 0,
    status: 'OVERDUE',
    lines: [line('i_006', 12, 5), line('i_011', 18, 5)],
  }),
  inv({
    daysAgo: 56,
    partyIdx: 6,
    status: 'OVERDUE',
    lines: [line('i_002', 28, 5)],
  }),
  inv({
    daysAgo: 65,
    partyIdx: 2,
    status: 'OVERDUE',
    lines: [line('i_009', 4, 5)],
  }),
  inv({
    daysAgo: 78,
    partyIdx: 1,
    status: 'OVERDUE',
    lines: [line('i_018', 22, 5), line('i_011', 8, 5)],
  }),

  // CANCELLED
  inv({
    daysAgo: 9,
    partyIdx: 7,
    status: 'CANCELLED',
    lines: [line('i_010', 4, 5)],
  }),
];

export function findInvoice(id: string): Invoice | undefined {
  return invoices.find((i) => i.invoice_id === id);
}

export const overdueInvoices = invoices.filter((i) => i.status === 'OVERDUE');
export const draftInvoices = invoices.filter((i) => i.status === 'DRAFT');
export const recentInvoices = [...invoices].sort((a, b) => (b.date > a.date ? 1 : -1)).slice(0, 8);
