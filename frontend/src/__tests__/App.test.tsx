import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import App from '@/App';

function renderApp() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>,
  );
}

describe('App shell', () => {
  it('renders the taana wordmark in the top bar', () => {
    renderApp();
    expect(screen.getByText(/^taana$/)).toBeInTheDocument();
  });

  it('renders the Daybook heading at the index route', async () => {
    renderApp();
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /Daybook/i })).toBeInTheDocument(),
    );
  });

  it('renders the bottom nav for mobile breakpoint', () => {
    renderApp();
    const nav = screen.getByRole('navigation', { name: /primary mobile/i });
    expect(nav).toBeInTheDocument();
  });

  it('toggles the firm switcher popover on click and lists every firm', () => {
    renderApp();
    const trigger = screen.getByRole('button', { name: /Rajesh Textiles/i });
    expect(screen.queryByRole('menu', { name: /switch firm/i })).not.toBeInTheDocument();

    fireEvent.click(trigger);
    const menu = screen.getByRole('menu', { name: /switch firm/i });
    expect(menu).toBeInTheDocument();
    expect(screen.getByText(/Add a firm/i)).toBeInTheDocument();
    expect(screen.getAllByRole('menuitemradio').length).toBeGreaterThanOrEqual(2);
  });

  it('opens the user menu and shows the theme stub copy', () => {
    renderApp();
    fireEvent.click(screen.getByRole('button', { name: /User menu/i }));
    expect(screen.getByText(/Light only · Phase 1/i)).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Sign out/i })).toBeInTheDocument();
  });
});
