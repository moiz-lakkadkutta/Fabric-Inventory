// Mock data for the five reports in T6: P&L, Trial Balance, GSTR-1,
// Stock summary, Daybook. Numbers in paise unless noted.

export interface PnlRow {
  group: string;
  label: string;
  current: number; // paise
  previous: number; // paise
  bold?: boolean;
  divider?: boolean;
}

export const pnlRows: PnlRow[] = [
  { group: 'Income', label: 'Sales — Tax invoices', current: 14_82_000_00, previous: 12_18_000_00 },
  { group: 'Income', label: 'Sales — Bill of supply', current: 1_46_000_00, previous: 0 },
  { group: 'Income', label: 'Other income', current: 8_400_00, previous: 12_400_00 },
  {
    group: 'Income',
    label: 'Total income',
    current: 16_36_400_00,
    previous: 12_30_400_00,
    bold: true,
    divider: true,
  },
  { group: 'COGS', label: 'Opening stock', current: 18_00_000_00, previous: 14_50_000_00 },
  { group: 'COGS', label: 'Purchases', current: 9_84_500_00, previous: 8_22_000_00 },
  { group: 'COGS', label: 'Karigar payouts', current: 1_72_000_00, previous: 1_28_000_00 },
  { group: 'COGS', label: 'Less: closing stock', current: -19_42_000_00, previous: -18_00_000_00 },
  {
    group: 'COGS',
    label: 'Cost of goods sold',
    current: 10_14_500_00,
    previous: 6_00_000_00,
    bold: true,
    divider: true,
  },
  {
    group: 'GP',
    label: 'Gross profit',
    current: 6_21_900_00,
    previous: 6_30_400_00,
    bold: true,
    divider: true,
  },
  { group: 'Expenses', label: 'Salaries', current: 1_20_000_00, previous: 1_12_000_00 },
  { group: 'Expenses', label: 'Rent', current: 75_000_00, previous: 72_000_00 },
  { group: 'Expenses', label: 'Electricity', current: 38_400_00, previous: 31_200_00 },
  { group: 'Expenses', label: 'Other expenses', current: 28_400_00, previous: 22_500_00 },
  {
    group: 'Expenses',
    label: 'Total expenses',
    current: 2_61_800_00,
    previous: 2_37_700_00,
    bold: true,
    divider: true,
  },
  { group: 'NP', label: 'Net profit', current: 3_60_100_00, previous: 3_92_700_00, bold: true },
];

export interface TrialBalanceRow {
  account: string;
  group: string;
  debit: number; // paise
  credit: number; // paise
}

export const tbRows: TrialBalanceRow[] = [
  { account: 'Cash on hand', group: 'Asset', debit: 84_500_00, credit: 0 },
  { account: 'ICICI Bank — Current', group: 'Asset', debit: 12_45_000_00, credit: 0 },
  { account: 'HDFC Bank — Current', group: 'Asset', debit: 4_82_000_00, credit: 0 },
  { account: 'Sundry debtors', group: 'Asset', debit: 6_84_500_00, credit: 0 },
  { account: 'Stock — finished', group: 'Asset', debit: 12_40_000_00, credit: 0 },
  { account: 'Stock — raw', group: 'Asset', debit: 7_02_000_00, credit: 0 },
  { account: 'Sundry creditors', group: 'Liability', debit: 0, credit: 4_28_000_00 },
  { account: 'Karigar payable', group: 'Liability', debit: 0, credit: 1_18_000_00 },
  { account: 'GST output payable', group: 'Liability', debit: 0, credit: 1_84_500_00 },
  { account: 'GST input credit', group: 'Asset', debit: 1_42_000_00, credit: 0 },
  { account: 'Capital — owner', group: 'Equity', debit: 0, credit: 25_00_000_00 },
  { account: 'Reserves', group: 'Equity', debit: 0, credit: 6_45_000_00 },
  { account: 'Sales — tax', group: 'Income', debit: 0, credit: 14_82_000_00 },
  { account: 'Sales — non-GST', group: 'Income', debit: 0, credit: 1_46_000_00 },
  { account: 'Purchases', group: 'Expense', debit: 9_84_500_00, credit: 0 },
  { account: 'Salaries', group: 'Expense', debit: 1_20_000_00, credit: 0 },
];

export type GstrSection = 'B2B' | 'B2C' | 'CDNR' | 'EXP' | 'NIL';

export interface GstrRow {
  section: GstrSection;
  party: string;
  gstin: string;
  invoice: string;
  date: string;
  taxable: number; // paise
  igst: number;
  cgst: number;
  sgst: number;
  total: number;
  status: 'OK' | 'WARN' | 'ERROR';
}

