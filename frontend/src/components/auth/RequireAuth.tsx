import * as React from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { useAuthStatus, useMe } from '@/store/auth';

interface RequireAuthProps {
  children?: React.ReactNode;
  /** Where to send users when their session is missing. Defaults to /login. */
  redirectTo?: string;
}

/**
 * Route guard that gates protected pages on `authStore.status`.
 *
 * - `unknown`     → render a quiet placeholder. Prevents flash-of-mock-
 *                   chrome while `useAuthBootstrap` is still calling
 *                   `/auth/refresh` on the page-load round-trip.
 * - `unauthenticated` → `<Navigate to="/login" replace />` so the back
 *                   button doesn't bounce the user back here pre-auth.
 *                   The original `from` location is preserved in router
 *                   state so post-login redirect can return them.
 * - `authenticated`   → render `children` (or `<Outlet />` via React
 *                   Router's data-router conventions).
 *
 * Note: this component does NOT trigger an /auth/refresh call. That's
 * `useAuthBootstrap`'s job (runs once on App mount). RequireAuth only
 * reads the status the bootstrap hook is racing to populate.
 */
export function RequireAuth({ children, redirectTo = '/login' }: RequireAuthProps) {
  const status = useAuthStatus();
  const me = useMe();
  const location = useLocation();

  if (status === 'unknown') {
    // Quiet, unstyled placeholder. The auth bootstrap typically resolves
    // in <100ms; a visible spinner would just flash. Keep DOM stable so
    // route content can mount in-place once auth lands.
    return (
      <div
        aria-busy="true"
        aria-label="Checking session"
        style={{ minHeight: '100vh', background: 'var(--bg-canvas)' }}
      />
    );
  }

  if (status === 'unauthenticated') {
    return <Navigate to={redirectTo} replace state={{ from: location }} />;
  }

  // Q01-03: an admin-class user without TOTP gets 403 MFA_ENROLLMENT_REQUIRED
  // from every business route — send them to enrolment instead.
  if (me?.mfa_enrollment_required) {
    return <Navigate to="/mfa/enroll" replace />;
  }

  return <>{children}</>;
}
