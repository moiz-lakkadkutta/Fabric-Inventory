import { LogOut, Moon, Settings, Sun, User as UserIcon } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Monogram } from '@/components/ui/monogram';
import { useClickOutside } from '@/hooks/useClickOutside';
import { currentUser } from '@/lib/mock';

/*
  Avatar trigger + dropdown. Click toggles a 240px popover anchored to the
  right edge of the trigger. ThemeToggle is a stub: a row that flips an
  icon on click but does nothing else (Phase 1 is light-only).
*/
export function UserMenu() {
  const [open, setOpen] = useState(false);
  const [themeIsDark, setThemeIsDark] = useState(false);
  const navigate = useNavigate();
  const ref = useClickOutside<HTMLDivElement>(open, () => setOpen(false));

  const onItem = (handler: () => void) => () => {
    setOpen(false);
    handler();
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="User menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center justify-center"
        style={{
          width: 36,
          height: 36,
          borderRadius: 999,
          background: open ? 'var(--bg-sunken)' : 'transparent',
          border: '1px solid var(--border-default)',
        }}
      >
        <Monogram initials={currentUser.initials} size={28} tone="info" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-[44px] z-20"
          style={{
            width: 240,
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-default)',
            borderRadius: 12,
            boxShadow: 'var(--shadow-3)',
            overflow: 'hidden',
          }}
        >
          <div className="px-3.5 pb-2 pt-3">
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              {currentUser.legal_name}
            </div>
            <div className="truncate" style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
              {currentUser.email} · {currentUser.role}
            </div>
          </div>
          <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
            <MenuItem icon={<UserIcon size={14} />} onClick={onItem(() => navigate('/admin'))}>
              My account
            </MenuItem>
            <MenuItem icon={<Settings size={14} />} onClick={onItem(() => navigate('/admin'))}>
              Settings
            </MenuItem>
            <ThemeToggle isDark={themeIsDark} onToggle={() => setThemeIsDark((v) => !v)} />
          </div>
          <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
            <MenuItem icon={<LogOut size={14} />} onClick={onItem(() => navigate('/login'))}>
              Sign out
            </MenuItem>
          </div>
        </div>
      )}
    </div>
  );
}

interface MenuItemProps {
  icon: React.ReactNode;
  children: React.ReactNode;
  onClick?: () => void;
  hint?: string;
}

function MenuItem({ icon, children, onClick, hint }: MenuItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left hover:bg-(--bg-sunken)"
      style={{ fontSize: 13, color: 'var(--text-primary)' }}
    >
      <span style={{ color: 'var(--text-secondary)' }}>{icon}</span>
      <span className="flex-1">{children}</span>
      {hint && (
        <span className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
          {hint}
        </span>
      )}
    </button>
  );
}

function ThemeToggle({ isDark, onToggle }: { isDark: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={isDark}
      onClick={onToggle}
      className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left hover:bg-(--bg-sunken)"
      style={{ fontSize: 13, color: 'var(--text-primary)' }}
    >
      <span style={{ color: 'var(--text-secondary)' }}>
        {isDark ? <Moon size={14} /> : <Sun size={14} />}
      </span>
      <span className="flex-1">Theme</span>
      <span
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
        }}
      >
        Light only · Phase 1
      </span>
    </button>
  );
}
