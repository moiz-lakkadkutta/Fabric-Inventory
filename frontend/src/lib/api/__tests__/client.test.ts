import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api, ApiError } from '@/lib/api/client';
import { authStore } from '@/store/auth';

/*
 * api() client unit tests.
 *
 * Mocks global.fetch directly so we can drive 401 → refresh → retry
 * without spinning up a server. The store gets reset between tests.
 */

const ENVELOPE_401 = {
  code: 'TOKEN_INVALID',
  title: 'Token invalid',
  detail: 'expired',
  status: 401,
  field_errors: {},
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  authStore.reset();
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('api()', () => {
  it('rejects mutating calls without an idempotency key', async () => {
    await expect(api('/auth/login', { method: 'POST', body: {} })).rejects.toThrow(
      /Idempotency-Key required/,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('attaches the access token as Bearer', async () => {
    authStore.setAccessToken('access-123');
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await api('/auth/me');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer access-123');
  });

  it('decodes the Q8a envelope into ApiError on non-2xx', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(409, {
        code: 'INVOICE_ALREADY_FINALIZED',
        title: 'Invoice already finalized',
        detail: 'try refresh',
        status: 409,
        field_errors: {},
      }),
    );

    const err = await api('/v1/invoices/abc/finalize', {
      method: 'POST',
      idempotencyKey: 'k1',
      body: {},
    }).catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe('INVOICE_ALREADY_FINALIZED');
    expect((err as ApiError).status).toBe(409);
  });

  it('on 401: refreshes once, populates new token, retries the original call', async () => {
    authStore.setAccessToken('stale-token');

    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, ENVELOPE_401)) // first /auth/me
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh-token' })) // /auth/refresh
      .mockResolvedValueOnce(jsonResponse(200, { user_id: 'u1' })); // retry of /auth/me

    const result = await api<{ user_id: string }>('/auth/me');

    expect(result.user_id).toBe('u1');
    expect(authStore.get().accessToken).toBe('fresh-token');
    expect(fetchMock).toHaveBeenCalledTimes(3);
    // The retry call carries the new bearer.
    const retryHeaders = fetchMock.mock.calls[2][1].headers as Record<string, string>;
    expect(retryHeaders.Authorization).toBe('Bearer fresh-token');
  });

  it('on 401: refresh fails → ApiError surfaces; store is cleared', async () => {
    authStore.setAccessToken('stale-token');

    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, ENVELOPE_401))
      .mockResolvedValueOnce(jsonResponse(401, ENVELOPE_401));

    const err = await api('/auth/me').catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe('TOKEN_INVALID');
    expect(authStore.get().accessToken).toBeNull();
  });

  it('falls back to a synthetic UNKNOWN envelope on non-JSON 5xx', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('<html>502 Bad Gateway</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      }),
    );

    const err = await api('/anything').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe('UNKNOWN');
    expect((err as ApiError).status).toBe(502);
  });
});
