import { suppliers } from './parties';

export type PoStatus = 'DRAFT' | 'OPEN' | 'GRN_RECEIVED' | 'INVOICED' | 'CLOSED' | 'CANCELLED';
export type MatchStatus = 'matched' | 'mismatched' | 'pending';

export interface PurchaseOrder {
  po_id: string;
  number: string;
  date: string; // dd-Mon-YY
  supplier_id: string;
  supplier_name: string;
  total: number; // paise
  status: PoStatus;
  // Three-way match: PO vs GRN vs PI
  po_match: MatchStatus;
  grn_match: MatchStatus;
  pi_match: MatchStatus;
  expected_date: string;
}

const POS = [
  {
    d: '12-Apr-26',
    s: 0,
    total: 222_214_00,
    st: 'GRN_RECEIVED',
    m: ['matched', 'mismatched', 'pending'],
    e: '20-Apr',
  },
  {
    d: '14-Apr-26',
    s: 1,
    total: 184_500_00,
    st: 'INVOICED',
    m: ['matched', 'matched', 'matched'],
    e: '22-Apr',
  },
  {
    d: '16-Apr-26',
    s: 2,
    total: 96_800_00,
    st: 'OPEN',
    m: ['pending', 'pending', 'pending'],
    e: '26-Apr',
  },
  {
    d: '20-Apr-26',
    s: 0,
    total: 312_400_00,
    st: 'OPEN',
    m: ['pending', 'pending', 'pending'],
    e: '02-May',
  },
  {
    d: '22-Apr-26',
    s: 1,
    total: 78_500_00,
    st: 'GRN_RECEIVED',
    m: ['matched', 'matched', 'pending'],
    e: '01-May',
  },
  {
    d: '24-Apr-26',
    s: 2,
    total: 142_900_00,
    st: 'INVOICED',
    m: ['matched', 'matched', 'matched'],
    e: '05-May',
  },
  {
    d: '26-Apr-26',
    s: 0,
    total: 56_700_00,
    st: 'CLOSED',
    m: ['matched', 'matched', 'matched'],
    e: '04-May',
  },
  {
    d: '28-Apr-26',
    s: 1,
    total: 24_500_00,
    st: 'DRAFT',
    m: ['pending', 'pending', 'pending'],
    e: '08-May',
  },
];

export const purchaseOrders: PurchaseOrder[] = POS.map((row, i) => {
  const s = suppliers[row.s % suppliers.length];
  const seq = 9000 + i + 1;
  return {
    po_id: `po_${seq}`,
    number: `PO/25-26/${String(seq - 9000).padStart(4, '0')}`,
    date: row.d,
    supplier_id: s.party_id,
    supplier_name: s.name,
    total: row.total,
    status: row.st as PoStatus,
    po_match: row.m[0] as MatchStatus,
    grn_match: row.m[1] as MatchStatus,
    pi_match: row.m[2] as MatchStatus,
    expected_date: row.e,
  };
});

export function findPurchaseOrder(id: string): PurchaseOrder | undefined {
  return purchaseOrders.find((p) => p.po_id === id);
}
