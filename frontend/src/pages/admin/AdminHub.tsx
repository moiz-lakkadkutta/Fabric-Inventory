/*
 * AdminHub (TASK-CUT-304) — Owner-facing user + role management.
 *
 * Live-mode wires:
 *   GET    /admin/users          → useUsers
 *   GET    /admin/roles          → useRoles
 *   POST   /admin/invites        → InviteUserDialog
 *   PATCH  /admin/users/{id}/role → useUpdateUserRole (per-row select)
 *
 * Mock-mode falls back to the fixtures in `lib/mock/admin.ts` so the
 * click-dummy still functions without a backend.
 *
 * The "Add custom role" affordance is still coming-soon — custom-role
 * CRUD is deferred to Wave 5+ per the cutover plan.
 */

import { Plus, ShieldCheck } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Monogram } from '@/components/ui/monogram';
import { Pill } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import {
  useRoles,
  useUpdateUserRole,
  useUsers,
  type AdminRole,
  type AdminUser,
} from '@/lib/queries/admin';
import { InviteUserDialog } from '@/pages/admin/InviteUserDialog';

export default function AdminHub() {
  const users = useUsers();
  const roles = useRoles();
  const [inviteOpen, setInviteOpen] = React.useState(false);
  const newRole = useComingSoon({
    feature: 'Add custom role',
    task: 'TASK-022 (Custom roles)',
  });

  const usersList = users.data ?? [];
  const rolesList = roles.data ?? [];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Admin</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {usersList.length} users · {rolesList.length} roles
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" {...newRole.triggerProps}>
            Add role
          </Button>
          <Button onClick={() => setInviteOpen(true)}>
            <Plus />
            Invite user
          </Button>
        </div>
      </header>
      {newRole.dialog}
      <InviteUserDialog open={inviteOpen} onClose={() => setInviteOpen(false)} />

      <section
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <header
          className="flex items-baseline gap-2 px-4"
          style={{
            paddingTop: 12,
            paddingBottom: 12,
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Users</h2>
        </header>
        {users.isPending ? (
          <div className="p-4">
            <Skeleton style={{ height: 24, marginBottom: 8 }} />
            <Skeleton style={{ height: 24, marginBottom: 8 }} />
            <Skeleton style={{ height: 24 }} />
          </div>
        ) : users.isError ? (
          <div className="p-4">
            <QueryError error={users.error} onRetry={() => users.refetch()} />
          </div>
        ) : (
          <table className="w-full text-left">
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Name</Th>
                <Th>Email</Th>
                <Th>Role</Th>
                <Th>Status</Th>
                <Th>Last active</Th>
              </tr>
            </thead>
            <tbody>
              {usersList.map((u) => (
                <UserRow key={u.user_id} user={u} roles={rolesList} />
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <header
          className="flex items-baseline gap-2 px-4"
          style={{
            paddingTop: 12,
            paddingBottom: 12,
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Roles &amp; permissions</h2>
        </header>
        <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2">
          {rolesList.map((r) => {
            const memberCount = usersList.filter((u) => u.role_id === r.role_id).length;
            return (
              <article
                key={r.role_id}
                style={{
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 8,
                  padding: 14,
                  background: 'var(--bg-canvas)',
                }}
              >
                <div className="flex items-baseline justify-between">
                  <span style={{ fontSize: 13.5, fontWeight: 600 }}>{r.name}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                    {memberCount} member{memberCount === 1 ? '' : 's'}
                  </span>
                </div>
                <div className="mt-1" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                  {r.description ?? '—'}
                </div>
                <div
                  className="mono mt-2"
                  style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}
                >
                  {r.code}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section
        className="flex items-start gap-3"
        style={{
          background: 'var(--accent-subtle)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: 14,
        }}
      >
        <ShieldCheck size={18} color="var(--accent)" />
        <div className="min-w-0">
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent)' }}>Audit log</div>
          <div className="mt-0.5" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
            Every mutation is logged with user + before/after diff. Browse the full audit trail to
            review who did what and when.
          </div>
        </div>
      </section>
    </div>
  );
}

function UserRow({ user, roles }: { user: AdminUser; roles: AdminRole[] }) {
  const updateRole = useUpdateUserRole();
  const idem = useIdempotencyKey();
  const [error, setError] = React.useState<string | null>(null);
  const initials = (user.name ?? user.email)
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  const onRoleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const next = e.target.value;
    if (next === user.role_id) return;
    setError(null);
    updateRole.mutate(
      { user_id: user.user_id, role_id: next, idempotencyKey: idem.key },
      {
        onSuccess: () => {
          idem.reset();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Could not change role.');
        },
      },
    );
  };

  return (
    <tr style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <td className="px-3 py-3">
        <span className="inline-flex items-center gap-2.5">
          <Monogram
            initials={initials}
            size={28}
            tone={user.role === 'Owner' ? 'accent' : 'neutral'}
          />
          <span style={{ fontSize: 13.5, fontWeight: 500 }}>{user.name ?? user.email}</span>
        </span>
      </td>
      <td className="px-3 py-3" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
        {user.email}
      </td>
      <td className="px-3 py-3">
        <select
          aria-label={`Role for ${user.email}`}
          value={user.role_id}
          onChange={onRoleChange}
          disabled={updateRole.isPending}
          className="h-8 rounded-md px-2"
          style={{
            border: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            fontSize: 12.5,
            fontWeight: 500,
          }}
        >
          {roles.map((r) => (
            <option key={r.role_id} value={r.role_id}>
              {r.name}
            </option>
          ))}
        </select>
        {error && (
          <div
            role="alert"
            className="mt-1"
            style={{ color: 'var(--danger-text)', fontSize: 11.5 }}
          >
            {error}
          </div>
        )}
      </td>
      <td className="px-3 py-3">
        <Pill
          kind={user.status === 'ACTIVE' ? 'paid' : user.status === 'INACTIVE' ? 'due' : 'scrap'}
        >
          {user.status[0] + user.status.slice(1).toLowerCase()}
        </Pill>
      </td>
      <td className="px-3 py-3" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
        {user.last_login_at
          ? new Date(user.last_login_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
          : '—'}
      </td>
    </tr>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th
      className="px-3 py-2.5"
      style={{
        textAlign: 'left',
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {children}
    </th>
  );
}
