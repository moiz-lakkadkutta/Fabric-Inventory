import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import Dashboard from '@/pages/Dashboard';
import { authStore, type MeResponse } from '@/store/auth';

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

  describe('header firm name', () => {
    const me: MeResponse = {
      user_id: '11111111-1111-1111-1111-111111111111',
      org_id: '22222222-2222-2222-2222-222222222222',
      firm_id: null,
      email: 'owner@example.com',
      permissions: [],
      flags: {},
      available_firms: [
        { firm_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', code: 'A', name: 'Alpha Co' },
        { firm_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', code: 'B', name: 'Beta Co' },
      ],
      token_expires_at: '2099-01-01T00:00:00Z',
    };
    afterEach(() => authStore.reset());

    it('does not claim a firm when the session has no active firm', () => {
      authStore.setMe(me);
      renderDashboard();
      expect(screen.queryByText(/for Alpha Co/)).not.toBeInTheDocument();
    });

    it('names the active firm', () => {
      authStore.setMe({ ...me, firm_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' });
      renderDashboard();
      expect(screen.getByText(/for Beta Co/)).toBeInTheDocument();
    });
  });
});
