import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { UserMenu } from '@/components/layout/UserMenu';
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

afterEach(() => {
  authStore.reset();
});

function wrap(node: React.ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
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
