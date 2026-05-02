import { Building2, Check, Eye, Mail } from 'lucide-react';
import * as React from 'react';
import { useNavigate } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useLogin } from '@/lib/queries/identity';
import { authStore } from '@/store/auth';

/*
  Login — visual port of fabric-2/project/shell-screens.jsx :: LoginIdle.

  Both Q6 branches via useLogin():
    - mock mode keeps the click-dummy sentinel: `error@taana.test` shows
      the inline error; anything else routes to /mfa.
    - live mode hits POST /v1/auth/login through the api() wrapper. The
      mutation's onSuccess routes based on `requires_mfa`.

  Org name is a real form field (CRIT-3 fix) — every tenant has a
  different org so we can't hardcode. Defaults to 'Rajesh Textiles'
  for click-dummy continuity; required input in live mode.

  When `requires_mfa=true`, we stash {email, password, org_name} on
  authStore.pendingMfa so the /mfa page can re-present them to the
  backend's mfa-verify endpoint without persisting the password.
*/

export default function Login() {
  const [email, setEmail] = React.useState('moiz@rajeshtextiles.in');
  const [password, setPassword] = React.useState('••••••••••••');
  const [orgName, setOrgName] = React.useState('Rajesh Textiles');
  const [remember, setRemember] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const navigate = useNavigate();
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const login = useLogin();

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmedEmail = email.trim();
    const trimmedOrg = orgName.trim();
    login.mutate(
      {
        email: trimmedEmail,
        password,
        org_name: trimmedOrg,
        idempotencyKey,
      },
      {
        onSuccess: (result) => {
          resetKey();
          if (result.requires_mfa) {
            authStore.setPendingMfa({
              email: trimmedEmail,
              password,
              org_name: trimmedOrg,
            });
            navigate('/mfa');
          } else {
            authStore.setPendingMfa(null);
            navigate('/');
          }
        },
        onError: () => {
          resetKey();
          setError('Email or password is incorrect.');
        },
      },
    );
  };

  return (
    <AuthShell>
      <AuthCard title="Sign in to your books" subtitle="Use the email associated with your firm.">
        <form className="flex flex-col gap-3.5" onSubmit={onSubmit}>
          <Field label="Organization" htmlFor="org-name">
            <Input
              id="org-name"
              type="text"
              autoComplete="organization"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              icon={<Building2 size={14} />}
            />
          </Field>

          <Field label="Email" htmlFor="email">
            <Input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              icon={<Mail size={14} />}
            />
          </Field>

          <Field label="Password" htmlFor="password" error={error ?? undefined}>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              suffix={<Eye size={14} />}
            />
          </Field>

          <RememberCheckbox checked={remember} onChange={setRemember} />

          <Button type="submit" size="lg">
            Sign in
          </Button>

          <div className="mt-1 flex flex-col items-center gap-1.5">
            <a
              href="/forgot"
              style={{
                fontSize: 13,
                color: 'var(--accent)',
                fontWeight: 500,
              }}
            >
              Forgot password?
            </a>
            <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
              New here?{' '}
              <a href="/onboarding" style={{ color: 'var(--accent)', fontWeight: 500 }}>
                Set up your business
              </a>
            </span>
          </div>
        </form>
      </AuthCard>
    </AuthShell>
  );
}

function RememberCheckbox({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      className="flex select-none items-center gap-2"
      style={{ fontSize: 13, color: 'var(--text-secondary)' }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
      />
      <span
        aria-hidden
        className="inline-flex items-center justify-center"
        style={{
          width: 16,
          height: 16,
          borderRadius: 4,
          border: '1.5px solid var(--accent)',
          background: checked ? 'var(--accent)' : 'transparent',
          transition: 'background-color .12s ease',
        }}
      >
        {checked && <Check size={12} color="#FAFAF7" strokeWidth={3} />}
      </span>
      Remember this device for 30 days
    </label>
  );
}
