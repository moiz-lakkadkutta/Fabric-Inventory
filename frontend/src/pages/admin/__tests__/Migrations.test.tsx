import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import Migrations from '@/pages/admin/Migrations';

function renderMigrations() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Migrations />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Migrations (CUT-402)', () => {
  it('renders the upload form + empty migration history', async () => {
    renderMigrations();
    expect(screen.getByText(/data migration/i)).toBeInTheDocument();
    expect(screen.getByText(/upload new migration/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload and preview/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/no migrations yet/i)).toBeInTheDocument());
  });

  it('uploading a file in mock mode renders the reconciliation report with Approve enabled', async () => {
    renderMigrations();

    const file = new File(['fake xlsx bytes'], 'vyapar-sample.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const input = screen.getByLabelText(/migration source file/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    fireEvent.click(screen.getByRole('button', { name: /upload and preview/i }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /reconciliation report/i })).toBeInTheDocument(),
    );

    // The mock fixture reconciliation reports balanced TB → Approve enabled.
    const approve = screen.getByRole('button', { name: /approve and commit/i });
    expect(approve).toBeEnabled();
    expect(screen.getByRole('button', { name: /^reject$/i })).toBeEnabled();
  });

  it('refuses to upload when no file selected', () => {
    renderMigrations();
    fireEvent.click(screen.getByRole('button', { name: /upload and preview/i }));
    // The Upload button is disabled until a file is picked; the alert
    // is only set if the user manages to submit (e.g. via Enter on a
    // file input). Either path leaves the report panel out of the DOM.
    expect(
      screen.queryByRole('heading', { name: /reconciliation report/i }),
    ).not.toBeInTheDocument();
  });
});
