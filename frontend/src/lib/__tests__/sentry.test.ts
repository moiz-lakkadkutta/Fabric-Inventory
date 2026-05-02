import { describe, expect, it } from 'vitest';

import { _stripPII } from '@/lib/sentry';

describe('sentry _stripPII', () => {
  it('redacts email addresses', () => {
    expect(_stripPII('Sent to moiz@rajeshtextiles.in OK')).toBe('Sent to [EMAIL] OK');
  });

  it('redacts GSTIN', () => {
    expect(_stripPII('GSTIN 24AAACR5055K1Z5 invalid')).toBe('GSTIN [GSTIN] invalid');
  });

  it('redacts PAN', () => {
    expect(_stripPII('PAN ABCDE1234F mismatch')).toBe('PAN [PAN] mismatch');
  });

  it('handles strings without PII unchanged', () => {
    expect(_stripPII('Failed to fetch /v1/invoices')).toBe('Failed to fetch /v1/invoices');
  });
});
