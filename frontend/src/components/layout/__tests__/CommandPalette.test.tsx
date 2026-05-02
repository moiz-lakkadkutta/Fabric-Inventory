import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { CommandPalette } from '@/components/layout/CommandPalette';
import { TopBar } from '@/components/layout/TopBar';
import { CommandPaletteProvider, useCommandPalette } from '@/hooks/useCommandPalette';

function ControlledPalette() {
  const { open, setOpen } = useCommandPalette();
  return <CommandPalette open={open} onClose={() => setOpen(false)} />;
}

function wrap(initialPath = '/') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <CommandPaletteProvider>
          <Routes>
            <Route
              path="/"
              element={
                <>
                  <TopBar />
                  <ControlledPalette />
                  <div>HOME_REACHED</div>
                </>
              }
            />
            <Route path="/sales/invoices/:id" element={<div>INVOICE_DETAIL_REACHED</div>} />
            <Route path="/masters/parties/:id" element={<div>PARTY_DETAIL_REACHED</div>} />
          </Routes>
        </CommandPaletteProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function openPalette() {
  // Two trigger buttons exist (desktop + mobile-icon variants) — click the
  // first one; both call the same handler.
  fireEvent.click(screen.getAllByRole('button', { name: /open command palette/i })[0]);
}

describe('CommandPalette (T8)', () => {
  it('opens via the TopBar search button and shows a Pages group', () => {
    wrap();
    openPalette();
    expect(screen.getByRole('dialog', { name: /command palette/i })).toBeInTheDocument();
    expect(screen.getByText(/^pages$/i)).toBeInTheDocument();
  });

  it('opens via the global Cmd+K shortcut', () => {
    wrap();
    expect(screen.queryByRole('dialog', { name: /command palette/i })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    expect(screen.getByRole('dialog', { name: /command palette/i })).toBeInTheDocument();
  });

  it('filters results by search query and routes on Enter', () => {
    wrap();
    openPalette();
    fireEvent.change(screen.getByLabelText(/command palette search/i), {
      target: { value: 'anjali' },
    });
    expect(screen.getByText('Anjali Saree Centre')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText(/command palette search/i), { key: 'Enter' });
    expect(screen.getByText('PARTY_DETAIL_REACHED')).toBeInTheDocument();
  });

  it('matches by invoice number and routes on click', () => {
    wrap();
    openPalette();
    fireEvent.change(screen.getByLabelText(/command palette search/i), {
      target: { value: 'RT/2526/0001' },
    });
    fireEvent.click(screen.getByText(/RT\/2526\/0001/));
    expect(screen.getByText('INVOICE_DETAIL_REACHED')).toBeInTheDocument();
  });

  it('shows an empty state when no result matches', () => {
    wrap();
    openPalette();
    fireEvent.change(screen.getByLabelText(/command palette search/i), {
      target: { value: 'zzzzzzzz-no-such-thing' },
    });
    expect(screen.getByText(/nothing matches/i)).toBeInTheDocument();
  });
});
