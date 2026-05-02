import { Check, Eye, Mail } from 'lucide-react';
import * as React from 'react';
import { useNavigate } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';

/*
  Login — visual port of fabric-2/project/shell-screens.jsx :: LoginIdle.
  Click-dummy auth: any non-sentinel credential routes to /mfa (the bundle
  defines MFA as a separate step). The reserved sentinel `error@taana.test`
  drives the error layout without faking a network failure. Real auth
  wires in TASK-008.
*/
const ERROR_SENTINEL = 'error@taana.test';

export default function Login() {
  const [email, setEmail] = React.useState('moiz@rajeshtextiles.in');
  const [password, setPassword] = React.useState('••••••••••••');
  const [remember, setRemember] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const navigate = useNavigate();

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (email.trim().toLowerCase() === ERROR_SENTINEL) {
      setError('Email or password is incorrect.');
      return;
    }
    navigate('/mfa');
  };

  return (
    <AuthShell>
      <AuthCard title="Sign in to your books" subtitle="Use the email associated with your firm.">
        <form className="flex flex-col gap-3.5" onSubmit={onSubmit}>
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
