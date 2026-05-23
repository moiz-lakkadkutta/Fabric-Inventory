import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { authStore } from '@/store/auth';
import AdminHub from '@/pages/admin/AdminHub';

function renderAdmin() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminHub />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AdminHub (CUT-304)', () => {
  it('renders the users list from the queries module', async () => {
    renderAdmin();
    // Mock-mode fixture includes Moiz as the Owner.
    await waitFor(() => expect(screen.getByText('Moiz Lakkadkutta')).toBeInTheDocument());
    // Status pill renders capitalised: ACTIVE → Active.
    expect(screen.getAllByText(/active/i).length).toBeGreaterThanOrEqual(1);
  });

  it('"+ Invite user" opens the InviteUserDialog (replaces TASK-021 coming-soon)', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getByText('Moiz Lakkadkutta')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /invite user/i }));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /invite user/i })).toBeInTheDocument(),
    );
    const dialog = screen.getByRole('dialog', { name: /invite user/i });
    expect(within(dialog).getByLabelText(/email/i)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/^role/i)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /send invite/i })).toBeInTheDocument();
  });

  it('renders per-row role selects (PATCH /admin/users/:id/role surface)', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getByText('Moiz Lakkadkutta')).toBeInTheDocument());
    // Each user row has a labelled select aria-label="Role for {email}".
    const select = screen.getByLabelText(/role for moiz@rajeshtextiles\.in/i);
    expect(select).toBeInTheDocument();
    // Defaults to the user's current role_id; mock fixture is Owner.
    expect((select as HTMLSelectElement).value).toBe('r-owner');
  });

  it('"New role" opens the RoleBuilder dialog (TASK-TR-B4)', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getByText('Moiz Lakkadkutta')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /new role/i }));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /new custom role/i })).toBeInTheDocument(),
    );
    const dialog = screen.getByRole('dialog', { name: /new custom role/i });
    expect(within(dialog).getByLabelText(/role code/i)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/role name/i)).toBeInTheDocument();
  });

  it('hides "New role" button when user lacks identity.role.create', async () => {
    // Re-seed me with a permission set that drops identity.role.create.
    authStore.setMe({
      user_id: 'u',
      org_id: 'mock-org',
      firm_id: 'f',
      email: 'no-perms@example.com',
      permissions: ['admin.user.invite'],
      flags: {},
      available_firms: [],
      token_expires_at: new Date(Date.now() + 3600_000).toISOString(),
    });
    renderAdmin();
    await waitFor(() => expect(screen.getByText('Moiz Lakkadkutta')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /new role/i })).not.toBeInTheDocument();
  });

  it('renders System badge on system roles + no Edit button', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getByText('Moiz Lakkadkutta')).toBeInTheDocument());
    // Mock fixtures: all 4 roles are system roles, so every card has the
    // System badge and no Edit affordance.
    expect(screen.getAllByText(/^system$/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByRole('button', { name: /^edit owner/i })).not.toBeInTheDocument();
  });
});
