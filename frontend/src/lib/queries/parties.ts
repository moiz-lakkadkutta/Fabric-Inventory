import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import {
  liveCreateParty,
  liveDeleteParty,
  liveGetParty,
  liveListParties,
  livePatchParty,
  type BackendParty,
  type BackendPartyCreateBody,
  type BackendPartyPatchBody,
  type ListPartiesParams,
} from '@/lib/api/parties';
import { fakeFetch } from '@/lib/mock/api';
import { customers as mockCustomers, parties as mockParties } from '@/lib/mock/parties';
import type { Party, PartyKind, PartyRole } from '@/lib/mock/types';

const KEY = ['parties'] as const;

// ──────────────────────────────────────────────────────────────────────
// Role / kind / boolean-flag mapping (TASK-CUT-101 schema shim)
//
// Backend  : 4 booleans (is_customer / is_supplier / is_karigar / is_transporter)
// Frontend : a single uppercase `role` enum + a derived lowercase `kind`
//   for legacy click-dummy components that filter by `kind`.
//
// Priority on BE→FE when multiple flags are true: customer > supplier >
//   karigar > transporter. Only one is_X is typically true; the priority
//   matters mostly for degenerate / dual-role rows.
// ──────────────────────────────────────────────────────────────────────

interface RoleFlags {
  is_customer?: boolean | null;
  is_supplier?: boolean | null;
  is_karigar?: boolean | null;
  is_transporter?: boolean | null;
}

function mapPartyRole(flags: RoleFlags): PartyRole {
  if (flags.is_customer) return 'CUSTOMER';
  if (flags.is_supplier) return 'SUPPLIER';
  if (flags.is_karigar) return 'KARIGAR';
  if (flags.is_transporter) return 'TRANSPORTER';
  return 'CUSTOMER';
}

function roleToFlags(role: PartyRole): {
  is_customer: boolean;
  is_supplier: boolean;
  is_karigar: boolean;
  is_transporter: boolean;
} {
  return {
    is_customer: role === 'CUSTOMER',
    is_supplier: role === 'SUPPLIER',
    is_karigar: role === 'KARIGAR',
    is_transporter: role === 'TRANSPORTER',
  };
}

function kindFromRole(role: PartyRole): PartyKind {
  switch (role) {
    case 'CUSTOMER':
      return 'customer';
    case 'SUPPLIER':
      return 'supplier';
    case 'KARIGAR':
      return 'karigar';
    case 'TRANSPORTER':
      return 'transporter';
  }
}

/**
 * Convert a BE Party row → FE Party shape.
 *
 * - `kind` derives from the highest-priority is_X flag.
 * - The four flags are preserved as optional fields so future multi-role
 *   displays can read all of them (the click-dummy ignores them today).
 * - `outstanding` defaults to 0: the BE `/parties` list endpoint doesn't
 *   include a per-party outstanding column today (it's a join against
 *   sales_invoice + payment_allocation). PartyDetail computes its own
 *   khata view from related invoices, so 0 is the right "unknown yet"
 *   default at the list boundary.
 * - `city` defaults to '' for the same reason: BE doesn't have a city
 *   column on Party. (Address is a separate `party_address` table.)
 */
function mapBackendParty(b: BackendParty): Party {
  const role = mapPartyRole(b);
  return {
    party_id: b.party_id,
    code: b.code,
    name: b.name,
    kind: kindFromRole(role),
    gstin: b.gstin ?? undefined,
    state_code: b.state_code ?? '',
    city: '',
    outstanding: 0,
    credit_limit:
      b.credit_limit !== null && b.credit_limit !== undefined
        ? Math.round(parseFloat(String(b.credit_limit)) * 100)
        : undefined,
    is_customer: b.is_customer ?? false,
    is_supplier: b.is_supplier ?? false,
    is_karigar: b.is_karigar ?? false,
    is_transporter: b.is_transporter ?? false,
  };
}

// ──────────────────────────────────────────────────────────────────────
// Mock store — same pattern as invoices.ts. Mutations append to a
// module-level array so the click-dummy stays consistent across renders.
// ──────────────────────────────────────────────────────────────────────

let mockStore: Party[] | null = null;

function ensureMockStore(): Party[] {
  if (mockStore === null) mockStore = [...mockParties];
  return mockStore;
}

