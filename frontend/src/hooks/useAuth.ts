import * as React from 'react';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { authStore, type MeResponse } from '@/store/auth';

/*
 * useAuthBootstrap — call once at app mount.
 *
 * Tries /auth/refresh against the httpOnly cookie. On success, populate
 * the access-token slot and fetch /auth/me to fill in user/firm/perms/
 * flags. On failure, mark unauthenticated.
 *
 * No-op in mock mode — the click-dummy doesn't have a backend to hit.
 * Returns nothing — components subscribe to authStore via useMe() etc.
 * The status transitions: unknown → authenticated | unauthenticated.
 */

export function useAuthBootstrap(): void {
  React.useEffect(() => {
    if (!IS_LIVE) return;
    if (authStore.get().status !== 'unknown') return;
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
        authStore.setMe(me);
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
