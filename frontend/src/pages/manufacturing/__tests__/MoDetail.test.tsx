/*
 * MoDetail — TASK-TR-A14-FU live-mode integration tests.
 *
 * Coverage:
 *   - Three tabs render and switch (Operations / Materials / Cost).
 *   - "Complete MO" button is disabled when status ≠ IN_PROGRESS.
 *   - Dialog open fires GET /completion-preview against the current
 *     produced_qty_target.
 *   - can_complete=false disables Confirm and surfaces blocking reasons.
 *   - can_complete=true enables Confirm; clicking it POSTs /complete
 *     with an Idempotency-Key.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: MoDetail } = await import('@/pages/manufacturing/MoDetail');

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const MO_ID = 'm0000000-0000-0000-0000-000000000001';
const DESIGN_ID = 'd0000000-0000-0000-0000-000000000001';
const ITEM_ID = 'i0000000-0000-0000-0000-000000000001';
const OP_MASTER_ID = 'op000000-0000-0000-0000-000000000001';
const MO_OP_ID = 'mp000000-0000-0000-0000-000000000001';
const MO_MAT_LINE_ID = 'mm000000-0000-0000-0000-000000000001';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

interface BuildMoOpts {
  status?: 'DRAFT' | 'RELEASED' | 'IN_PROGRESS' | 'COMPLETED' | 'CLOSED';
  producedQty?: string | null;
}

function buildMo(opts: BuildMoOpts = {}) {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    design_id: DESIGN_ID,
    finished_item_id: ITEM_ID,
    manufacturing_order_id: MO_ID,
    mo_date: '2026-05-01',
    number: '0001',
    series: 'MO/2026',
    bom_id: null,
    routing_id: null,
    planned_qty: '100.0000',
    produced_qty: opts.producedQty ?? null,
    scrap_qty: null,
    planned_start_date: '2026-05-02',
    planned_end_date: '2026-05-15',
    status: opts.status ?? 'IN_PROGRESS',
    closed_at: null,
    deleted_at: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    operations: [
      {
        manufacturing_order_id: MO_ID,
        mo_operation_id: MO_OP_ID,
        operation_master_id: OP_MASTER_ID,
        operation_sequence: 10,
        executor: 'IN_HOUSE',
        qty_in: '100.0000',
        qty_out: '95.0000',
        state: 'IN_PROGRESS',
      },
    ],
    material_lines: [
      {
        manufacturing_order_id: MO_ID,
        mo_material_line_id: MO_MAT_LINE_ID,
        item_id: ITEM_ID,
        qty_required: '50.0000',
        qty_issued: '20.0000',
        qty_scrap: '0.0000',
        is_optional: false,
      },
    ],
  };
}

function buildOperationMaster() {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    operation_master_id: OP_MASTER_ID,
    code: 'STITCH',
    name: 'Stitching',
    operation_type: 'STITCHING',
    default_duration_mins: null,
    cost_centre_id: null,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function buildItem() {
  return {
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    item_id: ITEM_ID,
    code: 'FAB',
    name: 'Cotton fabric',
    description: null,
    category: null,
    item_type: 'RAW',
    primary_uom: 'METER',
    tracking: 'NONE',
    hsn_code: '5208',
    gst_rate: '5',
    has_variants: false,
    has_expiry: false,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
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
    season: null,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function buildPreview(opts: {
  canComplete: boolean;
  blockingReasons?: string[];
  unitCost?: string;
  costPool?: string;
}) {
  return {
    mo_id: MO_ID,
    status: 'IN_PROGRESS',
    policy: 'ALL_OR_NONE',
    planned_qty: '100.0000',
    produced_qty_target: '100.0000',
    scrap_qty: '0.0000',
    wastage_qty: '0.0000',
    by_product_qty: '0.0000',
    rework_qty: '0.0000',
    cost_pool: opts.costPool ?? '50000.00',
    unit_cost: opts.unitCost ?? '500.000000',
    can_complete: opts.canComplete,
    blocking_reasons: opts.blockingReasons ?? [],
    ledger_codes: { inventory_dr: '1300', wip_cr: '1310' },
  };
}

function renderMoDetail() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/manufacturing/mo/${MO_ID}`]}>
        <Routes>
          <Route path="/manufacturing/mo/:id" element={<MoDetail />} />
          <Route path="/manufacturing/mo" element={<div>LIST_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('MoDetail (live-mode integration, TASK-TR-A14-FU)', () => {
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
      permissions: ['manufacturing.mo.read', 'manufacturing.mo.complete'],
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

  function defaultFetchImpl(mo: ReturnType<typeof buildMo>) {
    return async (url: RequestInfo) => {
      const u = String(url);
      if (
        u.includes('/manufacturing/mo/') &&
        !u.includes('completion-preview') &&
        !u.includes('complete')
      ) {
        return jsonResponse(200, mo);
      }
      if (u.includes('/designs/')) {
        return jsonResponse(200, buildDesign());
      }
      if (u.includes('/designs')) {
        return jsonResponse(200, { items: [buildDesign()], count: 1, limit: 100, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, { items: [buildItem()], count: 1, limit: 200, offset: 0 });
      }
      if (u.includes('/operation-masters')) {
        return jsonResponse(200, {
          items: [buildOperationMaster()],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    };
  }

  it('renders Operations / Materials / Cost tabs and switches between them', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo()));
    renderMoDetail();

    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    // Operations tab is default — Stitching op (from operation master lookup) is visible.
    await waitFor(() => expect(screen.getByText(/Stitching/)).toBeInTheDocument());
    expect(screen.getByText(/IN_HOUSE/)).toBeInTheDocument();

    // Switch to Materials.
    fireEvent.click(screen.getByRole('tab', { name: /materials/i }));
    await waitFor(() => expect(screen.getByText(/Cotton fabric/)).toBeInTheDocument());

    // Switch to Cost.
    fireEvent.click(screen.getByRole('tab', { name: /^cost$/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/Final per-unit cost is computed at completion/i),
      ).toBeInTheDocument(),
    );
  });

  it('"Complete MO" is disabled when status is not IN_PROGRESS', async () => {
    fetchMock.mockImplementation(defaultFetchImpl(buildMo({ status: 'DRAFT' })));
    renderMoDetail();

    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());
    const btn = screen.getByRole('button', { name: /complete mo/i });
    expect(btn).toBeDisabled();
  });

  it('opens the complete dialog, fetches preview, and disables Confirm when can_complete=false', async () => {
    let previewCalls = 0;
    let lastPreviewUrl: string | null = null;
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('completion-preview')) {
        previewCalls += 1;
        lastPreviewUrl = u;
        return jsonResponse(
          200,
          buildPreview({
            canComplete: false,
            blockingReasons: ['Operation 10 (Stitching) is still IN_PROGRESS.'],
          }),
        );
      }
      return defaultFetchImpl(buildMo())(url);
    });

    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /complete mo/i }));

    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /complete mo/i })).toBeInTheDocument(),
    );
    await waitFor(() => expect(previewCalls).toBeGreaterThan(0));

    // The preview URL carries firm_id and produced_qty_target.
    expect(lastPreviewUrl).toContain('firm_id=');
    expect(lastPreviewUrl).toContain('produced_qty_target=100.0000');

    const dialog = screen.getByRole('dialog', { name: /complete mo/i });

    // Blocking reason is rendered verbatim.
    await waitFor(() =>
      expect(
        within(dialog).getByText(/Operation 10 \(Stitching\) is still IN_PROGRESS/),
      ).toBeInTheDocument(),
    );

    // Cost numbers are surfaced even when can_complete is false.
    expect(within(dialog).getByText(/Cost pool/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Unit cost/i)).toBeInTheDocument();

    // Ledger codes show as a tooltip on the unit cost row.
    const unitCostLabel = within(dialog).getByText(/Unit cost/i);
    const unitCostValue = unitCostLabel.parentElement?.querySelector('[title]');
    expect(unitCostValue).toBeTruthy();
    expect((unitCostValue as HTMLElement).getAttribute('title')).toContain('DR 1300');
    expect((unitCostValue as HTMLElement).getAttribute('title')).toContain('CR 1310');

    // Confirm button is disabled.
    expect(within(dialog).getByRole('button', { name: /confirm complete/i })).toBeDisabled();
  });

  it('enables Confirm and POSTs /complete with Idempotency-Key when can_complete=true', async () => {
    let completePayload: Record<string, unknown> | null = null;
    let completeIdempotencyKey: string | null = null;
    let completePath: string | null = null;

    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? 'GET').toUpperCase();
      if (u.includes('completion-preview')) {
        return jsonResponse(200, buildPreview({ canComplete: true }));
      }
      if (u.endsWith('/complete') && method === 'POST') {
        completePath = u;
        completeIdempotencyKey =
          (init?.headers as Record<string, string> | undefined)?.['Idempotency-Key'] ?? null;
        completePayload = JSON.parse((init?.body as string) ?? '{}');
        return jsonResponse(200, buildMo({ status: 'COMPLETED', producedQty: '100.0000' }));
      }
      return defaultFetchImpl(buildMo())(url);
    });

    renderMoDetail();
    await waitFor(() => expect(screen.getByText(/MO\/2026\/0001/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /complete mo/i }));

    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /complete mo/i })).toBeInTheDocument(),
    );

    const dialog = screen.getByRole('dialog', { name: /complete mo/i });

    // Confirm button becomes enabled after the preview returns can_complete=true.
    await waitFor(() => {
      const confirmBtn = within(dialog).getByRole('button', { name: /confirm complete/i });
      expect(confirmBtn).not.toBeDisabled();
    });

    fireEvent.click(within(dialog).getByRole('button', { name: /confirm complete/i }));

    await waitFor(() => expect(completePath).not.toBeNull());
    expect(completePath).toContain(`/manufacturing/mo/${MO_ID}/complete`);
    expect(completePayload).toMatchObject({
      firm_id: FIRM_ID,
      produced_qty: '100.0000',
    });
    expect(completeIdempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);

    // Dialog closes on success.
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /complete mo/i })).not.toBeInTheDocument(),
    );
  });
});
