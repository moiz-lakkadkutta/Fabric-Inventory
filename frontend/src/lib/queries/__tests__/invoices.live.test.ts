import { afterEach, describe, expect, it } from 'vitest';

import { _internal } from '@/lib/queries/invoices';
import { authStore } from '@/store/auth';

const {
  mapDetail,
  mapListItem,
  mapStatus,
  rupeesToPaise,
  ageingDays,
  paiseToRupees,
  buildCreateBody,
} = _internal;

afterEach(() => {
  authStore.reset();
});

describe('invoices live-mode mappers', () => {
  it('rupeesToPaise rounds Decimal-as-string into paise integers', () => {
    expect(rupeesToPaise('1000.50')).toBe(100050);
    expect(rupeesToPaise('1000.555')).toBe(100056); // banker-style not required; nearest-integer is fine
    expect(rupeesToPaise(null)).toBe(0);
    expect(rupeesToPaise('0')).toBe(0);
  });

  it('mapStatus collapses backend lifecycle states to the frontend enum', () => {
    expect(mapStatus('DRAFT')).toBe('DRAFT');
    expect(mapStatus('CONFIRMED')).toBe('DRAFT');
    expect(mapStatus('FINALIZED')).toBe('FINALIZED');
    expect(mapStatus('POSTED')).toBe('FINALIZED');
    expect(mapStatus('PARTIALLY_PAID')).toBe('PARTIALLY_PAID');
    expect(mapStatus('PAID')).toBe('PAID');
    expect(mapStatus('OVERDUE')).toBe('OVERDUE');
    expect(mapStatus('DISCARDED')).toBe('CANCELLED');
    expect(mapStatus('something-else')).toBe('DRAFT');
  });

  it('ageingDays computes positive when due_date is in the past', () => {
    const today = new Date('2026-04-30T12:00:00Z');
    expect(ageingDays('2026-04-25', today)).toBe(5);
    expect(ageingDays('2026-05-05', today)).toBeLessThan(0);
    expect(ageingDays(null, today)).toBe(0);
  });

  it('mapListItem populates totals + status without lines', () => {
    const out = mapListItem({
      sales_invoice_id: 'si_1',
      firm_id: 'f_1',
      series: 'RT/2526',
      number: '0042',
      party_id: 'p_1',
      party_name: 'Anjali Saree Centre',
      invoice_date: '2026-04-30',
      due_date: '2026-05-15',
      invoice_amount: '254100.00',
      paid_amount: '0.00',
      lifecycle_status: 'FINALIZED',
      place_of_supply_state: '24',
      created_at: '2026-04-30T11:42:00Z',
    });
    expect(out.invoice_id).toBe('si_1');
    expect(out.number).toBe('RT/2526/0042');
    expect(out.total).toBe(25410000);
    expect(out.paid).toBe(0);
    expect(out.status).toBe('FINALIZED');
    expect(out.party_name).toBe('Anjali Saree Centre');
    expect(out.lines).toEqual([]);
  });

  it('mapDetail maps lines + computes subtotal as total minus gst', () => {
    const out = mapDetail({
      sales_invoice_id: 'si_2',
      org_id: 'o',
      firm_id: 'f',
      series: 'RT/2526',
      number: '0007',
      party_id: 'p',
      party_name: 'Sangeeta Traders',
      invoice_date: '2026-04-29',
      due_date: '2026-05-14',
      invoice_amount: '318200.00',
      gst_amount: '15910.00',
      paid_amount: '0',
      lifecycle_status: 'FINALIZED',
      place_of_supply_state: '24',
      invoice_type: null,
      tax_type: 'CGST_SGST',
      round_off: '0',
      notes: null,
      lines: [
        {
          si_line_id: 'l1',
          item_id: 'i1',
          item_name: 'Chiffon Silk',
          item_uom: 'METER',
          qty: '100.0000',
          price: '3000',
          line_amount: '300000',
          gst_rate: '5',
          gst_amount: '15000',
          sequence: 1,
        },
      ],
      created_at: '2026-04-29T16:30:00Z',
      updated_at: '2026-04-29T16:30:00Z',
    });
    expect(out.total).toBe(31820000);
    expect(out.gst_total).toBe(1591000);
    expect(out.subtotal).toBe(31820000 - 1591000);
    expect(out.lines).toHaveLength(1);
    expect(out.lines[0].uom).toBe('METER');
    expect(out.lines[0].qty).toBe(100);
    expect(out.lines[0].rate).toBe(300000); // 3000 rupees → 300000 paise
    expect(out.doc_type).toBe('TAX_INVOICE');
  });

  it('mapDetail derives BILL_OF_SUPPLY for nil-rated tax types', () => {
    const out = mapDetail({
      sales_invoice_id: 'si',
      org_id: 'o',
      firm_id: 'f',
      series: 'RT',
      number: '1',
      party_id: 'p',
      party_name: null,
      invoice_date: '2026-04-30',
      due_date: null,
      invoice_amount: '1000',
      gst_amount: '0',
      paid_amount: '0',
      lifecycle_status: 'DRAFT',
      place_of_supply_state: null,
      invoice_type: null,
      tax_type: 'NIL_LUT',
      round_off: '0',
      notes: null,
      lines: [],
      created_at: '2026-04-30T00:00:00Z',
      updated_at: '2026-04-30T00:00:00Z',
    });
    expect(out.doc_type).toBe('BILL_OF_SUPPLY');
  });
});

