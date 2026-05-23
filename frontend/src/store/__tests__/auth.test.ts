import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { authStore, useFeatureFlag, useFeatureFlagWithDefault } from '@/store/auth';

const FAKE_ME = {
  user_id: 'u1',
  org_id: 'o1',
  firm_id: 'f1',
  email: 'fixture@example.com',
  permissions: ['sales.invoice.create'],
  flags: { 'gst.einvoice.enabled': false },
  available_firms: [{ firm_id: 'f1', code: 'RT', name: 'Rajesh Textiles' }],
  token_expires_at: '2099-01-01T00:00:00Z',
};

// CUT-006: override the global setupFile beforeEach so authStore-state
// tests see actually-unknown initial state.
beforeEach(() => {
  authStore.reset();
});

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

describe('useFeatureFlag / useFeatureFlagWithDefault (TASK-TR-A14)', () => {
  it('useFeatureFlag returns false for missing keys', () => {
    authStore.setMe({ ...FAKE_ME, flags: {} });
    const { result } = renderHook(() => useFeatureFlag('manufacturing.enabled'));
    expect(result.current).toBe(false);
  });

  it('useFeatureFlagWithDefault returns the default for missing keys', () => {
    authStore.setMe({ ...FAKE_ME, flags: {} });
    const { result } = renderHook(() => useFeatureFlagWithDefault('manufacturing.enabled', true));
    expect(result.current).toBe(true);
  });

  it('useFeatureFlagWithDefault returns the explicit value when set', () => {
    authStore.setMe({ ...FAKE_ME, flags: { 'manufacturing.enabled': false } });
    const { result } = renderHook(() => useFeatureFlagWithDefault('manufacturing.enabled', true));
    expect(result.current).toBe(false);
  });

  it('useFeatureFlagWithDefault returns the default when /me has not loaded', () => {
    // Pre-bootstrap: status='unknown', me=null. Prevents the nav from
    // flashing a hidden state on first paint.
    authStore.reset();
    const { result } = renderHook(() => useFeatureFlagWithDefault('manufacturing.enabled', true));
    expect(result.current).toBe(true);
  });
});
