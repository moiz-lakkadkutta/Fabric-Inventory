// RFC 6238 TOTP (SHA-1, 30 s, 6 digits) — what pyotp and authenticator apps use.
import { createHmac } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';

function base32Decode(input) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const clean = input.replace(/=+$/, '').toUpperCase();
  let bits = 0;
  let value = 0;
  const out = [];
  for (const ch of clean) {
    value = (value << 5) | alphabet.indexOf(ch);
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

export function totp(secret, at = Date.now()) {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const hmac = createHmac('sha1', base32Decode(secret)).update(counter).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, '0');
}

// Codes are single-use (replay guard), even across processes, so remember the
// last 30 s window used in .auth/ and wait for a later one.
const stamp = new URL('./.auth/last-totp-window', import.meta.url);
export async function freshTotp(secret) {
  const last = existsSync(stamp) ? Number(readFileSync(stamp, 'utf8')) : 0;
  let window = Math.floor(Date.now() / 30000);
  while (window <= last) {
    await new Promise((r) => setTimeout(r, 1000));
    window = Math.floor(Date.now() / 30000);
  }
  writeFileSync(stamp, String(window));
  return totp(secret);
}
