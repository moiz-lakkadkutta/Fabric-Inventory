import type { VoucherTypeRaw } from '@/lib/mock/accounts';

// Display label per backend voucher_type.
const VOUCHER_TYPE_LABEL: Record<VoucherTypeRaw, string> = {
  SALES_INVOICE: 'Sales invoice',
  PURCHASE_INVOICE: 'Purchase invoice',
  PAYMENT: 'Payment',
  RECEIPT: 'Receipt',
  JOURNAL: 'Journal',
  CONTRA: 'Contra',
  DEBIT_NOTE: 'Debit note',
  CREDIT_NOTE: 'Credit note',
  OPENING_BAL: 'Opening balance',
};

// #216: a cancel reversal that is NOT a CGST §34 credit note (same-period
// cancellation, Bill of Supply / branch transfer, duplicate reversal) is
// still voucher_type CREDIT_NOTE but numbered in the internal CXL/<FY>
// series. It is not a GST document, so don't call it a credit note.
const CANCELLATION_REVERSAL_PREFIX = 'CXL/';

/** Label for a voucher given its type and full number (series/number). */
export function voucherTypeLabel(voucherType: VoucherTypeRaw, fullNumber: string): string {
  if (voucherType === 'CREDIT_NOTE' && fullNumber.startsWith(CANCELLATION_REVERSAL_PREFIX)) {
    return 'Cancellation reversal';
  }
  return VOUCHER_TYPE_LABEL[voucherType];
}
