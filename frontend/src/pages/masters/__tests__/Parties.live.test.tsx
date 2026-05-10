import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Live-mode parties tests (TASK-CUT-101).
 *
 * Force IS_LIVE=true so the parties query branches into the live API
 * path. Stub global.fetch so tests stay deterministic — no real backend
 * required. Tests assert the round-trip from `GET /parties` →
 * mapBackendParty → rendered table rows.
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: PartyList } = await import('@/pages/masters/PartyList');
const { default: PartyDetail } = await import('@/pages/masters/PartyDetail');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderMasters(initial = '/masters/parties') {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/masters/parties" element={<PartyList />} />
          <Route path="/masters/parties/:id" element={<PartyDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  // Authed me so RequireAuth-gated rendering and useCreateParty's firm_id
  // both have a valid context.
  authStore.setMe({
    user_id: 'u1',
    org_id: 'o1',
    firm_id: 'f1',
    email: 'tester@example.com',
    permissions: ['masters.party.read', 'masters.party.create', 'masters.party.update'],
    flags: {},
    available_firms: [{ firm_id: 'f1', code: 'AC', name: 'Audit Co' }],
    token_expires_at: '2099-01-01T00:00:00Z',
  });
  authStore.setAccessToken('access-token-abc');
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  authStore.reset();
});

describe('PartyList — live mode', () => {
  it('renders a 2-row party list from GET /parties', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.includes('/parties') && !u.match(/\/parties\/[a-f0-9-]+/)) {
        return jsonResponse(200, {
          items: [
            {
              party_id: '11111111-1111-1111-1111-111111111111',
              org_id: 'o1',
              firm_id: 'f1',
              code: 'ACME',
              name: 'ACME Pvt',
              legal_name: null,
              is_supplier: false,
              is_customer: true,
              is_karigar: false,
              is_transporter: false,
              tax_status: 'REGULAR',
              gstin: '27AAACA1234N1Z5',
              pan: null,
              phone: null,
              email: null,
              state_code: '27',
              contact_person: null,
              credit_limit: null,
              notes: null,
              is_active: true,
              created_at: '2026-05-10T00:00:00Z',
              updated_at: '2026-05-10T00:00:00Z',
              deleted_at: null,
            },
            {
              party_id: '22222222-2222-2222-2222-222222222222',
              org_id: 'o1',
              firm_id: 'f1',
              code: 'BEST',
              name: 'Best Suppliers',
              legal_name: null,
              is_supplier: true,
              is_customer: false,
              is_karigar: false,
              is_transporter: false,
              tax_status: 'REGULAR',
              gstin: null,
              pan: null,
              phone: null,
              email: null,
              state_code: '24',
              contact_person: null,
              credit_limit: null,
              notes: null,
              is_active: true,
              created_at: '2026-05-10T00:00:00Z',
              updated_at: '2026-05-10T00:00:00Z',
              deleted_at: null,
            },
          ],
          limit: 200,
          offset: 0,
          count: 2,
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderMasters();

    await waitFor(() => expect(screen.getByText('ACME Pvt')).toBeInTheDocument());
    expect(screen.getByText('Best Suppliers')).toBeInTheDocument();

    // Code column appears.
    expect(screen.getByText('ACME')).toBeInTheDocument();
    expect(screen.getByText('BEST')).toBeInTheDocument();
  });

  it('+ New party dialog POSTs to /parties with role→boolean-flag mapping and refetches list', async () => {
    let callCount = 0;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? 'GET';
      if (u.includes('/parties') && method === 'GET') {
        callCount += 1;
        if (callCount === 1) {
          return jsonResponse(200, { items: [], limit: 200, offset: 0, count: 0 });
        }
        // Refetch returns the just-created row.
        return jsonResponse(200, {
          items: [
            {
              party_id: '33333333-3333-3333-3333-333333333333',
              org_id: 'o1',
              firm_id: 'f1',
              code: 'NEW1',
              name: 'New Party 1',
              legal_name: null,
              is_supplier: false,
              is_customer: true,
              is_karigar: false,
              is_transporter: false,
              tax_status: 'UNREGISTERED',
              gstin: null,
              pan: null,
              phone: null,
              email: null,
              state_code: '24',
              contact_person: null,
              credit_limit: null,
              notes: null,
              is_active: true,
              created_at: '2026-05-10T00:00:00Z',
              updated_at: '2026-05-10T00:00:00Z',
              deleted_at: null,
            },
          ],
          limit: 200,
          offset: 0,
          count: 1,
        });
      }
      if (u.endsWith('/parties') && method === 'POST') {
        return jsonResponse(201, {
          party_id: '33333333-3333-3333-3333-333333333333',
          org_id: 'o1',
          firm_id: 'f1',
          code: 'NEW1',
          name: 'New Party 1',
          legal_name: null,
          is_supplier: false,
          is_customer: true,
          is_karigar: false,
          is_transporter: false,
          tax_status: 'UNREGISTERED',
          gstin: null,
          pan: null,
          phone: null,
          email: null,
          state_code: '24',
          contact_person: null,
          credit_limit: null,
          notes: null,
          is_active: true,
          created_at: '2026-05-10T00:00:00Z',
          updated_at: '2026-05-10T00:00:00Z',
          deleted_at: null,
        });
      }
      throw new Error(`unexpected fetch: ${method} ${u}`);
    });

    renderMasters();

    // Wait for first list fetch to complete (empty state).
    await waitFor(() => expect(callCount).toBeGreaterThanOrEqual(1));

    fireEvent.click(screen.getByRole('button', { name: /new party/i }));

    // Dialog opens with form fields.
    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: 'NEW1' } });
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'New Party 1' } });
    fireEvent.change(screen.getByLabelText(/^state code$/i), { target: { value: '24' } });
    // Role defaults to Customer; submit.

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    // Wait for refetch + new row.
    await waitFor(() => expect(screen.getByText('New Party 1')).toBeInTheDocument());

    // Inspect POST body — role=CUSTOMER → is_customer:true
    const postCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/parties') && (init as RequestInit | undefined)?.method === 'POST',
    );
    expect(postCall).toBeDefined();
    const body = JSON.parse((postCall![1] as RequestInit).body as string);
    expect(body).toMatchObject({
      code: 'NEW1',
      name: 'New Party 1',
      is_customer: true,
      is_supplier: false,
      is_karigar: false,
      is_transporter: false,
      state_code: '24',
    });
    // Idempotency-Key UUIDv4.
    const headers = (postCall![1] as RequestInit).headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
  });
});

