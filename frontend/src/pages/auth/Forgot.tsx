import { Building2, Mail } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useForgotPassword } from '@/lib/queries/identity';

/*
 * Forgot password — wired live to POST /auth/forgot (CUT-303).
 *
 * Two-step state machine: form → confirmation. The confirmation copy is
 * identical regardless of whether the email was registered (the BE's
 * no-enumeration contract — see `password_reset_service.request_reset`).
 *
 * `org_name` is a required field because the BE multi-tenancy model is
 * per-org email scoping (the same email can exist under different orgs
 * — we need to disambiguate). Mirrors the Login screen's field shape.
 *
 * Mock-mode preserves the click-dummy behaviour (form → confirmation
 * with no network) so existing UI tests in Forgot.test.tsx keep working
 * without further patching.
 */

export default function Forgot() {
  const [email, setEmail] = useState('moiz@rajeshtextiles.in');
  const [orgName, setOrgName] = useState('Rajesh Textiles');
  const [sent, setSent] = useState(false);
  const forgot = useForgotPassword();

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Fire-and-forget: even on error we transition to the success state
    // because the contract is "we won't tell you if the email exists" —
    // a visible error here would itself be an enumeration channel. The
    // mutation completing (or failing) is logged but not surfaced.
    forgot.mutate(
      { email: email.trim(), org_name: orgName.trim() },
      { onSettled: () => setSent(true) },
    );
  };

  if (sent) {
    return (
      <AuthShell>
        <AuthCard pad={28}>
          <div className="flex flex-col items-center gap-3.5 text-center">
            <div
              className="inline-flex items-center justify-center"
              style={{
                width: 48,
                height: 48,
                borderRadius: 999,
                background: 'var(--accent-subtle)',
              }}
            >
              <Mail size={20} color="var(--accent)" />
            </div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>Check your email</div>
            <div
              style={{
                fontSize: 13.5,
                color: 'var(--text-secondary)',
                lineHeight: 1.55,
                maxWidth: 320,
              }}
            >
              If an account exists for{' '}
              <strong style={{ color: 'var(--text-primary)' }}>{maskEmail(email)}</strong>, a reset
              link has been sent. The link expires in 30 minutes.
            </div>
            <div className="mt-2 flex flex-col items-center gap-1.5">
              <button
                type="button"
                onClick={() => setSent(false)}
                style={{
                  fontSize: 13,
                  color: 'var(--accent)',
                  fontWeight: 500,
                  background: 'none',
                  border: 0,
                  cursor: 'pointer',
                }}
              >
                Use a different email
              </button>
              <Link to="/login" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
                Back to sign in
              </Link>
            </div>
          </div>
        </AuthCard>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <AuthCard
        title="Reset your password"
        subtitle="Enter your organisation and email; we'll send a reset link."
      >
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
          <Button type="submit" size="lg" disabled={forgot.isPending}>
            Send reset link
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

function maskEmail(email: string): string {
  const [local, domain] = email.split('@');
  if (!domain) return email;
  return `${local.slice(0, 1)}${'•'.repeat(Math.max(2, local.length - 1))}@${domain}`;
}
