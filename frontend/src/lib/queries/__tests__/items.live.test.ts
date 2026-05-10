import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { _internal } from '@/lib/queries/items';
import { authStore } from '@/store/auth';

const { mapItemDetail, mapSku, mapUom, mapHsn } = _internal;

beforeEach(() => {
  authStore.reset();
});

afterEach(() => {
  authStore.reset();
});

describe('items live-mode mappers', () => {
  it('mapItemDetail handles a fully-populated GST item', () => {
    const out = mapItemDetail({
      item_id: 'i-1',
      org_id: 'o',
      firm_id: 'f',
      code: 'COTSUIT',
      name: 'Cotton Suit',
      description: null,
      category: null,
      item_type: 'FINISHED',
      primary_uom: 'PIECE',
      tracking: 'NONE',
      hsn_code: '5208',
      gst_rate: '5',
      has_variants: false,
      has_expiry: false,
      is_active: true,
      created_at: '2026-04-30T00:00:00Z',
      updated_at: '2026-04-30T00:00:00Z',
      deleted_at: null,
    });
    expect(out.item_id).toBe('i-1');
    expect(out.code).toBe('COTSUIT');
    expect(out.name).toBe('Cotton Suit');
    expect(out.item_type).toBe('FINISHED');
    expect(out.primary_uom).toBe('PIECE');
    expect(out.hsn_code).toBe('5208');
    expect(out.gst_rate).toBe(5);
    expect(out.is_active).toBe(true);
  });

  it('mapItemDetail handles missing gst_rate (GST-exempt item — Bill of Supply scenario)', () => {
    const out = mapItemDetail({
      item_id: 'i-2',
      org_id: 'o',
      firm_id: null,
      code: 'EXEMPT',
      name: 'Exempt Item',
      description: null,
      category: null,
      item_type: 'RAW',
      primary_uom: 'METER',
      tracking: 'NONE',
      hsn_code: null,
      gst_rate: null,
      has_variants: null,
      has_expiry: null,
      is_active: null,
      created_at: '2026-04-30T00:00:00Z',
      updated_at: '2026-04-30T00:00:00Z',
      deleted_at: null,
    });
    // Critical: GST-exempt items must map gst_rate to 0 (not NaN, not undefined).
    // The InvoiceCreate dropdown reads this field directly into the invoice line.
    expect(out.gst_rate).toBe(0);
    expect(out.hsn_code).toBeNull();
    expect(out.is_active).toBe(true); // null defaults to true for legacy rows
  });

  it('mapSku passes attributes through', () => {
    const out = mapSku({
      sku_id: 's-1',
      org_id: 'o',
      firm_id: null,
      item_id: 'i-1',
      code: 'COTSUIT-RED-M',
      variant_attributes: { color: 'red', size: 'M' },
      barcode_ean13: null,
      default_cost: '450.00',
      created_at: '2026-04-30T00:00:00Z',
      updated_at: '2026-04-30T00:00:00Z',
      deleted_at: null,
    });
    expect(out.sku_id).toBe('s-1');
    expect(out.code).toBe('COTSUIT-RED-M');
    expect(out.attributes).toEqual({ color: 'red', size: 'M' });
  });

  it('mapSku handles null attributes', () => {
    const out = mapSku({
      sku_id: 's-2',
      org_id: 'o',
      firm_id: null,
      item_id: 'i-1',
      code: 'COTSUIT-DEFAULT',
      variant_attributes: null,
      barcode_ean13: null,
      default_cost: null,
      created_at: '2026-04-30T00:00:00Z',
      updated_at: '2026-04-30T00:00:00Z',
      deleted_at: null,
    });
    expect(out.attributes).toEqual({});
  });

  it('mapUom forwards code as the canonical enum value', () => {
    const out = mapUom({
      uom_id: 'u-1',
      code: 'METER',
      name: 'Meter',
      uom_type: 'METER',
    });
    expect(out.code).toBe('METER');
    expect(out.label).toBe('Meter');
  });

  it('mapHsn forwards hsn_code', () => {
    const out = mapHsn({
      hsn_id: 'h-1',
      hsn_code: '5208',
      description: 'Cotton Fabric',
      gst_rate: '5',
      is_rcm_applicable: false,
    });
    expect(out.hsn_code).toBe('5208');
    expect(out.description).toBe('Cotton Fabric');
    expect(out.gst_rate).toBe(5);
  });
});
