import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

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

  it('"Add role" still opens the coming-soon (custom roles deferred)', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getByText('Moiz Lakkadkutta')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /add role/i }));
    await waitFor(() => expect(screen.getByText(/custom roles/i)).toBeInTheDocument());
  });
});
