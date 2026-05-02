import { Bell, CheckCircle2, FileText, PackageX, TrendingUp } from 'lucide-react';
import * as React from 'react';

import { useClickOutside } from '@/hooks/useClickOutside';

interface Notif {
  id: string;
  icon: React.ReactNode;
  iconColor: string;
  title: string;
  detail: string;
  when: string;
  unread?: boolean;
}

const NOTIFS: Notif[] = [
  {
    id: 'n1',
    icon: <CheckCircle2 size={14} />,
    iconColor: 'var(--success)',
    title: 'Payment received from Anjali Saree Centre',
    detail: '₹1.84 L applied to RT/2526/0010',
    when: '2 m ago',
    unread: true,
  },
  {
    id: 'n2',
    icon: <PackageX size={14} />,
    iconColor: 'var(--danger)',
    title: 'Chiffon Silk 44" below reorder level',
    detail: 'On hand 78 m · reorder at 100 m',
    when: '1 h ago',
    unread: true,
  },
  {
    id: 'n3',
    icon: <TrendingUp size={14} />,
    iconColor: 'var(--accent)',
    title: 'GSTR-1 ready for review',
    detail: '7 invoices · 1 to review · period Apr 2026',
    when: '3 h ago',
    unread: true,
  },
  {
    id: 'n4',
    icon: <FileText size={14} />,
    iconColor: 'var(--info)',
    title: 'PI/25-26/0014 imported from Surat Silk Mills',
    detail: 'Awaiting 3-way match',
    when: 'Yesterday',
  },
];

export function NotificationsPopover() {
  const [open, setOpen] = React.useState(false);
  const ref = useClickOutside<HTMLDivElement>(open, () => setOpen(false));
  const unread = NOTIFS.filter((n) => n.unread).length;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Notifications"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-md"
        style={{
          background: open ? 'var(--bg-sunken)' : 'transparent',
          border: '1px solid var(--border-default)',
          color: 'var(--text-secondary)',
        }}
      >
        <Bell size={16} />
        {unread > 0 && (
          <span
            className="absolute -right-1 -top-1 inline-flex min-w-[16px] items-center justify-center px-1"
            style={{
              height: 16,
              borderRadius: 999,
              background: 'var(--accent)',
              color: 'var(--accent-text)',
              fontSize: 10,
              fontWeight: 600,
            }}
          >
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Notifications"
          className="absolute right-0 top-[44px] z-20"
          style={{
            width: 360,
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-default)',
            borderRadius: 12,
            boxShadow: 'var(--shadow-3)',
            overflow: 'hidden',
          }}
        >
          <header
            className="flex items-baseline justify-between px-4 py-3"
            style={{ borderBottom: '1px solid var(--border-subtle)' }}
          >
            <span style={{ fontSize: 13, fontWeight: 600 }}>Notifications</span>
            <button
              type="button"
              style={{
                fontSize: 12,
                color: 'var(--accent)',
                background: 'transparent',
                fontWeight: 500,
              }}
            >
              Mark all read
            </button>
          </header>
          <ul className="max-h-[420px] overflow-y-auto">
            {NOTIFS.map((n) => (
              <li
                key={n.id}
                className="flex items-start gap-3 px-4 py-3"
                style={{
                  borderBottom: '1px solid var(--border-subtle)',
                  background: n.unread ? 'var(--bg-canvas)' : 'transparent',
                }}
              >
                <span style={{ color: n.iconColor, marginTop: 2 }}>{n.icon}</span>
                <div className="min-w-0 flex-1">
                  <div
                    className="truncate"
                    style={{ fontSize: 13, fontWeight: n.unread ? 600 : 500 }}
                  >
                    {n.title}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
                    {n.detail}
                  </div>
                </div>
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--text-tertiary)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {n.when}
                </span>
              </li>
            ))}
          </ul>
          <footer
            className="px-4 py-2.5 text-center"
            style={{
              borderTop: '1px solid var(--border-subtle)',
              background: 'var(--bg-sunken)',
            }}
          >
            <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
              Notification preferences in Admin
            </span>
          </footer>
        </div>
      )}
    </div>
  );
}
