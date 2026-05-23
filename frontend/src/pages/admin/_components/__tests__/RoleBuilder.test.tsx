/*
 * RoleBuilder (TASK-TR-B4) — create / edit / delete custom roles.
 *
 * These tests run against mock-mode so they don't need a live backend.
 * `usePermissionsCatalog`, `useCreateRole`, etc. fall back to the
 * MOCK_PERMISSION_CATALOG / fakeFetch wiring in `lib/queries/admin.ts`.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RoleBuilder } from '@/pages/admin/_components/RoleBuilder';

function renderBuilder(roleId: string | null = null) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  const handleClose = () => {};
  const utils = render(
    <QueryClientProvider client={qc}>
      <RoleBuilder open={true} onClose={handleClose} roleId={roleId} />
    </QueryClientProvider>,
  );
  return { ...utils, qc };
}

describe('RoleBuilder — create mode', () => {
  it('opens with empty code/name/description fields', async () => {
    renderBuilder(null);
    // Catalog loads asynchronously — wait for the form to render.
    await waitFor(() => expect(screen.getByTestId('module-sales')).toBeInTheDocument());
    const dialog = screen.getByRole('dialog', { name: /new custom role/i });
    expect((within(dialog).getByLabelText(/role code/i) as HTMLInputElement).value).toBe('');
    expect((within(dialog).getByLabelText(/role name/i) as HTMLInputElement).value).toBe('');
  });

  it('renders the permission tree grouped by module', async () => {
    renderBuilder(null);
    // Wait for catalog to load.
    await waitFor(() => expect(screen.getByTestId('module-sales')).toBeInTheDocument());
    // Mock catalog includes these modules.
    expect(screen.getByTestId('module-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('module-masters')).toBeInTheDocument();
    expect(screen.getByTestId('module-sales')).toBeInTheDocument();
    expect(screen.getByTestId('module-inventory')).toBeInTheDocument();
    expect(screen.getByTestId('module-accounting')).toBeInTheDocument();
    expect(screen.getByTestId('module-identity')).toBeInTheDocument();
  });

  it('"Select all" toggles every permission in a module', async () => {
    renderBuilder(null);
    await waitFor(() => expect(screen.getByTestId('module-masters')).toBeInTheDocument());
    const mastersSection = screen.getByTestId('module-masters');
    const selectAll = within(mastersSection).getByLabelText(/select all masters/i);
    // Initially none checked.
    expect((selectAll as HTMLInputElement).checked).toBe(false);
    fireEvent.click(selectAll);
    // After toggling, every per-permission checkbox in this module is checked.
    expect((selectAll as HTMLInputElement).checked).toBe(true);
    const leaf = within(mastersSection).getByLabelText('masters.party.create');
    expect((leaf as HTMLInputElement).checked).toBe(true);
  });

  it('shows a validation error when name is empty on submit', async () => {
    renderBuilder(null);
    await waitFor(() => expect(screen.getByTestId('module-sales')).toBeInTheDocument());
    const dialog = screen.getByRole('dialog', { name: /new custom role/i });
    // Fill code but leave name empty.
    fireEvent.change(within(dialog).getByLabelText(/role code/i), {
      target: { value: 'junior_acct' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: /create role/i }));
    await waitFor(() =>
      expect(within(dialog).getByText(/role name is required/i)).toBeInTheDocument(),
    );
  });

  it('validates lowercase code format', async () => {
    renderBuilder(null);
    await waitFor(() => expect(screen.getByTestId('module-sales')).toBeInTheDocument());
    const dialog = screen.getByRole('dialog', { name: /new custom role/i });
    // The input itself lowercases — but if a user pastes an invalid char (a
    // hyphen), the form should still refuse on submit.
    fireEvent.change(within(dialog).getByLabelText(/role code/i), {
      target: { value: 'bad-code' },
    });
    fireEvent.change(within(dialog).getByLabelText(/role name/i), {
      target: { value: 'Bad' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: /create role/i }));
    await waitFor(() =>
      expect(
        within(dialog).getByText(
          /role code must be lowercase letters, numbers, and underscores only/i,
        ),
      ).toBeInTheDocument(),
    );
  });
});

describe('RoleBuilder — edit mode (mock role)', () => {
  it('shows "Edit role" title and disables the code field', async () => {
    renderBuilder('mock-role-id');
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /edit role/i })).toBeInTheDocument(),
    );
    const dialog = screen.getByRole('dialog', { name: /edit role/i });
    // Mock RoleDetail returns a stable shape with code "mock_custom"
    await waitFor(() =>
      expect((within(dialog).getByLabelText(/role code/i) as HTMLInputElement).value).toBe(
        'mock_custom',
      ),
    );
    expect(within(dialog).getByLabelText(/role code/i)).toBeDisabled();
    // Delete button is visible in edit mode for non-system roles.
    expect(within(dialog).getByRole('button', { name: /delete/i })).toBeInTheDocument();
  });

  it('Delete button opens confirmation step', async () => {
    renderBuilder('mock-role-id');
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /edit role/i })).toBeInTheDocument(),
    );
    const dialog = screen.getByRole('dialog', { name: /edit role/i });
    // Wait for role detail to load before clicking delete.
    await waitFor(() =>
      expect((within(dialog).getByLabelText(/role code/i) as HTMLInputElement).value).toBe(
        'mock_custom',
      ),
    );
    fireEvent.click(within(dialog).getByRole('button', { name: /delete/i }));
    await waitFor(() => expect(within(dialog).getByText(/keep role/i)).toBeInTheDocument());
    expect(within(dialog).getByRole('button', { name: /delete role/i })).toBeInTheDocument();
  });
});
