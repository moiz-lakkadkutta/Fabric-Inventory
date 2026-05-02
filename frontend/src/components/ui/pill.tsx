import * as React from 'react';

import { cn } from '@/lib/utils';

export type PillKind = 'draft' | 'finalized' | 'paid' | 'overdue' | 'karigar' | 'scrap' | 'due';

const styles: Record<PillKind, { bg: string; fg: string }> = {
  draft: { bg: 'var(--info-subtle)', fg: 'var(--info-text)' },
  finalized: { bg: 'var(--accent-subtle)', fg: 'var(--accent)' },
  paid: { bg: 'var(--success-subtle)', fg: 'var(--success-text)' },
  overdue: { bg: 'var(--danger-subtle)', fg: 'var(--danger-text)' },
  karigar: { bg: 'var(--warning-subtle)', fg: 'var(--warning-text)' },
  scrap: { bg: '#EAE7DD', fg: '#605D52' },
  due: { bg: 'var(--info-subtle)', fg: 'var(--info-text)' },
};

interface PillProps extends React.HTMLAttributes<HTMLSpanElement> {
  kind?: PillKind;
}

export function Pill({ kind = 'draft', className, children, ...rest }: PillProps) {
  const c = styles[kind];
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 uppercase', className)}
      style={{
        height: 22,
        padding: '0 8px',
        borderRadius: 4,
        background: c.bg,
        color: c.fg,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.04em',
        whiteSpace: 'nowrap',
      }}
      {...rest}
    >
      {children}
    </span>
  );
}
