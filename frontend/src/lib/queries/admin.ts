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

// ──────────────────────────────────────────────────────────────────────
// Permission catalog (TASK-TR-B4) — drives the Role builder checkbox tree
// ──────────────────────────────────────────────────────────────────────

const PERMISSIONS_KEY = ['admin', 'permissions'] as const;

export interface PermissionCatalogEntry {
  code: string;
  resource: string;
  action: string;
  description: string | null;
}

export interface PermissionCatalogModule {
  module: string;
  permissions: PermissionCatalogEntry[];
}

interface PermissionCatalogEnvelope {
  items: PermissionCatalogModule[];
}

/**
 * Mock catalog — kept terse but covers every module we render so the
 * click-dummy keeps working without a backend. The live catalog is the
 * source of truth and adds permissions as they're shipped server-side.
 */
const MOCK_PERMISSION_CATALOG: PermissionCatalogModule[] = [
  {
    module: 'dashboard',
    permissions: [
      {
        code: 'dashboard.read',
        resource: 'dashboard',
        action: 'read',
        description: 'View dashboard KPIs and activity',
      },
    ],
  },
  {
    module: 'masters',
    permissions: [
      {
        code: 'masters.party.create',
        resource: 'masters.party',
        action: 'create',
        description: 'Create parties',
      },
      {
        code: 'masters.party.read',
        resource: 'masters.party',
        action: 'read',
        description: 'View parties',
      },
      {
        code: 'masters.party.update',
        resource: 'masters.party',
        action: 'update',
        description: 'Update parties',
      },
      {
        code: 'masters.item.create',
        resource: 'masters.item',
        action: 'create',
        description: 'Create items',
      },
      {
        code: 'masters.item.read',
        resource: 'masters.item',
        action: 'read',
        description: 'View items',
      },
      {
        code: 'masters.item.update',
        resource: 'masters.item',
        action: 'update',
        description: 'Update items',
      },
    ],
  },
  {
    module: 'sales',
    permissions: [
      {
        code: 'sales.invoice.create',
        resource: 'sales.invoice',
        action: 'create',
        description: 'Create draft sales invoices',
      },
      {
        code: 'sales.invoice.finalize',
        resource: 'sales.invoice',
        action: 'finalize',
        description: 'Finalize sales invoices',
      },
      {
        code: 'sales.invoice.read',
        resource: 'sales.invoice',
        action: 'read',
        description: 'View sales invoices',
      },
      {
        code: 'sales.order.create',
        resource: 'sales.order',
        action: 'create',
        description: 'Create sales orders',
      },
      {
        code: 'sales.order.read',
        resource: 'sales.order',
        action: 'read',
        description: 'View sales orders',
      },
      {
        code: 'sales.dc.create',
        resource: 'sales.dc',
        action: 'create',
        description: 'Create delivery challans',
      },
      {
        code: 'sales.dc.read',
        resource: 'sales.dc',
        action: 'read',
        description: 'View delivery challans',
      },
    ],
  },
  {
    module: 'inventory',
    permissions: [
      {
        code: 'inventory.stock.read',
        resource: 'inventory.stock',
        action: 'read',
        description: 'View stock positions',
      },
      {
        code: 'inventory.adjustment.create',
        resource: 'inventory.adjustment',
        action: 'create',
        description: 'Create stock adjustments',
      },
    ],
  },
  {
    module: 'accounting',
    permissions: [
      {
        code: 'accounting.voucher.post',
        resource: 'accounting.voucher',
        action: 'post',
        description: 'Post journal vouchers',
      },
      {
        code: 'accounting.voucher.read',
        resource: 'accounting.voucher',
        action: 'read',
        description: 'View vouchers',
      },
      {
        code: 'accounting.report.view',
        resource: 'accounting.report',
        action: 'view',
        description: 'View reports',
      },
    ],
  },
  {
    module: 'identity',
    permissions: [
      {
        code: 'identity.role.create',
        resource: 'identity.role',
        action: 'create',
        description: 'Create custom roles',
      },
      {
        code: 'identity.role.update',
        resource: 'identity.role',
        action: 'update',
        description: 'Update custom roles',
      },
      {
        code: 'identity.role.delete',
        resource: 'identity.role',
        action: 'delete',
        description: 'Soft-delete custom roles',
      },
      {
        code: 'identity.role.read',
        resource: 'identity.role',
        action: 'read',
        description: 'View roles + permissions',
      },
    ],
  },
];

