// Adds the demo staff (one login per role) through the real invite flow:
// the Owner invites, each invitee accepts and sets a password. Needs
// ENVIRONMENT=dev, where the invite response carries the link. Run after
// enroll-mfa.mjs.
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { freshTotp } from './totp.mjs';
import { API, LOGIN, STAFF } from './config.mjs';

async function call(method, path, body, token) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      'content-type': 'application/json',
      ...(method === 'GET' ? {} : { 'idempotency-key': randomUUID() }),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${JSON.stringify(json)}`);
  return json;
}

const secret = readFileSync(new URL('./.auth/totp-secret', import.meta.url), 'utf8').trim();
const owner = await call('POST', '/auth/mfa-verify', {
  ...LOGIN,
  totp_code: await freshTotp(secret),
});
const { items: roles } = await call('GET', '/admin/roles', null, owner.access_token);

for (const person of Object.values(STAFF)) {
  const role = roles.find((r) => r.code === person.role);
  if (!role) throw new Error(`role ${person.role} not found`);
  const invite = await call(
    'POST',
    '/admin/invites',
    { email: person.email, role_id: role.role_id },
    owner.access_token,
  );
  if (!invite.invite_link)
    throw new Error('no invite_link: is the stack running with ENVIRONMENT=dev?');
  const token = new URL(invite.invite_link).pathname.split('/').pop();
  await call('POST', '/admin/invites/accept', {
    token,
    name: person.name,
    password: person.password,
  });
  console.log(`staff: ${person.name} (${role.name})`);
}
