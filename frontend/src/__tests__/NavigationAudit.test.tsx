import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { TopBar } from '@/components/layout/TopBar';
import { CommandPaletteProvider } from '@/hooks/useCommandPalette';
import AdminHub from '@/pages/admin/AdminHub';
import InvoiceList from '@/pages/sales/InvoiceList';

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CommandPaletteProvider>{node}</CommandPaletteProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/*
  T7 navigation audit: spot-check that previously no-op buttons now open
  the ComingSoonDialog or a real popover. The discipline is enforced at
  code level by useComingSoon(); these tests are tracer assertions.
*/
describe('Navigation audit (T7)', () => {
  it('wires the InvoiceList Export CSV button to the live download flow (TASK-CUT-403)', async () => {
    // The old click-dummy ComingSoon dialog was replaced by a real
    // export under TASK-CUT-403. In test (mock-mode) the page short-
    // circuits to a "set VITE_API_MODE=live" notice instead of fetching
    // a CSV; the button is still wired live.
    wrap(<InvoiceList />);
    await waitFor(() => expect(screen.getByText(/RT\/2526\/0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /export invoices to csv/i }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/live backend/i);
    });
    expect(screen.queryByText(/click-dummy/i)).not.toBeInTheDocument();
  });

  it('opens the Notifications popover from the TopBar bell', () => {
    wrap(<TopBar />);
    fireEvent.click(screen.getByRole('button', { name: /notifications/i }));
    expect(screen.getByRole('menu', { name: /notifications/i })).toBeInTheDocument();
    expect(screen.getByText(/Mark all read/)).toBeInTheDocument();
  });

  it('renders the Admin page with users and roles', async () => {
    wrap(<AdminHub />);
    expect(screen.getByRole('heading', { level: 1, name: /admin/i })).toBeInTheDocument();
    // CUT-304: users + roles are loaded via TanStack Query (mock branch
    // in test mode), so we wait for the row to land.
    await waitFor(() => expect(screen.getByText('Naseem Begum')).toBeInTheDocument());
    expect(screen.getByText(/roles & permissions/i)).toBeInTheDocument();
  });
});
