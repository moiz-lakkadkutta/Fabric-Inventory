import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import Login from '@/pages/auth/Login';

declare global {
  interface Window {
    __FABRIC_TEST_NO_PREFILL__?: boolean;
  }
}

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
  afterEach(() => {
    delete window.__FABRIC_TEST_NO_PREFILL__;
  });

  it('renders empty fields when the production-equivalent kill-switch is set', () => {
    window.__FABRIC_TEST_NO_PREFILL__ = true;
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter>
          <Login />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText(/organization/i)).toHaveValue('');
    expect(screen.getByLabelText(/email/i)).toHaveValue('');
    expect(screen.getByLabelText(/password/i)).toHaveValue('');
  });

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
