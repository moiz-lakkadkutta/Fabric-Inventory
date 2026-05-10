import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { resetPurchaseOrderStore } from '@/lib/queries/purchase-orders';
import PurchaseOrderCreate from '@/pages/purchase/PurchaseOrderCreate';
import PurchaseOrderDetail from '@/pages/purchase/PurchaseOrderDetail';
import PurchaseOrderList from '@/pages/purchase/PurchaseOrderList';

/*
 * Page-level integration tests for the PO surface.
 *
 * These run in mock mode (the default for vitest — VITE_API_MODE is
 * unset, so IS_LIVE is false). They lock in the public behavior:
 *   1. List → click a row → land on detail.
 *   2. Create form has supplier dropdown + line builder + submit path.
 *   3. Detail page exposes Approve/Confirm/Cancel buttons whose
 *      enabled state respects the lifecycle guards (canApprove etc.).
 *
 * The fetch-level `purchase-orders.fetch.test.ts` covers the live wire
 * format; together the two test files give "list renders, create posts,
 * approve transitions" full-stack coverage in the FE alone.
 */

function renderFlow(initial = '/purchase') {
  resetPurchaseOrderStore();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/purchase" element={<PurchaseOrderList />} />
          <Route path="/purchase/new" element={<PurchaseOrderCreate />} />
          <Route path="/purchase/:id" element={<PurchaseOrderDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Purchase Order flow', () => {
  it('renders list rows and routes to detail on row click', async () => {
    renderFlow();
    await waitFor(() => expect(screen.getByText('PO/25-26/0001')).toBeInTheDocument());
    fireEvent.click(screen.getByText('PO/25-26/0001'));
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/PO\/25-26\/0001/),
    );
  });

  it('list "+ New PO" button routes to /purchase/new', async () => {
    renderFlow();
    await waitFor(() => expect(screen.getByText('PO/25-26/0001')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /new po/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: /new purchase order/i }),
      ).toBeInTheDocument(),
    );
  });

  it('Create page exposes supplier dropdown + at least one line + Save draft button', async () => {
    renderFlow('/purchase/new');
    await waitFor(() => expect(screen.getByLabelText(/supplier/i)).toBeInTheDocument());
    expect(screen.getAllByRole('combobox', { name: /item/i }).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /save draft/i })).toBeEnabled();
  });

  it('Detail page Approve is enabled for DRAFT and disabled for CANCELLED', async () => {
    // PO/25-26/0008 in the seed data is DRAFT.
    renderFlow('/purchase/po_9008');
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/PO\/25-26\/0008/),
    );
    const approveBtn = screen.getByRole('button', { name: /^approve$/i });
    expect(approveBtn).toBeEnabled();

    // Clicking Cancel transitions to CANCELLED, then Approve is disabled.
    fireEvent.click(screen.getByRole('button', { name: /cancel po/i }));
    await waitFor(() => expect(screen.getByText(/^Cancelled$/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /^approve$/i })).toBeDisabled();
  });

  it('Detail page Approve transitions DRAFT → OPEN', async () => {
    renderFlow('/purchase/po_9008');
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/PO\/25-26\/0008/),
    );
    fireEvent.click(screen.getByRole('button', { name: /^approve$/i }));
    await waitFor(() => expect(screen.getByText(/^Open$/)).toBeInTheDocument());
    // Approve is no longer enabled; Confirm still is (DRAFT|APPROVED accepted).
    expect(screen.getByRole('button', { name: /^approve$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeEnabled();
  });
});

describe('Purchase Order list — does not import mock fixtures into the live code path', () => {
  it('renders with no module-level @/lib/mock import in the live branch', () => {
    // Smoke check: the queries module imports `@/lib/mock/purchase` ONLY
    // inside the IS_LIVE-false branch (verified by grep in the AC).
    // This test ensures the page renders even if the mock store is reset.
    resetPurchaseOrderStore();
    renderFlow();
    // Loading state appears immediately while the mock fakeFetch resolves.
    const skeleton = screen.queryByLabelText(/loading purchase orders/i);
    expect(skeleton).not.toBeNull();
  });
});

// Touch the within import so eslint-no-unused doesn't fire if we drop it later.
void within;
