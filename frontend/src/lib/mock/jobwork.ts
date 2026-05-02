export interface Karigar {
  karigar_id: string;
  name: string;
  city: string;
  ops: string[];
  open_orders: number;
  active_qty: string;
  rate: string;
  on_time_pct: number;
}

export const karigars: Karigar[] = [
  {
    karigar_id: 'kar_001',
    name: 'Imran Khan',
    city: 'Surat',
    ops: ['Aari', 'Zardozi'],
    open_orders: 4,
    active_qty: '110.00 m',
    rate: '₹95/m',
    on_time_pct: 92,
  },
  {
    karigar_id: 'kar_002',
    name: 'Salim Sheikh',
    city: 'Surat',
    ops: ['Aari', 'Beadwork'],
    open_orders: 3,
    active_qty: '64.00 m',
    rate: '₹85/m',
    on_time_pct: 88,
  },
  {
    karigar_id: 'kar_003',
    name: 'Pooja Devi',
    city: 'Ahmedabad',
    ops: ['QC', 'Stitching'],
    open_orders: 2,
    active_qty: '42 pieces',
    rate: '₹60/pc',
    on_time_pct: 96,
  },
  {
    karigar_id: 'kar_004',
    name: 'Naseem Begum',
    city: 'Surat',
    ops: ['Cutting', 'Stitching'],
    open_orders: 5,
    active_qty: '180 pieces',
    rate: '₹45/pc',
    on_time_pct: 84,
  },
  {
    karigar_id: 'kar_005',
    name: 'Rakesh Patel',
    city: 'Vapi',
    ops: ['Dyeing', 'Finishing'],
    open_orders: 2,
    active_qty: '320.00 m',
    rate: '₹28/m',
    on_time_pct: 78,
  },
];

export type JobStatus = 'SENT' | 'IN_PROGRESS' | 'PARTIAL_RETURN' | 'COMPLETED' | 'BREACHED';

export interface JobOrder {
  job_id: string;
  number: string;
  karigar_id: string;
  karigar_name: string;
  op: string;
  sent_qty: string;
  returned_qty: string;
  sent_date: string;
  due_date: string;
  status: JobStatus;
  wastage_pct?: number;
}

export const jobs: JobOrder[] = [
  {
    job_id: 'job_001',
    number: 'JO/25-26/00102',
    karigar_id: 'kar_001',
    karigar_name: 'Imran Khan',
    op: 'Aari embroidery',
    sent_qty: '40.00 m',
    returned_qty: '38.00 m',
    sent_date: '18-Mar',
    due_date: '02-May',
    status: 'PARTIAL_RETURN',
    wastage_pct: 5,
  },
  {
    job_id: 'job_002',
    number: 'JO/25-26/00103',
    karigar_id: 'kar_002',
    karigar_name: 'Salim Sheikh',
    op: 'Aari embroidery',
    sent_qty: '10.00 m',
    returned_qty: '0.00 m',
    sent_date: '18-Mar',
    due_date: '02-May',
    status: 'IN_PROGRESS',
  },
  {
    job_id: 'job_003',
    number: 'JO/25-26/00104',
    karigar_id: 'kar_004',
    karigar_name: 'Naseem Begum',
    op: 'Stitching',
    sent_qty: '120 pieces',
    returned_qty: '120 pieces',
    sent_date: '02-Apr',
    due_date: '15-Apr',
    status: 'COMPLETED',
  },
  {
    job_id: 'job_004',
    number: 'JO/25-26/00105',
    karigar_id: 'kar_005',
    karigar_name: 'Rakesh Patel',
    op: 'Dyeing',
    sent_qty: '320.00 m',
    returned_qty: '0.00 m',
    sent_date: '12-Apr',
    due_date: '22-Apr',
    status: 'BREACHED',
    wastage_pct: 0,
  },
  {
    job_id: 'job_005',
    number: 'JO/25-26/00106',
    karigar_id: 'kar_003',
    karigar_name: 'Pooja Devi',
    op: 'QC review',
    sent_qty: '38.00 m',
    returned_qty: '12.00 m',
    sent_date: '26-Apr',
    due_date: '01-May',
    status: 'IN_PROGRESS',
  },
  {
    job_id: 'job_006',
    number: 'JO/25-26/00107',
    karigar_id: 'kar_001',
    karigar_name: 'Imran Khan',
    op: 'Zardozi work',
    sent_qty: '20.00 m',
    returned_qty: '20.00 m',
    sent_date: '20-Mar',
    due_date: '10-Apr',
    status: 'COMPLETED',
  },
];
