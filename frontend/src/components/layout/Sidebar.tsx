import { NavLink } from 'react-router-dom';

import { cn } from '@/lib/utils';

const NAV = [
  { to: '/', label: 'Dashboard' },
  { to: '/sales', label: 'Sales' },
  { to: '/purchase', label: 'Purchase' },
  { to: '/inventory', label: 'Inventory' },
  { to: '/accounting', label: 'Accounting' },
  { to: '/masters', label: 'Masters' },
  { to: '/admin', label: 'Admin' },
] as const;

export function Sidebar() {
  return (
    <aside className="w-56 border-r border-[--color-border] bg-[--color-background] flex flex-col">
      <div className="px-4 py-4 border-b border-[--color-border]">
        <h1 className="text-base font-semibold">Fabric ERP</h1>
        <p className="text-xs text-[--color-muted-foreground]">Phase 1 — MVP</p>
      </div>
      <nav className="flex-1 p-2 space-y-0.5 text-sm">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              cn(
                'block rounded-md px-3 py-2 transition-colors',
                isActive
                  ? 'bg-[--color-accent] text-[--color-accent-foreground]'
                  : 'hover:bg-[--color-accent]/60 text-[--color-foreground]',
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
