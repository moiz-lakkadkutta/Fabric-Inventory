/*
 * Live-path tests for the Manufacturing queries (TASK-TR-A12 v1).
 *
 * Vitest runs with VITE_API_MODE=mock so the hooks short-circuit to the
 * fixture. The live wrappers are exposed via `__live` and exercised
 * directly here with a mocked `globalThis.fetch`, mirroring the pattern
 * used by `purchase-orders.fetch.test.ts`.
 *
 * Coverage:
 *   - Status → Kanban-stage mapping (the lone shape-adaptation in the
 *     queries layer; the pipeline page depends on it).
 *   - `liveListMos` hits `/manufacturing/mo` with the active firm_id
 *     and returns the BE list items.
 *   - `liveGetMo` / `liveGetDesign` / `liveGetBom` / `liveGetRouting`
 *     return the BE detail payload unchanged.
 *   - `liveListDesigns` / `liveListBoms` / `liveListRoutings` send the
 *     active firm_id (required by the BE) and unwrap `data.items`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { __live, _internal } from '@/lib/queries/manufacturing';
import { authStore } from '@/store/auth';

const { mapMoListItemToKanban, moStatusToStage } = _internal;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  authStore.reset();
  authStore.setAccessToken('test-token');
  authStore.setMe({
    user_id: 'u',
    email: 'e@example.com',
    org_id: 'o',
    firm_id: 'f-active',
    permissions: [],
    flags: {},
    available_firms: [],
    token_expires_at: '2026-12-31T00:00:00Z',
  });
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  authStore.reset();
});

// ──────────────────────────────────────────────────────────────────────
// Mappers
// ──────────────────────────────────────────────────────────────────────

describe('moStatusToStage', () => {
  it('DRAFT and RELEASED collapse to PLANNED', () => {
    expect(moStatusToStage('DRAFT')).toBe('PLANNED');
    expect(moStatusToStage('RELEASED')).toBe('PLANNED');
  });
  it('IN_PROGRESS lands at STITCHING (coarse, by design)', () => {
    expect(moStatusToStage('IN_PROGRESS')).toBe('STITCHING');
  });
  it('COMPLETED and CLOSED both render under PACKED', () => {
    expect(moStatusToStage('COMPLETED')).toBe('PACKED');
    expect(moStatusToStage('CLOSED')).toBe('PACKED');
  });
});

describe('mapMoListItemToKanban', () => {
  const SAMPLE_LIST_ITEM = {
    manufacturing_order_id: 'mo-1',
    org_id: 'o',
    firm_id: 'f',
    series: 'MO/25-26',
    number: '00041',
    design_id: 'd-1',
    finished_item_id: 'i-1',
    mo_date: '2026-05-14',
    planned_qty: '25',
    status: 'IN_PROGRESS' as const,
    created_at: '2026-05-01T00:00:00Z',
  };

  it('preserves identity and combines series/number for display', () => {
    const out = mapMoListItemToKanban(SAMPLE_LIST_ITEM);
    expect(out.mo_id).toBe('mo-1');
    expect(out.number).toBe('MO/25-26/00041');
    expect(out.qty).toBe(25);
  });

  it('maps IN_PROGRESS → STITCHING stage so the Kanban places the card', () => {
    const out = mapMoListItemToKanban(SAMPLE_LIST_ITEM);
    expect(out.stage).toBe('STITCHING');
    // No operations array in list shape → progress flat 0.
    expect(out.progress_pct).toBe(0);
  });

  it('COMPLETED → PACKED with 100% progress', () => {
    const out = mapMoListItemToKanban({ ...SAMPLE_LIST_ITEM, status: 'COMPLETED' });
    expect(out.stage).toBe('PACKED');
    expect(out.progress_pct).toBe(100);
  });

  it('surfaces mo_date as due_date placeholder (planned_end_date not in list shape)', () => {
    const out = mapMoListItemToKanban(SAMPLE_LIST_ITEM);
    expect(out.due_date).toBe('2026-05-14');
  });
});

// ──────────────────────────────────────────────────────────────────────
// Live wrappers — fetch-mocked
// ──────────────────────────────────────────────────────────────────────

describe('liveListMos', () => {
  it('GET /manufacturing/mo includes the active firm_id from the auth store', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        items: [],
        count: 0,
        total_count: 0,
        limit: 100,
        offset: 0,
      }),
    );

    const out = await __live.liveListMos();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/manufacturing/mo?');
    expect(url).toContain('firm_id=f-active');
    expect(url).toContain('limit=100');
    expect(out).toEqual([]);
  });

  it('returns BE items unchanged for the Kanban mapper to consume', async () => {
    const item = {
      manufacturing_order_id: 'mo-1',
      org_id: 'o',
      firm_id: 'f-active',
      series: 'MO/25-26',
      number: '00041',
      design_id: 'd-1',
      finished_item_id: 'i-1',
      mo_date: '2026-05-14',
      planned_qty: '25',
      status: 'DRAFT',
      created_at: '2026-05-01T00:00:00Z',
    };
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { items: [item], count: 1, total_count: 1, limit: 100, offset: 0 }),
    );

    const out = await __live.liveListMos();

    expect(out).toHaveLength(1);
    expect(out[0].manufacturing_order_id).toBe('mo-1');
    expect(out[0].status).toBe('DRAFT');
  });
});

describe('liveGetMo', () => {
  it('GET /manufacturing/mo/{id} returns the detail payload', async () => {
    const mo = {
      manufacturing_order_id: 'mo-1',
      org_id: 'o',
      firm_id: 'f-active',
      series: 'MO/25-26',
      number: '00041',
      design_id: 'd-1',
      finished_item_id: 'i-1',
      bom_id: 'b-1',
      routing_id: 'r-1',
      mo_date: '2026-05-14',
      planned_start_date: null,
      planned_end_date: null,
      planned_qty: '25',
      produced_qty: null,
      scrap_qty: null,
      status: 'IN_PROGRESS',
      operations: [],
      material_lines: [],
      closed_at: null,
      created_at: '2026-05-01T00:00:00Z',
      updated_at: '2026-05-01T00:00:00Z',
      deleted_at: null,
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(200, mo));

    const out = await __live.liveGetMo('mo-1');

    expect(fetchMock.mock.calls[0][0]).toContain('/manufacturing/mo/mo-1');
    expect(out.manufacturing_order_id).toBe('mo-1');
    expect(out.status).toBe('IN_PROGRESS');
  });
});

describe('liveListDesigns / liveGetDesign', () => {
  it('liveListDesigns requires + sends firm_id and unwraps items', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        items: [
          {
            design_id: 'd-1',
            org_id: 'o',
            firm_id: 'f-active',
            code: 'BL-402',
            name: 'Bridal Lehenga 402',
            description: null,
            cost_centre_id: null,
            created_at: '2026-05-01T00:00:00Z',
            updated_at: '2026-05-01T00:00:00Z',
            deleted_at: null,
          },
        ],
        count: 1,
        limit: 100,
        offset: 0,
      }),
    );

    const out = await __live.liveListDesigns();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/designs?');
    expect(url).toContain('firm_id=f-active');
    expect(out).toHaveLength(1);
    expect(out[0].code).toBe('BL-402');
  });

  it('liveGetDesign hits /designs/{id}', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        design_id: 'd-1',
        org_id: 'o',
        firm_id: 'f-active',
        code: 'BL-402',
        name: 'Bridal Lehenga 402',
        description: null,
        cost_centre_id: null,
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
        deleted_at: null,
      }),
    );

    const out = await __live.liveGetDesign('d-1');

    expect(fetchMock.mock.calls[0][0]).toContain('/designs/d-1');
    expect(out.design_id).toBe('d-1');
  });
});

describe('liveListBoms / liveGetBom', () => {
  it('liveListBoms forwards firm_id + optional active_only flag', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        items: [],
        count: 0,
        total_count: 0,
        limit: 100,
        offset: 0,
      }),
    );

    await __live.liveListBoms({ active_only: true, design_id: 'd-1' });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/boms?');
    expect(url).toContain('firm_id=f-active');
    expect(url).toContain('design_id=d-1');
    expect(url).toContain('active_only=true');
  });

  it('liveGetBom hits /boms/{id} and returns the BOM with lines', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        bom_id: 'b-1',
        org_id: 'o',
        firm_id: 'f-active',
        design_id: 'd-1',
        finished_item_id: 'i-1',
        version_number: 1,
        is_active: true,
        lines: [
          {
            bom_line_id: 'bl-1',
            bom_id: 'b-1',
            item_id: 'i-2',
            qty_required: '1.5',
            uom: 'METER',
            part_role: 'BODY',
            is_optional: false,
            sequence: 1,
          },
        ],
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
        deleted_at: null,
      }),
    );

    const out = await __live.liveGetBom('b-1');

    expect(fetchMock.mock.calls[0][0]).toContain('/boms/b-1');
    expect(out.bom_id).toBe('b-1');
    expect(out.lines).toHaveLength(1);
    expect(out.lines[0].uom).toBe('METER');
  });
});

describe('liveListRoutings / liveGetRouting', () => {
  it('liveListRoutings forwards firm_id', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        items: [],
        count: 0,
        total_count: 0,
        limit: 100,
        offset: 0,
      }),
    );

    await __live.liveListRoutings();

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/routings?');
    expect(url).toContain('firm_id=f-active');
  });

  it('liveGetRouting hits /routings/{id} and returns edges', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        routing_id: 'r-1',
        org_id: 'o',
        firm_id: 'f-active',
        design_id: 'd-1',
        code: 'R1',
        version_number: 1,
        is_active: true,
        edges: [],
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
        deleted_at: null,
      }),
    );

    const out = await __live.liveGetRouting('r-1');

    expect(fetchMock.mock.calls[0][0]).toContain('/routings/r-1');
    expect(out.routing_id).toBe('r-1');
  });
});

describe('firm_id guard', () => {
  it('liveListDesigns throws when no active firm is set', async () => {
    authStore.reset();
    await expect(__live.liveListDesigns()).rejects.toThrow(/No active firm/);
  });

  it('liveListBoms throws when no active firm is set', async () => {
    authStore.reset();
    await expect(__live.liveListBoms()).rejects.toThrow(/No active firm/);
  });

  it('liveListRoutings throws when no active firm is set', async () => {
    authStore.reset();
    await expect(__live.liveListRoutings()).rejects.toThrow(/No active firm/);
  });
});
