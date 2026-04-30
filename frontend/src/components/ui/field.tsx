import * as React from 'react';

import { cn } from '@/lib/utils';

interface FieldProps {
  label: React.ReactNode;
  helper?: React.ReactNode;
  error?: React.ReactNode;
  hint?: React.ReactNode;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
  htmlFor?: string;
}

export function Field({
  label,
  helper,
  error,
  hint,
  required,
  children,
  className,
  htmlFor,
}: FieldProps) {
  const errored = Boolean(error);
  return (
    <label htmlFor={htmlFor} className={cn('block min-w-0', className)}>
      <div
        className="mb-1.5 flex items-baseline justify-between gap-2"
        style={{
          fontSize: 12,
          fontWeight: 500,
          color: 'var(--text-secondary)',
          letterSpacing: '0.005em',
        }}
      >
        <span className="min-w-0 truncate">
          {label}
          {required && <span style={{ color: 'var(--danger)' }}>*</span>}
        </span>
        {hint && (
          <span
            className="min-w-0 shrink truncate"
            style={{ color: 'var(--text-tertiary)', fontSize: 11 }}
          >
            {hint}
          </span>
        )}
      </div>
      {children}
      {(helper || error) && (
        <div
          className="mt-1.5"
          style={{
            fontSize: 12,
            color: errored ? 'var(--danger)' : 'var(--text-tertiary)',
          }}
        >
          {errored ? error : helper}
        </div>
      )}
    </label>
  );
}
