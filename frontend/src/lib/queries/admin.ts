/**
 * Admin queries — users list, invites, role changes (TASK-CUT-304).
 *
 * Both live and mock branches per the wave-2 contract; Vite tree-shakes
 * the unused branch at build time.
 *
 * Mock-mode keeps the original `AdminHub` click-dummy populated with the
 * faux user list defined in `lib/mock/admin.ts` so designers can still
 * iterate on the page without a backend.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { MOCK_ADMIN_ROLES, MOCK_ADMIN_USERS } from '@/lib/mock/admin';

const USERS_KEY = ['admin', 'users'] as const;
const ROLES_KEY = ['admin', 'roles'] as const;

export interface AdminUser {
  user_id: string;
  email: string;
  name: string | null;
  role: string;
  role_id: string;
  status: 'ACTIVE' | 'SUSPENDED' | 'INACTIVE';
  last_login_at: string | null;
  created_at: string;
}

export interface AdminRole {
  role_id: string;
  code: string;
  name: string;
  description: string | null;
  is_system_role: boolean;
}

interface AdminUserListEnvelope {
  items: AdminUser[];
  count: number;
}

interface AdminRoleListEnvelope {
  items: AdminRole[];
}

// ──────────────────────────────────────────────────────────────────────
// useUsers
// ──────────────────────────────────────────────────────────────────────

async function liveListUsers(): Promise<AdminUser[]> {
  const data = await api<AdminUserListEnvelope>('/admin/users');
  return data.items;
}

async function mockListUsers(): Promise<AdminUser[]> {
  return fakeFetch(MOCK_ADMIN_USERS);
}

export function useUsers() {
  return useQuery({
    queryKey: USERS_KEY,
    queryFn: () => (IS_LIVE ? liveListUsers() : mockListUsers()),
    staleTime: 30_000,
  });
}

// ──────────────────────────────────────────────────────────────────────
// useRoles
// ──────────────────────────────────────────────────────────────────────

async function liveListRoles(): Promise<AdminRole[]> {
  const data = await api<AdminRoleListEnvelope>('/admin/roles');
  return data.items;
}

async function mockListRoles(): Promise<AdminRole[]> {
  return fakeFetch(MOCK_ADMIN_ROLES);
}

export function useRoles() {
  return useQuery({
    queryKey: ROLES_KEY,
    queryFn: () => (IS_LIVE ? liveListRoles() : mockListRoles()),
    staleTime: 60_000,
  });
}

// ──────────────────────────────────────────────────────────────────────
// useCreateInvite
// ──────────────────────────────────────────────────────────────────────

export interface CreateInviteInput {
  email: string;
  role_id: string;
  firm_id?: string | null;
  idempotencyKey: string;
}

export interface InviteEnvelope {
  invite_id: string;
  email: string;
  expires_at: string;
  invite_link: string;
}

async function liveCreateInvite(input: CreateInviteInput): Promise<InviteEnvelope> {
  const body: Record<string, string> = {
    email: input.email,
    role_id: input.role_id,
  };
  if (input.firm_id) body.firm_id = input.firm_id;
  return api<InviteEnvelope>('/admin/invites', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

async function mockCreateInvite(input: CreateInviteInput): Promise<InviteEnvelope> {
  return fakeFetch({
    invite_id: `mock-invite-${crypto.randomUUID()}`,
    email: input.email,
    expires_at: new Date(Date.now() + 7 * 24 * 3600_000).toISOString(),
    invite_link: `${window.location.origin}/invite/mock-token-${crypto.randomUUID()}`,
  });
}

export function useCreateInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateInviteInput) =>
      IS_LIVE ? liveCreateInvite(input) : mockCreateInvite(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

// ──────────────────────────────────────────────────────────────────────
// useAcceptInvite (used by the public /invite/:token page)
// ──────────────────────────────────────────────────────────────────────

export interface AcceptInviteInput {
  token: string;
  name: string;
  password: string;
}

export interface AcceptInviteEnvelope {
  user_id: string;
  org_id: string;
  email: string;
  org_name: string;
}

async function liveAcceptInvite(input: AcceptInviteInput): Promise<AcceptInviteEnvelope> {
  // No Idempotency-Key — `/admin/invites/accept` is in the BE's
  // IDEMPOTENT_BY_DESIGN_PATHS allowlist (the invite token IS the
  // idempotency key — single-use, sha256-hashed in DB).
  return api<AcceptInviteEnvelope>('/admin/invites/accept', {
    method: 'POST',
    body: input,
  });
}

async function mockAcceptInvite(input: AcceptInviteInput): Promise<AcceptInviteEnvelope> {
  return fakeFetch({
    user_id: 'mock-user',
    org_id: 'mock-org',
    email: `${input.name.toLowerCase().replace(/\s+/g, '.')}@mock.example.com`,
    org_name: 'Mock Org',
  });
}

export function useAcceptInvite() {
  return useMutation({
    mutationFn: (input: AcceptInviteInput) =>
      IS_LIVE ? liveAcceptInvite(input) : mockAcceptInvite(input),
  });
}

// ──────────────────────────────────────────────────────────────────────
// useUpdateUserRole
// ──────────────────────────────────────────────────────────────────────

export interface UpdateUserRoleInput {
  user_id: string;
  role_id: string;
  idempotencyKey: string;
}

async function liveUpdateUserRole(input: UpdateUserRoleInput): Promise<void> {
  await api<undefined>(`/admin/users/${input.user_id}/role`, {
    method: 'PATCH',
    idempotencyKey: input.idempotencyKey,
    body: { role_id: input.role_id },
  });
}

async function mockUpdateUserRole(input: UpdateUserRoleInput): Promise<void> {
  // Echoing input keeps the click-dummy's no-op consistent with the
  // mutation signature (eslint no-unused-vars is happy and tests can
  // still spy on argument shape).
  await fakeFetch(input.user_id);
}

export function useUpdateUserRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateUserRoleInput) =>
      IS_LIVE ? liveUpdateUserRole(input) : mockUpdateUserRole(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}
