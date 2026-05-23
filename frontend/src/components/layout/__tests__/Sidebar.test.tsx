import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Sidebar } from '@/components/layout/Sidebar';
import { authStore, type MeResponse } from '@/store/auth';

const BASE_ME: MeResponse = {
  user_id: '11111111-1111-1111-1111-111111111111',
  org_id: '22222222-2222-2222-2222-222222222222',
  firm_id: '99999999-9999-9999-9999-999999999999',
  email: 'sidebar@example.com',
  permissions: [],
  flags: {},
  available_firms: [
    { firm_id: '99999999-9999-9999-9999-999999999999', code: 'TEST', name: 'Test Firm' },
  ],
  token_expires_at: '2099-01-01T00:00:00Z',
};

beforeEach(() => {
  authStore.reset();
});

afterEach(() => {
  authStore.reset();
});

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe('Sidebar — Manufacturing flag gating (TASK-TR-A14)', () => {
  it('shows the Manufacturing entry when the flag is missing from /me (default-on)', () => {
    authStore.setMe({ ...BASE_ME, flags: {} });
    renderSidebar();
    expect(screen.getByRole('link', { name: /manufacturing/i })).toBeInTheDocument();
  });

  it('shows the Manufacturing entry when the flag is explicitly true', () => {
    authStore.setMe({ ...BASE_ME, flags: { 'manufacturing.enabled': true } });
    renderSidebar();
    expect(screen.getByRole('link', { name: /manufacturing/i })).toBeInTheDocument();
  });

  it('hides the Manufacturing entry when the flag is explicitly false', () => {
    // A firm that has opted out of the module (admin set the flag to
    // false) must not see the nav row even though the FE default is on.
    authStore.setMe({ ...BASE_ME, flags: { 'manufacturing.enabled': false } });
    renderSidebar();
    expect(screen.queryByRole('link', { name: /manufacturing/i })).not.toBeInTheDocument();
  });

  it('still shows other top-level entries regardless of the flag', () => {
    // Sanity guard: gating Manufacturing must not collateral-hide its
    // neighbours. Inventory + Job work are the entries immediately
    // before and after Manufacturing in the nav.
    authStore.setMe({ ...BASE_ME, flags: { 'manufacturing.enabled': false } });
    renderSidebar();
    expect(screen.getByRole('link', { name: /inventory/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /job work/i })).toBeInTheDocument();
  });
});
