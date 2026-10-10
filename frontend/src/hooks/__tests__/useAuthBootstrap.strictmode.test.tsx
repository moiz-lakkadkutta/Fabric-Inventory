import { render, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * DEBT-04 regression — the E2E acceptance stack runs the Vite dev
 * server, where <StrictMode> mounts → unmounts → re-mounts every effect.
 * useAuthBootstrap used to fire POST /auth/refresh once per mount, so
 * every full page load sent TWO refreshes with the same rotating cookie.
 * The backend revokes the presented session row on refresh, so whichever
 * request committed second got 401. When the loser was the live
 * (second-mount) request, authStore.clear() logged the user out and the
 * page under test never rendered — CI saw a 10-minute locator.click hang
 * (PR #185, run 30696670939: refresh 200 then 401 six ms apart, then no
 * further API traffic).
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { useAuthBootstrap } = await import('@/hooks/useAuth');
const { authStore } = await import('@/store/auth');

function Probe() {
  useAuthBootstrap();
  return null;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const ME = {
  user_id: 'u1',
  org_id: 'o1',
  firm_id: 'f1',
  email: 'owner@example.com',
  permissions: [],
  flags: {},
  available_firms: [{ firm_id: 'f1', code: 'HQ', name: 'HQ' }],
  token_expires_at: new Date(Date.now() + 3600_000).toISOString(),
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  authStore.reset();
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

function refreshCalls() {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh'));
}

describe('useAuthBootstrap under <StrictMode>', () => {
  it('sends exactly one /auth/refresh per page load', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/refresh')) return json(200, { access_token: 'at-1' });
      if (url.endsWith('/auth/me')) return json(200, ME);
      throw new Error(`unexpected fetch ${url}`);
    });

    render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );

    await waitFor(() => expect(authStore.get().status).toBe('authenticated'));
    expect(refreshCalls()).toHaveLength(1);
  });

  it('stays signed in when a duplicate refresh would have lost the rotation race', async () => {
    // Model the server: the first refresh with the cookie rotates it;
    // any later refresh presenting the same cookie is rejected.
    let rotated = false;
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/refresh')) {
        if (rotated) return json(401, { error: { code: 'TOKEN_INVALID', message: 'revoked' } });
        rotated = true;
        return json(200, { access_token: 'at-1' });
      }
      if (url.endsWith('/auth/me')) return json(200, ME);
      throw new Error(`unexpected fetch ${url}`);
    });

    render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );

    await waitFor(() => expect(authStore.get().status).not.toBe('unknown'));
    expect(authStore.get().status).toBe('authenticated');
    expect(authStore.get().accessToken).toBe('at-1');
  });
});
