/**
 * GSTIN check digit — the GSTN mod-36 rule over the first 14 characters.
 * Mirrors `gstin_check_digit` in backend/app/utils/gst_states.py, which is
 * authoritative (the server rejects a mismatch on party create / GSTIN
 * change). The client uses it only as an early warning.
 */
const ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';

export function gstinCheckDigit(first14: string): string {
  let total = 0;
  const s = first14.toUpperCase();
  for (let i = 0; i < s.length; i++) {
    const value = ALPHABET.indexOf(s[i]);
    if (value < 0) return '';
    const product = value * (i % 2 ? 2 : 1);
    total += Math.floor(product / 36) + (product % 36);
  }
  return ALPHABET[(36 - (total % 36)) % 36];
}

/** True when a 15-character GSTIN's last character is its check digit. */
export function gstinChecksumOk(gstin: string): boolean {
  const g = gstin.trim().toUpperCase();
  return g.length === 15 && gstinCheckDigit(g.slice(0, 14)) === g[14];
}
