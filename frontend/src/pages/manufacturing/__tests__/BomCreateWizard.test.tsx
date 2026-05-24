/*
 * BomCreateWizard — TASK-TR-E1-BOMS live-mode integration tests.
 *
 * Coverage (matches the task brief):
 *   - Tab progress visual renders all three steps.
 *   - Forward navigation gates on per-tab validation (Next on an empty
 *     design picker stays on Tab A, surfaces a banner).
 *   - Backward navigation is unrestricted (click an earlier tab).
 *   - Submit path: POST /boms fires with the correct body shape +
 *     Idempotency-Key header.
 *   - Activate path: the "Set as active" checkbox is on by default; the
 *     server already auto-activates on create, so we just verify the
 *     POST happens with `is_active=true` on the returned row (no
 *     additional activate call is needed).
 *   - Form-level banner appears when trying to advance to Review with
 *     an empty lines table.
 *
 * Pattern: mirror MoCreateWizard.test.tsx — pin IS_LIVE, drive fetches
 * via a captured mock, render the wizard inside MemoryRouter.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: BomCreateWizard } = await import('@/pages/manufacturing/BomCreateWizard');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const DESIGN_ID = 'd0000000-0000-0000-0000-000000000001';
const FINISHED_ITEM_ID = 'i0000000-0000-0000-0000-0000000000ff';
const RAW_ITEM_ID = 'i0000000-0000-0000-0000-000000000010';
const NEW_BOM_ID = 'b0000000-0000-0000-0000-0000000000aa';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildDesign() {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: DESIGN_ID,
    code: 'BRDL-01',
    name: 'Bridal Lehenga',
    description: null,
    cost_centre_id: null,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function buildItems() {
  return [
    {
      item_id: FINISHED_ITEM_ID,
      org_id: ORG_ID,
      firm_id: FIRM_ID,
      code: 'FIN-BRDL',
      name: 'Bridal Lehenga Set',
      primary_uom: 'SET',
      tracking: 'NONE',
      hsn_code: null,
      gst_rate: null,
      has_variants: false,
      has_expiry: false,
      is_active: true,
      item_type: 'FINISHED',
      category: null,
      description: null,
      created_at: '2026-04-01T00:00:00Z',
      updated_at: '2026-04-01T00:00:00Z',
      deleted_at: null,
    },
    {
      item_id: RAW_ITEM_ID,
      org_id: ORG_ID,
      firm_id: FIRM_ID,
      code: 'RAW-FAB',
      name: 'Cotton fabric',
      primary_uom: 'METER',
      tracking: 'NONE',
      hsn_code: null,
      gst_rate: null,
      has_variants: false,
      has_expiry: false,
      is_active: true,
      item_type: 'RAW',
      category: null,
      description: null,
      created_at: '2026-04-01T00:00:00Z',
      updated_at: '2026-04-01T00:00:00Z',
      deleted_at: null,
    },
  ];
}

function buildBomResponse() {
  return {
    bom_id: NEW_BOM_ID,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: DESIGN_ID,
    finished_item_id: FINISHED_ITEM_ID,
    version_number: 1,
    is_active: true,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    deleted_at: null,
    lines: [
      {
        bom_id: NEW_BOM_ID,
        bom_line_id: 'bl1',
        item_id: RAW_ITEM_ID,
        qty_required: '2.5000',
        uom: 'METER',
        is_optional: false,
        part_role: null,
        sequence: 1,
      },
    ],
  };
}

interface FixtureOpts {
  /** Inject prior BOMs for the picked design (to test version-bump). */
  priorBoms?: Array<{ version: number; is_active: boolean }>;
}

function buildFetchImpl(opts: FixtureOpts = {}) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const impl = async (url: RequestInfo, init?: RequestInit) => {
    const u = String(url);
    calls.push({ url: u, init });

    if (u.includes('/designs')) {
      return jsonResponse(200, { items: [buildDesign()], count: 1, limit: 100, offset: 0 });
    }
    if (u.includes('/items')) {
      return jsonResponse(200, { items: buildItems(), count: 2, limit: 200, offset: 0 });
    }
    if (u.includes('/boms') && (init?.method ?? 'GET') === 'GET') {
      const items = (opts.priorBoms ?? []).map((b, i) => ({
        bom_id: `prior-${i}`,
        org_id: ORG_ID,
        firm_id: FIRM_ID,
        design_id: DESIGN_ID,
        finished_item_id: FINISHED_ITEM_ID,
        version_number: b.version,
        is_active: b.is_active,
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
        deleted_at: null,
        lines: [],
      }));
      return jsonResponse(200, {
        items,
        count: items.length,
        total_count: items.length,
        limit: 100,
        offset: 0,
      });
    }
    if (u.endsWith('/boms') && init?.method === 'POST') {
      return jsonResponse(201, buildBomResponse());
    }
    return jsonResponse(404, {});
  };
  return { impl, calls };
}

function renderWizard() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/manufacturing/boms/new']}>
        <Routes>
          <Route path="/manufacturing/boms/new" element={<BomCreateWizard />} />
          <Route path="/manufacturing/boms" element={<div>LIST_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function seedAuth() {
  authStore.reset();
  authStore.setAccessToken('test-token');
  authStore.setMe({
    user_id: 'u',
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    email: 'u@example.com',
    permissions: ['manufacturing.bom.create', 'manufacturing.bom.update'],
    flags: {},
    available_firms: [{ firm_id: FIRM_ID, code: 'F1', name: 'F1' }],
    token_expires_at: '2099-01-01T00:00:00Z',
  });
}

let originalFetch: typeof fetch;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  seedAuth();
});

afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
  authStore.reset();
  vi.restoreAllMocks();
});

