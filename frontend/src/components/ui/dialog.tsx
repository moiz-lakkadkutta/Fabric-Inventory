import { X } from 'lucide-react';
import * as React from 'react';

import { useClickOutside } from '@/hooks/useClickOutside';
import { cn } from '@/lib/utils';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}

/*
  Bare-bones modal with backdrop, close button, click-outside, and Esc.
  Built without Radix to keep the click-dummy dependency surface tight.
  Real shadcn dialog can drop in later if accessibility behaviour needs
  to be tightened (focus trap, scroll lock).
*/
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = 460,
}: DialogProps) {
  const cardRef = useClickOutside<HTMLDivElement>(open, onClose);

  React.useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className={cn('fixed inset-0 z-50 flex items-center justify-center px-4')}
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === 'string' ? title : undefined}
    >
      <div className="absolute inset-0" style={{ background: 'rgba(20, 20, 18, 0.32)' }} />
      <div
        ref={cardRef}
        className="relative"
        style={{
          width,
          maxWidth: '100%',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-default)',
          borderRadius: 12,
          boxShadow: 'var(--shadow-4)',
          overflow: 'hidden',
        }}
      >
        <header
          className="flex items-start gap-3 px-5 py-4"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <div className="min-w-0 flex-1">
            <h2 className="m-0" style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>
              {title}
            </h2>
            {description && (
              <p className="m-0 mt-1" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md"
            style={{
              background: 'transparent',
              border: '1px solid transparent',
              color: 'var(--text-tertiary)',
            }}
          >
            <X size={14} />
          </button>
        </header>
        {children && <div className="px-5 py-4">{children}</div>}
        {footer && (
          <footer
            className="flex items-center justify-end gap-2 px-5 py-3"
            style={{
              borderTop: '1px solid var(--border-subtle)',
              background: 'var(--bg-sunken)',
            }}
          >
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
