import { Eye, Lock } from 'lucide-react';
import * as React from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useResetPassword } from '@/lib/queries/identity';

/*
 * Reset password (CUT-303).
 *
 * Path: /reset/:token  (with ?org=<org_name> carried through from the
 * email link). The page reads both, lets the user pick a new password,
 * and POSTs all three to /auth/reset. On success: navigate to /login
 * so they re-authenticate with the new credential.
 *
 * Error surface: a single inline message under the password field for
 * any non-200 (matches the BE's INVALID_RESET_TOKEN posture — we don't
 * distinguish "expired" vs "already used" in the UI either).
 */

export default function ResetPassword() {
  const { token } = useParams<{ token: string }>();
  const [searchParams] = useSearchParams();
  // org_name from the link's ?org= query string. The BE needs it to
  // seed RLS GUC before the token lookup; if the URL was tampered
  // with, /auth/reset returns the same INVALID_RESET_TOKEN response
  // as any other failure, so the missing/wrong-org branch is safe.
  const orgName = searchParams.get('org') ?? '';

  const [newPassword, setNewPassword] = React.useState('');
  const [confirm, setConfirm] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const navigate = useNavigate();
  const reset = useResetPassword();

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (newPassword !== confirm) {
      setError("Passwords don't match.");
      return;
    }

    reset.mutate(
      { token: token ?? '', org_name: orgName, new_password: newPassword },
      {
        onSuccess: () => navigate('/login'),
        onError: () => {
          setError('Reset link is invalid or expired. Request a new one.');
        },
      },
    );
  };

  return (
    <AuthShell>
      <AuthCard
        title="Set a new password"
        subtitle="Pick something you'll remember — at least 8 characters."
      >
        <form className="flex flex-col gap-3.5" onSubmit={onSubmit}>
          <Field label="New password" htmlFor="new-password" error={error ?? undefined}>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              icon={<Lock size={14} />}
              suffix={<Eye size={14} />}
            />
          </Field>
          <Field label="Confirm new password" htmlFor="confirm-password">
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              icon={<Lock size={14} />}
              suffix={<Eye size={14} />}
            />
          </Field>
          <Button type="submit" size="lg" disabled={reset.isPending}>
            Set new password
          </Button>
          <Link
            to="/login"
            className="text-center"
            style={{ fontSize: 13, color: 'var(--text-secondary)' }}
          >
            Back to sign in
          </Link>
        </form>
      </AuthCard>
    </AuthShell>
  );
}
