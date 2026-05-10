import { describe, expect, it } from 'vitest';

import { _internal } from '@/lib/queries/accounts';

const { mapVoucherListItem, mapBankAccount, mapCheque, mapParty, rupeesToPaise } = _internal;

describe('accounts live-mode mappers (CUT-103)', () => {
  it('mapVoucherListItem converts ₹ to paise and labels balanced rows', () => {
    const out = mapVoucherListItem({
      voucher_id: 'v1',
      voucher_type: 'RECEIPT',
      series: 'RCT/2526',
      number: '0001',
      voucher_date: '2026-04-30',
      narration: 'Receipt from party 0xabcd',
      total_debit: '525.00',
      total_credit: '525.00',
      status: 'POSTED',
      created_at: '2026-04-30T11:00:00Z',
    });
    expect(out.voucher_id).toBe('v1');
    expect(out.number).toBe('RCT/2526/0001');
    expect(out.voucher_type).toBe('RECEIPT');
    expect(out.kind).toBe('PAYMENT'); // RECEIPT collapses to PAYMENT pill
    expect(out.debit_total).toBe(52500);
    expect(out.credit_total).toBe(52500);
    expect(out.balanced).toBe(true);
  });

  it('mapVoucherListItem flags zero-amount or unbalanced rows', () => {
    const empty = mapVoucherListItem({
      voucher_id: 'v2',
      voucher_type: 'JOURNAL',
      series: 'JV',
      number: '0001',
      voucher_date: '2026-04-30',
      narration: null,
      total_debit: null,
      total_credit: null,
      status: 'DRAFT',
      created_at: '2026-04-30T11:00:00Z',
    });
    expect(empty.debit_total).toBe(0);
    expect(empty.credit_total).toBe(0);
    // 0 == 0 but the !> 0 guard keeps `balanced` false for empty rows.
    expect(empty.balanced).toBe(false);

    const skewed = mapVoucherListItem({
      voucher_id: 'v3',
      voucher_type: 'JOURNAL',
      series: 'JV',
      number: '0002',
      voucher_date: '2026-04-30',
      narration: 'Bad',
      total_debit: '100.00',
      total_credit: '99.50',
      status: 'POSTED',
      created_at: '2026-04-30T11:00:00Z',
    });
    expect(skewed.balanced).toBe(false);
  });

  it('mapBankAccount converts balance to paise and surfaces null fields as empty strings', () => {
    const view = mapBankAccount({
      bank_account_id: 'b1',
      org_id: 'o',
      firm_id: 'f',
      ledger_id: 'l',
      bank_name: 'HDFC Bank',
      account_number: '00123456789012',
      ifsc_code: 'HDFC0001234',
      account_type: 'CURRENT',
      balance: '100000.50',
      last_reconciled_date: '2026-04-30',
      created_at: '2026-04-30T11:00:00Z',
      updated_at: '2026-04-30T11:00:00Z',
    });
    expect(view.bank_name).toBe('HDFC Bank');
    expect(view.balance_paise).toBe(10000050);
    expect(view.last_reconciled_date).toBe('2026-04-30');

    const sparse = mapBankAccount({
      bank_account_id: 'b2',
      org_id: 'o',
      firm_id: 'f',
      ledger_id: 'l',
      bank_name: null,
      account_number: null,
      ifsc_code: null,
      account_type: null,
      balance: null,
      last_reconciled_date: null,
      created_at: '2026-04-30T11:00:00Z',
      updated_at: '2026-04-30T11:00:00Z',
    });
    expect(sparse.bank_name).toBe('');
    expect(sparse.balance_paise).toBe(0);
  });

  it('mapCheque converts amount to paise', () => {
    const c = mapCheque({
      cheque_id: 'c1',
      org_id: 'o',
      firm_id: 'f',
      bank_account_id: 'b',
      cheque_number: '000001',
      cheque_date: '2026-04-27',
      payee_name: 'Supplier Co',
      amount: '5000.00',
      status: 'ISSUED',
      clearing_date: null,
      bounce_reason: null,
      voucher_id: null,
      created_at: '2026-04-27T11:00:00Z',
      updated_at: '2026-04-27T11:00:00Z',
    });
    expect(c.amount_paise).toBe(500000);
    expect(c.status).toBe('ISSUED');
    expect(c.payee_name).toBe('Supplier Co');
  });

  it('mapParty trims to id/code/name', () => {
    const p = mapParty({
      party_id: 'p',
      org_id: 'o',
      firm_id: null,
      code: 'ANJ',
      name: 'Anjali Saree Centre',
      legal_name: null,
      is_supplier: false,
      is_customer: true,
      is_karigar: false,
      is_transporter: false,
      state_code: 'MH',
      is_active: true,
    });
    expect(p).toEqual({ party_id: 'p', code: 'ANJ', name: 'Anjali Saree Centre' });
  });

  it('rupeesToPaise rounds string amounts safely', () => {
    expect(rupeesToPaise('1000.00')).toBe(100000);
    expect(rupeesToPaise(null)).toBe(0);
    expect(rupeesToPaise(undefined)).toBe(0);
  });
});
