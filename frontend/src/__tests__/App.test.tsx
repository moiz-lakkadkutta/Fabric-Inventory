import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import App from '@/App';

describe('App', () => {
  it('renders the Fabric ERP brand in the sidebar', () => {
    render(<App />);
    expect(screen.getByRole('heading', { level: 1, name: /Fabric ERP/i })).toBeInTheDocument();
  });

  it('renders the Dashboard heading at the index route', () => {
    render(<App />);
    expect(screen.getByRole('heading', { level: 2, name: /Dashboard/i })).toBeInTheDocument();
  });
});
