/*
 * InviteUserDialog (TASK-CUT-304) — Owner-initiated user invite.
 *
 * Form: email + role select. On submit, posts to /admin/invites; the BE
 * console-logs the invite link. The dialog shows the link in a
 * success banner so dev/test can copy-click without scraping logs.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useCreateInvite, useRoles, type InviteEnvelope } from '@/lib/queries/admin';

interface InviteUserDialogProps {
  open: boolean;
  onClose: () => void;
}

export function InviteUserDialog({ open, onClose }: InviteUserDialogProps) {
  const roles = useRoles();
  const createInvite = useCreateInvite();
  const idem = useIdempotencyKey();
  const [email, setEmail] = React.useState('');
  const [roleId, setRoleId] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<InviteEnvelope | null>(null);

  React.useEffect(() => {
    if (open) {
      setEmail('');
      setRoleId('');
      setError(null);
      setResult(null);
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError('Enter an email address.');
      return;
    }
    if (!roleId) {
      setError('Pick a role.');
      return;
    }
    createInvite.mutate(
      {
        email: email.trim(),
        role_id: roleId,
        idempotencyKey: idem.key,
      },
      {
        onSuccess: (envelope) => {
          setResult(envelope);
          idem.reset();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Could not send invite.');
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={result ? 'Invite sent' : 'Invite user'}
      description={
        result
          ? 'Share the link below with the invitee. They will set their name and password to finish onboarding.'
          : 'Send an invite link by email. The recipient sets their own password.'
      }
      width={520}
      footer={
        result ? (
          <Button type="button" onClick={onClose}>
            Done
          </Button>
        ) : (
          <>
            <Button variant="outline" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" form="invite-user-form" disabled={createInvite.isPending}>
              {createInvite.isPending ? 'Sending…' : 'Send invite'}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="flex flex-col gap-3">
          <div
            role="status"
            style={{
              padding: 10,
              background: 'var(--bg-sunken)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 6,
              fontSize: 12.5,
              wordBreak: 'break-all',
            }}
          >
            <div
              style={{
                color: 'var(--text-tertiary)',
                fontSize: 11,
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
                marginBottom: 4,
              }}
            >
              Invite link
            </div>
            <a
              href={result.invite_link}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--accent)' }}
            >
              {result.invite_link}
            </a>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
            Dev mode: the invite link is also printed to the server log. Email delivery wires up in
            Wave 5.
          </div>
        </div>
      ) : (
        <form id="invite-user-form" onSubmit={onSubmit} className="flex flex-col gap-3">
          <Field label="Email" htmlFor="invite-email" required>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="naseem@example.com"
              autoComplete="off"
            />
          </Field>
          <Field label="Role" htmlFor="invite-role" required>
            <select
              id="invite-role"
              value={roleId}
              onChange={(e) => setRoleId(e.target.value)}
              className="h-10 w-full rounded-md px-2"
              style={{
                border: '1px solid var(--border-default)',
                background: 'var(--bg-surface)',
                fontSize: 13,
              }}
            >
              <option value="">— Select role —</option>
              {(roles.data ?? []).map((r) => (
                <option key={r.role_id} value={r.role_id}>
                  {r.name}
                </option>
              ))}
            </select>
          </Field>
          {error && (
            <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 12.5 }}>
              {error}
            </div>
          )}
        </form>
      )}
    </Dialog>
  );
}
