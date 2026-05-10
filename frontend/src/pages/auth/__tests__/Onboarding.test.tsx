import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * Onboarding wizard tests.
 *
 * The first three exercise the local state machine without touching the
 * network — that's why they don't need a fetch mock. The signup-wire-up
 * tests force live mode (so useSignup picks the live branch) and mock
 * global.fetch to drive the /auth/signup → /auth/me round-trip.
 *
 * Live-mode pin must happen via vi.mock('@/lib/api/mode') BEFORE the
 * Onboarding import is resolved, otherwise IS_LIVE is captured at module
 * load time from the actual VITE_API_MODE env (which the rest of the
 * suite expects to be 'mock').
 */
vi.mock('@/lib/api/mode', () => ({
  API_MODE: 'live',
  IS_LIVE: true,
  IS_MOCK: false,
}));

// Imports below depend on the mock above being in place.
const { authStore } = await import('@/store/auth');
const { default: Onboarding } = await import('@/pages/auth/Onboarding');

function renderOnboardingIntoFlow() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/" element={<div>DASHBOARD_REACHED</div>} />
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
  authStore.reset();
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  authStore.reset();
});

describe('Onboarding wizard — local state machine', () => {
  it('starts on step 1 (Tell us about your organisation)', () => {
    renderOnboardingIntoFlow();
    expect(
      screen.getByRole('heading', { name: /tell us about your organisation/i }),
    ).toBeInTheDocument();
  });

  it('advances to step 2 (Add your first firm) when Next is clicked', () => {
    renderOnboardingIntoFlow();
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    expect(screen.getByRole('heading', { name: /add your first firm/i })).toBeInTheDocument();
  });

  it('returns to step 1 from step 2 with the Back affordance and preserves org name', () => {
    renderOnboardingIntoFlow();
    const orgInput = screen.getByLabelText(/organisation name/i);
    fireEvent.change(orgInput, { target: { value: 'Test Holdings' } });
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    fireEvent.click(screen.getByRole('button', { name: /back/i }));
    expect(
      screen.getByRole('heading', { name: /tell us about your organisation/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/organisation name/i)).toHaveValue('Test Holdings');
  });
});

describe('Onboarding wizard — fields required for signup', () => {
  it('exposes a password input on step 1', () => {
    renderOnboardingIntoFlow();
    const password = screen.getByLabelText(/password/i) as HTMLInputElement;
    expect(password).toBeInTheDocument();
    expect(password.type).toBe('password');
  });

  it('auto-fills state code from GSTIN first two chars on step 2', () => {
    renderOnboardingIntoFlow();
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    const gstin = document.getElementById('gstin') as HTMLInputElement;
    fireEvent.change(gstin, { target: { value: '27AAACR5055K1Z5' } });
    const stateCode = document.getElementById('state-code') as HTMLInputElement;
    expect(stateCode.value).toBe('27');
  });

  it('hides GSTIN and shows state code when tax regime is non-GST', () => {
    renderOnboardingIntoFlow();
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    // The "Non-GST" tax-regime tile is a button labelled "Non-GST · Below threshold or composition"
    const nonGstButton = screen
      .getAllByRole('button')
      .find((b) => /^Non-GST/.test(b.textContent ?? ''));
    expect(nonGstButton).toBeDefined();
    fireEvent.click(nonGstButton!);
    expect(document.getElementById('gstin')).toBeNull();
    expect(document.getElementById('state-code')).not.toBeNull();
  });
});

describe('Onboarding wizard — Vyapar option labelling', () => {
  it('labels the Vyapar import option as coming soon', () => {
    renderOnboardingIntoFlow();
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    fireEvent.click(screen.getByRole('button', { name: /next: opening balances/i }));
    // Either label includes 'coming soon' or the option is removed entirely.
    const optionText = screen.queryByText(/import from vyapar/i);
    if (optionText) {
      expect(optionText.parentElement?.textContent ?? '').toMatch(/coming soon/i);
    }
  });
});

describe('Onboarding wizard — signup wire-up (live mode)', () => {
  it('on Commit & finish: calls /auth/signup, hydrates authStore, navigates to /', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/auth/signup') && init?.method === 'POST') {
        return jsonResponse(201, {
          access_token: 'access-token-abc',
          refresh_token: 'refresh-token-xyz',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_expires_at: '2099-01-01T00:00:00Z',
          user_id: 'u1',
          org_id: 'o1',
          firm_id: 'f1',
        });
      }
      if (u.endsWith('/auth/me') && (!init || init.method === 'GET' || init.method === undefined)) {
        return jsonResponse(200, {
          user_id: 'u1',
          org_id: 'o1',
          firm_id: 'f1',
          permissions: ['org.admin'],
          flags: {},
          available_firms: [{ firm_id: 'f1', code: 'AUDIT', name: 'Audit Co HQ' }],
          token_expires_at: '2099-01-01T00:00:00Z',
        });
      }
      throw new Error(`unexpected fetch: ${init?.method ?? 'GET'} ${u}`);
    });

    renderOnboardingIntoFlow();

    // Step 1: org details + password
    fireEvent.change(screen.getByLabelText(/organisation name/i), {
      target: { value: 'Audit Co' },
    });
    fireEvent.change(screen.getByLabelText(/contact email/i), {
      target: { value: 'owner@auditco.test' },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'strong-password-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));

    // Step 2: firm + GSTIN (state code auto-derives)
    fireEvent.change(screen.getByLabelText(/firm name/i), {
      target: { value: 'Audit HQ' },
    });
    fireEvent.change(document.getElementById('gstin') as HTMLInputElement, {
      target: { value: '27AAACR5055K1Z5' },
    });
    fireEvent.click(screen.getByRole('button', { name: /next: opening balances/i }));

    // Step 3: keep the default opening-balance choice; commit.
    fireEvent.click(screen.getByRole('button', { name: /commit & finish/i }));

    await waitFor(() => {
      expect(screen.getByText('DASHBOARD_REACHED')).toBeInTheDocument();
    });

    // Auth store is hydrated end-to-end.
    expect(authStore.get().accessToken).toBe('access-token-abc');
    expect(authStore.get().me?.firm_id).toBe('f1');

    // Backend received the right body.
    const signupCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/auth/signup'));
    expect(signupCall).toBeDefined();
    const body = JSON.parse((signupCall![1] as RequestInit).body as string);
    expect(body).toMatchObject({
      email: 'owner@auditco.test',
      password: 'strong-password-1',
      org_name: 'Audit Co',
      firm_name: 'Audit HQ',
      state_code: '27',
      gstin: '27AAACR5055K1Z5',
    });
    // Idempotency-Key header is a UUID v4.
    const headers = (signupCall![1] as RequestInit).headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
  });

  it('surfaces the EmailTakenError envelope as an inline error', async () => {
    fetchMock.mockImplementation(async (url: RequestInfo) => {
      const u = String(url);
      if (u.endsWith('/auth/signup')) {
        return jsonResponse(409, {
          code: 'USER_EMAIL_TAKEN',
          title: 'Email already in use',
          detail: 'A user with this email already exists in this org.',
          status: 409,
          field_errors: {},
        });
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    renderOnboardingIntoFlow();
    fireEvent.change(screen.getByLabelText(/organisation name/i), {
      target: { value: 'Audit Co' },
    });
    fireEvent.change(screen.getByLabelText(/contact email/i), {
      target: { value: 'owner@auditco.test' },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'strong-password-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    fireEvent.change(screen.getByLabelText(/firm name/i), {
      target: { value: 'Audit HQ' },
    });
    fireEvent.change(document.getElementById('gstin') as HTMLInputElement, {
      target: { value: '27AAACR5055K1Z5' },
    });
    fireEvent.click(screen.getByRole('button', { name: /next: opening balances/i }));
    fireEvent.click(screen.getByRole('button', { name: /commit & finish/i }));

    expect(await screen.findByText(/email already in use/i)).toBeInTheDocument();
    expect(screen.queryByText('DASHBOARD_REACHED')).not.toBeInTheDocument();
  });
});
