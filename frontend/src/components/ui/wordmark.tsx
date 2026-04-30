import { TaanaMark } from './taana-mark';

interface WordmarkProps {
  size?: number;
  className?: string;
}

export function Wordmark({ size = 28, className }: WordmarkProps) {
  return (
    <span
      className={className}
      style={{
        fontFamily: 'var(--font-ui)',
        fontWeight: 600,
        fontSize: size,
        letterSpacing: '-0.02em',
        lineHeight: 1,
        color: 'var(--text-primary)',
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: size * 0.18,
      }}
    >
      <TaanaMark size={size * 0.95} color="var(--accent)" />
      <span>taana</span>
    </span>
  );
}