export const gstrRows: GstrRow[] = [
  {
    section: 'B2B',
    party: 'Anjali Saree Centre',
    gstin: '27ABCDE1234F1Z5',
    invoice: 'RT/2526/0001',
    date: '30-Apr',
    taxable: 37_200_00,
    igst: 1_860_00,
    cgst: 0,
    sgst: 0,
    total: 39_060_00,
    status: 'OK',
  },
  {
    section: 'B2B',
    party: 'Lakshmi Suit House',
    gstin: '24XYZAB5678C2D9',
    invoice: 'RT/2526/0006',
    date: '25-Apr',
    taxable: 36_000_00,
    cgst: 900_00,
    sgst: 900_00,
    igst: 0,
    total: 37_800_00,
    status: 'OK',
  },
  {
    section: 'B2B',
    party: 'Devi Fashions',
    gstin: '06DEFGH9876I3J2',
    invoice: 'RT/2526/0005',
    date: '26-Apr',
    taxable: 27_180_00,
    igst: 1_359_00,
    cgst: 0,
    sgst: 0,
    total: 28_539_00,
    status: 'WARN',
  },
  {
    section: 'B2B',
    party: 'Sangeeta Traders',
    gstin: '24SANGE2222T1Z9',
    invoice: 'RT/2526/0003',
    date: '29-Apr',
    taxable: 22_000_00,
    cgst: 550_00,
    sgst: 550_00,
    igst: 0,
    total: 23_100_00,
    status: 'OK',
  },
  {
    section: 'B2B',
    party: 'Royal Fashions Vadodara',
    gstin: '24ROYAL3344V5Z2',
    invoice: 'RT/2526/0008',
    date: '22-Apr',
    taxable: 29_700_00,
    cgst: 742_50,
    sgst: 742_50,
    igst: 0,
    total: 31_185_00,
    status: 'OK',
  },
  {
    section: 'B2C',
    party: '— Walk-in',
    gstin: '—',
    invoice: 'RT/2526/0014',
    date: '05-Apr',
    taxable: 12_700_00,
    cgst: 317_50,
    sgst: 317_50,
    igst: 0,
    total: 13_335_00,
    status: 'OK',
  },
  {
    section: 'CDNR',
    party: 'Shree Krishna Vastra Bhandar',
    gstin: '24SHREE0099V8Z4',
    invoice: 'CN/2526/0003',
    date: '21-Apr',
    taxable: -3_800_00,
    cgst: -95_00,
    sgst: -95_00,
    igst: 0,
    total: -3_990_00,
    status: 'OK',
  },
];

export interface StockRow {
  code: string;
  name: string;
  uom: string;
  on_hand: number;
  rate: number; // paise
  value: number; // paise
}

export const stockRows: StockRow[] = [
  {
    code: 'SLK-GEO-60',
    name: 'Silk Georgette 60"',
    uom: 'METER',
    on_hand: 248.5,
    rate: 145_00,
    value: 36_032_50,
  },
  {
    code: 'BAN-SLK-42',
    name: 'Banarasi Silk 42"',
    uom: 'METER',
    on_hand: 142.0,
    rate: 890_00,
    value: 1_26_380_00,
  },
  {
    code: 'CHF-SLK-44',
    name: 'Chiffon Silk 44"',
    uom: 'METER',
    on_hand: 78.0,
    rate: 320_00,
    value: 24_960_00,
  },
  {
    code: 'KAN-PAT-44',
    name: 'Kanchipuram Pattu',
    uom: 'METER',
    on_hand: 312.0,
    rate: 1_840_00,
    value: 5_74_080_00,
  },
  {
    code: 'PLY-COT-44',
    name: 'Poly-Cotton 44"',
    uom: 'METER',
    on_hand: 940.0,
    rate: 92_00,
    value: 86_480_00,
  },
  {
    code: 'EMB-SUI-3P',
    name: 'Embroidered Suit (3-pc)',
    uom: 'PIECE',
    on_hand: 42,
    rate: 4_200_00,
    value: 1_76_400_00,
  },
  {
    code: 'COT-SAR-XL',
    name: 'Cotton Saree',
    uom: 'PIECE',
    on_hand: 86,
    rate: 1_400_00,
    value: 1_20_400_00,
  },
  {
    code: 'COT-YRN-40',
    name: 'Cotton Yarn 40s',
    uom: 'KG',
    on_hand: 18,
    rate: 320_00,
    value: 5_760_00,
  },
];

export interface DaybookEntry {
  date: string;
  voucher: string;
  kind: 'Sales' | 'Receipt' | 'Payment' | 'Journal' | 'Purchase';
  narration: string;
  debit: number;
  credit: number;
}

export const daybookEntries: DaybookEntry[] = [
  {
    date: '02-May',
    voucher: 'RC/25-26/0001',
    kind: 'Receipt',
    narration: 'Receipt — Anjali Saree Centre',
    debit: 1_84_000_00,
    credit: 0,
  },
  {
    date: '02-May',
    voucher: 'RT/2526/0001',
    kind: 'Sales',
    narration: 'Sale — Anjali Saree Centre',
    debit: 0,
    credit: 39_060_00,
  },
  {
    date: '02-May',
    voucher: 'JV/25-26/0014',
    kind: 'Journal',
    narration: 'GST input reclassification',
    debit: 18_400_00,
    credit: 18_400_00,
  },
  {
    date: '01-May',
    voucher: 'RC/25-26/0002',
    kind: 'Receipt',
    narration: 'Receipt — Devi Fashions',
    debit: 2_00_000_00,
    credit: 0,
  },
  {
    date: '01-May',
    voucher: 'PV/25-26/0021',
    kind: 'Payment',
    narration: 'Payment — Surat Silk Mills',
    debit: 0,
    credit: 84_500_00,
  },
  {
    date: '30-Apr',
    voucher: 'RT/2526/0002',
    kind: 'Sales',
    narration: 'Sale — Meera Boutique',
    debit: 0,
    credit: 3_990_00,
  },
  {
    date: '30-Apr',
    voucher: 'PI/25-26/0014',
    kind: 'Purchase',
    narration: 'PI — Surat Silk Mills',
    debit: 1_84_500_00,
    credit: 0,
  },
  {
    date: '29-Apr',
    voucher: 'RT/2526/0003',
    kind: 'Sales',
    narration: 'Sale — Sangeeta Traders',
    debit: 0,
    credit: 23_100_00,
  },
];
