// Domain types for the mock layer. Mirror the backend schema where it
// matters for visual feel; collapse irrelevant fields. Real types come
// from the OpenAPI spec once routers exist (TASK-008+).

export type FirmId = string;
export type UserId = string;
export type PartyId = string;
export type ItemId = string;
export type InvoiceId = string;

export interface User {
  user_id: UserId;
  email: string;
  legal_name: string;
  initials: string;
  role: 'Owner' | 'Accountant' | 'Sales' | 'Admin';
}

export interface Firm {
  firm_id: FirmId;
  code: string;
  name: string;
  legal_name: string;
  gstin: string;
  state_code: string;
  state_name: string;
  address: string;
  has_gst: boolean;
}

export type PartyKind = 'customer' | 'supplier' | 'karigar' | 'transporter';

export interface Party {
  party_id: PartyId;
  code: string;
  name: string;
  kind: PartyKind;
  gstin?: string;
  state_code: string;
  city: string;
  outstanding: number; // paise
  credit_limit?: number; // paise
}

export interface Item {
  item_id: ItemId;
  code: string;
  name: string;
  type: 'RAW' | 'FINISHED' | 'SEMI_FINISHED';
  hsn: string;
  uom: 'METER' | 'PIECE' | 'KG';
  rate: number; // paise per uom
  stock_qty: number;
  reorder_level?: number;
}

export type InvoiceStatus =
  | 'DRAFT'
  | 'FINALIZED'
  | 'PAID'
  | 'PARTIALLY_PAID'
  | 'OVERDUE'
  | 'CANCELLED';

export interface InvoiceLine {
  item_id: ItemId;
  item_name: string;
  qty: number;
  uom: string;
  rate: number; // paise
  amount: number; // paise
  gst_pct: number;
  gst_amount: number; // paise
}

export interface Invoice {
  invoice_id: InvoiceId;
  number: string;
  date: string; // ISO yyyy-mm-dd
  due_date: string;
  party_id: PartyId;
  party_name: string;
  party_state: string;
  status: InvoiceStatus;
  subtotal: number; // paise
  gst_total: number; // paise
  total: number; // paise
  paid: number; // paise
  ageing_days: number; // negative = upcoming, positive = overdue
  lines: InvoiceLine[];
  doc_type: 'TAX_INVOICE' | 'BILL_OF_SUPPLY' | 'CASH_MEMO' | 'ESTIMATE';
}

export interface Kpi {
  key: string;
  label: string;
  value: number; // paise (or count)
  unit: '₹' | 'count';
  delta_pct: number;
  delta_kind: 'positive' | 'negative' | 'neutral';
  spark: number[];
}

export interface ActivityItem {
  id: string;
  ts: string; // ISO
  kind: 'invoice_finalized' | 'payment_received' | 'po_approved' | 'low_stock' | 'gst_filed';
  title: string;
  detail: string;
  amount?: number;
  party?: string;
}