describe('PartyDetail — live mode', () => {
  it('renders detail from GET /parties/:id and PATCHes on Save', async () => {
    const partyId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
    let getCount = 0;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? 'GET';
      if (u.includes(`/parties/${partyId}`) && method === 'GET') {
        getCount += 1;
        return jsonResponse(200, {
          party_id: partyId,
          org_id: 'o1',
          firm_id: 'f1',
          code: 'DETAIL',
          name: getCount > 1 ? 'Renamed Party' : 'Detail Party',
          legal_name: null,
          is_supplier: false,
          is_customer: true,
          is_karigar: false,
          is_transporter: false,
          tax_status: 'REGULAR',
          gstin: '24DETPA1234B1Z5',
          pan: null,
          phone: null,
          email: null,
          state_code: '24',
          contact_person: null,
          credit_limit: null,
          notes: null,
          is_active: true,
          created_at: '2026-05-10T00:00:00Z',
          updated_at: '2026-05-10T00:00:00Z',
          deleted_at: null,
        });
      }
      if (u.includes(`/parties/${partyId}`) && method === 'PATCH') {
        return jsonResponse(200, {
          party_id: partyId,
          org_id: 'o1',
          firm_id: 'f1',
          code: 'DETAIL',
          name: 'Renamed Party',
          legal_name: null,
          is_supplier: false,
          is_customer: true,
          is_karigar: false,
          is_transporter: false,
          tax_status: 'REGULAR',
          gstin: '24DETPA1234B1Z5',
          pan: null,
          phone: null,
          email: null,
          state_code: '24',
          contact_person: null,
          credit_limit: null,
          notes: null,
          is_active: true,
          created_at: '2026-05-10T00:00:00Z',
          updated_at: '2026-05-10T00:01:00Z',
          deleted_at: null,
        });
      }
      throw new Error(`unexpected fetch: ${method} ${u}`);
    });

    renderMasters(`/masters/parties/${partyId}`);

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /Detail Party/i })).toBeInTheDocument(),
    );

    // Click Edit to open the form.
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'Renamed Party' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /Renamed Party/i })).toBeInTheDocument(),
    );

    const patchCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === 'PATCH',
    );
    expect(patchCall).toBeDefined();
    const body = JSON.parse((patchCall![1] as RequestInit).body as string);
    expect(body.name).toBe('Renamed Party');
  });
});
