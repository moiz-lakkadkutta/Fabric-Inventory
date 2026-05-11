import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * ResetPassword page tests — live-mode integration.
 *
 * Live mode is pinned via vi.mock BEFORE importing the page so the
 * useResetPassword hook captures IS_LIVE=true at module load. The
 * test then stubs global.fetch to drive /auth/reset.
 *
 * The page reads its token from the route param `:token` and the
 * org_name from the URL's `?org=` query string (carried through from
 * the email link). Submitting POSTs both back to /auth/reset.
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { default: ResetPassword } = await import('@/pages/auth/ResetPassword');

function renderResetIntoFlow(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/reset/:token" element={<ResetPassword />} />
          <Route path="/login" element={<div>LOGIN_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResetPassword (live mode)', () => {
  it('submits token + org + new password and redirects to /login on success', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.endsWith('/auth/reset')) {
        return jsonResponse(200, { ok: true });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderResetIntoFlow('/reset/the-token-from-email?org=Rajesh%20Textiles');

    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: 'new-password-456' },
    });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), {
      target: { value: 'new-password-456' },
    });
    fireEvent.click(screen.getByRole('button', { name: /set new password/i }));

    await waitFor(() => {
      expect(screen.getByText('LOGIN_REACHED')).toBeInTheDocument();
    });

    const resetCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/auth/reset'));
    expect(resetCall).toBeDefined();
    const body = JSON.parse((resetCall![1] as RequestInit).body as string);
    expect(body).toMatchObject({
      token: 'the-token-from-email',
      org_name: 'Rajesh Textiles',
      new_password: 'new-password-456',
    });
  });

  it('surfaces INVALID_RESET_TOKEN as an inline error and does not redirect', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(400, {
        code: 'INVALID_RESET_TOKEN',
        title: 'Reset link invalid or expired',
        detail: 'Reset link is invalid or has expired.',
        status: 400,
        field_errors: {},
      }),
    );

    renderResetIntoFlow('/reset/expired-token?org=Rajesh%20Textiles');

    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: 'new-password-456' },
    });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), {
      target: { value: 'new-password-456' },
    });
    fireEvent.click(screen.getByRole('button', { name: /set new password/i }));

    expect(await screen.findByText(/invalid or expired/i)).toBeInTheDocument();
    expect(screen.queryByText('LOGIN_REACHED')).not.toBeInTheDocument();
  });
});
