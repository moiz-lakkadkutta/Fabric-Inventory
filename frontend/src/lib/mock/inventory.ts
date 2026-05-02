import type { StageId } from './stages';

export interface SkuRow {
  sku_id: string;
  code: string;
  name: string;
  uom: 'METER' | 'PIECE' | 'KG';
  on_hand: number;
  reorder: number;
  // Status mix: pct of on_hand in each stage. Sums to 100.
  mix: Partial<Record<StageId, number>>;
  lots: number;
}

export const skuRows: SkuRow[] = [
  {
    sku_id: 'sku_001',
    code: 'SLK-GEO-60',
    name: 'Silk Georgette 60"',
    uom: 'METER',
    on_hand: 248.5,
    reorder: 100,
    mix: { RAW: 30, CUT: 10, AT_EMBROIDERY: 35, QC_PENDING: 8, FINISHED: 12, PACKED: 5 },
    lots: 6,
  },
  {
    sku_id: 'sku_002',
    code: 'BAN-SLK-42',
    name: 'Banarasi Silk 42"',
    uom: 'METER',
    on_hand: 142.0,
    reorder: 100,
    mix: { RAW: 50, AT_EMBROIDERY: 30, FINISHED: 20 },
    lots: 4,
  },
  {
    sku_id: 'sku_003',
    code: 'CHF-SLK-44',
    name: 'Chiffon Silk 44"',
    uom: 'METER',
    on_hand: 78.0,
    reorder: 100,
    mix: { RAW: 100 },
    lots: 2,
  },
  {
    sku_id: 'sku_004',
    code: 'KAN-PAT-44',
    name: 'Kanchipuram Pattu',
    uom: 'METER',
    on_hand: 312.0,
    reorder: 80,
    mix: { RAW: 18, CUT: 12, AT_STITCHING: 40, FINISHED: 22, PACKED: 8 },
    lots: 5,
  },
  {
    sku_id: 'sku_005',
    code: 'PLY-COT-44',
    name: 'Poly-Cotton 44"',
    uom: 'METER',
    on_hand: 940.0,
    reorder: 200,
    mix: { RAW: 60, CUT: 20, AT_STITCHING: 15, FINISHED: 5 },
    lots: 8,
  },
  {
    sku_id: 'sku_006',
    code: 'EMB-SUI-3P',
    name: 'Embroidered Suit (3-pc)',
    uom: 'PIECE',
    on_hand: 42,
    reorder: 20,
    mix: { AT_EMBROIDERY: 50, QC_PENDING: 25, FINISHED: 25 },
    lots: 3,
  },
  {
    sku_id: 'sku_007',
    code: 'COT-SAR-XL',
    name: 'Cotton Saree',
    uom: 'PIECE',
    on_hand: 86,
    reorder: 30,
    mix: { FINISHED: 70, PACKED: 30 },
    lots: 4,
  },
  {
    sku_id: 'sku_008',
    code: 'COT-YRN-40',
    name: 'Cotton Yarn 40s (kg)',
    uom: 'KG',
    on_hand: 18,
    reorder: 50,
    mix: { RAW: 100 },
    lots: 1,
  },
];

export interface LotStage {
  stage: StageId;
  state: 'done' | 'active' | 'future';
  title: string;
  when?: string;
  duration?: string;
  qty: string;
  counterparty: string;
  splits?: Array<{ who: string; qty: string; since: string; state: 'returning' | 'idle' }>;
  detail?: { op: string; cost: string; note: string };
}

export interface Lot {
  lot_id: string;
  code: string;
  sku_id: string;
  sku_name: string;
  opening_qty: string;
  current_qty: string;
  bin: string;
  stages: LotStage[];
}

export const lot001: Lot = {
  lot_id: 'lot_001',
  code: 'LOT/SLK-GEO-60/2025-Q4-018',
  sku_id: 'sku_001',
  sku_name: 'Silk Georgette 60"',
  opening_qty: '50.00 m',
  current_qty: '38.00 m',
  bin: 'W-1 / Rack-3 / Shelf-B',
  stages: [
    {
      stage: 'RAW',
      state: 'done',
      title: 'Received',
      when: '12-Mar-2026',
      duration: '6d',
      qty: '50.00 m',
      counterparty: 'GRN/25-26/00318 · Reliance Industries',
      detail: {
        op: 'GRN intake',
        cost: '₹185/m × 50m',
        note: 'Bin W-1 / Rack-3 / Shelf-B. QC sample passed.',
      },
    },
    {
      stage: 'CUT',
      state: 'done',
      title: 'Cut to pattern',
      when: '18-Mar-2026',
      duration: '0d',
      qty: '50.00 m → 50.00 m',
      counterparty: 'MO/25-26/000041 · Naseem (in-house)',
      detail: {
        op: 'Pattern A-402 · 25 panels',
        cost: '₹450 added (labour)',
        note: 'No wastage at cutting.',
      },
    },
    {
      stage: 'AT_EMBROIDERY',
      state: 'active',
      title: 'At embroidery',
      when: '18-Mar-2026',
      duration: '39d in stage',
      qty: '40.00 m · split sent',
      counterparty: 'Karigar Imran · Surat · ₹95/m',
      splits: [
        { who: 'Karigar Imran', qty: '40.00 m', since: '18-Mar', state: 'returning' },
        { who: 'Karigar Salim', qty: '10.00 m', since: '18-Mar', state: 'returning' },
      ],
      detail: {
        op: 'Aari work — bridal motif',
        cost: '₹95/m × 40m = ₹3,800 estimated',
        note: 'Imran returned 38m · 2m wastage logged 26-Apr (5%). Salim batch in progress, ETA 02-May.',
      },
    },
    {
      stage: 'QC_PENDING',
      state: 'active',
      title: 'QC review',
      when: '26-Apr-2026',
      duration: 'in progress',
      qty: '38.00 m',
      counterparty: 'Karigar Pooja',
      detail: {
        op: 'Visual + measure',
        cost: '—',
        note: 'First 12m passed. Remaining 26m queued for inspection.',
      },
    },
    {
      stage: 'AT_STITCHING',
      state: 'future',
      title: 'Stitching',
      qty: '—',
      counterparty: 'Karigar Salim (planned)',
    },
    {
      stage: 'FINISHED',
      state: 'future',
      title: 'Finished',
      qty: '—',
      counterparty: 'Goes to MO/25-26/000041',
    },
    {
      stage: 'PACKED',
      state: 'future',
      title: 'Packed',
      qty: '—',
      counterparty: 'Dispatch to Khan Sarees',
    },
  ],
};

export const lots: Lot[] = [lot001];

export function findLot(id: string): Lot | undefined {
  return lots.find((l) => l.lot_id === id);
}