export function resetPartyStore() {
  mockStore = null;
}

// ──────────────────────────────────────────────────────────────────────
// Queries
// ──────────────────────────────────────────────────────────────────────

async function liveListAll(): Promise<Party[]> {
  const data = await liveListParties({ limit: 200 });
  return data.items.map(mapBackendParty);
}

async function liveListCustomers(): Promise<Party[]> {
  const data = await liveListParties({ limit: 200, party_type: 'customer' });
  return data.items.map(mapBackendParty);
}

async function liveListSuppliers(): Promise<Party[]> {
  const data = await liveListParties({ limit: 200, party_type: 'supplier' });
  return data.items.map(mapBackendParty);
}

export function useParties() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => (IS_LIVE ? liveListAll() : fakeFetch(() => [...ensureMockStore()])),
  });
}

export function useCustomers() {
  return useQuery({
    queryKey: [...KEY, 'customers'],
    queryFn: () =>
      IS_LIVE
        ? liveListCustomers()
        : fakeFetch(() =>
            // Use the live-projection of the mock fixtures so types stay
            // in sync. Mock customers all have kind='customer'.
            [...mockCustomers],
          ),
  });
}

/**
 * Suppliers (parties with `is_supplier=true`) — used by Purchase Order
 * forms (TASK-CUT-201) and Wave-3 GRN / PI flows. Live mode hits
 * `/parties?party_type=supplier`; mock mode filters the seed fixtures.
 */
export function useSuppliers() {
  return useQuery({
    queryKey: [...KEY, 'suppliers'],
    queryFn: () =>
      IS_LIVE
        ? liveListSuppliers()
        : fakeFetch(() => ensureMockStore().filter((p) => p.kind === 'supplier')),
  });
}

