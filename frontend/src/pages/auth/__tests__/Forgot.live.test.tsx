import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Forgot page — live-mode integration test (CUT-303).
 *
 * The mock-mode behaviour stays in `Forgot.test.tsx` (form → confirmation
 * state machine, no fetch). Here we pin live mode and stub fetch to
 * drive /auth/forgot end-to-end.
 *
 * Live mode is pinned via vi.mock BEFORE the Forgot import so the
 * useForgotPassword hook captures IS_LIVE=true at module load — same
 * pattern as Onboarding.test.tsx (signup wire-up tests).
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { default: Forgot } = await import('@/pages/auth/Forgot');

function renderForgot() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/forgot']}>
        <Forgot />
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

describe('Forgot (live mode)', () => {
  it('POSTs /auth/forgot with email + org_name and advances to the confirmation state', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.endsWith('/auth/forgot')) return jsonResponse(200, { ok: true });
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderForgot();

    fireEvent.change(screen.getByLabelText(/organization/i), {
      target: { value: 'Rajesh Textiles' },
    });
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: 'moiz@rajeshtextiles.in' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));

    await waitFor(() => {
      expect(screen.getByText(/check your email/i)).toBeInTheDocument();
    });

    const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/auth/forgot'));
    expect(call).toBeDefined();
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body).toMatchObject({
      email: 'moiz@rajeshtextiles.in',
      org_name: 'Rajesh Textiles',
    });
  });

  it('still shows the generic success state when the backend returned 200 ok (no enumeration)', async () => {
    fetchMock.mockImplementation(async () => jsonResponse(200, { ok: true }));

    renderForgot();

    fireEvent.change(screen.getByLabelText(/organization/i), {
      target: { value: 'No Such Org' },
    });
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: 'ghost@nope.test' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));

    // The generic copy must be identical to the "email exists" branch.
    await waitFor(() => {
      expect(screen.getByText(/check your email/i)).toBeInTheDocument();
    });
  });
});
