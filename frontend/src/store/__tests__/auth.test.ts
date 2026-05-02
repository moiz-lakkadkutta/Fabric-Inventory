import { afterEach, describe, expect, it } from 'vitest';

import { authStore } from '@/store/auth';

const FAKE_ME = {
  user_id: 'u1',
  org_id: 'o1',
  firm_id: 'f1',
  permissions: ['sales.invoice.create'],
  flags: { 'gst.einvoice.enabled': false },
  token_expires_at: '2099-01-01T00:00:00Z',
};

afterEach(() => {
  authStore.reset();
});

describe('authStore', () => {
  it('starts in unknown status with no token / me', () => {
    const s = authStore.get();
    expect(s.status).toBe('unknown');
    expect(s.accessToken).toBeNull();
    expect(s.me).toBeNull();
  });

  it('setMe transitions to authenticated', () => {
    authStore.setMe(FAKE_ME);
    expect(authStore.get().status).toBe('authenticated');
    expect(authStore.get().me?.user_id).toBe('u1');
  });

  it('setMe(null) transitions to unauthenticated', () => {
    authStore.setMe(FAKE_ME);
    authStore.setMe(null);
    expect(authStore.get().status).toBe('unauthenticated');
  });

  it('clear() drops access token + me + flips status', () => {
    authStore.setAccessToken('t');
    authStore.setMe(FAKE_ME);
    authStore.clear();
    const s = authStore.get();
    expect(s.accessToken).toBeNull();
    expect(s.me).toBeNull();
    expect(s.status).toBe('unauthenticated');
  });

  it('subscribers fire on state change', () => {
    let calls = 0;
    const unsub = authStore.subscribe(() => {
      calls += 1;
    });
    authStore.setAccessToken('t');
    authStore.setMe(FAKE_ME);
    unsub();
    authStore.clear();
    expect(calls).toBe(2);
  });
});
