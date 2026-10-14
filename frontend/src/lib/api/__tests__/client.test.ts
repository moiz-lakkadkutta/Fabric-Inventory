import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api, ApiError, IN_PROGRESS_MAX_RETRIES } from '@/lib/api/client';
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

/*
 * Q01-01: the backend answers a concurrent duplicate (same Idempotency-Key)
 * with 409 IDEMPOTENCY_REQUEST_IN_PROGRESS + Retry-After. api() waits and
 * re-sends the SAME request (same key + body) so the caller ends up with the
 * single 201, served as a replay.
 */
describe('api() — IDEMPOTENCY_REQUEST_IN_PROGRESS retry', () => {
  function inProgress(retryAfter: string | null = '1'): Response {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (retryAfter !== null) headers['Retry-After'] = retryAfter;
    return new Response(
      JSON.stringify({
        code: 'IDEMPOTENCY_REQUEST_IN_PROGRESS',
        title: 'Request already in progress',
        detail: 'A request with this Idempotency-Key is still being processed; retry shortly.',
        status: 409,
        field_errors: {},
      }),
      { status: 409, headers },
    );
  }

  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('retries with the same key and body after Retry-After and returns the replayed 201', async () => {
    fetchMock
      .mockResolvedValueOnce(inProgress('2'))
      .mockResolvedValueOnce(jsonResponse(201, { party_id: 'p1' }));

    const promise = api<{ party_id: string }>('/parties', {
      method: 'POST',
      idempotencyKey: 'key-1',
      body: { code: 'A' },
    });
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(promise).resolves.toEqual({ party_id: 'p1' });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [first, second] = fetchMock.mock.calls.map((c) => c[1] as RequestInit);
    const h1 = first.headers as Record<string, string>;
    const h2 = second.headers as Record<string, string>;
    expect(h2['Idempotency-Key']).toBe('key-1');
    expect(h2['Idempotency-Key']).toBe(h1['Idempotency-Key']);
    expect(second.body).toBe(first.body);
    expect(second.method).toBe('POST');
  });

  it('defaults to a 1s wait when Retry-After is absent', async () => {
    fetchMock
      .mockResolvedValueOnce(inProgress(null))
      .mockResolvedValueOnce(jsonResponse(201, { ok: true }));
    const promise = api('/parties', { method: 'POST', idempotencyKey: 'k', body: {} });
    await vi.advanceTimersByTimeAsync(999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(promise).resolves.toEqual({ ok: true });
  });

  it('does NOT retry IDEMPOTENCY_KEY_PAYLOAD_MISMATCH', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(409, {
        code: 'IDEMPOTENCY_KEY_PAYLOAD_MISMATCH',
        title: 'Idempotency key payload mismatch',
        detail: '',
        status: 409,
        field_errors: {},
      }),
    );
    const err = await api('/parties', { method: 'POST', idempotencyKey: 'k', body: {} }).catch(
      (e) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe('IDEMPOTENCY_KEY_PAYLOAD_MISMATCH');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('surfaces the in-progress error once the attempt cap is reached', async () => {
    fetchMock.mockImplementation(async () => inProgress('1'));
    const promise = api('/parties', { method: 'POST', idempotencyKey: 'k', body: {} }).catch(
      (e) => e,
    );
    await vi.advanceTimersByTimeAsync(60_000);
    const err = await promise;
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe('IDEMPOTENCY_REQUEST_IN_PROGRESS');
    // 1 original + IN_PROGRESS_MAX_RETRIES retries.
    expect(fetchMock).toHaveBeenCalledTimes(1 + IN_PROGRESS_MAX_RETRIES);
    expect(IN_PROGRESS_MAX_RETRIES).toBe(8);
  });

  it('caps a huge Retry-After so the total wait stays bounded', async () => {
    fetchMock.mockImplementation(async () => inProgress('3600'));
    const promise = api('/parties', { method: 'POST', idempotencyKey: 'k', body: {} }).catch(
      (e) => e,
    );
    await vi.advanceTimersByTimeAsync(20_000);
    const err = await promise;
    expect((err as ApiError).code).toBe('IDEMPOTENCY_REQUEST_IN_PROGRESS');
  });

  it('does not retry GETs that happen to return 409', async () => {
    fetchMock.mockResolvedValueOnce(inProgress('1'));
    const err = await api('/parties').catch((e) => e);
    expect((err as ApiError).code).toBe('IDEMPOTENCY_REQUEST_IN_PROGRESS');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('composes with 401 → refresh: in-progress on the post-refresh retry is retried with the new token', async () => {
    authStore.setAccessToken('old');
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, ENVELOPE_401))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'new' })) // /auth/refresh
      .mockResolvedValueOnce(inProgress('1'))
      .mockResolvedValueOnce(jsonResponse(201, { party_id: 'p1' }));

    const promise = api('/parties', { method: 'POST', idempotencyKey: 'key-1', body: {} });
    await vi.advanceTimersByTimeAsync(1000);
    await expect(promise).resolves.toEqual({ party_id: 'p1' });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/auth\/refresh$/);
    for (const i of [2, 3]) {
      const h = fetchMock.mock.calls[i][1].headers as Record<string, string>;
      expect(h.Authorization).toBe('Bearer new');
      expect(h['Idempotency-Key']).toBe('key-1');
    }
  });

  it('an in-progress retry that then gets 401 still goes through refresh once', async () => {
    authStore.setAccessToken('old');
    fetchMock
      .mockResolvedValueOnce(inProgress('1'))
      .mockResolvedValueOnce(jsonResponse(401, ENVELOPE_401))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'new' }))
      .mockResolvedValueOnce(jsonResponse(201, { party_id: 'p1' }));

    const promise = api('/parties', { method: 'POST', idempotencyKey: 'key-1', body: {} });
    await vi.advanceTimersByTimeAsync(1000);
    await expect(promise).resolves.toEqual({ party_id: 'p1' });
    expect(fetchMock).toHaveBeenCalledTimes(4);
    const h = fetchMock.mock.calls[3][1].headers as Record<string, string>;
    expect(h.Authorization).toBe('Bearer new');
  });
});
