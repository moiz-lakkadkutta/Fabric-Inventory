import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Q01-10: boot-time /auth/refresh treats a 503 + Retry-After (another tab is
 * rotating the same refresh-token family) as transient: wait, retry once,
 * and only then give up.
 */
vi.mock('@/lib/api/mode', () => ({ API_MODE: 'live', IS_LIVE: true, IS_MOCK: false }));

const { refreshOnBoot } = await import('@/hooks/useAuth');

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

const BUSY = { code: 'LOCK_TIMEOUT', title: 'Busy', detail: '', status: 503 };

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('refreshOnBoot', () => {
  it('retries once after Retry-After on a 503 and returns the new token', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(503, BUSY, { 'Retry-After': '1' }))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh' }));
    const pending = refreshOnBoot();
    await vi.advanceTimersByTimeAsync(999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(pending).resolves.toEqual({ access_token: 'fresh' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('gives up after one retry', async () => {
    fetchMock.mockResolvedValue(jsonResponse(503, BUSY, { 'Retry-After': '1' }));
    const pending = refreshOnBoot();
    const assertion = expect(pending).rejects.toMatchObject({ status: 503 });
    await vi.advanceTimersByTimeAsync(1000);
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not retry a 401 (really logged out)', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(401, { code: 'TOKEN_INVALID', title: 'x', detail: '', status: 401 }),
    );
    await expect(refreshOnBoot()).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not retry a 503 without Retry-After', async () => {
    fetchMock.mockResolvedValue(jsonResponse(503, BUSY));
    await expect(refreshOnBoot()).rejects.toMatchObject({ status: 503 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
