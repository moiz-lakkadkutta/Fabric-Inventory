/**
 * Migrations queries — TASK-CUT-402.
 *
 * Live and mock branches per the wave-2 contract. Vite tree-shakes the
 * unused branch at build time.
 *
 * The upload + approve endpoints accept multipart/form-data, which the
 * shared `api()` wrapper doesn't support (it JSON-stringifies bodies).
 * We post directly via `fetch()` against the Vite proxy / same-origin
 * URL so cookies + the in-memory access token still ride along.
 *
 * Mock-mode returns a hard-coded successful reconciliation envelope so
 * the FE dev path stays productive without a backend.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { decodeError } from '@/lib/api/errors';
import { IS_LIVE } from '@/lib/api/mode';
import { authStore } from '@/store/auth';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

const MIGRATIONS_KEY = ['admin', 'migrations'] as const;

// ──────────────────────────────────────────────────────────────────────
// Types — mirror backend schemas/migration.py
// ──────────────────────────────────────────────────────────────────────

export type MigrationStatus = 'UPLOADED' | 'RECONCILED' | 'APPROVED' | 'REJECTED' | 'FAILED';

export interface MigrationReconciliationRow {
  severity: 'error' | 'warn' | 'info';
  code: string;
  message: string;
  source_ref: string | null;
}

export interface MigrationReconciliationReport {
  total_parties: number;
  total_opening_balances: number;
  errors: number;
  warnings: number;
  rows: MigrationReconciliationRow[];
  tb_reconciles: boolean | null;
  /** Signed; positive == DR > CR. Serialised as a Decimal string. */
  tb_diff: string | null;
}

export interface Migration {
  migration_id: string;
  org_id: string;
  firm_id: string;
  source_format: string;
  source_filename: string;
  status: MigrationStatus;
  uploaded_by: string | null;
  uploaded_at: string;
  approved_by: string | null;
  approved_at: string | null;
  rejected_at: string | null;
  failure_reason: string | null;
  reconciliation: MigrationReconciliationReport | null;
}

interface MigrationListEnvelope {
  items: Migration[];
  count: number;
}

// ──────────────────────────────────────────────────────────────────────
// Helpers — multipart fetch with auth + decoded errors
// ──────────────────────────────────────────────────────────────────────

async function multipartPost(
  path: string,
  form: FormData,
  idempotencyKey: string,
): Promise<unknown> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Idempotency-Key': idempotencyKey,
  };
  const accessToken = authStore.get().accessToken;
  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: form,
    credentials: 'include',
  });
  if (!resp.ok) {
    throw await decodeError(resp);
  }
  if (resp.status === 204) return undefined;
  const text = await resp.text();
  if (!text) return undefined;
  return JSON.parse(text);
}

async function jsonPost(path: string, idempotencyKey: string): Promise<unknown> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Idempotency-Key': idempotencyKey,
  };
  const accessToken = authStore.get().accessToken;
  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    credentials: 'include',
  });
  if (!resp.ok) {
    throw await decodeError(resp);
  }
  if (resp.status === 204) return undefined;
  const text = await resp.text();
  if (!text) return undefined;
  return JSON.parse(text);
}

// ──────────────────────────────────────────────────────────────────────
// useMigrations — list
// ──────────────────────────────────────────────────────────────────────

async function liveListMigrations(): Promise<Migration[]> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const accessToken = authStore.get().accessToken;
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;
  const resp = await fetch(`${API_BASE}/admin/migrations`, {
    headers,
    credentials: 'include',
  });
  if (!resp.ok) throw await decodeError(resp);
  const data = (await resp.json()) as MigrationListEnvelope;
  return data.items;
}

function mockListMigrations(): Promise<Migration[]> {
  return Promise.resolve([]);
}

export function useMigrations() {
  return useQuery({
    queryKey: MIGRATIONS_KEY,
    queryFn: () => (IS_LIVE ? liveListMigrations() : mockListMigrations()),
    staleTime: 30_000,
  });
}

// ──────────────────────────────────────────────────────────────────────
// useUploadMigration — POST /admin/migrations multipart
// ──────────────────────────────────────────────────────────────────────

export interface UploadMigrationInput {
  file: File;
  idempotencyKey: string;
}

