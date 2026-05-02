import { customers, suppliers } from './parties';

export type ReceiptStatus = 'POSTED' | 'PENDING' | 'BOUNCED';

export interface Receipt {
  receipt_id: string;
  number: string;
  date: string; // dd-Mon-YY
  party_id: string;
  party_name: string;
  amount: number; // paise
  mode: 'CASH' | 'BANK' | 'UPI' | 'CHEQUE';
  reference: string;
  status: ReceiptStatus;
  allocated_to: string[]; // invoice numbers
}

const R = [
  {
    d: '02-May-26',
    s: 0,
    amt: 184_000_00,
    m: 'BANK',
    ref: 'NEFT-998211',
    st: 'POSTED',
    alloc: ['RT/2526/0010', 'RT/2526/0001'],
  },
  {
    d: '01-May-26',
    s: 1,
    amt: 200_000_00,
    m: 'UPI',
    ref: 'UPI-AX912/04',
    st: 'POSTED',
    alloc: ['RT/2526/0011'],
  },
  {
    d: '30-Apr-26',
    s: 2,
    amt: 150_000_00,
    m: 'CHEQUE',
    ref: 'CHQ-7748811',
    st: 'PENDING',
    alloc: ['RT/2526/0012'],
  },
  {
    d: '28-Apr-26',
    s: 3,
    amt: 80_000_00,
    m: 'BANK',
    ref: 'NEFT-998104',
    st: 'POSTED',
    alloc: ['RT/2526/0013'],
  },
  {
    d: '26-Apr-26',
    s: 4,
    amt: 50_000_00,
    m: 'CASH',
    ref: '—',
    st: 'POSTED',
    alloc: ['RT/2526/0014'],
  },
  {
    d: '24-Apr-26',
    s: 1,
    amt: 12_705_00,
    m: 'UPI',
    ref: 'UPI-BX221/12',
    st: 'POSTED',
    alloc: ['RT/2526/0016'],
  },
  {
    d: '22-Apr-26',
    s: 2,
    amt: 17_640_00,
    m: 'BANK',
    ref: 'NEFT-997800',
    st: 'POSTED',
    alloc: ['RT/2526/0017'],
  },
  {
    d: '20-Apr-26',
    s: 0,
    amt: 25_000_00,
    m: 'CHEQUE',
    ref: 'CHQ-7748752',
    st: 'BOUNCED',
    alloc: ['RT/2526/0021'],
  },
  {
    d: '18-Apr-26',
    s: 5,
    amt: 46_620_00,
    m: 'BANK',
    ref: 'NEFT-997600',
    st: 'POSTED',
    alloc: ['RT/2526/0018'],
  },
  {
    d: '14-Apr-26',
    s: 3,
    amt: 14_952_00,
    m: 'UPI',
    ref: 'UPI-CX441/05',
    st: 'POSTED',
    alloc: ['RT/2526/0019'],
  },
];

export const receipts: Receipt[] = R.map((row, i) => {
  const c = customers[row.s % customers.length];
  const seq = 5000 + i + 1;
  return {
    receipt_id: `rcp_${seq}`,
    number: `RC/25-26/${String(seq - 5000).padStart(4, '0')}`,
    date: row.d,
    party_id: c.party_id,
    party_name: c.name,
    amount: row.amt,
    mode: row.m as Receipt['mode'],
    reference: row.ref,
    status: row.st as ReceiptStatus,
    allocated_to: row.alloc,
  };
});

export type VoucherKind = 'JOURNAL' | 'PAYMENT' | 'CONTRA' | 'EXPENSE';

export interface Voucher {
  voucher_id: string;
  number: string;
  date: string;
  kind: VoucherKind;
  narration: string;
  debit_total: number; // paise
  credit_total: number; // paise
  balanced: boolean;
}

export const vouchers: Voucher[] = [
  {
    voucher_id: 'v_001',
    number: 'JV/25-26/0014',
    date: '02-May-26',
    kind: 'JOURNAL',
    narration: 'GST input reclassification',
    debit_total: 18_400_00,
    credit_total: 18_400_00,
    balanced: true,
  },
  {
    voucher_id: 'v_002',
    number: 'PV/25-26/0021',
    date: '01-May-26',
    kind: 'PAYMENT',
    narration: `Payment to ${suppliers[0].name}`,
    debit_total: 84_500_00,
    credit_total: 84_500_00,
    balanced: true,
  },
  {
    voucher_id: 'v_003',
    number: 'CV/25-26/0008',
    date: '30-Apr-26',
    kind: 'CONTRA',
    narration: 'Cash to ICICI current',
    debit_total: 50_000_00,
    credit_total: 50_000_00,
    balanced: true,
  },
  {
    voucher_id: 'v_004',
    number: 'EV/25-26/0033',
    date: '29-Apr-26',
    kind: 'EXPENSE',
    narration: 'Electricity bill — Apr',
    debit_total: 12_400_00,
    credit_total: 12_400_00,
    balanced: true,
  },
  {
    voucher_id: 'v_005',
    number: 'JV/25-26/0015',
    date: '28-Apr-26',
    kind: 'JOURNAL',
    narration: 'Stock adjustment — wastage',
    debit_total: 8_200_00,
    credit_total: 8_200_00,
    balanced: true,
  },
  {
    voucher_id: 'v_006',
    number: 'PV/25-26/0022',
    date: '26-Apr-26',
    kind: 'PAYMENT',
    narration: `Karigar payout — Imran`,
    debit_total: 38_000_00,
    credit_total: 38_000_00,
    balanced: true,
  },
];
