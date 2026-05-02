import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import Dashboard from '@/pages/Dashboard';

function renderDashboard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Dashboard', () => {
  it('renders skeleton placeholders before mock data resolves', () => {
    renderDashboard();
    expect(screen.getAllByLabelText(/loading/i).length).toBeGreaterThan(0);
  });

  it('renders the KPI labels once mock data has resolved', async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText(/outstanding receivables/i)).toBeInTheDocument();
    });
    // The skeletons should disappear once data lands.
    expect(screen.queryAllByLabelText(/loading/i)).toHaveLength(0);
  });
});
