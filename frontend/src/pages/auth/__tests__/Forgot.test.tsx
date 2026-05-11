import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import Forgot from '@/pages/auth/Forgot';

/*
 * Mock-mode tests for the Forgot page (the page's local state-machine).
 * Live-mode wire-up against /auth/forgot lives in Forgot.live.test.tsx.
 * The submit handler dispatches the mutation regardless of mode; in
 * mock mode `fakeFetch` resolves synchronously on the same microtask so
 * `onSettled` flips the page into the success state by the next render.
 */

function renderForgot() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/forgot']}>
        <Forgot />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Forgot', () => {
  it('advances to the confirmation step after submitting an email', async () => {
    renderForgot();
    expect(screen.getByRole('heading', { name: /reset your password/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));
    await waitFor(() => {
      expect(screen.getByText(/check your email/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /send reset link/i })).not.toBeInTheDocument();
  });

  it('returns to step 1 from the "Use a different email" affordance', async () => {
    renderForgot();
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /use a different email/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /use a different email/i }));
    expect(screen.getByRole('heading', { name: /reset your password/i })).toBeInTheDocument();
  });
});
