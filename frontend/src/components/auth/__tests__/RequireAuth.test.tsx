import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { RequireAuth } from '@/components/auth/RequireAuth';
import { authStore, type MeResponse } from '@/store/auth';

const FAKE_ME: MeResponse = {
  user_id: '11111111-1111-1111-1111-111111111111',
  org_id: '22222222-2222-2222-2222-222222222222',
  firm_id: '33333333-3333-3333-3333-333333333333',
  email: 'audit@audit.example',
  permissions: [],
  flags: {},
  available_firms: [],
  token_expires_at: '2099-01-01T00:00:00Z',
};

afterEach(() => {
  authStore.reset();
});

function renderProtectedAt(
  initialPath: string,
  status: 'authenticated' | 'unauthenticated' | 'unknown',
) {
  if (status === 'authenticated') {
    authStore.setMe(FAKE_ME);
  } else if (status === 'unauthenticated') {
    authStore.clear();
  } else {
    // 'unknown' — leave default reset state.
  }
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<div>LOGIN_PAGE</div>} />
        <Route
          path="/protected"
          element={
            <RequireAuth>
              <div>PROTECTED_CONTENT</div>
            </RequireAuth>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAuth', () => {
  it('redirects to /login when unauthenticated', () => {
    renderProtectedAt('/protected', 'unauthenticated');
    expect(screen.queryByText('PROTECTED_CONTENT')).not.toBeInTheDocument();
    expect(screen.getByText('LOGIN_PAGE')).toBeInTheDocument();
  });

  it('renders children when authenticated', () => {
    renderProtectedAt('/protected', 'authenticated');
    expect(screen.getByText('PROTECTED_CONTENT')).toBeInTheDocument();
    expect(screen.queryByText('LOGIN_PAGE')).not.toBeInTheDocument();
  });

  it('renders neither protected content nor /login while status is unknown (no flash of mock identity)', () => {
    renderProtectedAt('/protected', 'unknown');
    expect(screen.queryByText('PROTECTED_CONTENT')).not.toBeInTheDocument();
    expect(screen.queryByText('LOGIN_PAGE')).not.toBeInTheDocument();
  });
});
