/*
 * api() — the single authenticated fetch wrapper.
 *
 * Responsibilities (Q8b):
 *   - Attach the in-memory access token as Bearer header.
 *   - Inject Idempotency-Key on mutating methods (caller passes one;
 *     the wrapper rejects if it's missing — fail-loud, since the
 *     backend will 400 anyway).
 *   - Decode Q8a error envelope into ApiError on non-2xx.
 *   - On 401 with a TOKEN_INVALID code: try one /auth/refresh against
 *     the httpOnly cookie, populate the new access token, retry the
 *     original request. Subsequent 401 surfaces as ApiError so the
 *     caller can redirect to /login.
 *   - On 409 IDEMPOTENCY_REQUEST_IN_PROGRESS (Q01-01: a request with the
 *     same Idempotency-Key is still executing — typically a double-click):
 *     wait Retry-After and re-send the SAME request (same key + body) so
 *     the caller receives the single result as a replay. See
 *     `fetchWithInProgressRetry` for the cap. IDEMPOTENCY_KEY_PAYLOAD_MISMATCH
 *     is never retried (it's a caller bug, not a transient state).
 *
 * Base URL defaults to the same origin (`/api/...`) so localhost dev
 * with Vite's proxy and prod behind Caddy both work without env-vars.
 */

import { authStore } from '@/store/auth';

import { ApiError, decodeError } from './errors';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

interface ApiOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  /** Required for POST/PATCH/PUT/DELETE. Mint via useIdempotencyKey(). */
  idempotencyKey?: string;
  headers?: Record<string, string>;
  /** Skip the auto 401-refresh-retry. Used by /auth/refresh itself. */
  skipRefresh?: boolean;
  /** Override the default credential mode for this call. */
  credentials?: RequestCredentials;
  signal?: AbortSignal;
}

const MUTATING = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);

/*
 * Q01-01 in-progress retry budget. The server holds the in-flight lock for
 * as long as the first request runs (30s TTL, heartbeat-extended), so this
 * is a UX bound, not a correctness one: at most 8 retries, each wait taken
 * from Retry-After (default 1s) and clamped to [0.25s, 2s], so the worst
 * case is ~16s before the in-progress ApiError surfaces. A request still
 * running after that is almost certainly stuck; the user can retry the same
 * form (same key) and get the replay once it finishes.
 */
const IN_PROGRESS_CODE = 'IDEMPOTENCY_REQUEST_IN_PROGRESS';
export const IN_PROGRESS_MAX_RETRIES = 8;
const IN_PROGRESS_DEFAULT_WAIT_MS = 1000;
const IN_PROGRESS_MIN_WAIT_MS = 250;
const IN_PROGRESS_MAX_WAIT_MS = 2000;

async function isInProgress(response: Response): Promise<boolean> {
  if (response.status !== 409) return false;
  try {
    const data = (await response.clone().json()) as { code?: string };
    return data.code === IN_PROGRESS_CODE;
  } catch {
    return false;
  }
}

function retryAfterMs(response: Response): number {
  const raw = response.headers.get('Retry-After');
  const secs = raw === null ? NaN : Number(raw);
  const ms = Number.isFinite(secs) ? secs * 1000 : IN_PROGRESS_DEFAULT_WAIT_MS;
  return Math.min(IN_PROGRESS_MAX_WAIT_MS, Math.max(IN_PROGRESS_MIN_WAIT_MS, ms));
}

function sleep(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(signal?.reason);
    }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/**
 * fetch() that transparently waits out IDEMPOTENCY_REQUEST_IN_PROGRESS on
 * mutating requests, re-sending the identical `init` (same Idempotency-Key,
 * same body string). Returns the final Response — a 2xx replay, any other
 * status, or the last in-progress 409 once the cap is hit. Each attempt goes
 * through the caller's 401 handling unchanged because this sits below it.
 */
export async function fetchWithInProgressRetry(url: string, init: RequestInit): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase();
  let response = await fetch(url, init);
  if (!MUTATING.has(method)) return response;
  for (let attempt = 0; attempt < IN_PROGRESS_MAX_RETRIES; attempt++) {
    if (!(await isInProgress(response))) return response;
    await sleep(retryAfterMs(response), init.signal);
    response = await fetch(url, init);
  }
  return response;
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': crypto.randomUUID(),
        },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        authStore.clear();
        return false;
      }
      const data = (await response.json()) as { access_token: string };
      authStore.setAccessToken(data.access_token);
      return true;
    } catch {
      authStore.clear();
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export async function api<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...options.headers,
  };

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  if (MUTATING.has(method)) {
    if (!options.idempotencyKey) {
      throw new Error(
        `api(${method} ${path}): Idempotency-Key required for mutating methods. Use useIdempotencyKey().`,
      );
    }
    headers['Idempotency-Key'] = options.idempotencyKey;
  }

  const accessToken = authStore.get().accessToken;
  if (accessToken && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }

  const init: RequestInit = {
    method,
    headers,
    credentials: options.credentials ?? 'include',
    signal: options.signal,
  };
  if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
  }

  const response = await fetchWithInProgressRetry(`${API_BASE}${path}`, init);

  if (response.status === 401 && !options.skipRefresh) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      const retryHeaders = { ...headers };
      const newToken = authStore.get().accessToken;
      if (newToken) retryHeaders['Authorization'] = `Bearer ${newToken}`;
      const retry = await fetchWithInProgressRetry(`${API_BASE}${path}`, {
        ...init,
        headers: retryHeaders,
      });
      if (!retry.ok) throw await decodeError(retry);
      return parseBody<T>(retry);
    }
    throw await decodeError(response);
  }

  if (!response.ok) {
    throw await decodeError(response);
  }

  return parseBody<T>(response);
}

async function parseBody<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

/**
 * Fetch a binary endpoint (e.g. /invoices/{id}/pdf) with auth + 401 refresh,
 * returning the raw `Blob` so the caller can trigger a download or open
 * an object URL. The JSON-only `api()` wrapper above can't be reused here
 * because PDF responses don't survive `JSON.parse`. CUT-205.
 *
 * Errors still come back as `ApiError` so the caller's catch path matches
 * the rest of the FE.
 */
export async function apiBlob(path: string): Promise<Blob> {
  const accessToken = authStore.get().accessToken;
  const headers: Record<string, string> = { Accept: 'application/pdf' };
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  const init: RequestInit = { method: 'GET', headers, credentials: 'include' };
  let response = await fetch(`${API_BASE}${path}`, init);

  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      const newToken = authStore.get().accessToken;
      if (newToken) headers['Authorization'] = `Bearer ${newToken}`;
      response = await fetch(`${API_BASE}${path}`, { ...init, headers });
    }
  }
  if (!response.ok) throw await decodeError(response);
  return response.blob();
}

export { ApiError };
