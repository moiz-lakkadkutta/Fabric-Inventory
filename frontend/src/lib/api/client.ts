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

  const response = await fetch(`${API_BASE}${path}`, init);

  if (response.status === 401 && !options.skipRefresh) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      const retryHeaders = { ...headers };
      const newToken = authStore.get().accessToken;
      if (newToken) retryHeaders['Authorization'] = `Bearer ${newToken}`;
      const retry = await fetch(`${API_BASE}${path}`, {
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

export { ApiError };
