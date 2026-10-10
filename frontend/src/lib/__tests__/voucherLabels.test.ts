import { describe, expect, it } from 'vitest';

import { voucherTypeLabel } from '@/lib/voucherLabels';

describe('voucherTypeLabel (#216)', () => {
  it('labels a §34 credit note as a credit note', () => {
    expect(voucherTypeLabel('CREDIT_NOTE', 'CN/26-27/0001')).toBe('Credit note');
  });

  it('labels a legacy credit note (invoice series) as a credit note', () => {
    expect(voucherTypeLabel('CREDIT_NOTE', 'RT/2526/0001')).toBe('Credit note');
  });

  it('labels an internal CXL reversal as a cancellation reversal', () => {
    expect(voucherTypeLabel('CREDIT_NOTE', 'CXL/26-27/0001')).toBe('Cancellation reversal');
  });

  it('labels other voucher types by type', () => {
    expect(voucherTypeLabel('RECEIPT', 'RCPT/0001')).toBe('Receipt');
    expect(voucherTypeLabel('SALES_INVOICE', 'RT/2526/0001')).toBe('Sales invoice');
  });
});