async function liveListPermissions(): Promise<PermissionCatalogModule[]> {
  const data = await api<PermissionCatalogEnvelope>('/admin/permissions');
  return data.items;
}

async function mockListPermissions(): Promise<PermissionCatalogModule[]> {
  return fakeFetch(MOCK_PERMISSION_CATALOG);
}

export function usePermissionsCatalog() {
  return useQuery({
    queryKey: PERMISSIONS_KEY,
    queryFn: () => (IS_LIVE ? liveListPermissions() : mockListPermissions()),
    // Catalog is effectively static within a release — long stale window.
    staleTime: 5 * 60_000,
  });
}

// ──────────────────────────────────────────────────────────────────────
// Custom-role CRUD (TASK-TR-B4)
// ──────────────────────────────────────────────────────────────────────

export interface RoleDetail {
  role_id: string;
  code: string;
  name: string;
  description: string | null;
  is_system_role: boolean;
  permissions: string[];
}

export interface CreateRoleInput {
  code: string;
  name: string;
  description?: string | null;
  permissions: string[];
  idempotencyKey: string;
}

export interface UpdateRoleInput {
  role_id: string;
  name?: string | null;
  description?: string | null;
  permissions?: string[] | null;
  idempotencyKey: string;
}

export interface DeleteRoleInput {
  role_id: string;
  idempotencyKey: string;
}

async function liveGetRole(role_id: string): Promise<RoleDetail> {
  return api<RoleDetail>(`/admin/roles/${role_id}`);
}

async function mockGetRole(role_id: string): Promise<RoleDetail> {
  return fakeFetch({
    role_id,
    code: 'mock_custom',
    name: 'Mock Custom Role',
    description: 'Mock role for click-dummy',
    is_system_role: false,
    permissions: [],
  });
}

export function useRoleDetail(role_id: string | null) {
  return useQuery({
    queryKey: ['admin', 'role', role_id] as const,
    queryFn: () => {
      // queryFn won't run unless `enabled` is true (role_id set), so the
      // bang is safe; mock branch returns a stable shape regardless.
      const id = role_id!;
      return IS_LIVE ? liveGetRole(id) : mockGetRole(id);
    },
    enabled: !!role_id,
  });
}

async function liveCreateRole(input: CreateRoleInput): Promise<RoleDetail> {
  const body: Record<string, unknown> = {
    code: input.code,
    name: input.name,
    permissions: input.permissions,
  };
  if (input.description != null && input.description !== '') {
    body.description = input.description;
  }
  return api<RoleDetail>('/admin/roles', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

async function mockCreateRole(input: CreateRoleInput): Promise<RoleDetail> {
  return fakeFetch({
    role_id: `mock-role-${crypto.randomUUID()}`,
    code: input.code,
    name: input.name,
    description: input.description ?? null,
    is_system_role: false,
    permissions: input.permissions,
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateRoleInput) =>
      IS_LIVE ? liveCreateRole(input) : mockCreateRole(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });
}

async function liveUpdateRole(input: UpdateRoleInput): Promise<RoleDetail> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.description !== undefined) body.description = input.description;
  if (input.permissions !== undefined) body.permissions = input.permissions;
  return api<RoleDetail>(`/admin/roles/${input.role_id}`, {
    method: 'PATCH',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

async function mockUpdateRole(input: UpdateRoleInput): Promise<RoleDetail> {
  return fakeFetch({
    role_id: input.role_id,
    code: 'mock_custom',
    name: input.name ?? 'Mock Custom Role',
    description: input.description ?? null,
    is_system_role: false,
    permissions: input.permissions ?? [],
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateRoleInput) =>
      IS_LIVE ? liveUpdateRole(input) : mockUpdateRole(input),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ROLES_KEY });
      qc.invalidateQueries({ queryKey: ['admin', 'role', vars.role_id] });
    },
  });
}

async function liveDeleteRole(input: DeleteRoleInput): Promise<void> {
  await api<undefined>(`/admin/roles/${input.role_id}`, {
    method: 'DELETE',
    idempotencyKey: input.idempotencyKey,
  });
}

async function mockDeleteRole(input: DeleteRoleInput): Promise<void> {
  await fakeFetch(input.role_id);
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: DeleteRoleInput) =>
      IS_LIVE ? liveDeleteRole(input) : mockDeleteRole(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });
}
