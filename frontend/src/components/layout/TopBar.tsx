import { ChevronRight, Search } from 'lucide-react';
import { useLocation } from 'react-router-dom';

import { TaanaMark } from '@/components/ui/taana-mark';
import { useCommandPalette } from '@/hooks/useCommandPalette';

import { FirmSwitcher } from './FirmSwitcher';
import { NotificationsPopover } from './NotificationsPopover';
import { UserMenu } from './UserMenu';

const ROUTE_LABELS: Record<string, string[]> = {
  '/': ['Home'],
  '/sales': ['Sales'],
  '/sales/invoices': ['Sales', 'Invoices'],
  '/sales/quotes': ['Sales', 'Quotes'],
  '/sales/orders': ['Sales', 'Sales orders'],
  '/sales/challans': ['Sales', 'Delivery challans'],
  '/sales/returns': ['Sales', 'Returns'],
  '/sales/credit-control': ['Sales', 'Credit control'],
  '/purchase': ['Purchase'],
  '/inventory': ['Inventory'],
  '/manufacturing': ['Manufacturing'],
  '/jobwork': ['Job work'],
  '/accounting': ['Accounts'],
  '/reports': ['Reports'],
  '/masters': ['Masters'],
  '/admin': ['Admin'],
};

export function TopBar() {
  const { pathname } = useLocation();
  const breadcrumb = ROUTE_LABELS[pathname] ?? ['Home'];
  const palette = useCommandPalette();

  return (
    <div
      className="flex items-center gap-2 px-3 md:gap-3.5 md:px-4"
      style={{
        height: 56,
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

      <div className="ml-1 md:ml-2">
        <FirmSwitcher />
      </div>

      <nav
        aria-label="Breadcrumb"
        className="hidden min-w-0 items-center gap-1.5 md:flex"
        style={{ fontSize: 13, color: 'var(--text-tertiary)' }}
      >
        {breadcrumb.map((b, i) => (
          <span key={`${b}-${i}`} className="inline-flex items-center gap-1.5">
            {i > 0 && <ChevronRight size={12} color="var(--text-tertiary)" />}
            <span
              className="whitespace-nowrap"
              style={{
                color:
                  i === breadcrumb.length - 1 ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontWeight: i === breadcrumb.length - 1 ? 500 : 400,
              }}
            >
              {b}
            </span>
          </span>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-1.5 md:gap-2">
        <button
          type="button"
          name="search"
          aria-label="Open command palette"
          onClick={() => palette.setOpen(true)}
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
          aria-label="Open command palette"
          onClick={() => palette.setOpen(true)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md md:hidden"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <Search size={16} />
        </button>

        <NotificationsPopover />

        <UserMenu />
      </div>
    </div>
  );
}
