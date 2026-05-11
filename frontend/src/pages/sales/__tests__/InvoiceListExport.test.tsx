import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetInvoiceStore } from '@/lib/queries/invoices';
import InvoiceList from '@/pages/sales/InvoiceList';

/**
 * TASK-CUT-403 — Export CSV button in InvoiceList wires to the
 * download helper.
 *
 * Tests run in mock mode (VITE_API_MODE=mock), so the page short-
 * circuits to a friendly error message instead of hitting the real
 * backend. That's sufficient: it proves the button is wired live and
 * the previous `useComingSoon` dialog is gone.
 *
 * The actual download mechanics (fetch → blob → <a download>) are
 * covered by the unit tests on `download.ts`.
 */

function renderInvoiceList() {
  resetInvoiceStore();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/sales/invoices']}>
        <Routes>
          <Route path="/sales/invoices" element={<InvoiceList />} />
          <Route path="/sales/invoices/new" element={<div>NEW</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InvoiceList — Export CSV (TASK-CUT-403)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders an Export CSV button (not the old coming-soon dialog)', async () => {
    renderInvoiceList();
    await waitFor(() => expect(screen.getByText(/RT\/2526\/0001/)).toBeInTheDocument());
    const button = screen.getByRole('button', { name: /export invoices to CSV/i });
    expect(button).toBeInTheDocument();
  });

  it('clicking Export CSV in mock mode surfaces a clear "live backend" hint', async () => {
    renderInvoiceList();
    await waitFor(() => expect(screen.getByText(/RT\/2526\/0001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /export invoices to CSV/i }));
    // No coming-soon dialog opens — instead we see an inline notice.
    expect(screen.queryByText(/click-dummy/i)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/live backend/i);
    });
  });
});