export function useParty(partyId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, partyId],
    enabled: partyId !== undefined,
    queryFn: () => {
      if (IS_LIVE) {
        return liveGetParty(partyId as string).then(mapBackendParty);
      }
      return fakeFetch(() => {
        const all = ensureMockStore();
        return all.find((p) => p.party_id === partyId) ?? null;
      });
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Mutations
// ──────────────────────────────────────────────────────────────────────

export interface CreatePartyInput {
  code: string;
  name: string;
  role: PartyRole;
  state_code?: string;
  gstin?: string;
  pan?: string;
  email?: string;
  phone?: string;
  legal_name?: string;
  /** Provided by the form via useIdempotencyKey(). */
  idempotencyKey: string;
}

function buildCreateBody(input: CreatePartyInput): BackendPartyCreateBody {
  const flags = roleToFlags(input.role);
  // tax_status: backend infers REGULAR-vs-UNREGISTERED downstream;
  // we send REGULAR if a GSTIN is present, UNREGISTERED otherwise.
  // (Composition / consumer / overseas are edge cases — defer to a
  // future "advanced" form.)
  const tax_status = input.gstin ? 'REGULAR' : 'UNREGISTERED';
  return {
    code: input.code,
    name: input.name,
    legal_name: input.legal_name || undefined,
    is_customer: flags.is_customer,
    is_supplier: flags.is_supplier,
    is_karigar: flags.is_karigar,
    is_transporter: flags.is_transporter,
    tax_status,
    gstin: input.gstin || undefined,
    pan: input.pan || undefined,
    phone: input.phone || undefined,
    email: input.email || undefined,
    state_code: input.state_code || undefined,
  };
}

async function liveCreate(input: CreatePartyInput): Promise<Party> {
  const body = buildCreateBody(input);
  const data = await liveCreateParty(body, input.idempotencyKey);
  return mapBackendParty(data);
}

async function mockCreate(input: CreatePartyInput): Promise<Party> {
  return fakeFetch(() => {
    const list = ensureMockStore();
    const created: Party = {
      party_id: `p_mock_${Date.now()}`,
      code: input.code,
      name: input.name,
      kind: kindFromRole(input.role),
      gstin: input.gstin,
      state_code: input.state_code ?? '',
      city: '',
      outstanding: 0,
      ...roleToFlags(input.role),
    };
    mockStore = [created, ...list];
    return created;
  });
}

export function useCreateParty() {
  const qc = useQueryClient();
  return useMutation<Party, ApiError | Error, CreatePartyInput>({
    mutationFn: (input) => (IS_LIVE ? liveCreate(input) : mockCreate(input)),
    onSuccess: () => {
      // Refetch list rather than splice — the live BE may sort or apply
      // RLS in ways the mapper can't reproduce client-side, so the list
      // is best treated as the source of truth.
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}

export interface PatchPartyInput {
  partyId: string;
  patch: {
    name?: string;
    legal_name?: string;
    role?: PartyRole;
    state_code?: string;
    gstin?: string;
    pan?: string;
    email?: string;
    phone?: string;
    is_active?: boolean;
  };
  idempotencyKey: string;
}

function buildPatchBody(patch: PatchPartyInput['patch']): BackendPartyPatchBody {
  const body: BackendPartyPatchBody = {};
  if (patch.name !== undefined) body.name = patch.name;
  if (patch.legal_name !== undefined) body.legal_name = patch.legal_name || null;
  if (patch.state_code !== undefined) body.state_code = patch.state_code || null;
  if (patch.gstin !== undefined) body.gstin = patch.gstin || null;
  if (patch.pan !== undefined) body.pan = patch.pan || null;
  if (patch.email !== undefined) body.email = patch.email || null;
  if (patch.phone !== undefined) body.phone = patch.phone || null;
  if (patch.is_active !== undefined) body.is_active = patch.is_active;
  if (patch.role !== undefined) {
    const flags = roleToFlags(patch.role);
    body.is_customer = flags.is_customer;
    body.is_supplier = flags.is_supplier;
    body.is_karigar = flags.is_karigar;
    body.is_transporter = flags.is_transporter;
  }
  return body;
}

async function livePatch(input: PatchPartyInput): Promise<Party> {
  const body = buildPatchBody(input.patch);
  const data = await livePatchParty(input.partyId, body, input.idempotencyKey);
  return mapBackendParty(data);
}

async function mockPatch(input: PatchPartyInput): Promise<Party> {
  return fakeFetch(() => {
    const list = ensureMockStore();
    const idx = list.findIndex((p) => p.party_id === input.partyId);
    if (idx === -1) throw new Error(`Party ${input.partyId} not found`);
    const merged: Party = { ...list[idx] };
    if (input.patch.name !== undefined) merged.name = input.patch.name;
    if (input.patch.state_code !== undefined) merged.state_code = input.patch.state_code;
    if (input.patch.gstin !== undefined) merged.gstin = input.patch.gstin;
    if (input.patch.role !== undefined) {
      merged.kind = kindFromRole(input.patch.role);
      const flags = roleToFlags(input.patch.role);
      merged.is_customer = flags.is_customer;
      merged.is_supplier = flags.is_supplier;
      merged.is_karigar = flags.is_karigar;
      merged.is_transporter = flags.is_transporter;
    }
    mockStore = [...list.slice(0, idx), merged, ...list.slice(idx + 1)];
    return merged;
  });
}

export function usePatchParty() {
  const qc = useQueryClient();
  return useMutation<Party, ApiError | Error, PatchPartyInput>({
    mutationFn: (input) => (IS_LIVE ? livePatch(input) : mockPatch(input)),
    onSuccess: (next) => {
      qc.setQueryData([...KEY, next.party_id], next);
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}

export interface DeletePartyInput {
  partyId: string;
  idempotencyKey: string;
}

async function liveDelete(input: DeletePartyInput): Promise<void> {
  await liveDeleteParty(input.partyId, input.idempotencyKey);
}

async function mockDelete(input: DeletePartyInput): Promise<void> {
  await fakeFetch(() => {
    const list = ensureMockStore();
    mockStore = list.filter((p) => p.party_id !== input.partyId);
    return undefined;
  });
}

export function useDeleteParty() {
  const qc = useQueryClient();
  return useMutation<void, ApiError | Error, DeletePartyInput>({
    mutationFn: (input) => (IS_LIVE ? liveDelete(input) : mockDelete(input)),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

// Test-only exports.
export const _internal = {
  mapBackendParty,
  mapPartyRole,
  roleToFlags,
  kindFromRole,
  buildCreateBody,
  buildPatchBody,
};

// Re-exports for callers that want the live API types directly (avoids a
// second import path; mirrors the invoices.ts pattern).
export type { BackendParty, BackendPartyCreateBody, BackendPartyPatchBody, ListPartiesParams };
