import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { _internal } from '@/lib/queries/purchase-orders';
import { authStore } from '@/store/auth';

const { mapPo, mapPoListItem, mapStatus, rupeesToPaise, paiseToRupees, buildCreateBody } =
  _internal;

/*
 * Unit tests for the purchase-order live-mode mapper shim.
 *
 * Backend ships:
 *   - PurchaseOrderStatus enum: DRAFT | APPROVED | CONFIRMED | PARTIAL_GRN | FULLY_RECEIVED | CANCELLED
 *   - Money as Decimal-as-string in rupees
 *   - po_date in YYYY-MM-DD
 *   - response includes lines with qty_ordered (string), rate (string), line_amount (string|null)
 *
 * Frontend uses:
 *   - PoStatus enum: DRAFT | OPEN | GRN_RECEIVED | INVOICED | CLOSED | CANCELLED
 *     (mapped from BE status; APPROVED/CONFIRMED → OPEN; PARTIAL_GRN/FULLY_RECEIVED → GRN_RECEIVED)
 *   - Money as paise (integer) for the lifecycle list view consumption
 */

const SAMPLE_PO = {
  purchase_order_id: '11111111-1111-1111-1111-111111111111',
  org_id: 'o',
  firm_id: 'f',
  series: 'PO/25-26',
  number: '0001',
  party_id: 'p1',
  po_date: '2026-04-12',
  delivery_date: '2026-04-20',
  status: 'DRAFT' as const,
  total_amount: '22221.40',
  notes: null,
  lines: [
    {
      po_line_id: 'l1',
      item_id: 'i1',
      qty_ordered: '10.000',
      qty_received: '0.000',
      rate: '500.00',
      line_amount: '5000.00',
      line_sequence: 1,
      taxes_applicable: null,
      notes: null,
    },
  ],
  created_at: '2026-04-12T00:00:00Z',
  updated_at: '2026-04-12T00:00:00Z',
};

beforeEach(() => {
  authStore.reset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('mapStatus — BE PurchaseOrderStatus → FE PoStatus', () => {
  it('DRAFT stays DRAFT', () => {
    expect(mapStatus('DRAFT')).toBe('DRAFT');
  });

  it('APPROVED collapses to OPEN', () => {
    expect(mapStatus('APPROVED')).toBe('OPEN');
  });

  it('CONFIRMED collapses to OPEN', () => {
    expect(mapStatus('CONFIRMED')).toBe('OPEN');
  });

  it('PARTIAL_GRN → GRN_RECEIVED', () => {
    expect(mapStatus('PARTIAL_GRN')).toBe('GRN_RECEIVED');
  });

  it('FULLY_RECEIVED → CLOSED', () => {
    expect(mapStatus('FULLY_RECEIVED')).toBe('CLOSED');
  });

  it('CANCELLED stays CANCELLED', () => {
    expect(mapStatus('CANCELLED')).toBe('CANCELLED');
  });

  it('unknown status falls back to DRAFT', () => {
    expect(mapStatus('SOMETHING_ELSE')).toBe('DRAFT');
  });
});

describe('rupeesToPaise / paiseToRupees', () => {
  it('rupeesToPaise rounds to nearest paise', () => {
    expect(rupeesToPaise('1000.50')).toBe(100050);
    expect(rupeesToPaise('999.999')).toBe(100000);
    expect(rupeesToPaise(null)).toBe(0);
    expect(rupeesToPaise(undefined)).toBe(0);
  });

  it('paiseToRupees emits a fixed-2 string', () => {
    expect(paiseToRupees(100050)).toBe('1000.50');
    expect(paiseToRupees(0)).toBe('0.00');
  });
});

describe('mapPo — full BE PO → FE PurchaseOrder', () => {
  it('preserves po_id, number, supplier_id, total in paise, lines', () => {
    const out = mapPo(SAMPLE_PO);
    expect(out.po_id).toBe(SAMPLE_PO.purchase_order_id);
    expect(out.number).toBe('PO/25-26/0001');
    expect(out.supplier_id).toBe('p1');
    expect(out.total).toBe(2222140);
    expect(out.status).toBe('DRAFT');
    expect(out.lines ?? []).toHaveLength(1);
    expect(out.lines?.[0]?.qty).toBe(10);
    expect(out.lines?.[0]?.rate).toBe(50000);
    expect(out.lines?.[0]?.amount).toBe(500000);
  });

  it('null total_amount maps to 0 paise', () => {
    const out = mapPo({ ...SAMPLE_PO, total_amount: null });
    expect(out.total).toBe(0);
  });

  it('null delivery_date maps to empty expected_date', () => {
    const out = mapPo({ ...SAMPLE_PO, delivery_date: null });
    expect(out.expected_date).toBe('');
  });
});

describe('mapPoListItem — list-row variant uses the same shape', () => {
  it('maps the list item without losing supplier info', () => {
    const out = mapPoListItem(SAMPLE_PO);
    expect(out.po_id).toBe(SAMPLE_PO.purchase_order_id);
    expect(out.number).toBe('PO/25-26/0001');
    expect(out.total).toBe(2222140);
  });
});

describe('buildCreateBody — FE draft → BE POCreateRequest', () => {
  it('rejects when no firm in auth store', () => {
    expect(() =>
      buildCreateBody(
        {
          supplier_id: 'p1',
          po_date: '2026-04-12',
          expected_date: '2026-04-20',
          lines: [{ item_id: 'i1', qty: 10, rate: 50000, gst_pct: 5 }],
        },
        'PO/25-26',
      ),
    ).toThrow(/active firm/i);
  });

  it('builds the right shape with paise→rupees conversion', () => {
    authStore.reset();
    authStore.setAccessToken('t');
    authStore.setMe({
      user_id: 'u',
      email: 'e',
      org_id: 'o',
      firm_id: 'f',
      permissions: [],
      flags: {},
      available_firms: [],
      token_expires_at: '2026-12-31T00:00:00Z',
    });
    const body = buildCreateBody(
      {
        supplier_id: 'p1',
        po_date: '2026-04-12',
        expected_date: '2026-04-20',
        lines: [{ item_id: 'i1', qty: 10, rate: 50000, gst_pct: 5 }],
      },
      'PO/25-26',
    );
    expect(body.firm_id).toBe('f');
    expect(body.party_id).toBe('p1');
    expect(body.po_date).toBe('2026-04-12');
    expect(body.delivery_date).toBe('2026-04-20');
    expect(body.series).toBe('PO/25-26');
    expect(body.lines).toHaveLength(1);
    expect(body.lines[0].item_id).toBe('i1');
    expect(body.lines[0].qty_ordered).toBe('10');
    expect(body.lines[0].rate).toBe('500.00');
    expect(body.lines[0].line_sequence).toBe(1);
  });

  it('omits delivery_date when expected_date is empty', () => {
    authStore.reset();
    authStore.setAccessToken('t');
    authStore.setMe({
      user_id: 'u',
      email: 'e',
      org_id: 'o',
      firm_id: 'f',
      permissions: [],
      flags: {},
      available_firms: [],
      token_expires_at: '2026-12-31T00:00:00Z',
    });
    const body = buildCreateBody(
      {
        supplier_id: 'p1',
        po_date: '2026-04-12',
        expected_date: '',
        lines: [{ item_id: 'i1', qty: 10, rate: 50000, gst_pct: 5 }],
      },
      'PO/25-26',
    );
    expect(body.delivery_date).toBeNull();
  });
});
