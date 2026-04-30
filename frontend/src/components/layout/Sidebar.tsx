import type { LucideIcon } from 'lucide-react';
import {
  BarChart3,
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
import { NavLink } from 'react-router-dom';

import { cn } from '@/lib/utils';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/sales', label: 'Sales', icon: ShoppingBag },
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
  return (
    <aside
      className="hidden md:flex w-60 shrink-0 flex-col"
      style={{
        background: 'var(--bg-surface)',
        borderRight: '1px solid var(--border-default)',
      }}
    >
      <nav className="flex flex-col gap-0.5 px-2 py-3">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-[13.5px] transition-colors',
                isActive ? 'font-semibold' : 'hover:bg-(--bg-sunken)',
              )
            }
            style={({ isActive }) =>
              isActive
                ? {
                    background: 'var(--accent-subtle)',
                    color: 'var(--accent)',
                  }
                : { color: 'var(--text-primary)' }
            }
          >
            {({ isActive }) => (
              <>
                <Icon
                  size={16}
                  className="shrink-0"
                  // The icon inherits color from currentColor.
                  // For inactive items the muted tertiary makes the active
                  // emerald pop.
                  style={{
                    color: isActive ? 'var(--accent)' : 'var(--text-tertiary)',
                  }}
                />
                <span>{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div
        className="mt-auto px-4 py-3"
        style={{
          borderTop: '1px solid var(--border-subtle)',
          fontSize: 11,
          color: 'var(--text-tertiary)',
        }}
      >
        v0.1 · audit-grade ledger
      </div>
    </aside>
  );
}
