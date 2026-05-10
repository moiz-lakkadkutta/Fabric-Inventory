/*
 * Backend response shapes for the items / SKUs / UOMs / HSN endpoints.
 *
 * Kept here (rather than in `lib/queries/items.ts`) so future masters
 * pages — InvoiceCreate's item dropdown, the soon-to-arrive Stock
 * Adjustments dialog, etc. — can import the type without depending on
 * the React-Query hook module.
 *
 * These will be replaced by `pnpm run openapi:gen` output (CUT-106).
 * Until then, hand-rolled to match `backend/app/schemas/masters.py`.
 */

export type BackendItemType =
  | 'RAW'
  | 'SEMI_FINISHED'
  | 'FINISHED'
  | 'SERVICE'
  | 'CONSUMABLE'
  | 'BY_PRODUCT'
  | 'SCRAP';

export type BackendUomType =
  | 'METER'
  | 'PIECE'
  | 'KG'
  | 'LITER'
  | 'SET'
  | 'GROSS'
  | 'DOZEN'
  | 'ROLL'
  | 'BUNDLE'
  | 'OTHER';

export type BackendTrackingType = 'NONE' | 'BATCH' | 'LOT' | 'SERIAL';

export interface BackendItem {
  item_id: string;
  org_id: string;
  firm_id: string | null;
  code: string;
  name: string;
  description: string | null;
  category: string | null;
  item_type: BackendItemType;
  primary_uom: BackendUomType;
  tracking: BackendTrackingType | null;
  hsn_code: string | null;
  gst_rate: string | null;
  has_variants: boolean | null;
  has_expiry: boolean | null;
  is_active: boolean | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface BackendItemListResponse {
  items: BackendItem[];
  limit: number;
  offset: number;
  count: number;
}

export interface BackendSku {
  sku_id: string;
  org_id: string;
  firm_id: string | null;
  item_id: string;
  code: string;
  variant_attributes: Record<string, unknown> | null;
  barcode_ean13: string | null;
  default_cost: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface BackendSkuListResponse {
  items: BackendSku[];
  count: number;
}

export interface BackendUom {
  uom_id: string;
  code: BackendUomType;
  name: string;
  uom_type: BackendUomType;
}

export interface BackendUomListResponse {
  items: BackendUom[];
  count: number;
}

export interface BackendHsn {
  hsn_id: string;
  hsn_code: string;
  description: string | null;
  gst_rate: string | null;
  is_rcm_applicable: boolean | null;
}

export interface BackendHsnListResponse {
  items: BackendHsn[];
  count: number;
}

/**
 * Frontend-shaped versions of the above. These are what hooks return.
 */

export interface ItemDetail {
  item_id: string;
  firm_id: string | null;
  code: string;
  name: string;
  description: string | null;
  category: string | null;
  item_type: BackendItemType;
  primary_uom: BackendUomType;
  tracking: BackendTrackingType;
  hsn_code: string | null;
  /** GST rate as percentage (5 = 5%). 0 means GST-exempt. */
  gst_rate: number;
  has_variants: boolean;
  has_expiry: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SkuDetail {
  sku_id: string;
  firm_id: string | null;
  item_id: string;
  code: string;
  /** Variant attributes flattened from `variant_attributes`. Empty when null. */
  attributes: Record<string, unknown>;
  barcode_ean13: string | null;
  default_cost: number | null; // paise
  created_at: string;
  updated_at: string;
}

export interface UomChoice {
  code: BackendUomType;
  label: string;
}

export interface HsnChoice {
  hsn_id: string;
  hsn_code: string;
  description: string | null;
  /** GST rate as percentage (e.g. 5). null when the HSN row has no rate. */
  gst_rate: number | null;
}

export interface ItemCreateBody {
  code: string;
  name: string;
  item_type: BackendItemType;
  primary_uom: BackendUomType;
  // BE looks up HSN by the digit code (NOT the UUID) — see schemas/masters.py.
  hsn_code?: string;
  gst_rate?: string; // Decimal-as-string per BE convention
  description?: string;
  category?: string;
  firm_id?: string;
  has_variants?: boolean;
  has_expiry?: boolean;
  tracking?: BackendTrackingType;
  is_active?: boolean;
}

export interface SkuCreateBody {
  code: string;
  variant_attributes?: Record<string, unknown> | null;
  barcode_ean13?: string;
  default_cost?: string; // Decimal-as-string per BE convention
  firm_id?: string;
}
