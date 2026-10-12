import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Q01-03 follow-up — /mfa (live): sign in with a one-time backup code, and
 * a rejected TOTP tells the user to wait for the next code (the replay guard
 * refuses the code they just used to confirm enrolment).
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

const { default: Mfa } = await import('@/pages/auth/Mfa');
const { authStore } = await import('@/store/auth');

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderMfa() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/mfa']}>
        <Routes>
          <Route path="/mfa" element={<Mfa />} />
          <Route path="/" element={<div>DASHBOARD_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let fetchMock: ReturnType<typeof vi.fn>;
let verifyBodies: Record<string, unknown>[];

beforeEach(() => {
  authStore.reset();
  authStore.setPendingMfa({ email: 'o@example.com', password: 'pw', org_name: 'Org' });
  verifyBodies = [];
  fetchMock = vi.fn(async (url: RequestInfo, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/auth/mfa-verify')) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      verifyBodies.push(body);
      if (body.backup_code === 'abcde-fghij') {
        return jsonResponse(200, {
          access_token: 'full',
          refresh_token: 'r',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_expires_at: '2099-01-01T00:00:00Z',
        });
      }
      return jsonResponse(401, {
        code: 'INVALID_CREDENTIALS',
        title: 'x',
        detail: '',
        status: 401,
      });
    }
    if (u.endsWith('/auth/me')) {
      return jsonResponse(200, {
        user_id: 'u',
        org_id: 'o',
        firm_id: 'f',
        email: 'o@example.com',
        permissions: [],
        flags: {},
        available_firms: [],
        token_expires_at: '2099-01-01T00:00:00Z',
        mfa_enrollment_required: false,
      });
    }
    return jsonResponse(401, { code: 'TOKEN_INVALID', title: 'x', detail: '', status: 401 });
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  authStore.reset();
  vi.restoreAllMocks();
});

describe('Mfa (live mode)', () => {
  it('signs in with a backup code instead of a TOTP code', async () => {
    renderMfa();
    fireEvent.click(screen.getByRole('button', { name: /use a backup code/i }));
    fireEvent.change(screen.getByLabelText(/backup code/i), {
      target: { value: 'abcde-fghij' },
    });
    fireEvent.click(screen.getByRole('button', { name: /verify/i }));
    expect(await screen.findByText('DASHBOARD_REACHED')).toBeInTheDocument();
    expect(verifyBodies[0]).toMatchObject({ backup_code: 'abcde-fghij' });
    expect(verifyBodies[0]).not.toHaveProperty('totp_code');
  });

  it('tells the user to wait for the next code when a TOTP is rejected', async () => {
    renderMfa();
    fireEvent.change(screen.getByLabelText(/verification code/i), {
      target: { value: '123456' },
    });
    fireEvent.click(screen.getByRole('button', { name: /verify/i }));
    expect(await screen.findByText(/wait for the next code/i)).toBeInTheDocument();
  });
});
