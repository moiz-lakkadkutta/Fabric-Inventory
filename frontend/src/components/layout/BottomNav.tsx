import type { LucideIcon } from 'lucide-react';
import { BarChart3, Home, Menu, Package, ShoppingBag } from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { cn } from '@/lib/utils';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const ITEMS: NavItem[] = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/sales/invoices', label: 'Sales', icon: ShoppingBag },
  { to: '/inventory', label: 'Inventory', icon: Package },
  { to: '/reports', label: 'Reports', icon: BarChart3 },
  { to: '/admin', label: 'More', icon: Menu },
];

/*
  Mobile bottom navigation. Five items, equal-width columns, 56px tall.
  Active state: emerald icon + label, weight 600. Hidden on >= md.
*/
export function BottomNav() {
  return (
    <nav
      className="flex md:hidden"
      style={{
        height: 56,
        background: 'var(--bg-surface)',
        borderTop: '1px solid var(--border-default)',
      }}
      aria-label="Primary mobile"
    >
      {ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            cn(
              'flex flex-1 flex-col items-center justify-center gap-1',
              isActive && 'font-semibold',
            )
          }
          style={({ isActive }) => ({
            color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
          })}
        >
          {({ isActive }) => (
            <>
              <Icon size={18} color={isActive ? 'var(--accent)' : 'var(--text-secondary)'} />
              <span style={{ fontSize: 10.5, fontWeight: isActive ? 600 : 500 }}>{label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
