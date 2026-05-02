import type { LucideIcon } from 'lucide-react';
import {
  BarChart3,
  CircleHelp,
  Cog,
  Database,
  Home,
  Package,
  ShieldCheck,
  ShoppingBag,
  Truck,
  Wallet,
  Wrench,
} from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';

import { cn } from '@/lib/utils';

interface SubItem {
  to: string;
  label: string;
}

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  prefix?: string;
  sub?: SubItem[];
}

const NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: Home, end: true },
  {
    to: '/sales/invoices',
    label: 'Sales',
    icon: ShoppingBag,
    prefix: '/sales',
    sub: [
      { to: '/sales/invoices', label: 'Invoices' },
      { to: '/sales/quotes', label: 'Quotes' },
      { to: '/sales/orders', label: 'Sales orders' },
      { to: '/sales/challans', label: 'Delivery challans' },
      { to: '/sales/returns', label: 'Returns' },
      { to: '/sales/credit-control', label: 'Credit control' },
    ],
  },
  { to: '/purchase', label: 'Purchase', icon: Truck },
  { to: '/inventory', label: 'Inventory', icon: Package },
  { to: '/manufacturing', label: 'Manufacturing', icon: Cog },
  { to: '/jobwork', label: 'Job work', icon: Wrench },
  { to: '/accounting', label: 'Accounts', icon: Wallet },
  { to: '/reports', label: 'Reports', icon: BarChart3 },
  { to: '/masters', label: 'Masters', icon: Database },
  { to: '/admin', label: 'Admin', icon: ShieldCheck },
];

export function Sidebar() {
  const { pathname } = useLocation();

  return (
    <aside
      className="hidden w-60 shrink-0 flex-col md:flex"
      style={{
        background: 'var(--bg-surface)',
        borderRight: '1px solid var(--border-default)',
      }}
    >
      <nav className="flex flex-col gap-0.5 px-2 py-3" aria-label="Primary">
        {NAV.map((item) => {
          const Icon = item.icon;
          const isActive = item.prefix
            ? pathname.startsWith(item.prefix)
            : item.end
              ? pathname === item.to
              : pathname.startsWith(item.to);
          return (
            <div key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={cn(
                  'relative flex items-center gap-3 rounded-md px-3 py-2 text-[13.5px] transition-colors',
                  !isActive && 'hover:bg-(--bg-sunken)',
                )}
                style={{
                  background: isActive ? 'var(--accent-subtle)' : 'transparent',
                  color: isActive ? 'var(--accent)' : 'var(--text-primary)',
                  fontWeight: isActive ? 600 : 500,
                }}
              >
                {isActive && (
                  <span
                    aria-hidden
                    className="absolute"
                    style={{
                      left: -8,
                      top: 6,
                      bottom: 6,
                      width: 2,
                      background: 'var(--accent)',
                      borderRadius: '0 2px 2px 0',
                    }}
                  />
                )}
                <Icon
                  size={16}
                  className="shrink-0"
                  style={{
                    color: isActive ? 'var(--accent)' : 'var(--text-tertiary)',
                  }}
                />
                <span>{item.label}</span>
              </NavLink>
              {isActive && item.sub && (
                <div className="flex flex-col py-1 pl-[38px] pr-2">
                  {item.sub.map((s) => (
                    <NavLink
                      key={s.to}
                      to={s.to}
                      className="flex h-8 items-center rounded px-3 text-[12.5px]"
                      style={({ isActive: subActive }) => ({
                        background: subActive ? 'var(--bg-sunken)' : 'transparent',
                        color: subActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: subActive ? 600 : 400,
                      })}
                    >
                      {s.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>
      <div
        className="mt-auto flex items-center gap-2.5 px-4 py-3"
        style={{
          borderTop: '1px solid var(--border-subtle)',
          fontSize: 12,
          color: 'var(--text-tertiary)',
        }}
      >
        <CircleHelp size={14} color="var(--text-tertiary)" />
        <span>Help & shortcuts</span>
        <span
          className="mono ml-auto"
          style={{
            fontSize: 10,
            color: 'var(--text-tertiary)',
            padding: '1px 5px',
            borderRadius: 3,
            background: 'var(--bg-sunken)',
            border: '1px solid var(--border-default)',
          }}
        >
          ?
        </span>
      </div>
    </aside>
  );
}
