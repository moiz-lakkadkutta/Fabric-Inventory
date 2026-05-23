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

const {
  mapMoListItemToKanban,
  moStatusToStage,
  deriveMoStage,
  operationTypeToStage,
  daysSinceStart,
} = _internal;

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

describe('operationTypeToStage', () => {
  it('STITCHING → STITCHING lane', () => {
    expect(operationTypeToStage('STITCHING')).toBe('STITCHING');
  });
  it('EMBROIDERY → EMBROIDERY lane', () => {
    expect(operationTypeToStage('EMBROIDERY')).toBe('EMBROIDERY');
  });
  it('QC → QC lane', () => {
    expect(operationTypeToStage('QC')).toBe('QC');
  });
  it('PACKING → PACKED lane (renders in the final column with progress badge)', () => {
    expect(operationTypeToStage('PACKING')).toBe('PACKED');
  });
  it.each(['WEAVING', 'DYEING', 'OTHER', null, undefined] as const)(
    'fabric-prep / unclassified op type (%s) → CUTTING lane',
    (t) => {
      expect(operationTypeToStage(t)).toBe('CUTTING');
    },
  );
});

describe('deriveMoStage', () => {
  it('DRAFT / RELEASED → PLANNED regardless of operations', () => {
    expect(deriveMoStage('DRAFT', [])).toBe('PLANNED');
    expect(deriveMoStage('RELEASED', null)).toBe('PLANNED');
  });
  it('COMPLETED / CLOSED → PACKED', () => {
    expect(deriveMoStage('COMPLETED', null)).toBe('PACKED');
    expect(deriveMoStage('CLOSED', null)).toBe('PACKED');
  });
  it('IN_PROGRESS without operations → falls back to legacy STITCHING', () => {
    expect(deriveMoStage('IN_PROGRESS', null)).toBe('STITCHING');
  });
  it('IN_PROGRESS with all ops CLOSED → PACKED', () => {
    const ops = [
      {
        mo_operation_id: 'op-1',
        operation_master_id: 'm-1',
        operation_sequence: 1,
        state: 'CLOSED' as const,
        executor: 'IN_HOUSE',
        operation_type: 'STITCHING' as const,
        operation_master_name: 'Stitching',
        start_date: '2026-05-10T00:00:00Z',
      },
    ];
    expect(deriveMoStage('IN_PROGRESS', ops)).toBe('PACKED');
  });
  it('picks the FIRST non-CLOSED op by sequence and maps its operation_type', () => {
    // Order in the input shouldn't matter — we sort by operation_sequence.
    const ops = [
      {
        mo_operation_id: 'op-3',
        operation_master_id: 'm-3',
        operation_sequence: 3,
        state: 'PENDING' as const,
        executor: 'IN_HOUSE',
        operation_type: 'QC' as const,
        operation_master_name: 'QC',
        start_date: null,
      },
      {
        mo_operation_id: 'op-1',
        operation_master_id: 'm-1',
        operation_sequence: 1,
        state: 'CLOSED' as const,
        executor: 'IN_HOUSE',
        operation_type: 'WEAVING' as const,
        operation_master_name: 'Weaving',
        start_date: '2026-05-01T00:00:00Z',
      },
      {
        mo_operation_id: 'op-2',
        operation_master_id: 'm-2',
        operation_sequence: 2,
        state: 'IN_PROGRESS' as const,
        executor: 'IN_HOUSE',
        operation_type: 'STITCHING' as const,
        operation_master_name: 'Stitching',
        start_date: '2026-05-12T00:00:00Z',
      },
    ];
    expect(deriveMoStage('IN_PROGRESS', ops)).toBe('STITCHING');
  });
  it('skips past SKIPPED / CANCELLED ops looking for the active one', () => {
    const ops = [
      {
        mo_operation_id: 'op-1',
        operation_master_id: 'm-1',
        operation_sequence: 1,
        state: 'SKIPPED' as const,
        executor: 'IN_HOUSE',
        operation_type: 'WEAVING' as const,
        operation_master_name: 'Weaving',
        start_date: null,
      },
      {
        mo_operation_id: 'op-2',
        operation_master_id: 'm-2',
        operation_sequence: 2,
        state: 'IN_PROGRESS' as const,
        executor: 'IN_HOUSE',
        operation_type: 'EMBROIDERY' as const,
        operation_master_name: 'Embroidery',
        start_date: '2026-05-12T00:00:00Z',
      },
    ];
    expect(deriveMoStage('IN_PROGRESS', ops)).toBe('EMBROIDERY');
  });
});