describe('buildCreateBody (T-INT-4)', () => {
  it('throws when authStore has no firm_id', () => {
    expect(() =>
      buildCreateBody({
        date: '2026-04-30',
        due_date: '2026-05-15',
        party_id: 'p_1',
        party_name: 'X',
        party_state: 'MH',
        subtotal: 0,
        gst_total: 0,
        total: 0,
        paid: 0,
        ageing_days: 0,
        lines: [],
        doc_type: 'TAX_INVOICE',
      }),
    ).toThrow(/No active firm/);
  });

  it('converts paise → rupees-as-string and forwards line shape', () => {
    authStore.setMe({
      user_id: 'u',
      org_id: 'o',
      firm_id: 'f1',
      permissions: ['sales.invoice.create'],
      flags: {},
      token_expires_at: '2099-01-01T00:00:00Z',
    });

    const body = buildCreateBody({
      date: '2026-04-30',
      due_date: '2026-05-15',
      party_id: 'p_1',
      party_name: 'Anjali',
      party_state: 'MH',
      subtotal: 1000000, // ₹10,000.00 in paise
      gst_total: 50000,
      total: 1050000,
      paid: 0,
      ageing_days: 0,
      lines: [
        {
          item_id: 'i_1',
          item_name: 'Chiffon',
          qty: 10,
          uom: 'METER',
          rate: 100000, // ₹1000.00 in paise
          amount: 1000000,
          gst_pct: 5,
          gst_amount: 50000,
        },
      ],
      doc_type: 'TAX_INVOICE',
    });

    expect(body.firm_id).toBe('f1');
    expect(body.party_id).toBe('p_1');
    expect(body.invoice_date).toBe('2026-04-30');
    expect(body.due_date).toBe('2026-05-15');
    expect(body.ship_to_state).toBe('MH');
    expect(body.lines).toHaveLength(1);
    expect(body.lines[0].qty).toBe('10');
    expect(body.lines[0].price).toBe('1000.00'); // 100000 paise → "1000.00"
    expect(body.lines[0].gst_rate).toBe('5');
    expect(body.lines[0].sequence).toBe(1);
  });
});

describe('paiseToRupees', () => {
  it('formats integers to two decimals', () => {
    expect(paiseToRupees(0)).toBe('0.00');
    expect(paiseToRupees(100050)).toBe('1000.50');
    expect(paiseToRupees(1)).toBe('0.01');
  });
});
