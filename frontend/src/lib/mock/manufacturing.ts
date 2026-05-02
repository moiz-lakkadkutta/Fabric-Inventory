export type MoStage = 'PLANNED' | 'CUTTING' | 'EMBROIDERY' | 'STITCHING' | 'QC' | 'PACKED';

export interface ManufacturingOrder {
  mo_id: string;
  number: string;
  product: string;
  qty: number;
  uom: 'PIECE' | 'METER';
  customer: string;
  due_date: string;
  stage: MoStage;
  progress_pct: number;
  days_in_stage: number;
  std_days_in_stage: number;
}

export const manufacturingOrders: ManufacturingOrder[] = [
  {
    mo_id: 'mo_001',
    number: 'MO/25-26/00041',
    product: 'Bridal Lehenga · Pattern A-402',
    qty: 25,
    uom: 'PIECE',
    customer: 'Khan Sarees',
    due_date: '12-May',
    stage: 'EMBROIDERY',
    progress_pct: 55,
    days_in_stage: 39,
    std_days_in_stage: 28,
  },
  {
    mo_id: 'mo_002',
    number: 'MO/25-26/00042',
    product: 'Cotton Kurta Set · 200 pcs',
    qty: 200,
    uom: 'PIECE',
    customer: 'Patel Cloth Stores',
    due_date: '08-May',
    stage: 'STITCHING',
    progress_pct: 70,
    days_in_stage: 6,
    std_days_in_stage: 8,
  },
  {
    mo_id: 'mo_003',
    number: 'MO/25-26/00043',
    product: 'Silk Saree (premium) · Run 12',
    qty: 12,
    uom: 'PIECE',
    customer: 'Lakshmi Suit House',
    due_date: '15-May',
    stage: 'PLANNED',
    progress_pct: 0,
    days_in_stage: 1,
    std_days_in_stage: 2,
  },
  {
    mo_id: 'mo_004',
    number: 'MO/25-26/00044',
    product: 'Embroidered Suit · Run 38',
    qty: 38,
    uom: 'PIECE',
    customer: 'Sangeeta Traders',
    due_date: '06-May',
    stage: 'CUTTING',
    progress_pct: 35,
    days_in_stage: 4,
    std_days_in_stage: 3,
  },
  {
    mo_id: 'mo_005',
    number: 'MO/25-26/00045',
    product: 'Dupatta · Net Embroidered · Run 60',
    qty: 60,
    uom: 'PIECE',
    customer: 'Anjali Saree Centre',
    due_date: '10-May',
    stage: 'QC',
    progress_pct: 90,
    days_in_stage: 2,
    std_days_in_stage: 3,
  },
  {
    mo_id: 'mo_006',
    number: 'MO/25-26/00040',
    product: 'Cotton Saree · Run 80',
    qty: 80,
    uom: 'PIECE',
    customer: 'Devi Fashions',
    due_date: '04-May',
    stage: 'PACKED',
    progress_pct: 100,
    days_in_stage: 1,
    std_days_in_stage: 2,
  },
];

export const KANBAN_COLUMNS: Array<{ id: MoStage; label: string }> = [
  { id: 'PLANNED', label: 'Planned' },
  { id: 'CUTTING', label: 'Cutting' },
  { id: 'EMBROIDERY', label: 'Embroidery' },
  { id: 'STITCHING', label: 'Stitching' },
  { id: 'QC', label: 'QC' },
  { id: 'PACKED', label: 'Packed' },
];
