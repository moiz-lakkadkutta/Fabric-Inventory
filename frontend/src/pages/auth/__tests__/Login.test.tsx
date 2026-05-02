import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import Login from '@/pages/auth/Login';

function renderLoginIntoFlow() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<div>DASHBOARD_REACHED</div>} />
          <Route path="/mfa" element={<div>MFA_REACHED</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Login', () => {
  it('routes to the dashboard when the user submits any non-sentinel credentials', async () => {
    renderLoginIntoFlow();
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: 'anyone@taana.test' },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'anything' },
    });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() => {
      expect(screen.getByText('MFA_REACHED')).toBeInTheDocument();
    });
  });

  it('shows the error state when the email is the documented error sentinel', async () => {
    renderLoginIntoFlow();
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: 'error@taana.test' },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'wrong' },
    });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText(/email or password is incorrect/i)).toBeInTheDocument();
    expect(screen.queryByText('MFA_REACHED')).not.toBeInTheDocument();
  });
});
