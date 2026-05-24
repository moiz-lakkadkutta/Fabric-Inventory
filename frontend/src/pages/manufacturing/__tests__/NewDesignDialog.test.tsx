/*
 * NewDesignDialog — TASK-TR-E1 live-mode integration tests.
 *
 * Coverage:
 *   - Code auto-derives from name (slugify-uppercase).
 *   - Submit is gated until code + name (>= 3 chars) + finished item.
 *   - Typeahead filters Items master to item_type === 'FINISHED'.
 *   - Submit POSTs /designs with the right body + Idempotency-Key header.
 *   - Success closes the dialog.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { NewDesignDialog, slugifyCode } = await import('@/pages/manufacturing/NewDesignDialog');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const FINISHED_ITEM_ID = 'i0000000-0000-0000-0000-000000000001';
const RAW_ITEM_ID = 'i0000000-0000-0000-0000-000000000002';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildItem(opts: { id: string; code: string; name: string; kind: 'FINISHED' | 'RAW' }) {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    item_id: opts.id,
    code: opts.code,
    name: opts.name,
    description: null,
    category: null,
    item_type: opts.kind,
    primary_uom: 'PIECE',
    tracking: 'NONE',
    hsn_code: null,
    gst_rate: '5',
    has_variants: false,
    has_expiry: false,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function renderDialog() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const onClose = vi.fn();
  const result = render(
    <QueryClientProvider client={qc}>
      <NewDesignDialog open={true} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { ...result, onClose };
}

describe('slugifyCode', () => {
  it('uppercases and dash-separates a name', () => {
    expect(slugifyCode('Anarkali Pink')).toBe('ANARKALI-PINK');
    expect(slugifyCode('Kurta off-white chikan!')).toBe('KURTA-OFF-WHITE-CHIKAN');
    expect(slugifyCode('  trailing  spaces  ')).toBe('TRAILING-SPACES');
    expect(slugifyCode('')).toBe('');
    expect(slugifyCode('---')).toBe('');
  });
});

describe('NewDesignDialog (live-mode, TASK-TR-E1)', () => {
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
      permissions: ['manufacturing.design.create'],
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

  function setupFetchHappy(opts: { onCreate?: (body: unknown, idem: string) => void } = {}) {
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.includes('/items') && method === 'GET') {
        return jsonResponse(200, {
          items: [
            buildItem({
              id: FINISHED_ITEM_ID,
              code: 'FIN-KRT-IND',
              name: 'Kurta Indigo Block Print',
              kind: 'FINISHED',
            }),
            buildItem({
              id: 'i-fin-2',
              code: 'FIN-ANK-PNK',
              name: 'Anarkali Pink',
              kind: 'FINISHED',
            }),
            buildItem({
              id: RAW_ITEM_ID,
              code: 'RAW-CTV-60',
              name: 'Cotton Voile 60s',
              kind: 'RAW',
            }),
          ],
          count: 3,
          limit: 200,
          offset: 0,
        });
      }
      if (u.endsWith('/designs') && method === 'POST') {
        const body = JSON.parse((init?.body as string) ?? '{}');
        const idem =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? '';
        opts.onCreate?.(body, idem);
        return jsonResponse(201, {
          org_id: ORG_ID,
          firm_id: FIRM_ID,
          design_id: 'd-new',
          code: body.code,
          name: body.name,
          description: body.description ?? null,
          cost_centre_id: null,
          created_at: '2026-05-23T00:00:00Z',
          updated_at: '2026-05-23T00:00:00Z',
          deleted_at: null,
        });
      }
      return jsonResponse(404, {});
    });
  }

  it('renders the dialog with all required fields', async () => {
    setupFetchHappy();
    renderDialog();
    expect(await screen.findByRole('dialog', { name: /new design/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Code$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Description$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Finished item$/i)).toBeInTheDocument();
  });

  it('Submit is disabled by default and code auto-derives from name', async () => {
    setupFetchHappy();
    renderDialog();
    const dialog = await screen.findByRole('dialog', { name: /new design/i });
    const submit = within(dialog).getByRole('button', { name: /create design/i });
    expect(submit).toBeDisabled();

    const nameInput = screen.getByLabelText(/^Name$/i) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'Anarkali Pink' } });

    const codeInput = screen.getByLabelText(/^Code$/i) as HTMLInputElement;
    await waitFor(() => expect(codeInput.value).toBe('ANARKALI-PINK'));
  });

  it('Submit stays disabled until name >= 3 chars AND a finished item is picked', async () => {
    setupFetchHappy();
    renderDialog();
    const dialog = await screen.findByRole('dialog', { name: /new design/i });
    const submit = within(dialog).getByRole('button', { name: /create design/i });

    fireEvent.change(screen.getByLabelText(/^Name$/i), { target: { value: 'Ku' } });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^Name$/i), { target: { value: 'Kurta Pink' } });
    // Still disabled — no finished item picked.
    expect(submit).toBeDisabled();

    // Pick a finished item via the typeahead.
    const fiInput = screen.getByLabelText(/^Finished item$/i);
    fireEvent.focus(fiInput);
    fireEvent.change(fiInput, { target: { value: 'kurta' } });

    await waitFor(() => expect(screen.getByText(/Kurta Indigo Block Print/i)).toBeInTheDocument());
    // The raw (Cotton Voile) item must NOT appear — typeahead is filtered to FINISHED.
    expect(screen.queryByText(/Cotton Voile/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText(/Kurta Indigo Block Print/i));

    await waitFor(() => expect(submit).not.toBeDisabled());
  });

  it('Submit POSTs /designs with idempotency-key and closes on success', async () => {
    let lastBody: Record<string, unknown> | null = null;
    let lastIdem: string | null = null;
    setupFetchHappy({
      onCreate: (body, idem) => {
        lastBody = body as Record<string, unknown>;
        lastIdem = idem;
      },
    });

    const { onClose } = renderDialog();

    fireEvent.change(screen.getByLabelText(/^Name$/i), {
      target: { value: 'Kurta Off-white Chikankari' },
    });
    fireEvent.change(screen.getByLabelText(/^Description$/i), {
      target: { value: 'Lucknow chikankari panel, Ramadan collection' },
    });

    const fiInput = screen.getByLabelText(/^Finished item$/i);
    fireEvent.focus(fiInput);
    fireEvent.change(fiInput, { target: { value: 'kurta' } });
    await waitFor(() => expect(screen.getByText(/Kurta Indigo Block Print/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Kurta Indigo Block Print/i));

    const dialog = await screen.findByRole('dialog', { name: /new design/i });
    const submit = within(dialog).getByRole('button', { name: /create design/i });
    await waitFor(() => expect(submit).not.toBeDisabled());

    fireEvent.click(submit);

    await waitFor(() => expect(lastBody).not.toBeNull());
    expect(lastBody).toMatchObject({
      firm_id: FIRM_ID,
      code: 'KURTA-OFF-WHITE-CHIKANKARI',
      name: 'Kurta Off-white Chikankari',
      description: 'Lucknow chikankari panel, Ramadan collection',
    });
    expect(lastIdem).toMatch(/^[0-9a-f-]{36}$/i);
    // BE Design has no finished_item_id field today — it must NOT be on the wire.
    expect(lastBody).not.toHaveProperty('finished_item_id');

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('Submit surfaces BE field_errors per-field on 422', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.includes('/items') && method === 'GET') {
        return jsonResponse(200, {
          items: [
            buildItem({
              id: FINISHED_ITEM_ID,
              code: 'FIN-KRT-IND',
              name: 'Kurta Indigo Block Print',
              kind: 'FINISHED',
            }),
          ],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (u.endsWith('/designs') && method === 'POST') {
        return jsonResponse(422, {
          code: 'VALIDATION_ERROR',
          title: 'Validation failed',
          detail: 'Design code already exists',
          status: 422,
          field_errors: { code: ['A design with this code already exists in this firm.'] },
        });
      }
      return jsonResponse(404, {});
    });

    renderDialog();

    fireEvent.change(screen.getByLabelText(/^Name$/i), { target: { value: 'Anarkali Pink' } });

    const fiInput = screen.getByLabelText(/^Finished item$/i);
    fireEvent.focus(fiInput);
    fireEvent.change(fiInput, { target: { value: 'kurta' } });
    await waitFor(() => expect(screen.getByText(/Kurta Indigo Block Print/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Kurta Indigo Block Print/i));

    const dialog = await screen.findByRole('dialog', { name: /new design/i });
    const submit = within(dialog).getByRole('button', { name: /create design/i });
    await waitFor(() => expect(submit).not.toBeDisabled());
    fireEvent.click(submit);

    await waitFor(() =>
      expect(
        screen.getByText(/A design with this code already exists in this firm/i),
      ).toBeInTheDocument(),
    );
  });
});
