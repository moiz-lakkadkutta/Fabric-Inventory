import { describe, expect, it } from 'vitest';

import { gstinCheckDigit, gstinChecksumOk } from '@/lib/gstin';

// Same real GSTINs the backend test pins (tests/test_gstin_checksum.py).
const REAL = [
  '27AAACR5055K1Z7',
  '27AAACR5055K4Z4',
  '29AAACI4798L1ZU',
  '36AAACI4798L3ZX',
  '07AAACI4798L1Z0',
];

describe('GSTIN check digit (mirrors the server rule)', () => {
  it.each(REAL)('accepts real GSTIN %s', (g) => {
    expect(gstinCheckDigit(g.slice(0, 14))).toBe(g[14]);
    expect(gstinChecksumOk(g)).toBe(true);
  });

  it.each(['27AAACR5055K1Z8', '27AAACR5505K1Z7', '29AAACI4798L1ZT'])('rejects %s', (g) => {
    expect(gstinChecksumOk(g)).toBe(false);
  });

  it('is case-insensitive', () => {
    expect(gstinChecksumOk('27aaacr5055k1z7')).toBe(true);
  });
});
