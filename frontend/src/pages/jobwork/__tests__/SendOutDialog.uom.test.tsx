/*
 * CUT-QA-07c (B21) — SendOut UOM defaults from the chosen item's primary_uom.
 *
 * Bug report: the Send-out dialog's UOM textbox defaulted to "METER"
 * regardless of the selected item's primary UOM. For a Cotton Suit item
 * (``primary_uom = "PIECE"``) the operator had to hand-edit METER → PIECE
 * on every send-out.
 *
 * The dialog already runs an effect on ``itemId`` change that copies
 * ``items.data.find(...).primary_uom`` into the UOM state. This test
 * locks that behaviour against regression — pick an item whose
 * primary_uom is "PIECE" and assert the UOM field becomes "PIECE",
 * not the literal default "METER".
 *
 * The ``useItems`` query is verified to expose ``primary_uom`` on
 * ``ItemDetail`` (see ``lib/queries/items.ts:mapItemDetail``), so this
 * test stays close to the live wire shape.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: JobWorkOverview } = await import('@/pages/jobwork/JobWorkOverview');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const FIRM_ID = 'f0000000-0000-0000-0000-000000000001';
const ORG_ID = 'o0000000-0000-0000-0000-000000000001';
const KARIGAR_ID = 'k0000000-0000-0000-0000-000000000001';
const ITEM_COTSUIT_ID = 'i0000000-0000-0000-0000-000000000002';

function renderJobWork() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobWorkOverview />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function karigarParty() {
  return {
    party_id: KARIGAR_ID,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    code: 'IMRAN',
    name: 'Imran Khan',
    legal_name: 'Imran Khan',
    is_customer: false,
    is_supplier: false,
    is_karigar: true,
    is_transporter: false,
    tax_status: 'UNREGISTERED',
    gstin: null,
    pan: null,
    phone: null,
    email: null,
    state_code: '24',
    credit_limit: null,
    credit_days: null,
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    deleted_at: null,
  };
}

function cottonSuitItem() {
  return {
    item_id: ITEM_COTSUIT_ID,
    org_id: ORG_ID,
    firm_id: FIRM_ID,
    code: 'COTSUIT',
    name: 'Cotton Suit',
    description: null,
    category: null,
    item_type: 'FINISHED',
    primary_uom: 'PIECE',
    tracking: 'NONE',
    hsn_code: '6204',
    gst_rate: '5',
    has_variants: false,
    has_expiry: false,
    is_active: true,
    created_at: '2026-04-30T00:00:00Z',
    updated_at: '2026-04-30T00:00:00Z',
    deleted_at: null,
  };
}

describe('CUT-QA-07c — SendOutDialog UOM defaults from primary_uom (B21)', () => {
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
      permissions: [
        'jobwork.order.create',
        'jobwork.order.read',
        'masters.party.read',
        'masters.item.read',
      ],
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

  it('selecting Cotton Suit (primary_uom PIECE) sets the UOM field to PIECE', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/job-work-orders') && !u.includes('/receive')) {
        return jsonResponse(200, { items: [], count: 0, limit: 200, offset: 0 });
      }
      if (u.includes('/parties')) {
        return jsonResponse(200, { items: [karigarParty()], count: 1, limit: 200, offset: 0 });
      }
      if (u.includes('/items')) {
        return jsonResponse(200, {
          items: [cottonSuitItem()],
          count: 1,
          limit: 200,
          offset: 0,
        });
      }
      return jsonResponse(404, {});
    });

    renderJobWork();

    fireEvent.click(screen.getByRole('button', { name: /send out/i }));
    const dialog = await screen.findByRole('dialog', { name: /send out/i });

    const itemSelect = within(dialog).getByLabelText(/^item/i) as HTMLSelectElement;
    const uomInput = within(dialog).getByLabelText(/uom/i) as HTMLInputElement;

    // Wait until the items query resolves and the dropdown has the row.
    await waitFor(() => expect(itemSelect.options.length).toBeGreaterThan(1));

    // Pick Cotton Suit.
    fireEvent.change(itemSelect, { target: { value: ITEM_COTSUIT_ID } });

    // The UOM field MUST reflect the item's primary_uom ("PIECE") — not
    // the literal default "METER".
    await waitFor(() => expect(uomInput.value).toBe('PIECE'));
  });
});
