import * as React from 'react';

import { cn } from '@/lib/utils';

interface PageHeaderProps {
  title: React.ReactNode;
  pill?: React.ReactNode;
  sub?: React.ReactNode;
  secondary?: React.ReactNode;
  primary?: React.ReactNode;
  className?: string;
}

export function PageHeader({ title, pill, sub, secondary, primary, className }: PageHeaderProps) {
  return (
    <div
      className={cn(
        'flex items-center gap-3 border-b px-4 py-5 md:px-8',
        'bg-(--bg-surface)',
        className,
      )}
      style={{
        borderColor: 'var(--border-default)',
      }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2.5">
          <h1
            className="m-0 truncate"
            style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.012em' }}
          >
            {title}
          </h1>
          {pill}
        </div>
        {sub && (
          <div
            className="mt-0.5 truncate"
            style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}
          >
            {sub}
          </div>
        )}
      </div>
      {secondary && <div className="flex-shrink-0">{secondary}</div>}
      {primary && <div className="flex-shrink-0">{primary}</div>}
    </div>
  );
}
