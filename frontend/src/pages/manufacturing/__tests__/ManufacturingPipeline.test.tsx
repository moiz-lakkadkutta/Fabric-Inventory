import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import ManufacturingPipeline from '@/pages/manufacturing/ManufacturingPipeline';

function renderPipeline() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ManufacturingPipeline />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ManufacturingPipeline', () => {
  it('renders all six kanban columns with their counts after data resolves', async () => {
    renderPipeline();
    await waitFor(() =>
      expect(screen.getByRole('region', { name: /Embroidery/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole('region', { name: /Planned/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /Cutting/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /Stitching/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /^QC$/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /Packed/i })).toBeInTheDocument();
    // The Bridal Lehenga MO is in the Embroidery column.
    expect(screen.getByText(/Bridal Lehenga/)).toBeInTheDocument();
  });
});
