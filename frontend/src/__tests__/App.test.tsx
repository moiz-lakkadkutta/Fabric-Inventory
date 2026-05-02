import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import App from '@/App';

describe('App', () => {
  it('renders the taana wordmark in the top bar', () => {
    render(<App />);
    expect(screen.getByText(/^taana$/)).toBeInTheDocument();
  });

  it('renders the Daybook heading at the index route', () => {
    render(<App />);
    expect(screen.getByRole('heading', { level: 1, name: /Daybook/i })).toBeInTheDocument();
  });
});
