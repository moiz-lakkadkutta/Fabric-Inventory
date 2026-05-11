import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { currentUser, defaultFirm } from '@/lib/mock/identity';
import { authStore, type MeResponse } from '@/store/auth';
import type { components } from '@/types/api';

/**
 * Auto-switch to the user's only firm when the JWT lacks a firm_id.
 *
 * Owner signups have org-wide roles → JWT.firm_id is null. Most
 * dogfood users have exactly one firm in their org. Forcing them to
 * click the firm switcher on day one is friction the API doesn't
 * actually require — `/auth/me` exposes available_firms; if there's
 * exactly one, we hit `/auth/switch-firm` and refetch /me.
 *
 * No-op if firm_id is already set or available_firms is 0 / 2+.
 * Returns the (possibly refetched) MeResponse so callers can keep
 * using the latest snapshot. Errors propagate as ApiError.
 */
export async function maybeAutoSwitchSingleFirm(me: MeResponse): Promise<MeResponse> {
  if (me.firm_id !== null) return me;
  if (me.available_firms.length !== 1) return me;
  const target = me.available_firms[0].firm_id;

  const data = await api<{ access_token: string; firm_id: string }>('/auth/switch-firm', {
    method: 'POST',
    idempotencyKey: crypto.randomUUID(),
    body: { firm_id: target },
  });
  authStore.setAccessToken(data.access_token);
  return await api<MeResponse>('/auth/me');
}

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

