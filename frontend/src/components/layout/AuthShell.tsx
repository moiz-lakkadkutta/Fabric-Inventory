import * as React from 'react';

import { Wordmark } from '@/components/ui/wordmark';

/*
  AuthShell — shared chrome for /login, /mfa, /forgot, /invite.
  - warm-paper canvas
  - subtle warp/weft pattern at 5% opacity (the brand mark, scaled out)
  - centred 460px column with wordmark above and audit-grade footer below
*/
interface AuthShellProps {
  children: React.ReactNode;
  width?: number;
}

export function AuthShell({ children, width = 460 }: AuthShellProps) {
  return (
    <div
      className="relative flex min-h-full w-full items-center justify-center overflow-hidden"
      style={{ background: 'var(--bg-canvas)' }}
    >
      <WeaveBackground />
      <div className="relative z-10 px-4" style={{ width }}>
        <div className="mb-6 flex justify-center">
          <Wordmark size={28} />
        </div>
        {children}
        <div className="mt-5 text-center" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
          taana · v0.1 · audit-grade ledger
        </div>
      </div>
    </div>
  );
}

function WeaveBackground() {
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      style={{ opacity: 0.05 }}
      aria-hidden="true"
    >
      <defs>
        <pattern id="taana-auth-weave" width="32" height="32" patternUnits="userSpaceOnUse">
          {[0, 1, 2, 3, 4].map((i) => (
            <line
              key={`v${i}`}
              x1={4 + i * 7}
              y1={0}
              x2={4 + i * 7}
              y2={32}
              stroke="#1A1A17"
              strokeWidth={1}
            />
          ))}
          <line x1="0" y1="8" x2="32" y2="8" stroke="#1A1A17" strokeWidth="1" />
          <line x1="0" y1="24" x2="32" y2="24" stroke="#1A1A17" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#taana-auth-weave)" />
    </svg>
  );
}

interface AuthCardProps {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  pad?: number;
  children: React.ReactNode;
}

export function AuthCard({ title, subtitle, pad = 32, children }: AuthCardProps) {
  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 12,
        padding: pad,
        boxShadow: 'var(--shadow-2)',
      }}
    >
      {(title || subtitle) && (
        <div className="mb-6">
          {title && (
            <h2
              className="m-0"
              style={{
                fontSize: 20,
                fontWeight: 600,
                letterSpacing: '-0.01em',
              }}
            >
              {title}
            </h2>
          )}
          {subtitle && (
            <p
              className="m-0 mt-1.5"
              style={{
                fontSize: 13.5,
                color: 'var(--text-secondary)',
                lineHeight: 1.5,
              }}
            >
              {subtitle}
            </p>
          )}
        </div>
      )}
      {children}
    </div>
  );
}
