import { describe, expect, it } from 'vitest';

import { _internal } from '@/lib/queries/sales-orders';
import type { BackendSO } from '@/lib/api/sales-orders';

const { mapSO, buildCreateBody, rupeesToPaise, paiseToRupees } = _internal;

/*
 * TASK-CUT-203 — Sales-Order BE → FE mapper / FE → BE body builder.
 *
 * BE talks rupees-as-string; FE talks paise-as-int (CLAUDE.md money rule).
 * The mapper must round-trip cleanly: a BE row with line_amount "1500.00"
 * shows as 150_000 paise on the FE; a FE create draft with price 50000
 * paise sends "500.00" rupees on the wire.
 */

const SAMPLE_BE: BackendSO = {
  sales_order_id: '11111111-1111-1111-1111-111111111111',
  org_id: 'o1',
  firm_id: 'f1',
  series: 'SO/2526',
  number: '0001',
  party_id: 'p1',
  so_date: '2026-04-30',
  delivery_date: '2026-05-15',
  status: 'DRAFT',
  total_amount: '1500.00',
  notes: null,
  lines: [
    {
      so_line_id: 'l1',
      item_id: 'i1',
      qty_ordered: '3',
      qty_dispatched: null,
      price: '500.00',
      line_amount: '1500.00',
      gst_rate: '5',
      sequence: 1,
    },
  ],
  created_at: '2026-04-30T00:00:00Z',
  updated_at: '2026-04-30T00:00:00Z',
};

describe('rupeesToPaise / paiseToRupees', () => {
  it('rupees string "500.00" → 50000 paise', () => {
    expect(rupeesToPaise('500.00')).toBe(50_000);
  });

  it('rounds to nearest paise (no float-imprecision artifacts)', () => {
    expect(rupeesToPaise('1599.999')).toBe(160_000); // 159_999.9 rounds to 160_000
    expect(rupeesToPaise('1599.994')).toBe(159_999); // strict rounding
  });

  it('null / undefined / empty → 0', () => {
    expect(rupeesToPaise(null)).toBe(0);
    expect(rupeesToPaise(undefined)).toBe(0);
    expect(rupeesToPaise('')).toBe(0);
  });

  it('paiseToRupees round-trips through rupeesToPaise', () => {
    expect(rupeesToPaise(paiseToRupees(50_000))).toBe(50_000);
    expect(rupeesToPaise(paiseToRupees(1_234))).toBe(1_234);
  });
});

describe('mapSO — BE SOResponse → FE SalesOrder', () => {
  it('preserves identity fields and computes display_number', () => {
    const out = mapSO(SAMPLE_BE);
    expect(out.sales_order_id).toBe(SAMPLE_BE.sales_order_id);
    expect(out.series).toBe('SO/2526');
    expect(out.number).toBe('0001');
    expect(out.display_number).toBe('SO/2526/0001');
    expect(out.status).toBe('DRAFT');
    expect(out.party_id).toBe('p1');
  });

  it('converts total_amount from rupees-string to paise-int', () => {
    expect(mapSO(SAMPLE_BE).total_amount).toBe(150_000);
  });

  it('maps lines with correct paise + gst conversion', () => {
    const out = mapSO(SAMPLE_BE);
    expect(out.lines).toHaveLength(1);
    const line = out.lines[0];
    expect(line.qty_ordered).toBe(3);
    expect(line.qty_dispatched).toBe(0); // null on BE → 0 on FE
    expect(line.price).toBe(50_000);
    expect(line.line_amount).toBe(150_000);
    expect(line.gst_pct).toBe(5);
  });

  it('null total_amount maps to 0 (DRAFT before any lines)', () => {
    const out = mapSO({ ...SAMPLE_BE, total_amount: null });
    expect(out.total_amount).toBe(0);
  });
});

describe('buildCreateBody — FE input → BE SOCreateRequest', () => {
  it('converts paise prices back to rupees-as-string', () => {
    const body = buildCreateBody({
      firm_id: 'f1',
      party_id: 'p1',
      so_date: '2026-04-30',
      lines: [{ item_id: 'i1', qty_ordered: 3, price: 50_000, gst_pct: 5 }],
      idempotencyKey: 'k',
    });
    expect(body.lines[0].price).toBe('500.00');
    expect(body.lines[0].qty_ordered).toBe('3');
    expect(body.lines[0].gst_rate).toBe('5');
    expect(body.lines[0].sequence).toBe(1);
  });

  it('defaults series to SO/2526 and assigns sequence per line', () => {
    const body = buildCreateBody({
      firm_id: 'f1',
      party_id: 'p1',
      so_date: '2026-04-30',
      lines: [
        { item_id: 'i1', qty_ordered: 1, price: 100 },
        { item_id: 'i2', qty_ordered: 2, price: 200 },
      ],
      idempotencyKey: 'k',
    });
    expect(body.series).toBe('SO/2526');
    expect(body.lines[0].sequence).toBe(1);
    expect(body.lines[1].sequence).toBe(2);
  });

  it('refuses to build a body with zero lines', () => {
    expect(() =>
      buildCreateBody({
        firm_id: 'f1',
        party_id: 'p1',
        so_date: '2026-04-30',
        lines: [],
        idempotencyKey: 'k',
      }),
    ).toThrow(/at least one line/);
  });
});
