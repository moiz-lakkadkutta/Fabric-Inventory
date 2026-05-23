import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ReportsHub from '@/pages/reports/ReportsHub';

function renderReports() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ReportsHub />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ReportsHub', () => {
  it('opens on the P&L tab and shows Total income / Net profit rows', async () => {
    renderReports();
    await waitFor(() => expect(screen.getAllByText(/total income/i).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/net profit/i).length).toBeGreaterThan(0);
  });

  it('switches to Trial balance and shows the balanced banner', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /trial balance/i }));
    await waitFor(() => expect(screen.getByText(/balanced/i)).toBeInTheDocument());
    // Sundry debtors is one of the asset rows.
    expect(screen.getByText(/sundry debtors/i)).toBeInTheDocument();
  });

  it('switches to GSTR-1 and shows the four-bucket panel', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /GSTR-1/i }));
    // The four required buckets render as section headings (B2B / B2CL /
    // B2CS / HSN). In mock mode, the panel renders an empty-state for
    // every bucket except B2B (the click-dummy fixture only has B2B rows).
    await waitFor(() => expect(screen.getByRole('heading', { name: /B2B/i })).toBeInTheDocument());
    expect(screen.getByRole('heading', { name: /B2CL/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /B2CS/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /HSN/i })).toBeInTheDocument();
    // The period picker is wired so the user can change month.
    expect(screen.getByLabelText(/GSTR-1 period/i)).toBeInTheDocument();
  });

  it('switches to Stock and shows the total stock value', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /^stock$/i }));
    await waitFor(() => expect(screen.getByText(/total stock value/i)).toBeInTheDocument());
  });

  it('switches to Daybook and shows recent vouchers', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: /daybook/i }));
    await waitFor(() => expect(screen.getByText(/RC\/25-26\/0001/)).toBeInTheDocument());
  });
});

describe('ReportsHub — Print (TASK-TR-B1)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('Print button calls window.print() once (no ComingSoon dialog)', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {});
    renderReports();
    // Wait for the page to settle (P&L panel renders).
    await waitFor(() => expect(screen.getAllByText(/total income/i).length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole('button', { name: /print report/i }));
    expect(printSpy).toHaveBeenCalledTimes(1);
    // The old "coming soon" copy must not be on screen.
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/click-dummy/i)).not.toBeInTheDocument();
  });

  it('renders a print-only header block above the tabs', async () => {
    renderReports();
    await waitFor(() => expect(screen.getAllByText(/total income/i).length).toBeGreaterThan(0));
    // The print header is screen-hidden by CSS but present in the DOM
    // so the browser surfaces it when @media print kicks in.
    const header = document.querySelector('.print-header');
    expect(header).not.toBeNull();
    expect(header?.querySelector('.print-header-title')?.textContent).toMatch(/P&L/i);
  });
});
