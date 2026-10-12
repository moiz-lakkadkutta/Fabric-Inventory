import { AlertCircle, CheckCircle2 } from 'lucide-react';
import * as React from 'react';
import { Link } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { IS_LIVE } from '@/lib/api/mode';
import { useMfaConfirm, useMfaSetup } from '@/lib/queries/identity';
import { useAccessToken } from '@/store/auth';

/*
  MfaEnroll — Q01-03: MFA is mandatory for admin-class users.

  Reached from Login (`requires_mfa_enrollment`) or from RequireAuth
  (`/auth/me` says `mfa_enrollment_required`). Steps:
    1. POST /auth/mfa/setup → show the secret + otpauth link to add to an
       authenticator app (manual entry; no QR library in the bundle yet).
    2. POST /auth/mfa/confirm with the first 6-digit code.
    3. Sign out and ask the user to sign in again — that login goes through
       /mfa (TOTP verify) and returns a full session.
*/
export default function MfaEnroll() {
  const accessToken = useAccessToken();
  const setup = useMfaSetup();
  const confirm = useMfaConfirm();
  const { key: setupKey } = useIdempotencyKey();
  const { key: confirmKey, reset: resetConfirmKey } = useIdempotencyKey();
  const [code, setCode] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);
  const started = React.useRef(false);

  // Confirm signs out (clears the token) just before `done` flips, so a
  // pending/finished confirm must not fall back to the "expired" card.
  const canStart = !IS_LIVE || Boolean(accessToken) || confirm.isPending || done;

  React.useEffect(() => {
    if (!canStart || started.current || done) return;
    started.current = true;
    setup.mutate({ idempotencyKey: setupKey });
  }, [canStart, done, setup, setupKey]);

  if (!canStart) {
    return (
      <AuthShell>
        <AuthCard
          title="Set up two-factor authentication"
          subtitle="Your session has expired. Sign in again to continue."
        >
          <Link to="/login" style={{ color: 'var(--accent)', fontWeight: 500 }}>
            Back to sign in
          </Link>
        </AuthCard>
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell>
        <AuthCard
          title="Two-factor authentication is on"
          subtitle="Sign in again. You'll be asked for a code from your authenticator app."
        >
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2" style={{ fontSize: 13 }}>
              <CheckCircle2 size={16} color="var(--accent)" />
              <span>Your account is now protected with a second factor.</span>
            </div>
            <Link to="/login" style={{ color: 'var(--accent)', fontWeight: 500 }}>
              Sign in again
            </Link>
          </div>
        </AuthCard>
      </AuthShell>
    );
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    confirm.mutate(
      { code, idempotencyKey: confirmKey },
      {
        onSuccess: () => setDone(true),
        onError: () => {
          resetConfirmKey();
          setError("That code didn't match. Use the current code from your app.");
        },
      },
    );
  };

  return (
    <AuthShell>
      <AuthCard
        title="Set up two-factor authentication"
        subtitle="Your role can manage users and permissions, so a second factor is required."
      >
        <form className="flex flex-col gap-4" onSubmit={onSubmit}>
          {setup.isError && (
            <div role="alert" className="flex items-start gap-2" style={{ fontSize: 12.5 }}>
              <AlertCircle size={14} color="var(--danger)" />
              <span>Couldn't start setup. Sign in again and retry.</span>
            </div>
          )}
          {setup.data && (
            <div className="flex flex-col gap-2" style={{ fontSize: 13 }}>
              <span>
                Add this key to your authenticator app (Google Authenticator, 1Password, …):
              </span>
              <code
                data-testid="mfa-secret"
                className="num"
                style={{
                  padding: '8px 10px',
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 6,
                  letterSpacing: '0.12em',
                  wordBreak: 'break-all',
                }}
              >
                {setup.data.secret}
              </code>
              <a href={setup.data.provisioning_uri} style={{ color: 'var(--accent)' }}>
                Open in authenticator app
              </a>
            </div>
          )}
          <Field label="6-digit code" htmlFor="mfa-code" error={error ?? undefined}>
            <Input
              id="mfa-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            />
          </Field>
          <Button
            type="submit"
            size="lg"
            disabled={!setup.data || code.length !== 6 || confirm.isPending}
          >
            Turn on two-factor authentication
          </Button>
        </form>
      </AuthCard>
    </AuthShell>
  );
}