// Codegen surface — pydantic's `Optional[X] = None` becomes
// `string | null | undefined` (note both `null` and `undefined`),
// stricter than the hand-written `string?` was. Read sites already
// use `data.access_token ?? ...` so the extra `null` channel is a
// no-op at the call sites — the codegen just makes the wire shape
// explicit.
type LoginEnvelope = components['schemas']['LoginResponse'];

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
    const settled = await maybeAutoSwitchSingleFirm(me);
    authStore.setMe(settled);
  }
  return {
    requires_mfa: data.requires_mfa,
    // Codegen models pydantic's `Optional[str]` as `string | null |
    // undefined`; LoginResult exposes `string | undefined`. Coerce
    // null → undefined so the public type stays narrow.
    user_id: data.user_id ?? undefined,
    access_token: data.access_token ?? undefined,
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

// ──────────────────────────────────────────────────────────────────────
// Signup (TASK-CUT-003) — wires the Onboarding wizard to /auth/signup
// ──────────────────────────────────────────────────────────────────────

export interface SignupInput {
  email: string;
  password: string;
  org_name: string;
  firm_name: string;
  /** 2-character Indian state code (e.g. "MH"). Required by backend. */
  state_code: string;
  /** Optional. Backend infers tax_status from presence/absence. */
  gstin?: string;
  idempotencyKey: string;
}

export interface SignupResult {
  user_id: string;
  org_id: string;
  firm_id: string;
  access_token: string;
}

type SignupEnvelope = components['schemas']['SignupResponse'];

/**
 * Live-mode signup. Mirrors `liveLogin` (token storage + /auth/me hop)
 * with one wrinkle: signup always returns tokens (no MFA branch), so
 * we always fetch /auth/me on success.
 *
 * Exported for unit testing. Routine callers go through `useSignup`.
 */
export async function liveSignup(input: SignupInput): Promise<SignupResult> {
  const body: Record<string, string> = {
    email: input.email,
    password: input.password,
    org_name: input.org_name,
    firm_name: input.firm_name,
    state_code: input.state_code,
  };
  if (input.gstin) body.gstin = input.gstin;

  const data = await api<SignupEnvelope>('/auth/signup', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
  authStore.setAccessToken(data.access_token);
  const me = await api<MeResponse>('/auth/me');
  // Owner-of-new-org JWTs are org-scoped (firm_id=null) — auto-switch
  // to the only firm so subsequent firm-scoped POSTs (invoices, etc.)
  // don't trip the "No active firm in this session" guard. Mirrors
  // liveLogin's behaviour.
  const settled = await maybeAutoSwitchSingleFirm(me);
  authStore.setMe(settled);
  return {
    user_id: data.user_id,
    org_id: data.org_id,
    firm_id: data.firm_id,
    access_token: data.access_token,
  };
}

async function mockSignup(input: SignupInput): Promise<SignupResult> {
  // Stub — the click-dummy doesn't sign anyone up; live mode is the
  // exclusive code path. We echo a slug of the requested org name so
  // any caller inspecting the result sees something reasonable.
  await fakeFetch(undefined);
  return {
    user_id: currentUser.user_id,
    org_id: `mock-org-${input.org_name.toLowerCase().replace(/\s+/g, '-')}`,
    firm_id: 'mock-firm',
    access_token: 'mock-access-token',
  };
}

export function useSignup() {
  return useMutation({
    mutationFn: (input: SignupInput) => (IS_LIVE ? liveSignup(input) : mockSignup(input)),
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
  const settled = await maybeAutoSwitchSingleFirm(me);
  authStore.setMe(settled);
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

// ──────────────────────────────────────────────────────────────────────
// Switch firm (Q3)
// ──────────────────────────────────────────────────────────────────────

export interface SwitchFirmInput {
  firm_id: string;
  idempotencyKey: string;
}

type SwitchFirmEnvelope = components['schemas']['SwitchFirmResponse'];

async function liveSwitchFirm(input: SwitchFirmInput): Promise<SwitchFirmEnvelope> {
  const data = await api<SwitchFirmEnvelope>('/auth/switch-firm', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: { firm_id: input.firm_id },
  });
  authStore.setAccessToken(data.access_token);
  // Refresh /me so flags + permissions reflect the new firm context.
  const me = await api<MeResponse>('/auth/me');
  authStore.setMe(me);
  return data;
}

async function mockSwitchFirm(input: SwitchFirmInput): Promise<SwitchFirmEnvelope> {
  await fakeFetch(undefined);
  return {
    access_token: 'mock-access-token',
    refresh_token: 'mock-refresh-token',
    access_expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
    refresh_expires_at: new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString(),
    firm_id: input.firm_id,
  };
}

export function useSwitchFirm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SwitchFirmInput) =>
      IS_LIVE ? liveSwitchFirm(input) : mockSwitchFirm(input),
    // Cross-firm data isolation: drop everything cached for the old firm.
    onSuccess: () => qc.clear(),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Forgot / reset password (CUT-303)
// ──────────────────────────────────────────────────────────────────────

export interface ForgotPasswordInput {
  email: string;
  org_name: string;
}

export interface ResetPasswordInput {
  token: string;
  org_name: string;
  new_password: string;
}

// The BE response is uniform `{ ok: true }` whether the email matched a
// real user or not — that's the no-enumeration contract. The hooks
// expose the same shape regardless of mode so callers don't branch.
interface OkResponse {
  ok: true;
}

async function liveForgotPassword(input: ForgotPasswordInput): Promise<OkResponse> {
  // BE has /auth/forgot on the Idempotency-Key exempt list, but the
  // FE api() wrapper requires a key for all mutating methods. Mint one
  // per call — server-side it's a no-op for these paths.
  await api<OkResponse>('/auth/forgot', {
    method: 'POST',
    idempotencyKey: crypto.randomUUID(),
    body: { email: input.email, org_name: input.org_name },
  });
  return { ok: true };
}

async function mockForgotPassword(): Promise<OkResponse> {
  await fakeFetch(undefined);
  return { ok: true };
}

export function useForgotPassword() {
  return useMutation({
    mutationFn: (input: ForgotPasswordInput) =>
      IS_LIVE ? liveForgotPassword(input) : mockForgotPassword(),
  });
}

async function liveResetPassword(input: ResetPasswordInput): Promise<OkResponse> {
  await api<OkResponse>('/auth/reset', {
    method: 'POST',
    idempotencyKey: crypto.randomUUID(),
    body: {
      token: input.token,
      org_name: input.org_name,
      new_password: input.new_password,
    },
  });
  return { ok: true };
}

async function mockResetPassword(): Promise<OkResponse> {
  await fakeFetch(undefined);
  return { ok: true };
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (input: ResetPasswordInput) =>
      IS_LIVE ? liveResetPassword(input) : mockResetPassword(),
  });
}
