import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { UserMenu } from '@/components/layout/UserMenu';
import * as identityQueries from '@/lib/queries/identity';
import { authStore, type MeResponse } from '@/store/auth';

const FAKE_ME: MeResponse = {
  user_id: '11111111-1111-1111-1111-111111111111',
  org_id: '22222222-2222-2222-2222-222222222222',
  firm_id: '33333333-3333-3333-3333-333333333333',
  permissions: ['sales.invoice.create'],
  flags: {},
  available_firms: [
    { firm_id: '33333333-3333-3333-3333-333333333333', code: 'ACME', name: 'Acme Co' },
  ],
  token_expires_at: '2099-01-01T00:00:00Z',
  email: 'audit@audit.example',
};

// CUT-006: override the global setupFile beforeEach (which pre-populates
// authStore with mock identity) so this file's empty/unknown-state tests
// see what they expect. Reset BEFORE each test, not after.
beforeEach(() => {
  authStore.reset();
});

afterEach(() => {
  authStore.reset();
  vi.restoreAllMocks();
});

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('UserMenu — identity from authStore', () => {
  it('does NOT render the mock identity ("moiz@rajeshtextiles.in") when authStore is empty', () => {
    wrap(<UserMenu />);
    fireEvent.click(screen.getByRole('button', { name: /User menu/i }));
    expect(screen.queryByText(/moiz@rajeshtextiles\.in/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Moiz Lakkadkutta/i)).not.toBeInTheDocument();
  });

  it('renders the real signed-in email + initials when authStore has a me payload', () => {
    authStore.setMe(FAKE_ME);
    wrap(<UserMenu />);
    fireEvent.click(screen.getByRole('button', { name: /User menu/i }));
    expect(screen.getByText(/audit@audit\.example/i)).toBeInTheDocument();
    // Two-letter initials derived from the email local-part ("AU" from "audit").
    // The trigger button renders the monogram with these initials.
    const avatar = screen.getByRole('button', { name: /User menu/i });
    expect(avatar.textContent).toMatch(/A/i);
  });

  it('renders a quiet placeholder while auth is unknown (no mock leak)', () => {
    // status starts as 'unknown' after reset()
    wrap(<UserMenu />);
    // Trigger renders but identity panel hides the mock email even if popped open.
    fireEvent.click(screen.getByRole('button', { name: /User menu/i }));
    expect(screen.queryByText(/moiz@rajeshtextiles\.in/i)).not.toBeInTheDocument();
  });
});

describe('UserMenu — sign out', () => {
  function mockLogout(mutate: ReturnType<typeof vi.fn>) {
    vi.spyOn(identityQueries, 'useLogout').mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof identityQueries.useLogout>);
  }

  function renderWithLogin() {
    const qc = new QueryClient();
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route path="/" element={<UserMenu />} />
            <Route path="/login" element={<div>login page</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('revokes the server session before leaving for /login', () => {
    const mutate = vi.fn();
    mockLogout(mutate);
    authStore.setMe(FAKE_ME);
    renderWithLogin();
    fireEvent.click(screen.getByRole('button', { name: /User menu/i }));
    fireEvent.click(screen.getByText('Sign out'));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toMatchObject({ idempotencyKey: expect.any(String) });
  });

  it('lands on /login even when the logout call fails', () => {
    const mutate = vi.fn((_input, opts: { onSettled?: () => void }) => opts?.onSettled?.());
    mockLogout(mutate);
    authStore.setMe(FAKE_ME);
    renderWithLogin();
    fireEvent.click(screen.getByRole('button', { name: /User menu/i }));
    fireEvent.click(screen.getByText('Sign out'));
    expect(screen.getByText('login page')).toBeInTheDocument();
  });
});
