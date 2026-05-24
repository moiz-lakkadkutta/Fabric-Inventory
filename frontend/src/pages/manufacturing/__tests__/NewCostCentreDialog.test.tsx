/*
 * NewCostCentreDialog — TASK-TR-E1-COSTCENTRES unit tests.
 *
 * Live-mode tests so the POST /cost-centres path runs end-to-end through
 * the real api() wrapper. Each test stubs globalThis.fetch + asserts on
 * the wire body / Idempotency-Key header / success path / failure path.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { NewCostCentreDialog, suggestCostCentreCode } =
  await import('@/pages/manufacturing/NewCostCentreDialog');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const CC_ID = 'c0000000-0000-0000-0000-000000000001';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderDialog(onClose: () => void = () => {}) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <NewCostCentreDialog open={true} onClose={onClose} />
    </QueryClientProvider>,
  );
}

describe('suggestCostCentreCode (helper)', () => {
  it('derives CC-* code from a multi-word name', () => {
    // "In-house stitching" splits as 3 letter-runs: In, house, stitching.
    expect(suggestCostCentreCode('In-house stitching')).toBe('CC-IN-HOU-STI');
  });
  it('handles single-word names', () => {
    expect(suggestCostCentreCode('QC')).toBe('CC-QC');
  });
  it('returns empty when name has no alphanumerics', () => {
    expect(suggestCostCentreCode('   —   ')).toBe('');
  });
  it('strips diacritics and punctuation but keeps letter runs', () => {
    expect(suggestCostCentreCode('Karigar embroidery Imran')).toBe('CC-KAR-EMB-IMR');
  });
});

describe('NewCostCentreDialog (live-mode integration)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    authStore.reset();
    authStore.setAccessToken('test-token');
    authStore.setMe({
      user_id: 'u',
      org_id: ORG_ID,
      firm_id: FIRM_ID,
      email: 'u@example.com',
      permissions: ['manufacturing.cost_centre.create'],
      flags: {},
      available_firms: [{ firm_id: FIRM_ID, code: 'F1', name: 'F1' }],
      token_expires_at: '2099-01-01T00:00:00Z',
    });
  });

  afterEach(() => {
    cleanup();
    globalThis.fetch = originalFetch;
    authStore.reset();
    vi.restoreAllMocks();
  });

  it('auto-suggests the code from the name and stops once the user edits the code', () => {
    renderDialog();
    const name = screen.getByLabelText(/^name$/i);
    const code = screen.getByLabelText(/^code$/i) as HTMLInputElement;

    fireEvent.change(name, { target: { value: 'Karigar embroidery — Imran' } });
    expect(code.value).toBe('CC-KAR-EMB-IMR');

    // User manually edits the code → suggestion no longer overrides it.
    fireEvent.change(code, { target: { value: 'CC-KAR-IMR' } });
    fireEvent.change(name, { target: { value: 'Karigar embroidery — Imran v2' } });
    expect(code.value).toBe('CC-KAR-IMR');
  });

  it('submit stays disabled until code + name are both present', () => {
    renderDialog();
    const submit = screen.getByRole('button', { name: /create cost centre/i });
    expect(submit).toBeDisabled();

    // Only a name (auto-fills code) — but the auto-suggested 3-char name
    // doesn't satisfy the >=3 char rule, so we use a real-looking name.
    fireEvent.change(screen.getByLabelText(/^name$/i), {
      target: { value: 'Karigar embroidery — Imran' },
    });
    // Now both code (auto) and name (>= 3 chars) are set.
    expect(submit).not.toBeDisabled();
  });

  it('POSTs the wire body with Idempotency-Key and closes on success', async () => {
    const onClose = vi.fn();
    let capturedInit: RequestInit | undefined;
    let capturedUrl: string | undefined;

    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      capturedUrl = String(url);
      capturedInit = init;
      return jsonResponse(201, {
        cost_centre_id: CC_ID,
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        code: 'CC-KAR-IMR',
        name: 'Karigar embroidery — Imran',
        cost_centre_type: null,
        parent_cost_centre_id: null,
        is_active: true,
        created_at: '2026-05-24T00:00:00Z',
        updated_at: '2026-05-24T00:00:00Z',
        deleted_at: null,
      });
    });

    renderDialog(onClose);

    fireEvent.change(screen.getByLabelText(/^name$/i), {
      target: { value: 'Karigar embroidery — Imran' },
    });
    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: 'CC-KAR-IMR' } });
    fireEvent.change(screen.getByLabelText(/^description$/i), {
      target: { value: 'Hand embroidery karigar' },
    });
    fireEvent.click(screen.getByRole('button', { name: /create cost centre/i }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());

    // Verify wire endpoint.
    expect(capturedUrl).toContain('/cost-centres');
    expect(capturedInit?.method).toBe('POST');

    // Idempotency-Key header MUST be present (mutating POST).
    const headers = new Headers(capturedInit?.headers as HeadersInit);
    const idemKey = headers.get('Idempotency-Key');
    expect(idemKey).toBeTruthy();
    expect(idemKey).toMatch(/[0-9a-f-]{36}/i);

    // Body shape: firm_id, code, name, is_active — description is UI-only
    // (BE has no column for it) and is intentionally dropped on the wire.
    const body = JSON.parse(capturedInit?.body as string);
    expect(body).toEqual({
      firm_id: FIRM_ID,
      code: 'CC-KAR-IMR',
      name: 'Karigar embroidery — Imran',
      is_active: true,
    });
    expect(body.description).toBeUndefined();
  });

  it('surfaces a field_errors envelope (e.g. duplicate code) inline', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(422, {
        code: 'VALIDATION_ERROR',
        title: 'Validation failed',
        detail: 'Cost centre code already exists',
        field_errors: { code: ['Code already exists for this firm'] },
      }),
    );

    renderDialog();
    fireEvent.change(screen.getByLabelText(/^name$/i), {
      target: { value: 'Karigar embroidery — Imran' },
    });
    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: 'CC-KAR-IMR' } });
    fireEvent.click(screen.getByRole('button', { name: /create cost centre/i }));

    await waitFor(() =>
      expect(screen.getByText(/Code already exists for this firm/i)).toBeInTheDocument(),
    );
  });
});