async function liveUploadMigration(input: UploadMigrationInput): Promise<Migration> {
  const form = new FormData();
  form.append('file', input.file, input.file.name);
  const out = await multipartPost('/admin/migrations', form, input.idempotencyKey);
  return out as Migration;
}

function mockUploadMigration(input: UploadMigrationInput): Promise<Migration> {
  // Echo a plausible reconciliation envelope so the click-dummy renders
  // something convincing without a backend.
  const now = new Date().toISOString();
  return Promise.resolve({
    migration_id: `mock-${crypto.randomUUID()}`,
    org_id: 'mock-org',
    firm_id: 'mock-firm',
    source_format: 'vyapar_excel',
    source_filename: input.file.name,
    status: 'RECONCILED',
    uploaded_by: 'mock-user',
    uploaded_at: now,
    approved_by: null,
    approved_at: null,
    rejected_at: null,
    failure_reason: null,
    reconciliation: {
      total_parties: 47,
      total_opening_balances: 12,
      errors: 0,
      warnings: 1,
      rows: [
        {
          severity: 'info',
          code: 'EXTRACTED',
          message: 'Extracted 47 parties and 12 opening balances from Vyapar export.',
          source_ref: null,
        },
        {
          severity: 'warn',
          code: 'GSTIN_FORMAT_INVALID',
          message: "GSTIN 'BADGSTIN' on row 12 doesn't match the standard format.",
          source_ref: 'row:12',
        },
      ],
      tb_reconciles: true,
      tb_diff: '0',
    },
  });
}

export function useUploadMigration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UploadMigrationInput) =>
      IS_LIVE ? liveUploadMigration(input) : mockUploadMigration(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: MIGRATIONS_KEY }),
  });
}

// ──────────────────────────────────────────────────────────────────────
// useApproveMigration — POST /admin/migrations/{id}/approve multipart
// ──────────────────────────────────────────────────────────────────────

export interface ApproveMigrationInput {
  migration_id: string;
  file: File;
  idempotencyKey: string;
}

async function liveApproveMigration(input: ApproveMigrationInput): Promise<Migration> {
  const form = new FormData();
  form.append('file', input.file, input.file.name);
  const out = await multipartPost(
    `/admin/migrations/${input.migration_id}/approve`,
    form,
    input.idempotencyKey,
  );
  return out as Migration;
}

function mockApproveMigration(input: ApproveMigrationInput): Promise<Migration> {
  const now = new Date().toISOString();
  return Promise.resolve({
    migration_id: input.migration_id,
    org_id: 'mock-org',
    firm_id: 'mock-firm',
    source_format: 'vyapar_excel',
    source_filename: input.file.name,
    status: 'APPROVED',
    uploaded_by: 'mock-user',
    uploaded_at: now,
    approved_by: 'mock-user',
    approved_at: now,
    rejected_at: null,
    failure_reason: null,
    reconciliation: null,
  });
}

export function useApproveMigration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ApproveMigrationInput) =>
      IS_LIVE ? liveApproveMigration(input) : mockApproveMigration(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: MIGRATIONS_KEY }),
  });
}

// ──────────────────────────────────────────────────────────────────────
// useRejectMigration — POST /admin/migrations/{id}/reject
// ──────────────────────────────────────────────────────────────────────

export interface RejectMigrationInput {
  migration_id: string;
  idempotencyKey: string;
}

async function liveRejectMigration(input: RejectMigrationInput): Promise<Migration> {
  const out = await jsonPost(
    `/admin/migrations/${input.migration_id}/reject`,
    input.idempotencyKey,
  );
  return out as Migration;
}

function mockRejectMigration(input: RejectMigrationInput): Promise<Migration> {
  const now = new Date().toISOString();
  return Promise.resolve({
    migration_id: input.migration_id,
    org_id: 'mock-org',
    firm_id: 'mock-firm',
    source_format: 'vyapar_excel',
    source_filename: 'mock.xlsx',
    status: 'REJECTED',
    uploaded_by: 'mock-user',
    uploaded_at: now,
    approved_by: null,
    approved_at: null,
    rejected_at: now,
    failure_reason: null,
    reconciliation: null,
  });
}

export function useRejectMigration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: RejectMigrationInput) =>
      IS_LIVE ? liveRejectMigration(input) : mockRejectMigration(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: MIGRATIONS_KEY }),
  });
}

// Re-export ApiError so consumers can narrow on error type.
export { ApiError };
