import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * NewPartyDialog — B3 (field_errors) regression tests (TASK-CUT-QA-05a).
 *
 * Forces live mode + stubs fetch so we can shape the BE response.
 * Mirrors the harness in Parties.live.test.tsx.
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: PartyList } = await import('@/pages/masters/PartyList');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderPartyList() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/masters/parties']}>
        <Routes>
          <Route path="/masters/parties" element={<PartyList />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  authStore.setMe({
    user_id: 'u1',
    org_id: 'o1',
    firm_id: 'f1',
    email: 'tester@example.com',
    permissions: ['masters.party.read', 'masters.party.create'],
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

describe('NewPartyDialog — B3 surfaces BE field_errors', () => {
  it('renders per-field errors from a 422 response instead of a generic toast', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? 'GET';
      if (u.includes('/parties') && method === 'GET') {
        return jsonResponse(200, { items: [], limit: 200, offset: 0, count: 0 });
      }
      if (u.endsWith('/parties') && method === 'POST') {
        return jsonResponse(422, {
          code: 'VALIDATION_ERROR',
          title: 'Validation error',
          detail: 'One or more fields are invalid.',
          status: 422,
          field_errors: {
            email: ['Invalid email'],
            gstin: ['Invalid GSTIN format'],
          },
        });
      }
      throw new Error(`unexpected fetch: ${method} ${u}`);
    });

    renderPartyList();

    fireEvent.click(screen.getByRole('button', { name: /new party/i }));
    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: 'BAD1' } });
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Bad Party' } });
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: 'not-an-email' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    // Field-level errors are surfaced near each input.
    await waitFor(() => expect(screen.getByText(/Invalid email/i)).toBeInTheDocument());
    expect(screen.getByText(/Invalid GSTIN format/i)).toBeInTheDocument();
  });
});

describe('NewPartyDialog — B4 resets idempotency key on close + error', () => {
  it('uses a fresh Idempotency-Key for the retry after a 422 + reopen', async () => {
    let listCount = 0;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? 'GET';
      if (u.includes('/parties') && method === 'GET') {
        listCount += 1;
        return jsonResponse(200, { items: [], limit: 200, offset: 0, count: 0 });
      }
      if (u.endsWith('/parties') && method === 'POST') {
        // Always reject with 422 so we exercise the error -> retry path.
        return jsonResponse(422, {
          code: 'VALIDATION_ERROR',
          title: 'Validation error',
          detail: 'Email invalid',
          status: 422,
          field_errors: { email: ['Invalid email'] },
        });
      }
      throw new Error(`unexpected fetch: ${method} ${u}`);
    });

    renderPartyList();
    await waitFor(() => expect(listCount).toBeGreaterThanOrEqual(1));

    // First submit -> 422.
    fireEvent.click(screen.getByRole('button', { name: /new party/i }));
    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: 'X1' } });
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'X Party' } });
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: 'bad' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(screen.getByText(/Invalid email/i)).toBeInTheDocument());

    // Close dialog (resets state) then reopen + change email + submit.
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
    fireEvent.click(screen.getByRole('button', { name: /new party/i }));
    fireEvent.change(screen.getByLabelText(/^code$/i), { target: { value: 'X2' } });
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'X Party 2' } });
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: 'still-bad' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith('/parties') && (init as RequestInit | undefined)?.method === 'POST',
      );
      expect(posts.length).toBeGreaterThanOrEqual(2);
    });

    const postCalls = fetchMock.mock.calls.filter(
      ([url, init]) =>
        String(url).endsWith('/parties') && (init as RequestInit | undefined)?.method === 'POST',
    );
    const firstKey = (postCalls[0][1] as RequestInit).headers as Record<string, string>;
    const secondKey = (postCalls[1][1] as RequestInit).headers as Record<string, string>;
    expect(firstKey['Idempotency-Key']).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
    expect(secondKey['Idempotency-Key']).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
    expect(secondKey['Idempotency-Key']).not.toBe(firstKey['Idempotency-Key']);
  });
});
