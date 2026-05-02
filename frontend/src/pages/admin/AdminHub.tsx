import { Plus, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Monogram } from '@/components/ui/monogram';
import { Pill } from '@/components/ui/pill';

interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: 'Owner' | 'Accountant' | 'Sales' | 'Warehouse';
  status: 'Active' | 'Pending' | 'Disabled';
  last_active: string;
}

const USERS: AdminUser[] = [
  {
    id: 'u1',
    name: 'Moiz Lakkadkutta',
    email: 'moiz@rajeshtextiles.in',
    role: 'Owner',
    status: 'Active',
    last_active: '2 m ago',
  },
  {
    id: 'u2',
    name: 'Naseem Begum',
    email: 'naseem@rajeshtextiles.in',
    role: 'Sales',
    status: 'Active',
    last_active: '1 h ago',
  },
  {
    id: 'u3',
    name: 'Pooja Devi',
    email: 'pooja.qc@rajeshtextiles.in',
    role: 'Warehouse',
    status: 'Active',
    last_active: 'Yesterday',
  },
  {
    id: 'u4',
    name: 'Rajesh Patel CA',
    email: 'rajesh.ca@finbridge.in',
    role: 'Accountant',
    status: 'Active',
    last_active: '4 d ago',
  },
  {
    id: 'u5',
    name: 'Salim Sheikh',
    email: 'salim.aari@gmail.com',
    role: 'Sales',
    status: 'Pending',
    last_active: 'Invite sent 2 d ago',
  },
];

const ROLES = [
  {
    name: 'Owner',
    desc: 'Full access incl. firm + admin settings',
    permissions: 'sales.* · purchase.* · accounts.* · admin.*',
    members: 1,
  },
  {
    name: 'Accountant',
    desc: 'Books, vouchers, reports, GSTR. No admin.',
    permissions: 'accounts.* · reports.* · sales.read · purchase.read',
    members: 1,
  },
  {
    name: 'Sales',
    desc: 'Create invoices, quotes, customer ledger.',
    permissions: 'sales.* · masters.party.read',
    members: 2,
  },
  {
    name: 'Warehouse',
    desc: 'GRN intake, lot moves, QC, dispatch.',
    permissions: 'inventory.* · purchase.grn.* · jobwork.receive',
    members: 1,
  },
];

export default function AdminHub() {
  const invite = useComingSoon({
    feature: 'Invite user',
    task: 'TASK-021 (User invites)',
  });
  const newRole = useComingSoon({
    feature: 'Add custom role',
    task: 'TASK-022 (Custom roles)',
  });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Admin</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {USERS.length} users · {ROLES.length} roles
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" {...newRole.triggerProps}>
            Add role
          </Button>
          <Button {...invite.triggerProps}>
            <Plus />
            Invite user
          </Button>
        </div>
      </header>
      {invite.dialog}
      {newRole.dialog}

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
            {USERS.map((u) => {
              const initials = u.name
                .split(' ')
                .map((w) => w[0])
                .slice(0, 2)
                .join('')
                .toUpperCase();
              return (
                <tr key={u.id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td className="px-3 py-3">
                    <span className="inline-flex items-center gap-2.5">
                      <Monogram
                        initials={initials}
                        size={28}
                        tone={u.role === 'Owner' ? 'accent' : 'neutral'}
                      />
                      <span style={{ fontSize: 13.5, fontWeight: 500 }}>{u.name}</span>
                    </span>
                  </td>
                  <td
                    className="px-3 py-3"
                    style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                  >
                    {u.email}
                  </td>
                  <td className="px-3 py-3" style={{ fontSize: 12.5, fontWeight: 500 }}>
                    {u.role}
                  </td>
                  <td className="px-3 py-3">
                    <Pill
                      kind={
                        u.status === 'Active' ? 'paid' : u.status === 'Pending' ? 'due' : 'scrap'
                      }
                    >
                      {u.status}
                    </Pill>
                  </td>
                  <td className="px-3 py-3" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                    {u.last_active}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
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
          {ROLES.map((r) => (
            <article
              key={r.name}
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
                  {r.members} member{r.members === 1 ? '' : 's'}
                </span>
              </div>
              <div className="mt-1" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                {r.desc}
              </div>
              <div className="mono mt-2" style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
                {r.permissions}
              </div>
            </article>
          ))}
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
