/*
 * AcceptInvite (TASK-CUT-304) — the public `/invite/:token` page.
 *
 * The recipient lands here from the link in the dev console log (or
 * future email). They enter their name + password; we POST to
 * /admin/invites/accept; on success we redirect to /login with the org
 * name and email pre-filled (decision: we do not bundle login so the
 * fresh bcrypt password gets exercised in the happy path).
 *
 * This page is OUTSIDE RequireAuth — the invitee has no session yet.
 */

import { Mail, ShieldCheck } from 'lucide-react';
import * as React from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { AuthCard, AuthShell } from '@/components/layout/AuthShell';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/errors';
import { useAcceptInvite } from '@/lib/queries/admin';

export default function AcceptInvite() {
  const params = useParams<{ token: string }>();
  const token = params.token ?? '';
  const accept = useAcceptInvite();
  const navigate = useNavigate();
  const [name, setName] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError('Enter your name.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    accept.mutate(
      { token, name: name.trim(), password },
      {
        onSuccess: (envelope) => {
          // Hand the new user to /login with org + email pre-filled so
          // they just type the password they just set. This exercises
          // the bcrypt-verify path on the FIRST login and keeps every
          // user behind the same MFA-enrollment workflow.
          navigate('/login', {
            replace: true,
            state: {
              prefillEmail: envelope.email,
              prefillOrgName: envelope.org_name,
              flash: 'Invite accepted. Sign in to continue.',
            },
          });
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.code === 'TOKEN_INVALID') {
              setError(
                'This invite link is invalid or has been used. Ask your admin to resend the invite.',
              );
              return;
            }
            if (err.code === 'USER_EMAIL_TAKEN') {
              setError('A user with this email already exists. Try signing in instead.');
              return;
            }
          }
          setError(err instanceof Error ? err.message : 'Could not accept invite.');
        },
      },
    );
  };

  return (
    <AuthShell>
      <AuthCard title="Set up your account" subtitle="Pick a password to finish onboarding.">
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <Field label="Your name" htmlFor="invite-name" required>
            <Input
              id="invite-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Naseem Begum"
              autoComplete="name"
              icon={<Mail size={14} />}
            />
          </Field>
          <Field label="Password" htmlFor="invite-password" required>
            <Input
              id="invite-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              autoComplete="new-password"
              icon={<ShieldCheck size={14} />}
            />
          </Field>
          {error && (
            <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 12.5 }}>
              {error}
            </div>
          )}
          <Button type="submit" disabled={accept.isPending}>
            {accept.isPending ? 'Setting up…' : 'Accept invite'}
          </Button>
        </form>
      </AuthCard>
    </AuthShell>
  );
}
