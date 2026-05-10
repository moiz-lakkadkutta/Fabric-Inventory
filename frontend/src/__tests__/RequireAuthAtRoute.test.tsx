import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { RequireAuth } from '@/components/auth/RequireAuth';
import { AppLayout } from '@/components/layout/AppLayout';
import AdminHub from '@/pages/admin/AdminHub';
import Login from '@/pages/auth/Login';
import { authStore } from '@/store/auth';

afterEach(() => {
  authStore.reset();
});

/*
  Functional cover for the e2e acceptance:

  > In a Playwright e2e: open /admin (or any protected route) in an
  > incognito-equivalent state (cleared authStore). Assert
  > <Navigate to="/login"> fires — URL becomes /login.

  Wired as a Vitest render with a real React-Router so the redirect
  resolves through the router. No Playwright infrastructure exists in
  the repo yet; this assertion is equivalent at the route level.
*/
describe('Protected route gate (App-level)', () => {
  it('redirects to /login when authStore is cleared and the user opens /admin', () => {
    authStore.clear(); // ensure status === 'unauthenticated'
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/admin']}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/"
              element={
                <RequireAuth>
                  <AppLayout />
                </RequireAuth>
              }
            >
              <Route path="admin" element={<AdminHub />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // The Login page renders its "Sign in to your books" heading — confirms
    // the Navigate fired and the route matched /login.
    expect(screen.queryByRole('heading', { level: 1, name: /admin/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Sign in to your books/i)).toBeInTheDocument();
  });
});
