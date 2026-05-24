/*
 * NewOperationDialog — TASK-TR-E1-OPERATIONS integration tests.
 *
 * Covers:
 *   - Radio group renders all 7 operation types.
 *   - Cost-centre select degrades gracefully with no data (hint copy).
 *   - Successful submit POSTs to /operation-masters with the expected
 *     body shape + Idempotency-Key header.
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
const { NewOperationDialog } = await import('@/pages/manufacturing/NewOperationDialog');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const NEW_OP_ID = '99999999-9999-9999-9999-999999999999';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderDialog() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <NewOperationDialog open onClose={() => {}} />
    </QueryClientProvider>,
  );
}

describe('NewOperationDialog (live-mode, TASK-TR-E1)', () => {
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
      permissions: ['manufacturing.operation_master.create'],
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

  it('renders all 7 operation_type radios', () => {
    renderDialog();
    const radios = screen.getAllByRole('radio');
    // 7 op types: WEAVING / DYEING / EMBROIDERY / STITCHING / QC /
    // PACKING / OTHER. They're explicit aria-label values on the
    // buttons so we assert by name.
    const labels = ['Weaving', 'Dyeing', 'Embroidery', 'Stitching', 'QC', 'Packing', 'Other'];
    expect(radios).toHaveLength(7);
    for (const label of labels) {
      expect(screen.getByRole('radio', { name: label })).toBeInTheDocument();
    }
  });

  it('cost-centre select degrades to the loading hint when no data', () => {
    renderDialog();
    expect(
      screen.getByText(/Cost centres are loading — pick one or leave blank/i),
    ).toBeInTheDocument();
    // The select still renders + the empty option is selectable.
    const select = screen.getByLabelText('Cost centre') as HTMLSelectElement;
    expect(select.value).toBe('');
  });

  it('submits the correct body + Idempotency-Key on a happy-path create', async () => {
    fetchMock.mockImplementation(async (_url: RequestInfo, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      const headers = (init?.headers ?? {}) as Record<string, string>;
      return jsonResponse(201, {
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        operation_master_id: NEW_OP_ID,
        code: body?.code ?? '',
        name: body?.name ?? '',
        operation_type: body?.operation_type ?? null,
        default_duration_mins: body?.default_duration_mins ?? null,
        cost_centre_id: body?.cost_centre_id ?? null,
        is_active: true,
        created_at: '2026-05-23T00:00:00Z',
        updated_at: '2026-05-23T00:00:00Z',
        deleted_at: null,
        _capturedHeaders: headers,
      });
    });

    renderDialog();
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'OP-EMB-MKS' } });
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Hand Embroidery — Mukaish' },
    });
    fireEvent.change(screen.getByLabelText('Default duration in minutes'), {
      target: { value: '480' },
    });
    fireEvent.click(screen.getByRole('radio', { name: 'Embroidery' }));

    const submit = screen.getByRole('button', { name: /Create operation/i });
    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/operation-masters'));
    expect(call).toBeTruthy();
    const init = (call as unknown as [RequestInfo, RequestInit])[1];
    expect(init.method).toBe('POST');
    const headers = init.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBeTruthy();
    const body = JSON.parse(String(init.body));
    expect(body).toMatchObject({
      firm_id: FIRM_ID,
      code: 'OP-EMB-MKS',
      name: 'Hand Embroidery — Mukaish',
      operation_type: 'EMBROIDERY',
      default_duration_mins: '480',
      is_active: true,
    });
    // cost_centre_id is omitted when blank.
    expect(body.cost_centre_id).toBeUndefined();
  });

  it('submit stays disabled until code + name + type are present', () => {
    renderDialog();
    const submit = screen.getByRole('button', { name: /Create operation/i });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'OP-EMB-MKS' } });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Mukaish' } });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole('radio', { name: 'Embroidery' }));
    expect(submit).not.toBeDisabled();
  });
});
