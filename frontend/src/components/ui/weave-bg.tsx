import * as React from 'react';

import { cn } from '@/lib/utils';

interface WeaveBgProps {
  opacity?: number;
  className?: string;
}

let weaveIdCounter = 0;
function nextWeaveId() {
  weaveIdCounter += 1;
  return `taana-weave-${weaveIdCounter}`;
}

/*
  Subtle warp/weft pattern in --text-primary at low opacity. Lives behind
  auth screens, empty states, and onboarding. Render inside a positioned
  parent so the absolute fill clips correctly.
*/
export function WeaveBg({ opacity = 0.045, className }: WeaveBgProps) {
  const id = React.useMemo(nextWeaveId, []);
  return (
    <svg
      className={cn('pointer-events-none absolute inset-0 h-full w-full', className)}
      style={{ opacity }}
      aria-hidden="true"
    >
      <defs>
        <pattern id={id} width="24" height="24" patternUnits="userSpaceOnUse">
          <line x1="3" y1="0" x2="3" y2="24" stroke="#1A1A17" strokeWidth="1" />
          <line x1="9" y1="0" x2="9" y2="24" stroke="#1A1A17" strokeWidth="1" />
          <line x1="15" y1="0" x2="15" y2="24" stroke="#1A1A17" strokeWidth="1" />
          <line x1="21" y1="0" x2="21" y2="24" stroke="#1A1A17" strokeWidth="1" />
          <line x1="0" y1="6" x2="24" y2="6" stroke="#1A1A17" strokeWidth="1" />
          <line x1="0" y1="18" x2="24" y2="18" stroke="#1A1A17" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}

interface WeaveSurfaceProps {
  children?: React.ReactNode;
  height?: number | string;
  className?: string;
}

export function WeaveSurface({ children, height = 520, className }: WeaveSurfaceProps) {
  return (
    <div
      className={cn('relative overflow-hidden', className)}
      style={{
        height,
        background: 'var(--bg-canvas)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
      }}
    >
      <WeaveBg opacity={0.04} />
      <div className="relative flex h-full items-center justify-center p-6">{children}</div>
    </div>
  );
}
