import type { LucideIcon } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  body?: React.ReactNode;
  cta?: { label: string; onClick: () => void };
  secondary?: React.ReactNode;
}

/*
  Reusable empty state for tables / lists / panels. Centred icon in a
  warm-paper circle, headline, optional sub-copy, optional primary CTA
  + secondary affordance underneath.
*/
export function EmptyState({ icon: Icon, title, body, cta, secondary }: EmptyStateProps) {
  return (
    <div
      role="status"
      className="mx-auto flex max-w-md flex-col items-center px-4 py-12 text-center"
    >
      <span
        aria-hidden
        className="inline-flex items-center justify-center"
        style={{
          width: 48,
          height: 48,
          borderRadius: 999,
          background: 'var(--bg-sunken)',
          color: 'var(--text-secondary)',
          marginBottom: 14,
        }}
      >
        <Icon size={20} />
      </span>
      <h3 className="m-0" style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
        {title}
      </h3>
      {body && (
        <p
          className="m-0 mt-1.5"
          style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}
        >
          {body}
        </p>
      )}
      {(cta || secondary) && (
        <div className="mt-4 inline-flex items-center gap-2">
          {cta && (
            <Button onClick={cta.onClick} size="sm">
              {cta.label}
            </Button>
          )}
          {secondary}
        </div>
      )}
    </div>
  );
}
