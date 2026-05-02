import { Mail } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';

export default function Forgot() {
  const [email, setEmail] = useState('moiz@rajeshtextiles.in');
  const [sent, setSent] = useState(false);

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
              We sent a reset link to{' '}
              <strong style={{ color: 'var(--text-primary)' }}>{maskEmail(email)}</strong>. The link
              expires in 30 minutes.
            </div>
            <div className="mt-2 flex flex-col items-center gap-1.5">
              <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
                Didn't get it? Resend in <span className="num">0:45</span>
              </span>
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
        subtitle="Enter your email and we'll send a reset link."
      >
        <form
          className="flex flex-col gap-3.5"
          onSubmit={(e) => {
            e.preventDefault();
            setSent(true);
          }}
        >
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
          <Button type="submit" size="lg">
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
