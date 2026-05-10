import * as React from 'react';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { currentUser, defaultFirm, firms } from '@/lib/mock/identity';
import { maybeAutoSwitchSingleFirm } from '@/lib/queries/identity';
import { authStore, type MeResponse } from '@/store/auth';

/*
 * useAuthBootstrap — call once at app mount.
 *
 * Live mode: tries /auth/refresh against the httpOnly cookie. On
 * success, populate the access-token slot and fetch /auth/me to fill
 * in user/firm/perms/flags. On failure, clear the store (status flips
 * to 'unauthenticated' and `<RequireAuth>` redirects to /login).
 *
 * Mock mode: synthesizes a `me` payload from the mock identity
 * fixtures so the click-dummy stays usable end-to-end. Without this
 * synth, `<RequireAuth>` would block every protected route in dev
 * because there's no live /auth/me to hit.
 *
 * Returns nothing — components subscribe to authStore via useMe() etc.
 * The status transitions: unknown → authenticated | unauthenticated.
 */

function buildMockMe(): MeResponse {
  return {
    user_id: currentUser.user_id,
    org_id: 'mock-org',
    firm_id: defaultFirm.firm_id,
    email: currentUser.email,
    permissions: [
      // Wide-open in mock so every "Coming soon"-gated CTA works the same.
      'sales.invoice.create',
      'sales.invoice.finalize',
      'accounting.voucher.post',
      'admin.user.invite',
    ],
    flags: {},
    available_firms: firms.map((f) => ({ firm_id: f.firm_id, code: f.code, name: f.name })),
    token_expires_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
  };
}

export function useAuthBootstrap(): void {
  React.useEffect(() => {
    if (authStore.get().status !== 'unknown') return;

    if (!IS_LIVE) {
      // Click-dummy: synth a `me` so RequireAuth + UserMenu + FirmSwitcher
      // all render normally. Tests can still call authStore.reset() in
      // setup to exercise the unknown / unauthenticated branches.
      authStore.setMe(buildMockMe());
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        const tokens = await api<{ access_token: string }>('/auth/refresh', {
          method: 'POST',
          idempotencyKey: crypto.randomUUID(),
          body: {},
          skipRefresh: true,
        });
        if (cancelled) return;
        authStore.setAccessToken(tokens.access_token);

        const me = await api<MeResponse>('/auth/me');
        if (cancelled) return;
        const settled = await maybeAutoSwitchSingleFirm(me);
        if (cancelled) return;
        authStore.setMe(settled);
      } catch {
        // Any failure → unauthenticated. The router gates protected pages
        // and redirects to /login.
        if (!cancelled) authStore.clear();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);
}
