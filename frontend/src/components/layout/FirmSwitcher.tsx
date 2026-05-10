import { Building2, Check, ChevronDown, Plus } from 'lucide-react';
import { useState } from 'react';

import { Monogram } from '@/components/ui/monogram';
import { useClickOutside } from '@/hooks/useClickOutside';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useSwitchFirm } from '@/lib/queries/identity';
import { cn } from '@/lib/utils';
import { useMe, type MeFirmRef } from '@/store/auth';

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
  below the trigger; click-outside or Esc closes it.

  Identity comes from `authStore.me.available_firms` (CUT-004). The
  popover's `optimisticFirmId` tracks the user's most recent click so the
  chip updates instantly while `useSwitchFirm` round-trips to /auth/
  switch-firm — on success the mutation refetches /me and the optimistic
  state collapses into the canonical store value; on failure the
  optimistic state is reverted.

  When `me` is null (status `unknown` / `unauthenticated`) the switcher
  renders a quiet placeholder rather than leaking any mock fixtures.
*/
export function FirmSwitcher({ compact = false }: FirmSwitcherProps) {
  const me = useMe();
  const [open, setOpen] = useState(false);
  const [optimisticFirmId, setOptimisticFirmId] = useState<string | null>(null);
  const ref = useClickOutside<HTMLDivElement>(open, () => setOpen(false));
  const switchFirm = useSwitchFirm();
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();

  const availableFirms: MeFirmRef[] = me?.available_firms ?? [];
  const currentId = optimisticFirmId ?? me?.firm_id ?? availableFirms[0]?.firm_id ?? null;
  const current = availableFirms.find((f) => f.firm_id === currentId) ?? null;

  // No identity yet (bootstrap pending or signed out) — render a quiet
  // chip placeholder. Hide the popover entirely so users can't open
  // an empty list. The route gate (<RequireAuth>) means this is rare in
  // practice; this branch keeps the topbar layout stable mid-bootstrap.
  if (!me || availableFirms.length === 0) {
    return (
      <div
        aria-hidden="true"
        className="inline-flex h-9 items-center gap-2 rounded-md px-2.5"
        style={{
          background: 'transparent',
          border: '1px solid var(--border-default)',
          color: 'var(--text-tertiary)',
          maxWidth: compact ? 200 : 320,
          minWidth: 0,
          opacity: 0.5,
        }}
      >
        <Building2 size={14} color="var(--text-secondary)" />
        <span className="truncate" style={{ fontSize: 13 }}>
          —
        </span>
      </div>
    );
  }

  const triggerLabel = current?.name ?? '—';

  const onSelect = (firmId: string) => {
    if (firmId === currentId) {
      setOpen(false);
      return;
    }
    const previousId = optimisticFirmId;
    setOptimisticFirmId(firmId);
    setOpen(false);
    switchFirm.mutate(
      { firm_id: firmId, idempotencyKey },
      {
        onSuccess: () => {
          resetKey();
          // Once the mutation refetches /me, store has the new firm_id;
          // drop our optimistic shadow so future renders read store.
          setOptimisticFirmId(null);
        },
        onError: () => {
          resetKey();
          setOptimisticFirmId(previousId);
        },
      },
    );
  };

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
          {triggerLabel}
        </span>
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
            {availableFirms.map((f) => {
              const isCurrent = f.firm_id === currentId;
              return (
                <button
                  key={f.firm_id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={isCurrent}
                  onClick={() => onSelect(f.firm_id)}
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
                        {f.code}
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