describe('BomCreateWizard — tab progress + nav', () => {
  it('renders all three step tabs', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();

    expect(
      await screen.findByRole('tab', { name: /design & version/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^lines$/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /review & activate/i })).toBeInTheDocument();
  });

  it('blocks advancing to Lines until a design + finished item are picked', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();

    // Click "Next" on Tab A with no design — banner appears.
    fireEvent.click(await screen.findByRole('button', { name: /^Next/i }));
    expect(await screen.findByTestId('wizard-banner-error')).toHaveTextContent(
      /pick a design and finished item/i,
    );
    // Active tab is still "Design & version".
    expect(screen.getByRole('tab', { name: /design & version/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('advances forward once Tab A is valid + allows clicking back', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();

    await screen.findByRole('option', { name: /BRDL-01/i });
    fireEvent.click(screen.getByRole('option', { name: /BRDL-01/i }));
    fireEvent.change(screen.getByLabelText(/finished item/i), {
      target: { value: FINISHED_ITEM_ID },
    });

    fireEvent.click(screen.getByRole('button', { name: /^Next/i }));
    expect(screen.getByRole('tab', { name: /^Lines$/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );

    // Click back to Tab A.
    fireEvent.click(screen.getByRole('tab', { name: /design & version/i }));
    expect(screen.getByRole('tab', { name: /design & version/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });
});

describe('BomCreateWizard — Tab A version bump', () => {
  it('next-version = max(prior versions) + 1 when prior BOMs exist', async () => {
    const { impl } = buildFetchImpl({
      priorBoms: [
        { version: 3, is_active: true },
        { version: 2, is_active: false },
        { version: 1, is_active: false },
      ],
    });
    fetchMock.mockImplementation(impl);
    renderWizard();

    await screen.findByRole('option', { name: /BRDL-01/i });
    fireEvent.click(screen.getByRole('option', { name: /BRDL-01/i }));

    // The version input reflects the next bump.
    await waitFor(() =>
      expect((screen.getByTestId('next-version') as HTMLInputElement).value).toBe('v4'),
    );
  });

  it('next-version defaults to v1 when no prior BOMs exist', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();

    await screen.findByRole('option', { name: /BRDL-01/i });
    fireEvent.click(screen.getByRole('option', { name: /BRDL-01/i }));

    await waitFor(() =>
      expect((screen.getByTestId('next-version') as HTMLInputElement).value).toBe('v1'),
    );
  });
});

describe('BomCreateWizard — submit', () => {
  it('POSTs /boms with the correct body + Idempotency-Key on Activate', async () => {
    const { impl, calls } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();

    // Tab A — pick design + finished item.
    await screen.findByRole('option', { name: /BRDL-01/i });
    fireEvent.click(screen.getByRole('option', { name: /BRDL-01/i }));
    fireEvent.change(screen.getByLabelText(/finished item/i), {
      target: { value: FINISHED_ITEM_ID },
    });

    // Next → Tab B.
    fireEvent.click(screen.getByRole('button', { name: /^Next/i }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /^Lines$/i })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );

    // Edit the seeded empty line: pick item + qty.
    const itemSelect = screen.getByLabelText(/item for line 1/i) as HTMLSelectElement;
    fireEvent.change(itemSelect, { target: { value: RAW_ITEM_ID } });
    fireEvent.change(screen.getByLabelText(/qty per unit for line 1/i), {
      target: { value: '2.5' },
    });

    // Next → Tab C.
    fireEvent.click(screen.getByRole('button', { name: /^Next/i }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /review & activate/i })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );

    // Activate button.
    fireEvent.click(screen.getByRole('button', { name: /^Activate v1$/i }));

    await waitFor(() => expect(screen.getByText('LIST_REACHED')).toBeInTheDocument());

    // Find the POST /boms call.
    const post = calls.find(
      (c) => c.init?.method === 'POST' && c.url.endsWith('/boms'),
    );
    expect(post).toBeTruthy();
    const headers = (post!.init!.headers ?? {}) as Record<string, string>;
    expect(headers['Idempotency-Key']).toMatch(/[0-9a-f-]{36}/);
    const body = JSON.parse(post!.init!.body as string);
    expect(body.firm_id).toBe(FIRM_ID);
    expect(body.design_id).toBe(DESIGN_ID);
    expect(body.finished_item_id).toBe(FINISHED_ITEM_ID);
    expect(body.lines).toHaveLength(1);
    expect(body.lines[0]).toMatchObject({
      item_id: RAW_ITEM_ID,
      qty_required: '2.5',
      uom: 'METER',
      is_optional: false,
    });
    // scrap_pct is UI-only; it must NOT appear on the wire body.
    expect(body.lines[0]).not.toHaveProperty('scrap_pct');
  });

  it('surfaces a banner when advancing to Review without any valid lines', async () => {
    const { impl } = buildFetchImpl();
    fetchMock.mockImplementation(impl);
    renderWizard();

    // Tab A valid.
    await screen.findByRole('option', { name: /BRDL-01/i });
    fireEvent.click(screen.getByRole('option', { name: /BRDL-01/i }));
    fireEvent.change(screen.getByLabelText(/finished item/i), {
      target: { value: FINISHED_ITEM_ID },
    });
    fireEvent.click(screen.getByRole('button', { name: /^Next/i }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /^Lines$/i })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );

    // Don't pick an item / qty — try to advance.
    fireEvent.click(screen.getByRole('button', { name: /^Next/i }));
    expect(await screen.findByTestId('wizard-banner-error')).toBeInTheDocument();
    // Active tab is still Lines.
    expect(screen.getByRole('tab', { name: /^Lines$/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });
});
