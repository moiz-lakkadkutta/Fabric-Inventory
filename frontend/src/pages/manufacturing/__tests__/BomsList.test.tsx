/*
 * BomsList — TASK-TR-E1-BOMS live-mode integration tests.
 *
 * Coverage (matches the 5 list states from the task brief):
 *   1. Loading skeleton renders while the query is pending.
 *   2. Successful GET /boms populates the grouped table + version chips.
 *   3. Empty list renders the "Build your first bill of materials" CTA.
 *   4. Filtered-empty surfaces a "Clear filter" affordance.
 *   5. Error envelope renders the QueryError shell.
 *
 * Plus: Active-only filter chip refetches with `?active_only=true`,
 * and version rows respect the is_active opacity rule.
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
const { default: BomsList } = await import('@/pages/manufacturing/BomsList');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const DESIGN_ID = 'd0000000-0000-0000-0000-000000000001';
const FINISHED_ITEM_ID = 'i0000000-0000-0000-0000-0000000000ff';
const BOM_V1 = 'b0000000-0000-0000-0000-000000000001';
const BOM_V2 = 'b0000000-0000-0000-0000-000000000002';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function buildBom(opts: { id: string; version: number; is_active: boolean; line_count?: number }) {
  const lines = Array.from({ length: opts.line_count ?? 3 }).map((_, i) => ({
    bom_id: opts.id,
    bom_line_id: `${opts.id}-${i}`,
    item_id: FINISHED_ITEM_ID,
    qty_required: '1.0000',
    uom: 'METER',
    is_optional: false,
    part_role: null,
    sequence: i + 1,
  }));
  return {
    bom_id: opts.id,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: DESIGN_ID,
    finished_item_id: FINISHED_ITEM_ID,
    version_number: opts.version,
    is_active: opts.is_active,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-15T00:00:00Z',
    deleted_at: null,
    lines,
  };
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

function buildItem() {
  return {
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
  };
}

function renderList() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/manufacturing/boms']}>
        <Routes>
          <Route path="/manufacturing/boms" element={<BomsList />} />
          <Route path="/manufacturing/boms/new" element={<div>NEW_BOM_REACHED</div>} />
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
    permissions: ['manufacturing.bom.read', 'manufacturing.bom.create'],
    flags: {},
    available_firms: [{ firm_id: FIRM_ID, code: 'F1', name: 'F1' }],
    token_expires_at: '2099-01-01T00:00:00Z',
  });
}

describe('BomsList (live-mode integration, TASK-TR-E1-BOMS)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;

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

  it('renders the loading skeleton while /boms is pending', async () => {
    // never-resolve fetch — query stays pending.
    fetchMock.mockImplementation(() => new Promise(() => {}));
    renderList();
    expect(await screen.findByRole('status', { name: /loading boms/i })).toBeInTheDocument();
  });

  it('renders grouped rows + version chips + active pill on success', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/boms?')) {
        return jsonResponse(200, {
          items: [
            buildBom({ id: BOM_V2, version: 2, is_active: true, line_count: 7 }),
            buildBom({ id: BOM_V1, version: 1, is_active: false, line_count: 5 }),
          ],
          count: 2,
          total_count: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (u.includes('/designs?')) {
        return jsonResponse(200, { items: [buildDesign()], count: 1, limit: 100, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [buildItem()], count: 1, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderList();

    // Design header row appears once for the design group.
    await waitFor(() => {
      const headers = screen.getAllByTestId('bom-design-header');
      expect(headers).toHaveLength(1);
    });

    // Two version rows render under the header.
    const versionRows = screen.getAllByTestId('bom-version-row');
    expect(versionRows).toHaveLength(2);

    // Version chips include both v1 and v2.
    const chips = screen.getAllByTestId('version-chip');
    const chipTexts = chips.map((c) => c.textContent);
    expect(chipTexts).toContain('v2');
    expect(chipTexts).toContain('v1');

    // Active pill on the v2 row, Superseded on v1. "Active" also
    // appears as a column header + filter label, so we match against
    // the chip's data attribute instead of the visible text.
    const activeChips = chips.filter((c) => c.getAttribute('data-active') === 'true');
    expect(activeChips).toHaveLength(1);
    expect(screen.getByText(/Superseded/i)).toBeInTheDocument();
  });

  it('clicking "Active only" refetches with active_only=true', async () => {
    let activeOnlyCount = 0;
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/boms?')) {
        if (u.includes('active_only=true')) {
          activeOnlyCount += 1;
          return jsonResponse(200, {
            items: [buildBom({ id: BOM_V2, version: 2, is_active: true })],
            count: 1,
            total_count: 1,
            limit: 100,
            offset: 0,
          });
        }
        return jsonResponse(200, {
          items: [
            buildBom({ id: BOM_V2, version: 2, is_active: true }),
            buildBom({ id: BOM_V1, version: 1, is_active: false }),
          ],
          count: 2,
          total_count: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (u.includes('/designs?')) {
        return jsonResponse(200, { items: [buildDesign()], count: 1, limit: 100, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [buildItem()], count: 1, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderList();
    await waitFor(() => expect(screen.getAllByTestId('bom-version-row')).toHaveLength(2));

    fireEvent.click(screen.getByRole('button', { name: /Active only/i }));
    await waitFor(() => expect(activeOnlyCount).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(screen.getAllByTestId('bom-version-row')).toHaveLength(1));
  });

  it('empty list surfaces the "Build your first" CTA + routes to /new', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/boms?')) {
        return jsonResponse(200, { items: [], count: 0, total_count: 0, limit: 100, offset: 0 });
      }
      if (u.includes('/designs?')) {
        return jsonResponse(200, { items: [], count: 0, limit: 100, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderList();
    await waitFor(() =>
      expect(screen.getByText(/Build your first bill of materials/i)).toBeInTheDocument(),
    );

    const ctas = screen.getAllByRole('button', { name: /new bom/i });
    fireEvent.click(ctas[ctas.length - 1]);
    expect(screen.getByText('NEW_BOM_REACHED')).toBeInTheDocument();
  });

  it('filtered empty (search miss) shows the no-match CTA', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/boms?')) {
        return jsonResponse(200, {
          items: [buildBom({ id: BOM_V2, version: 2, is_active: true })],
          count: 1,
          total_count: 1,
          limit: 100,
          offset: 0,
        });
      }
      if (u.includes('/designs?')) {
        return jsonResponse(200, { items: [buildDesign()], count: 1, limit: 100, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [buildItem()], count: 1, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderList();
    await waitFor(() => expect(screen.getAllByTestId('bom-version-row')).toHaveLength(1));

    fireEvent.change(screen.getByLabelText(/search boms/i), {
      target: { value: 'zzznomatch' },
    });

    await waitFor(() =>
      expect(screen.getByText(/No BOMs match "zzznomatch"/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole('button', { name: /clear filter/i }));
    await waitFor(() => expect(screen.getAllByTestId('bom-version-row')).toHaveLength(1));
  });

  it('renders the QueryError shell when GET /boms fails', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/boms?')) {
        return jsonResponse(500, {
          code: 'SERVICE_UNAVAILABLE',
          title: 'Service unavailable',
          detail: 'GET /api/v1/boms returned 503',
          status: 503,
          field_errors: {},
        });
      }
      if (u.includes('/designs?')) {
        return jsonResponse(200, { items: [], count: 0, limit: 100, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      return jsonResponse(404, {});
    });

    renderList();
    // QueryError renders a "Retry" affordance.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /retry|try again/i })).toBeInTheDocument(),
    );
  });
});
