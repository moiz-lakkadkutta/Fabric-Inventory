import { Bell, Building2, ChevronDown, Search } from 'lucide-react';
import { useLocation } from 'react-router-dom';

import { Monogram } from '@/components/ui/monogram';
import { TaanaMark } from '@/components/ui/taana-mark';
import { currentUser, defaultFirm } from '@/lib/mock';

const ROUTE_LABELS: Record<string, string> = {
  '/': 'Home',
  '/sales': 'Sales',
  '/sales/invoices': 'Sales · Invoices',
  '/purchase': 'Purchase',
  '/inventory': 'Inventory',
  '/manufacturing': 'Manufacturing',
  '/jobwork': 'Job work',
  '/accounting': 'Accounts',
  '/reports': 'Reports',
  '/masters': 'Masters',
  '/admin': 'Admin',
};

export function TopBar() {
  const { pathname } = useLocation();
  const breadcrumb = ROUTE_LABELS[pathname] ?? 'Home';

  return (
    <div
      className="flex h-14 items-center gap-3 px-4"
      style={{
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-default)',
      }}
    >
      <div className="inline-flex shrink-0 items-center gap-2">
        <TaanaMark size={22} color="var(--accent)" />
        <span
          className="hidden sm:inline"
          style={{ fontSize: 17, fontWeight: 600, letterSpacing: '-0.02em' }}
        >
          taana
        </span>
      </div>

      <button
        type="button"
        className="ml-2 inline-flex h-9 max-w-[18rem] items-center gap-2 rounded-md px-2.5"
        style={{
          background: 'transparent',
          border: '1px solid var(--border-default)',
          color: 'var(--text-primary)',
        }}
      >
        <Building2 size={14} color="var(--text-secondary)" />
        <span className="truncate" style={{ fontSize: 13, fontWeight: 500 }}>
          {defaultFirm.name}
        </span>
        <span
          className="mono hidden truncate md:inline"
          style={{
            fontSize: 11,
            color: 'var(--text-tertiary)',
            maxWidth: 130,
          }}
        >
          · {defaultFirm.gstin}
        </span>
        <ChevronDown size={14} color="var(--text-tertiary)" />
      </button>

      <span
        className="hidden md:inline truncate"
        style={{ fontSize: 13, color: 'var(--text-secondary)' }}
      >
        {breadcrumb}
      </span>

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          className="hidden md:inline-flex h-9 min-w-[14rem] items-center gap-2 rounded-md px-3"
          style={{
            background: 'var(--bg-sunken)',
            border: '1px solid var(--border-default)',
            color: 'var(--text-tertiary)',
            fontSize: 13,
          }}
        >
          <Search size={14} />
          <span className="flex-1 text-left">Search invoices, parties…</span>
          <span
            className="mono"
            style={{
              fontSize: 11,
              padding: '1px 5px',
              borderRadius: 3,
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-default)',
              color: 'var(--text-tertiary)',
            }}
          >
            ⌘K
          </span>
        </button>

        <button
          type="button"
          aria-label="Notifications"
          className="relative inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <Bell size={16} />
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
            3
          </span>
        </button>

        <button
          type="button"
          aria-label="User menu"
          className="inline-flex items-center justify-center"
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            background: 'transparent',
            border: '1px solid var(--border-default)',
          }}
        >
          <Monogram initials={currentUser.initials} size={28} tone="info" />
        </button>
      </div>
    </div>
  );
}
