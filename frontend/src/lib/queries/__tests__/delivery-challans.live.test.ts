import { describe, expect, it } from 'vitest';

import { _internal } from '@/lib/queries/delivery-challans';
import type { BackendDC } from '@/lib/api/delivery-challans';

const { mapDC, buildCreateBody } = _internal;

/*
 * TASK-CUT-203 — Delivery-Challan BE → FE mapper / FE → BE body builder.
 *
 * Same paise/rupees boundary as Sales Orders. DC is special in that
 * `price` is nullable on the BE (transfer / job-work DCs have no price),
 * so the FE shape preserves null to distinguish "no price set" from "₹0".
 */

const SAMPLE_BE: BackendDC = {
  delivery_challan_id: 'dc-1',
  org_id: 'o1',
  firm_id: 'f1',
  series: 'DC/2526',
  number: '0001',
  sales_order_id: 'so-1',
  party_id: 'p1',
  bill_to_address: '123 Lane',
  ship_to_address: '123 Lane',
  place_of_supply_state: 'MH',
  dispatch_date: '2026-05-01',
  status: 'DRAFT',
  total_qty: '3',
  total_amount: '1500.00',
  lines: [
    {
      dc_line_id: 'dl1',
      delivery_challan_id: 'dc-1',
      item_id: 'i1',
      lot_id: null,
      qty_dispatched: '3',
      price: '500.00',
      sequence: 1,
    },
  ],
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
};

describe('mapDC — BE DCResponse → FE DeliveryChallan', () => {
  it('preserves identity fields and computes display_number', () => {
    const out = mapDC(SAMPLE_BE);
    expect(out.delivery_challan_id).toBe('dc-1');
    expect(out.display_number).toBe('DC/2526/0001');
    expect(out.status).toBe('DRAFT');
    expect(out.sales_order_id).toBe('so-1');
  });

  it('converts amounts from rupees-string to paise-int', () => {
    const out = mapDC(SAMPLE_BE);
    expect(out.total_amount).toBe(150_000);
    expect(out.total_qty).toBe(3);
    expect(out.lines[0].price).toBe(50_000);
    expect(out.lines[0].qty_dispatched).toBe(3);
  });

  it('preserves null price (transfer DC, no price set)', () => {
    const out = mapDC({
      ...SAMPLE_BE,
      lines: [{ ...SAMPLE_BE.lines[0], price: null }],
    });
    expect(out.lines[0].price).toBeNull();
  });

  it('null total_amount → 0', () => {
    expect(mapDC({ ...SAMPLE_BE, total_amount: null }).total_amount).toBe(0);
  });
});

describe('buildCreateBody — FE input → BE DCCreateRequest', () => {
  it('serializes lines with paise → rupees and assigns sequence', () => {
    const body = buildCreateBody({
      firm_id: 'f1',
      party_id: 'p1',
      dispatch_date: '2026-05-01',
      sales_order_id: 'so-1',
      place_of_supply_state: 'MH',
      lines: [{ item_id: 'i1', qty_dispatched: 3, price: 50_000 }],
      idempotencyKey: 'k',
    });
    expect(body.series).toBe('DC/2526');
    expect(body.sales_order_id).toBe('so-1');
    expect(body.place_of_supply_state).toBe('MH');
    expect(body.lines[0].price).toBe('500.00');
    expect(body.lines[0].qty_dispatched).toBe('3');
    expect(body.lines[0].sequence).toBe(1);
  });

  it('omits price (null on wire) when not provided — transfer DC case', () => {
    const body = buildCreateBody({
      firm_id: 'f1',
      party_id: 'p1',
      dispatch_date: '2026-05-01',
      lines: [{ item_id: 'i1', qty_dispatched: 5 }],
      idempotencyKey: 'k',
    });
    expect(body.lines[0].price).toBeNull();
  });

  it('refuses to build a body with zero lines', () => {
    expect(() =>
      buildCreateBody({
        firm_id: 'f1',
        party_id: 'p1',
        dispatch_date: '2026-05-01',
        lines: [],
        idempotencyKey: 'k',
      }),
    ).toThrow(/at least one line/);
  });
});
