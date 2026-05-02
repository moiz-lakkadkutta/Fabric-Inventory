import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import JobWorkOverview from '@/pages/jobwork/JobWorkOverview';

function renderJobWork() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobWorkOverview />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('JobWorkOverview', () => {
  it('shows a loading skeleton then karigar cards and the active jobs table', async () => {
    renderJobWork();
    expect(screen.getByLabelText(/loading karigars/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('Imran Khan').length).toBeGreaterThanOrEqual(1));
    expect(screen.getAllByText('Naseem Begum').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('JO/25-26/00102')).toBeInTheDocument();
    // Breach state pill renders for the breached job.
    expect(screen.getAllByText(/breached/i).length).toBeGreaterThanOrEqual(1);
  });
});
