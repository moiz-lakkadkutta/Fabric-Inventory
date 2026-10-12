import { AlertCircle } from 'lucide-react';
import * as React from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useMfaVerify } from '@/lib/queries/identity';
import { authStore, usePendingMfa } from '@/store/auth';

/*
  Mfa — visual port of fabric-2/project/shell-screens.jsx :: MfaIdle/Error.

  Both Q6 branches via useMfaVerify():
    - mock mode keeps the sentinel: 000000 → error layout, anything else → /.
    - live mode re-presents the credentials stashed by Login (authStore
      .pendingMfa) plus the TOTP code to POST /v1/auth/mfa-verify.

  Live-mode users who land here directly without a pending login fall
  back to the mock-style sentinel — typically that path means a stale
  page; the redirect to /login on success of the mfa-verify still
  works once the user re-enters Login.
*/
const ERROR_SENTINEL = '000000';

export default function Mfa() {
  const [code, setCode] = React.useState('');
  const [error, setError] = React.useState(false);
  // Q01-03 follow-up: sign in with a one-time backup code instead of TOTP.
  const [useBackup, setUseBackup] = React.useState(false);
  const [backupCode, setBackupCode] = React.useState('');
  const navigate = useNavigate();
  const pending = usePendingMfa();
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mfa = useMfaVerify();

  const onChange = (next: string) => {
    const cleaned = next.replace(/\D/g, '').slice(0, 6);
    setCode(cleaned);
    if (error) setError(false);
  };

  const onVerify = () => {
    // Mock-mode shortcut OR live-mode fallback when the pending stash
    // is empty (e.g. user landed on /mfa directly).
    if (!pending) {
      if (code === ERROR_SENTINEL) {
        setError(true);
        return;
      }
      navigate('/');
      return;
    }

    mfa.mutate(
      {
        email: pending.email,
        password: pending.password,
        org_name: pending.org_name,
        ...(useBackup ? { backup_code: backupCode.trim() } : { totp_code: code }),
        idempotencyKey,
      },
      {
        onSuccess: () => {
          authStore.setPendingMfa(null);
          resetKey();
          navigate('/');
        },
        onError: () => {
          resetKey();
          setError(true);
        },
      },
    );
  };

  const ready = useBackup ? backupCode.replace(/[^a-z0-9]/gi, '').length === 10 : code.length === 6;

  return (
    <AuthShell>
      <AuthCard
        title="Two-factor authentication"
        subtitle="Enter the 6-digit code from your authenticator app."
      >
        <div className="flex flex-col gap-5">
          {useBackup ? (
            <input
              aria-label="Backup code"
              autoComplete="off"
              value={backupCode}
              onChange={(e) => {
                setBackupCode(e.target.value);
                if (error) setError(false);
              }}
              placeholder="xxxxx-xxxxx"
              className="num"
              style={{
                height: 44,
                padding: '0 12px',
                borderRadius: 6,
                border: `1.5px solid ${error ? 'var(--danger)' : 'var(--border-default)'}`,
                background: 'var(--bg-surface)',
                fontSize: 16,
                letterSpacing: '0.08em',
              }}
              autoFocus
            />
          ) : (
            <CodeInput value={code} onChange={onChange} error={error} />
          )}
          {error && (
            <div
              role="alert"
              className="flex items-start gap-2"
              style={{
                padding: '10px 12px',
                background: 'var(--danger-subtle)',
                color: 'var(--danger-text)',
                borderRadius: 6,
                fontSize: 12.5,
              }}
            >
              <AlertCircle size={14} color="var(--danger)" />
              <span>
                {useBackup
                  ? "That backup code didn't match or was already used."
                  : "Code didn't match. If you just set up two-factor, wait for the next code in your app — a code can't be used twice."}
              </span>
            </div>
          )}
          <div className="flex justify-between" style={{ fontSize: 12.5 }}>
            <button
              type="button"
              onClick={() => {
                setUseBackup((v) => !v);
                setError(false);
              }}
              style={{ color: 'var(--accent)', fontWeight: 500 }}
            >
              {useBackup ? 'Use your authenticator app' : 'Use a backup code'}
            </button>
            <Link to="/login" style={{ color: 'var(--text-tertiary)' }}>
              Back to sign in
            </Link>
          </div>
          <Button size="lg" disabled={!ready} onClick={onVerify}>
            {error ? 'Try again' : 'Verify'}
          </Button>
        </div>
      </AuthCard>
    </AuthShell>
  );
}

interface CodeInputProps {
  value: string;
  onChange: (v: string) => void;
  error?: boolean;
}

function CodeInput({ value, onChange, error }: CodeInputProps) {
  return (
    <div className="relative">
      <input
        aria-label="Verification code"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="\d{6}"
        maxLength={6}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 z-10 h-full w-full opacity-0"
        style={{ letterSpacing: '2.6em' }}
        autoFocus
      />
      <div className="flex justify-center gap-2" aria-hidden>
        {Array.from({ length: 6 }).map((_, i) => {
          const ch = value[i] ?? '';
          const focused = i === Math.min(value.length, 5) && !error;
          return (
            <div
              key={i}
              className="inline-flex items-center justify-center"
              style={{
                width: 44,
                height: 56,
                borderRadius: 6,
                border: `1.5px solid ${
                  error ? 'var(--danger)' : focused ? 'var(--accent)' : 'var(--border-default)'
                }`,
                background: error ? 'var(--danger-subtle)' : 'var(--bg-surface)',
                fontSize: 24,
                fontWeight: 600,
                fontVariantNumeric: 'tabular-nums',
                color: error ? 'var(--danger-text)' : 'var(--text-primary)',
                boxShadow: focused ? '0 0 0 3px rgba(15,122,78,.16)' : 'none',
              }}
            >
              {ch}
            </div>
          );
        })}
      </div>
    </div>
  );
}
