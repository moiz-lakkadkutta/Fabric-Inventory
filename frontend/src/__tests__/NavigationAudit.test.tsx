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
  it('opens the ComingSoon dialog when InvoiceList Export CSV is clicked', async () => {
    wrap(<InvoiceList />);
    await waitFor(() => expect(screen.getByText(/RT\/2526\/0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /export csv/i }));
    expect(screen.getByRole('dialog', { name: /export invoices to csv/i })).toBeInTheDocument();
  });

  it('opens the Notifications popover from the TopBar bell', () => {
    wrap(<TopBar />);
    fireEvent.click(screen.getByRole('button', { name: /notifications/i }));
    expect(screen.getByRole('menu', { name: /notifications/i })).toBeInTheDocument();
    expect(screen.getByText(/Mark all read/)).toBeInTheDocument();
  });

  it('renders the Admin page with users and roles', () => {
    wrap(<AdminHub />);
    expect(screen.getByRole('heading', { level: 1, name: /admin/i })).toBeInTheDocument();
    expect(screen.getByText('Naseem Begum')).toBeInTheDocument();
    expect(screen.getByText(/roles & permissions/i)).toBeInTheDocument();
  });
});
