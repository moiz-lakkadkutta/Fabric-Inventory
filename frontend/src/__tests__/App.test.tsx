import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import App from '@/App';

describe('App shell', () => {
  it('renders the taana wordmark in the top bar', () => {
    render(<App />);
    expect(screen.getByText(/^taana$/)).toBeInTheDocument();
  });

  it('renders the Daybook heading at the index route', () => {
    render(<App />);
    expect(screen.getByRole('heading', { level: 1, name: /Daybook/i })).toBeInTheDocument();
  });

  it('renders the bottom nav for mobile breakpoint', () => {
    render(<App />);
    const nav = screen.getByRole('navigation', { name: /primary mobile/i });
    expect(nav).toBeInTheDocument();
  });

  it('toggles the firm switcher popover on click and lists every firm', () => {
    render(<App />);
    const trigger = screen.getByRole('button', { name: /Rajesh Textiles/i });
    expect(screen.queryByRole('menu', { name: /switch firm/i })).not.toBeInTheDocument();

    fireEvent.click(trigger);
    const menu = screen.getByRole('menu', { name: /switch firm/i });
    expect(menu).toBeInTheDocument();
    expect(screen.getByText(/Add a firm/i)).toBeInTheDocument();
    expect(screen.getAllByRole('menuitemradio').length).toBeGreaterThanOrEqual(2);
  });

  it('opens the user menu and shows the theme stub copy', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /User menu/i }));
    expect(screen.getByText(/Light only · Phase 1/i)).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Sign out/i })).toBeInTheDocument();
  });
});
