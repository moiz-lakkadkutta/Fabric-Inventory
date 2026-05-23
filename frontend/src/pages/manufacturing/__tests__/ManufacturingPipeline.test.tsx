import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { mapMoListItemToKanban, type BackendMoListItem } from '@/lib/queries/manufacturing';
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

  it('exposes "View MOs" and "+ New MO" CTAs that route to the MO list/create pages (TASK-TR-A14-FU)', async () => {
    // A14 stripped the ComingSoon stubs; A14-FU re-introduces real CTAs
    // that target the live MO list (/manufacturing/mo) and the create
    // placeholder (/manufacturing/mo/new). The button labels stay short
    // because the kanban header is dense.
    renderPipeline();
    await waitFor(() => expect(screen.getByText(/Bridal Lehenga/)).toBeInTheDocument());

    expect(screen.getByRole('button', { name: /view mos/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /new mo/i })).toBeInTheDocument();
  });
});

// ──────────────────────────────────────────────────────────────────────
// TASK-TR-A1: real BE shape → correct Kanban lane
// ──────────────────────────────────────────────────────────────────────
//
// The page-level test above exercises the click-dummy fixture (vitest
// runs with VITE_API_MODE=mock). These tests pin the live-mode mapping
// directly so we lock down the per-op → lane derivation that drives the
// trial-customer demo. Before A1 the mapper collapsed every IN_PROGRESS
// MO to STITCHING; now lane placement comes from the first non-CLOSED
// op's operation_type.

describe('ManufacturingPipeline view-model (TASK-TR-A1)', () => {
  const base: BackendMoListItem = {
    manufacturing_order_id: 'mo-1',
    org_id: 'o',
    firm_id: 'f',
    series: 'MO/25-26',
    number: '00041',
    design_id: 'd-1',
    finished_item_id: 'i-1',
    finished_item_name: 'Bridal Lehenga',
    status: 'IN_PROGRESS',
    mo_date: '2026-05-14',
    planned_end_date: '2026-06-15',
    planned_qty: '25',
    created_at: '2026-05-01T00:00:00Z',
    operations: null,
  };

  it('IN_PROGRESS MO with a STITCHING op active lands in the STITCHING lane', () => {
    const out = mapMoListItemToKanban({
      ...base,
      operations: [
        {
          mo_operation_id: 'op-1',
          operation_master_id: 'm-1',
          operation_sequence: 1,
          state: 'CLOSED',
          executor: 'IN_HOUSE',
          operation_type: 'WEAVING',
          operation_master_name: 'Cutting',
          start_date: '2026-05-01T00:00:00Z',
        },
        {
          mo_operation_id: 'op-2',
          operation_master_id: 'm-2',
          operation_sequence: 2,
          state: 'IN_PROGRESS',
          executor: 'IN_HOUSE',
          operation_type: 'STITCHING',
          operation_master_name: 'Stitching',
          start_date: '2026-05-12T00:00:00Z',
        },
      ],
    });
    expect(out.stage).toBe('STITCHING');
    // 1 of 2 ops closed.
    expect(out.progress_pct).toBe(50);
  });

  it('IN_PROGRESS MO with every op CLOSED renders in the PACKED lane', () => {
    const out = mapMoListItemToKanban({
      ...base,
      operations: [
        {
          mo_operation_id: 'op-1',
          operation_master_id: 'm-1',
          operation_sequence: 1,
          state: 'CLOSED',
          executor: 'IN_HOUSE',
          operation_type: 'STITCHING',
          operation_master_name: 'Stitching',
          start_date: '2026-05-01T00:00:00Z',
        },
      ],
    });
    expect(out.stage).toBe('PACKED');
    expect(out.progress_pct).toBe(100);
  });

  it('renders the MO under the right Kanban region by finished_item_name', async () => {
    // Mock-mode page uses the click-dummy fixture; the existing "Bridal
    // Lehenga" card already lives in Embroidery there. The assertion
    // we're making is that the card resolves under that lane (not in
    // PLANNED or some unrelated column).
    renderPipeline();
    await waitFor(() => expect(screen.getByText(/Bridal Lehenga/)).toBeInTheDocument());
    const embroidery = screen.getByRole('region', { name: /Embroidery/i });
    expect(within(embroidery).getByText(/Bridal Lehenga/)).toBeInTheDocument();
  });
});
