import { cn } from '@/lib/utils';

type Tone = 'neutral' | 'accent' | 'info';

const tones: Record<Tone, { bg: string; fg: string }> = {
  neutral: { bg: '#E5E2D6', fg: '#4A4840' },
  accent: { bg: '#D7E9DF', fg: '#0A4A2B' },
  info: { bg: '#DEE3EA', fg: '#283038' },
};

interface MonogramProps {
  initials: string;
  size?: number;
  tone?: Tone;
  className?: string;
}

export function Monogram({ initials, size = 28, tone = 'neutral', className }: MonogramProps) {
  const c = tones[tone];
  return (
    <span
      className={cn('inline-flex items-center justify-center', className)}
      style={{
        width: size,
        height: size,
        borderRadius: 999,
        background: c.bg,
        color: c.fg,
        fontSize: size * 0.42,
        fontWeight: 600,
        letterSpacing: '0.005em',
        flexShrink: 0,
      }}
    >
      {initials}
    </span>
  );
}
