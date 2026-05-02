import { Building2, Check, ChevronDown, Plus } from 'lucide-react';
import { useState } from 'react';

import { Monogram } from '@/components/ui/monogram';
import { Pill } from '@/components/ui/pill';
import { useClickOutside } from '@/hooks/useClickOutside';
import { firms } from '@/lib/mock';
import { cn } from '@/lib/utils';

const FY_LABEL = 'FY 2025-26';

function initials(name: string) {
  return name
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

interface FirmSwitcherProps {
  compact?: boolean;
}

/*
  Firm-switcher trigger + popover. Click toggles a 380px popover anchored
  below the trigger; click-outside or Esc closes it. The "current firm"
  state is component-local for the click dummy; the real flow ties to
  identity.currentFirm in T2/T7.
*/
export function FirmSwitcher({ compact = false }: FirmSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [currentId, setCurrentId] = useState(firms[0].firm_id);
  const ref = useClickOutside<HTMLDivElement>(open, () => setOpen(false));

  const current = firms.find((f) => f.firm_id === currentId) ?? firms[0];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex h-9 items-center gap-2 rounded-md px-2.5"
        style={{
          background: open ? 'var(--bg-sunken)' : 'transparent',
          border: `1px solid ${open ? 'var(--border-strong)' : 'var(--border-default)'}`,
          color: 'var(--text-primary)',
          maxWidth: compact ? 200 : 320,
          minWidth: 0,
        }}
      >
        <Building2 size={14} color="var(--text-secondary)" />
        <span className="truncate" style={{ fontSize: 13, fontWeight: 500 }}>
          {current.name}
        </span>
        {!compact && current.gstin && (
          <span
            className="mono hidden truncate md:inline"
            style={{ fontSize: 11, color: 'var(--text-tertiary)', maxWidth: 130 }}
          >
            · {current.gstin}
          </span>
        )}
        <ChevronDown size={14} color="var(--text-tertiary)" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Switch firm"
          className="absolute left-0 top-[44px] z-20"
          style={{
            width: compact ? 320 : 380,
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-default)',
            borderRadius: 12,
            boxShadow: 'var(--shadow-3)',
            overflow: 'hidden',
          }}
        >
          <div className="flex items-center gap-2 px-3.5 pb-2 pt-3">
            <span
              className="uppercase"
              style={{
                fontSize: 11,
                color: 'var(--text-tertiary)',
                letterSpacing: '.06em',
                fontWeight: 600,
              }}
            >
              Switch firm
            </span>
            <span className="ml-auto" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
              {FY_LABEL}
            </span>
          </div>
          <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
            {firms.map((f) => {
              const isCurrent = f.firm_id === currentId;
              return (
                <button
                  key={f.firm_id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={isCurrent}
                  onClick={() => {
                    setCurrentId(f.firm_id);
                    setOpen(false);
                  }}
                  className={cn(
                    'flex w-full items-center gap-3 px-3.5 text-left',
                    'hover:bg-(--bg-sunken)',
                  )}
                  style={{
                    background: isCurrent ? 'var(--accent-subtle)' : 'transparent',
                    borderBottom: '1px solid var(--border-subtle)',
                    minHeight: 56,
                    paddingTop: 10,
                    paddingBottom: 10,
                  }}
                >
                  <Monogram
                    initials={initials(f.name)}
                    size={36}
                    tone={isCurrent ? 'accent' : 'neutral'}
                  />
                  <div className="min-w-0 flex-1">
                    <div
                      className="truncate"
                      style={{
                        fontSize: 13.5,
                        fontWeight: 600,
                        color: 'var(--text-primary)',
                      }}
                    >
                      {f.name}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span
                        className="mono truncate"
                        style={{
                          fontSize: 11,
                          color: 'var(--text-secondary)',
                          maxWidth: '60%',
                        }}
                      >
                        {f.gstin ?? '—'}
                      </span>
                      {!f.has_gst && <Pill kind="scrap">Non-GST</Pill>}
                      <span
                        className="ml-auto"
                        style={{ fontSize: 11, color: 'var(--text-tertiary)' }}
                      >
                        {f.state_name}
                      </span>
                    </div>
                  </div>
                  {isCurrent && <Check size={16} color="var(--accent)" />}
                </button>
              );
            })}
          </div>
          <div
            className="flex items-center gap-2.5 px-3.5 py-2.5"
            style={{
              borderTop: '1px solid var(--border-subtle)',
              background: 'var(--bg-sunken)',
            }}
          >
            <Plus size={14} color="var(--accent)" />
            <span style={{ fontSize: 13, color: 'var(--accent)', fontWeight: 500 }}>
              Add a firm
            </span>
            <span className="ml-auto" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
              Owner only
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
