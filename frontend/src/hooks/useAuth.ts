import * as React from 'react';

import { api, ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { currentUser, defaultFirm, firms } from '@/lib/mock/identity';
import { maybeAutoSwitchSingleFirm } from '@/lib/queries/identity';
import { authStore, type MeResponse } from '@/store/auth';

/*
 * useAuthBootstrap — call once at app mount.
 *
 * Live mode: tries /auth/refresh against the httpOnly cookie. On
 * success, populate the access-token slot and fetch /auth/me to fill
 * in user/firm/perms/flags. A 503 + Retry-After is retried once
 * (`refreshOnBoot`). On any other failure, clear the store (status flips
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
      // TASK-TR-B2: needed so the click-dummy "Import parties" button
      // isn't permanently disabled in mock mode.
      'masters.party.create',
      // TASK-TR-B4: click-dummy "current user" is the Owner — surface
      // the custom-role-builder buttons on the Admin page.
      'identity.role.create',
      'identity.role.update',
      'identity.role.delete',
      'identity.role.read',
    ],
    flags: {},
    available_firms: firms.map((f) => ({ firm_id: f.firm_id, code: f.code, name: f.name })),
    token_expires_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
  };
}

/** Longest Retry-After we honour on boot before giving up (seconds). */
const BOOT_RETRY_MAX_SECONDS = 5;

function postRefresh(): Promise<{ access_token: string }> {
  return api<{ access_token: string }>('/auth/refresh', {
    method: 'POST',
    idempotencyKey: crypto.randomUUID(),
    body: {},
    skipRefresh: true,
  });
}

/**
 * Q01-10: a 503 with Retry-After from /auth/refresh (LOCK_TIMEOUT /
 * DEADLOCK_DETECTED — another tab is rotating the same token family) is
 * transient and the token was NOT consumed. Wait once and retry before
 * treating the session as gone; anything else propagates (→ logged out).
 */
export async function refreshOnBoot(
  isCancelled: () => boolean = () => false,
): Promise<{ access_token: string }> {
  try {
    return await postRefresh();
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 503 || err.retry_after === undefined) {
      throw err;
    }
    const waitMs = Math.min(err.retry_after, BOOT_RETRY_MAX_SECONDS) * 1000;
    await new Promise((resolve) => setTimeout(resolve, waitMs));
    if (isCancelled()) throw err;
    return postRefresh();
  }
}

/*
 * Single-flight guard for the live bootstrap (DEBT-04).
 *
 * In dev, <StrictMode> runs every effect twice (mount → cleanup →
 * mount). Firing /auth/refresh from each run sends two requests with
 * the same rotating cookie; the backend revokes the presented session
 * row, so whichever request lands second gets 401. If that loser is the
 * live (second-mount) request, the old code called authStore.clear()
 * and logged the user out on a perfectly valid page load — the root
 * cause of the intermittent E2E acceptance hangs on PR #185.
 *
 * Both effect runs now await the same promise. It is dropped once it
 * settles so a later bootstrap (e.g. a test that calls
 * authStore.reset()) starts fresh.
 */
let bootstrapInFlight: Promise<MeResponse> | null = null;

function bootstrapLive(): Promise<MeResponse> {
  if (bootstrapInFlight) return bootstrapInFlight;
  bootstrapInFlight = (async () => {
    try {
      const tokens = await refreshOnBoot();
      authStore.setAccessToken(tokens.access_token);
      const me = await api<MeResponse>('/auth/me');
      return await maybeAutoSwitchSingleFirm(me);
    } finally {
      bootstrapInFlight = null;
    }
  })();
  return bootstrapInFlight;
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

    bootstrapLive().then(
      (settled) => {
        if (!cancelled) authStore.setMe(settled);
      },
      () => {
        // Any failure → unauthenticated. The router gates protected pages
        // and redirects to /login.
        if (!cancelled) authStore.clear();
      },
    );

    return () => {
      cancelled = true;
    };
  }, []);
}
