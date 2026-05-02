import * as React from 'react';

import { cn } from '@/lib/utils';

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  width?: number | string;
  height?: number | string;
  radius?: number;
}

/*
  Single-block skeleton with a soft warm-paper shimmer. Use for any
  rectangular placeholder during fakeFetch latency. Composed (rather
  than templated as TableRowSkeleton, KPICardSkeleton, etc.) so each
  consumer can spec exact dimensions.
*/
export function Skeleton({
  width = '100%',
  height = 16,
  radius = 4,
  className,
  style,
  ...rest
}: SkeletonProps) {
  return (
    <div
      aria-hidden
      className={cn('taana-skeleton', className)}
      style={{
        width,
        height,
        borderRadius: radius,
        background:
          'linear-gradient(90deg, var(--bg-sunken) 0%, var(--border-subtle) 50%, var(--bg-sunken) 100%)',
        backgroundSize: '200% 100%',
        animation: 'taana-skeleton-shimmer 1.4s linear infinite',
        ...style,
      }}
      {...rest}
    />
  );
}
