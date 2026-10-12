import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Q01-03 — MFA mandatory for admins (live mode).
 *   - Login answering `requires_mfa_enrollment` stores the enrolment-only
 *     token and routes to /mfa/enroll (no /auth/me, no switch-firm).
 *   - /mfa/enroll runs setup → confirm → logout and ends signed out.
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { default: Login } = await import('@/pages/auth/Login');
const { default: MfaEnroll } = await import('@/pages/auth/MfaEnroll');
const { authStore } = await import('@/store/auth');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderAt(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/mfa/enroll" element={<MfaEnroll />} />
          <Route path="/mfa" element={<div>MFA_VERIFY_REACHED</div>} />
          <Route path="/" element={<div>DASHBOARD_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let fetchMock: ReturnType<typeof vi.fn>;
const calls = () => fetchMock.mock.calls.map(([url]) => String(url));

beforeEach(() => {
  authStore.reset();
  window.__FABRIC_TEST_NO_PREFILL__ = true;
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  delete window.__FABRIC_TEST_NO_PREFILL__;
  authStore.reset();
  vi.restoreAllMocks();
});

describe('MFA enrolment required (live mode)', () => {
  it('routes an unenrolled admin from login to /mfa/enroll holding only the enrolment token', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.endsWith('/auth/login')) {
        return jsonResponse(200, {
          requires_mfa: false,
          requires_mfa_enrollment: true,
          enrollment_token: 'enrol-token',
          user_id: 'u1',
        });
      }
      if (u.endsWith('/auth/mfa/setup')) {
        return jsonResponse(200, { secret: 'ABCDEF234567', provisioning_uri: 'otpauth://x' });
      }
      return jsonResponse(500, { code: 'UNKNOWN', title: 'unexpected', detail: u, status: 500 });
    });

    renderAt('/login');
    fireEvent.change(screen.getByLabelText(/organization/i), { target: { value: 'Org' } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'o@example.com' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByTestId('mfa-secret')).toHaveTextContent('ABCDEF234567');
    expect(authStore.get().accessToken).toBe('enrol-token');
    expect(calls().some((u) => u.endsWith('/auth/me'))).toBe(false);
    expect(calls().some((u) => u.endsWith('/auth/switch-firm'))).toBe(false);
  });

  it('confirms the first code, signs out, and asks the user to sign in again', async () => {
    authStore.setAccessToken('enrol-token');
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/auth/mfa/setup')) {
        return jsonResponse(200, { secret: 'ABCDEF234567', provisioning_uri: 'otpauth://x' });
      }
      if (u.endsWith('/auth/mfa/confirm')) {
        const body = JSON.parse(String(init?.body)) as { code: string };
        const auth = (init?.headers as Record<string, string>)['Authorization'];
        if (body.code === '123456' && auth === 'Bearer enrol-token') {
          return jsonResponse(200, {
            ok: true,
            backup_codes: ['aaaaa-bbbbb', 'ccccc-ddddd'],
          });
        }
        return jsonResponse(400, {
          code: 'INVALID_MFA_CODE',
          title: 'bad',
          detail: '',
          status: 400,
        });
      }
      if (u.endsWith('/auth/logout')) return jsonResponse(200, { revoked: false });
      return jsonResponse(500, { code: 'UNKNOWN', title: 'unexpected', detail: u, status: 500 });
    });

    renderAt('/mfa/enroll');
    await screen.findByTestId('mfa-secret');
    fireEvent.change(screen.getByLabelText(/6-digit code/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /turn on two-factor/i }));

    expect(await screen.findByText(/two-factor authentication is on/i)).toBeInTheDocument();
    expect(screen.getByTestId('mfa-backup-codes')).toHaveTextContent('aaaaa-bbbbb');
    expect(screen.getByText(/wait for a new code/i)).toBeInTheDocument();
    await waitFor(() => expect(authStore.get().accessToken).toBeNull());
    expect(calls().some((u) => u.endsWith('/auth/logout'))).toBe(true);
    expect(screen.getByRole('link', { name: /sign in again/i })).toHaveAttribute('href', '/login');
  });

  it('shows a sign-in link instead of calling setup when there is no token', () => {
    renderAt('/mfa/enroll');
    expect(screen.getByRole('link', { name: /back to sign in/i })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
