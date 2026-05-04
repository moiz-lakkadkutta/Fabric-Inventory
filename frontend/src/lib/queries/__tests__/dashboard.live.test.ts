import { describe, expect, it } from 'vitest';

import { _internal } from '@/lib/queries/dashboard';

const { mapKpi, mapActivity } = _internal;

describe('dashboard live-mode mappers', () => {
  it('mapKpi converts ₹ values from rupees to paise', () => {
    const kpi = mapKpi({
      key: 'outstanding_ar',
      label: 'Outstanding receivables',
      value: '12345.67',
      unit: '₹',
      delta_pct: '0',
      delta_kind: 'negative',
      spark: [],
    });
    expect(kpi.value).toBe(1234567); // 12345.67 → 1,234,567 paise
    expect(kpi.unit).toBe('₹');
    expect(kpi.delta_kind).toBe('negative');
  });

  it('mapKpi passes count units through unchanged', () => {
    const kpi = mapKpi({
      key: 'low_stock_skus',
      label: 'Stocked-out SKUs',
      value: '4',
      unit: 'count',
      delta_pct: '0',
      delta_kind: 'negative',
      spark: [],
    });
    expect(kpi.value).toBe(4);
    expect(kpi.unit).toBe('count');
  });

  it('mapKpi parses delta_pct from string', () => {
    const kpi = mapKpi({
      key: 'sales_today',
      label: 'Sales today',
      value: '0',
      unit: '₹',
      delta_pct: '12.5',
      delta_kind: 'positive',
      spark: [],
    });
    expect(kpi.delta_pct).toBe(12.5);
  });

  it('mapActivity narrows entity_type.action into the click-dummy kind', () => {
    const out = mapActivity({
      id: 'a1',
      ts: '2026-04-30T10:00:00Z',
      kind: 'sales.invoice.finalize',
      title: 'Invoice finalized',
      detail: null,
      actor_user_id: null,
    });
    expect(out.kind).toBe('invoice_finalized');
    expect(out.detail).toBe('');
  });

  it('mapActivity has a fallback for unknown kinds', () => {
    const out = mapActivity({
      id: 'a2',
      ts: '2026-04-30T10:00:00Z',
      kind: 'something.random.action',
      title: 'unknown',
      detail: 'some detail',
      actor_user_id: null,
    });
    expect(out.kind).toBe('invoice_finalized');
    expect(out.detail).toBe('some detail');
  });
});
