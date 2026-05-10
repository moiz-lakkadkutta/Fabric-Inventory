import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { liveSignup } from '@/lib/queries/identity';
import { authStore } from '@/store/auth';

/*
 * Focused unit tests for the live-mode signup path.
 *
 * `liveSignup` is the implementation under the `useSignup` mutation. We
 * mock `globalThis.fetch` so the test exercises the api() wrapper end-
 * to-end without spinning up a server (mirrors the pattern in
 * `lib/api/__tests__/client.test.ts`).
 */

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
  authStore.reset();
});

describe('liveSignup', () => {
  it('posts the full body to /auth/signup with Idempotency-Key', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.endsWith('/auth/signup')) {
        return jsonResponse(201, {
          access_token: 'tok',
          refresh_token: 'r',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_expires_at: '2099-01-01T00:00:00Z',
          user_id: 'u',
          org_id: 'o',
          firm_id: 'f',
        });
      }
      if (u.endsWith('/auth/me')) {
        return jsonResponse(200, {
          user_id: 'u',
          org_id: 'o',
          firm_id: 'f',
          permissions: [],
          flags: {},
          available_firms: [],
          token_expires_at: '2099-01-01T00:00:00Z',
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    await liveSignup({
      email: 'owner@example.test',
      password: 'strong-password-1',
      org_name: 'Acme',
      firm_name: 'Acme HQ',
      state_code: 'MH',
      gstin: '27AAACR5055K1Z5',
      idempotencyKey: '11111111-1111-4111-8111-111111111111',
    });

    const signupCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/auth/signup'));
    expect(signupCall).toBeDefined();
    const headers = (signupCall![1] as RequestInit).headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBe('11111111-1111-4111-8111-111111111111');
    const body = JSON.parse((signupCall![1] as RequestInit).body as string);
    expect(body).toEqual({
      email: 'owner@example.test',
      password: 'strong-password-1',
      org_name: 'Acme',
      firm_name: 'Acme HQ',
      state_code: 'MH',
      gstin: '27AAACR5055K1Z5',
    });
  });

  it('omits gstin from the body when undefined', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.endsWith('/auth/signup')) {
        return jsonResponse(201, {
          access_token: 'tok',
          refresh_token: 'r',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_expires_at: '2099-01-01T00:00:00Z',
          user_id: 'u',
          org_id: 'o',
          firm_id: 'f',
        });
      }
      if (u.endsWith('/auth/me')) {
        return jsonResponse(200, {
          user_id: 'u',
          org_id: 'o',
          firm_id: 'f',
          permissions: [],
          flags: {},
          available_firms: [],
          token_expires_at: '2099-01-01T00:00:00Z',
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    await liveSignup({
      email: 'owner@example.test',
      password: 'strong-password-1',
      org_name: 'Acme',
      firm_name: 'Acme HQ',
      state_code: 'MH',
      idempotencyKey: '22222222-2222-4222-8222-222222222222',
    });

    const signupCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/auth/signup'));
    const body = JSON.parse((signupCall![1] as RequestInit).body as string);
    expect(body.gstin).toBeUndefined();
    expect(Object.keys(body)).not.toContain('gstin');
  });

  it('on success: stores access_token + me on authStore', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.endsWith('/auth/signup')) {
        return jsonResponse(201, {
          access_token: 'access-token-abc',
          refresh_token: 'r',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_expires_at: '2099-01-01T00:00:00Z',
          user_id: 'u1',
          org_id: 'o1',
          firm_id: 'f1',
        });
      }
      if (u.endsWith('/auth/me')) {
        return jsonResponse(200, {
          user_id: 'u1',
          org_id: 'o1',
          firm_id: 'f1',
          permissions: ['org.admin'],
          flags: { 'gst.einvoice.enabled': false },
          available_firms: [{ firm_id: 'f1', code: 'ACME', name: 'Acme HQ' }],
          token_expires_at: '2099-01-01T00:00:00Z',
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    const out = await liveSignup({
      email: 'owner@example.test',
      password: 'strong-password-1',
      org_name: 'Acme',
      firm_name: 'Acme HQ',
      state_code: 'MH',
      idempotencyKey: '33333333-3333-4333-8333-333333333333',
    });

    expect(out.access_token).toBe('access-token-abc');
    expect(out.user_id).toBe('u1');
    expect(out.firm_id).toBe('f1');
    expect(authStore.get().accessToken).toBe('access-token-abc');
    expect(authStore.get().me?.firm_id).toBe('f1');
    expect(authStore.get().me?.permissions).toEqual(['org.admin']);
    expect(authStore.get().status).toBe('authenticated');
  });

  // CUT-107: Owner signup → /auth/me returns firm_id=null + a single
  // available firm. liveSignup must auto-switch (POST /auth/switch-firm)
  // and re-fetch /auth/me so the JWT carries the firm context. Without
  // this, every firm-scoped POST (invoices, receipts, vouchers) throws
  // "No active firm in this session — switch to a firm first."
  it('on signup: auto-switches to the only available firm when /auth/me returns firm_id=null', async () => {
    let switchCalls = 0;
    let meHits = 0;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/auth/signup')) {
        return jsonResponse(201, {
          access_token: 'tok-pre-switch',
          refresh_token: 'r',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_expires_at: '2099-01-01T00:00:00Z',
          user_id: 'u1',
          org_id: 'o1',
          firm_id: 'f1',
        });
      }
      if (u.endsWith('/auth/me')) {
        meHits += 1;
        // First /me hit: org-wide JWT, no firm. Second hit (after
        // switch-firm): the firm is now active.
        if (meHits === 1) {
          return jsonResponse(200, {
            user_id: 'u1',
            org_id: 'o1',
            firm_id: null,
            permissions: ['org.admin'],
            flags: {},
            available_firms: [{ firm_id: 'f1', code: 'ACME', name: 'Acme HQ' }],
            token_expires_at: '2099-01-01T00:00:00Z',
          });
        }
        return jsonResponse(200, {
          user_id: 'u1',
          org_id: 'o1',
          firm_id: 'f1',
          permissions: ['org.admin'],
          flags: {},
          available_firms: [{ firm_id: 'f1', code: 'ACME', name: 'Acme HQ' }],
          token_expires_at: '2099-01-01T00:00:00Z',
        });
      }
      if (u.endsWith('/auth/switch-firm')) {
        switchCalls += 1;
        const body = JSON.parse(String(init!.body));
        expect(body).toEqual({ firm_id: 'f1' });
        return jsonResponse(200, {
          access_token: 'tok-post-switch',
          refresh_token: 'r2',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_expires_at: '2099-01-01T00:00:00Z',
          firm_id: 'f1',
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    await liveSignup({
      email: 'owner@example.test',
      password: 'strong-password-1',
      org_name: 'Acme',
      firm_name: 'Acme HQ',
      state_code: 'MH',
      idempotencyKey: '55555555-5555-4555-8555-555555555555',
    });

    expect(switchCalls).toBe(1);
    expect(meHits).toBe(2);
    // After auto-switch, the store carries the firm-scoped token + me.
    expect(authStore.get().accessToken).toBe('tok-post-switch');
    expect(authStore.get().me?.firm_id).toBe('f1');
  });

  it('propagates the 409 USER_EMAIL_TAKEN as an ApiError', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(409, {
        code: 'USER_EMAIL_TAKEN',
        title: 'Email already in use',
        detail: 'A user with this email already exists in this org.',
        status: 409,
        field_errors: {},
      }),
    );

    const err = await liveSignup({
      email: 'owner@example.test',
      password: 'strong-password-1',
      org_name: 'Acme',
      firm_name: 'Acme HQ',
      state_code: 'MH',
      idempotencyKey: '44444444-4444-4444-8444-444444444444',
    }).catch((e) => e);

    expect(err).toBeInstanceOf(Error);
    expect(err.code).toBe('USER_EMAIL_TAKEN');
    expect(err.status).toBe(409);
    // Auth store should remain empty on failure.
    expect(authStore.get().accessToken).toBeNull();
    expect(authStore.get().me).toBeNull();
  });
});