describe('daysSinceStart', () => {
  it('returns 0 when start_date is missing', () => {
    expect(daysSinceStart(null)).toBe(0);
    expect(daysSinceStart(undefined)).toBe(0);
  });
  it('returns the floor of (now - start) in days', () => {
    const now = new Date('2026-05-23T12:00:00Z');
    expect(daysSinceStart('2026-05-20T12:00:00Z', now)).toBe(3);
    expect(daysSinceStart('2026-05-23T00:00:00Z', now)).toBe(0);
  });
  it('clamps to 0 for future timestamps', () => {
    const now = new Date('2026-05-23T12:00:00Z');
    expect(daysSinceStart('2026-06-01T00:00:00Z', now)).toBe(0);
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
    finished_item_name: 'Bridal Lehenga · Pattern A-402',
    mo_date: '2026-05-14',
    planned_end_date: '2026-06-15',
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

  it('renders finished_item_name as the card product line (was "MO {number}" placeholder)', () => {
    const out = mapMoListItemToKanban(SAMPLE_LIST_ITEM);
    expect(out.product).toBe('Bridal Lehenga · Pattern A-402');
  });

  it('falls back to "MO {number}" when finished_item_name is null (legacy MO)', () => {
    const out = mapMoListItemToKanban({ ...SAMPLE_LIST_ITEM, finished_item_name: null });
    expect(out.product).toBe('MO 00041');
  });

  it('without operations: IN_PROGRESS → legacy STITCHING fallback', () => {
    const out = mapMoListItemToKanban({ ...SAMPLE_LIST_ITEM, operations: null });
    expect(out.stage).toBe('STITCHING');
    expect(out.progress_pct).toBe(0);
  });

  it('with operations: lane comes from the first non-CLOSED op', () => {
    const ops = [
      {
        mo_operation_id: 'op-1',
        operation_master_id: 'm-1',
        operation_sequence: 1,
        state: 'CLOSED' as const,
        executor: 'IN_HOUSE',
        operation_type: 'WEAVING' as const,
        operation_master_name: 'Weaving',
        start_date: '2026-05-01T00:00:00Z',
      },
      {
        mo_operation_id: 'op-2',
        operation_master_id: 'm-2',
        operation_sequence: 2,
        state: 'IN_PROGRESS' as const,
        executor: 'IN_HOUSE',
        operation_type: 'STITCHING' as const,
        operation_master_name: 'Stitching',
        start_date: '2026-05-12T00:00:00Z',
      },
      {
        mo_operation_id: 'op-3',
        operation_master_id: 'm-3',
        operation_sequence: 3,
        state: 'PENDING' as const,
        executor: 'IN_HOUSE',
        operation_type: 'QC' as const,
        operation_master_name: 'QC',
        start_date: null,
      },
    ];
    const now = new Date('2026-05-15T00:00:00Z');
    const out = mapMoListItemToKanban({ ...SAMPLE_LIST_ITEM, operations: ops }, now);
    expect(out.stage).toBe('STITCHING');
    // 1 of 3 ops closed → 33%.
    expect(out.progress_pct).toBe(33);
    // STITCHING op started 2026-05-12; now is 2026-05-15 → 3 days.
    expect(out.days_in_stage).toBe(3);
  });

  it('with operations: all CLOSED → PACKED + 100% (no IN_PROGRESS to time)', () => {
    const ops = [
      {
        mo_operation_id: 'op-1',
        operation_master_id: 'm-1',
        operation_sequence: 1,
        state: 'CLOSED' as const,
        executor: 'IN_HOUSE',
        operation_type: 'STITCHING' as const,
        operation_master_name: 'Stitching',
        start_date: '2026-05-01T00:00:00Z',
      },
    ];
    const out = mapMoListItemToKanban({ ...SAMPLE_LIST_ITEM, operations: ops });
    expect(out.stage).toBe('PACKED');
    expect(out.progress_pct).toBe(100);
    expect(out.days_in_stage).toBe(0);
  });

  it('COMPLETED → PACKED with 100% progress', () => {
    const out = mapMoListItemToKanban({
      ...SAMPLE_LIST_ITEM,
      status: 'COMPLETED',
      operations: null,
    });
    expect(out.stage).toBe('PACKED');
    expect(out.progress_pct).toBe(100);
  });

  it('prefers planned_end_date over mo_date for due_date', () => {
    const out = mapMoListItemToKanban(SAMPLE_LIST_ITEM);
    expect(out.due_date).toBe('2026-06-15');
  });

  it('falls back to mo_date when planned_end_date is absent (legacy MO)', () => {
    const out = mapMoListItemToKanban({
      ...SAMPLE_LIST_ITEM,
      planned_end_date: null,
    });
    expect(out.due_date).toBe('2026-05-14');
  });

  it('leaves customer slot empty (no MO ↔ sales-order link in v1)', () => {
    const out = mapMoListItemToKanban(SAMPLE_LIST_ITEM);
    expect(out.customer).toBe('');
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

  it('forwards ``include=operations`` so the Kanban gets per-op state (TASK-TR-A1)', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        items: [],
        count: 0,
        total_count: 0,
        limit: 100,
        offset: 0,
      }),
    );

    await __live.liveListMos({ include: 'operations' });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('include=operations');
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
