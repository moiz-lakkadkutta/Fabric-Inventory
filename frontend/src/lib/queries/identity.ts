import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { currentUser, defaultFirm } from '@/lib/mock/identity';
import { authStore, type MeResponse } from '@/store/auth';

/*
 * useLogin / useLogout / useMfa — both branches per Q6.
 *
 * The mock branch preserves the click-dummy's sentinel behaviour
 * (`error@taana.test` → INVALID_CREDENTIALS) so existing UI tests
 * keep working unchanged.
 *
 * Live branch hits /auth/login; on success it populates the in-memory
 * access token and triggers a /auth/me fetch so the rest of the app
 * has user/firm/perms/flags available immediately.
 */

const ERROR_SENTINEL = 'error@taana.test';

export interface LoginInput {
  email: string;
  password: string;
  org_name: string;
  idempotencyKey: string;
}

export interface LoginResult {
  requires_mfa: boolean;
  user_id?: string;
  access_token?: string;
}

interface LoginEnvelope {
  requires_mfa: boolean;
  user_id?: string;
  access_token?: string;
  refresh_token?: string;
  access_expires_at?: string;
  refresh_expires_at?: string;
}

async function liveLogin(input: LoginInput): Promise<LoginResult> {
  const data = await api<LoginEnvelope>('/auth/login', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: {
      email: input.email,
      password: input.password,
      org_name: input.org_name,
    },
  });
  if (data.access_token) authStore.setAccessToken(data.access_token);
  if (!data.requires_mfa) {
    const me = await api<MeResponse>('/auth/me');
    authStore.setMe(me);
  }
  return {
    requires_mfa: data.requires_mfa,
    user_id: data.user_id,
    access_token: data.access_token,
  };
}

async function mockLogin(input: LoginInput): Promise<LoginResult> {
  if (input.email.trim().toLowerCase() === ERROR_SENTINEL) {
    await fakeFetch(undefined);
    throw new Error('INVALID_CREDENTIALS');
  }
  return fakeFetch({
    requires_mfa: true,
    user_id: currentUser.user_id,
  });
}

export function useLogin() {
  return useMutation({
    mutationFn: (input: LoginInput) => (IS_LIVE ? liveLogin(input) : mockLogin(input)),
  });
}

export interface MfaVerifyInput {
  email: string;
  password: string;
  org_name: string;
  totp_code: string;
  idempotencyKey: string;
}

async function liveMfaVerify(input: MfaVerifyInput): Promise<LoginEnvelope> {
  const data = await api<LoginEnvelope>('/auth/mfa-verify', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: {
      email: input.email,
      password: input.password,
      org_name: input.org_name,
      totp_code: input.totp_code,
    },
  });
  if (data.access_token) authStore.setAccessToken(data.access_token);
  const me = await api<MeResponse>('/auth/me');
  authStore.setMe(me);
  return data;
}

async function mockMfaVerify(input: MfaVerifyInput): Promise<LoginEnvelope> {
  if (input.totp_code === '000000') {
    await fakeFetch(undefined);
    throw new Error('MFA_INVALID');
  }
  return fakeFetch({
    requires_mfa: false,
    user_id: currentUser.user_id,
    access_token: 'mock-access-token',
  });
}

export function useMfaVerify() {
  return useMutation({
    mutationFn: (input: MfaVerifyInput) => (IS_LIVE ? liveMfaVerify(input) : mockMfaVerify(input)),
  });
}

export interface LogoutInput {
  idempotencyKey: string;
}

async function liveLogout(input: LogoutInput): Promise<void> {
  // Send empty body — the cookie carries the refresh token.
  await api('/auth/logout', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: { refresh_token: '' },
  });
  authStore.clear();
}

async function mockLogout(): Promise<void> {
  await fakeFetch(undefined);
  authStore.clear();
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: LogoutInput) => (IS_LIVE ? liveLogout(input) : mockLogout()),
    onSuccess: () => qc.clear(),
  });
}

/*
 * Mock-mode placeholders for code that imports the firm bundle
 * directly. Live mode reads from authStore via useMe().
 */
export const mockFirms = [defaultFirm];
