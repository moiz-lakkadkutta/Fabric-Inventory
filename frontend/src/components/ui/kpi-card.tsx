import * as React from 'react';

import { cn } from '@/lib/utils';

interface KPICardProps {
  label: string;
  value: React.ReactNode;
  delta?: string;
  deltaKind?: 'positive' | 'negative' | 'neutral';
  icon?: React.ReactNode;
  spark?: number[];
  className?: string;
}

export function KPICard({
  label,
  value,
  delta,
  deltaKind = 'positive',
  icon,
  spark,
  className,
}: KPICardProps) {
  const deltaColor =
    deltaKind === 'positive'
      ? 'var(--data-positive)'
      : deltaKind === 'negative'
        ? 'var(--data-negative)'
        : 'var(--data-neutral)';

  return (
    <div
      className={cn('flex flex-col', className)}
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        padding: 16,
        gap: 6,
        minHeight: 132,
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <span
          className="min-w-0 flex-1"
          style={{
            fontSize: 12,
            color: 'var(--text-secondary)',
            fontWeight: 500,
            letterSpacing: '0.005em',
            lineHeight: 1.35,
            // Reserve 2 lines so values stay vertically aligned across cards.
            minHeight: '2.7em',
            display: '-webkit-box',
            WebkitBoxOrient: 'vertical',
            WebkitLineClamp: 2,
            overflow: 'hidden',
          }}
        >
          {label}
        </span>
        {icon && (
          <span className="inline-flex shrink-0" style={{ color: 'var(--text-tertiary)' }}>
            {icon}
          </span>
        )}
      </div>
      <div
        className="num"
        style={{
          fontSize: 24,
          fontWeight: 600,
          letterSpacing: '-0.015em',
          color: 'var(--text-primary)',
          lineHeight: 1.15,
          marginTop: 4,
        }}
      >
        {value}
      </div>
      {delta && (
        <div style={{ fontSize: 12, color: deltaColor, fontWeight: 500 }}>
          <span className="num">{delta}</span>
        </div>
      )}
      {spark && <Sparkline data={spark} />}
    </div>
  );
}

function Sparkline({
  data,
  w = 240,
  h = 28,
  color = 'var(--text-tertiary)',
}: {
  data: number[];
  w?: number;
  h?: number;
  color?: string;
}) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const stepX = w / (data.length - 1);
  const pts = data.map((v, i) => `${i * stepX},${h - ((v - min) / range) * h}`).join(' ');
  return (
    <svg
      width="100%"
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      style={{ marginTop: 'auto' }}
      aria-hidden="true"
    >
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.25" />
    </svg>
  );
}
