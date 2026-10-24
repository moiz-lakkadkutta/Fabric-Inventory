// Enrols TOTP MFA for the seeded Owner via the public API and saves the
// secret to .auth/ (gitignored) so record.mjs can log in unattended.
import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { markTotpUsed, totp } from './totp.mjs';
import { API, LOGIN } from './config.mjs';

async function post(path, body, token) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'idempotency-key': randomUUID(),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  if (!res.ok) throw new Error(`${path} → ${res.status} ${JSON.stringify(json)}`);
  return json;
}

const login = await post('/auth/login', LOGIN);
if (!login.requires_mfa_enrollment) {
  throw new Error('Owner is already enrolled; run prepare.sh to start from a clean DB.');
}
const setup = await post('/auth/mfa/setup', null, login.enrollment_token);
mkdirSync(new URL('./.auth/', import.meta.url), { recursive: true });
const at = Date.now();
await post('/auth/mfa/confirm', { code: totp(setup.secret, at) }, login.enrollment_token);
markTotpUsed(at);
writeFileSync(new URL('./.auth/totp-secret', import.meta.url), setup.secret, { mode: 0o600 });
console.log('MFA enrolled; secret saved to demo-video/.auth/totp-secret');
