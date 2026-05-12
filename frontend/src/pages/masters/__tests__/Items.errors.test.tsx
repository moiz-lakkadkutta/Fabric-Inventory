import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * NewItemDialog — B3 (field_errors) + B4 (idempotency reset) regression
 * tests (TASK-CUT-QA-05c). Mirrors the harness in Parties.errors.test.tsx.
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { authStore } = await import('@/store/auth');
const { default: ItemList } = await import('@/pages/masters/ItemList');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderItemList() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/masters/items']}>
        <Routes>
          <Route path="/masters/items" element={<ItemList />} />
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
    permissions: ['masters.item.read', 'masters.item.create'],
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

function defaultListGet(u: string, method: string): Response | null {
  if (u.includes('/items') && method === 'GET') {
    return jsonResponse(200, { items: [], limit: 200, offset: 0, count: 0 });
  }
  if ((u.includes('/uoms') || u.includes('/hsn')) && method === 'GET') {
    return jsonResponse(200, []);
  }
  return null;
}

describe('NewItemDialog — B3 surfaces BE field_errors', () => {
  it('renders per-field errors from a 422 response', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? 'GET';
      const stock = defaultListGet(u, method);
      if (stock) return stock;
      if (u.endsWith('/items') && method === 'POST') {
        return jsonResponse(422, {
          code: 'VALIDATION_ERROR',
          title: 'Validation error',
          detail: 'One or more fields are invalid.',
          status: 422,
          field_errors: {
            code: ['Item code already exists'],
            hsn_code: ['Unknown HSN'],
          },
        });
      }
      throw new Error(`unexpected fetch: ${method} ${u}`);
    });

    renderItemList();
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /items/i })).toBeInTheDocument(),
    );

    // Header "New item" button has aria-label="New item"; the EmptyState
    // CTA shares the same accessible name when the list is empty. Use
    // the first match (header).
    fireEvent.click(screen.getAllByRole('button', { name: /new item/i })[0]);
    fireEvent.change(screen.getByLabelText(/item code/i), { target: { value: 'DUP' } });
    fireEvent.change(screen.getByLabelText(/item name/i), { target: { value: 'Dup item' } });
    fireEvent.click(screen.getByRole('button', { name: /create item/i }));

    await waitFor(() =>
      expect(screen.getByText(/Item code already exists/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Unknown HSN/i)).toBeInTheDocument();
  });
});

describe('NewItemDialog — B4 resets idempotency key on close + error', () => {
  it('uses a fresh Idempotency-Key for the retry after a 422 + reopen', async () => {
    let listCount = 0;
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? 'GET';
      if (u.includes('/items') && method === 'GET') {
        listCount += 1;
        return jsonResponse(200, { items: [], limit: 200, offset: 0, count: 0 });
      }
      if ((u.includes('/uoms') || u.includes('/hsn')) && method === 'GET') {
        return jsonResponse(200, []);
      }
      if (u.endsWith('/items') && method === 'POST') {
        return jsonResponse(422, {
          code: 'VALIDATION_ERROR',
          title: 'Validation error',
          detail: 'Code already in use.',
          status: 422,
          field_errors: { code: ['Item code already exists'] },
        });
      }
      throw new Error(`unexpected fetch: ${method} ${u}`);
    });

    renderItemList();
    await waitFor(() => expect(listCount).toBeGreaterThanOrEqual(1));

    fireEvent.click(screen.getAllByRole('button', { name: /new item/i })[0]);
    fireEvent.change(screen.getByLabelText(/item code/i), { target: { value: 'X1' } });
    fireEvent.change(screen.getByLabelText(/item name/i), { target: { value: 'X item' } });
    fireEvent.click(screen.getByRole('button', { name: /create item/i }));
    await waitFor(() =>
      expect(screen.getByText(/Item code already exists/i)).toBeInTheDocument(),
    );

    // Close + reopen + retry with a tweaked code.
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
    fireEvent.click(screen.getAllByRole('button', { name: /new item/i })[0]);
    fireEvent.change(screen.getByLabelText(/item code/i), { target: { value: 'X2' } });
    fireEvent.change(screen.getByLabelText(/item name/i), { target: { value: 'X item 2' } });
    fireEvent.click(screen.getByRole('button', { name: /create item/i }));

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith('/items') &&
          (init as RequestInit | undefined)?.method === 'POST',
      );
      expect(posts.length).toBeGreaterThanOrEqual(2);
    });

    const postCalls = fetchMock.mock.calls.filter(
      ([url, init]) =>
        String(url).endsWith('/items') && (init as RequestInit | undefined)?.method === 'POST',
    );
    const firstKey = (postCalls[0][1] as RequestInit).headers as Record<string, string>;
    const secondKey = (postCalls[1][1] as RequestInit).headers as Record<string, string>;
    expect(secondKey['Idempotency-Key']).not.toBe(firstKey['Idempotency-Key']);
  });
});
