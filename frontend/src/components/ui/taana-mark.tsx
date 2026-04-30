/*
  Taana mark — five vertical warp threads with one horizontal weft.
  The centre warp passes UNDER the weft, suggesting one weave intersection.
  Geometric, ownable, scales crisply from 16px to display sizes.
*/

interface TaanaMarkProps {
  size?: number;
  color?: string;
  stroke?: number;
  className?: string;
}

export function TaanaMark({
  size = 32,
  color = 'currentColor',
  stroke,
  className,
}: TaanaMarkProps) {
  const sw = stroke ?? Math.max(1.5, size / 18);
  const pad = size * 0.18;
  const inner = size - pad * 2;
  const cols = 5;
  const gap = inner / (cols - 1);
  const weftY = pad + inner * 0.58;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      className={className}
    >
      <line
        x1={pad}
        y1={weftY}
        x2={size - pad}
        y2={weftY}
        stroke={color}
        strokeWidth={sw}
        strokeLinecap="square"
      />
      {Array.from({ length: cols }).map((_, i) => {
        const x = pad + gap * i;
        const isCenter = i === 2;
        if (isCenter) {
          return (
            <g key={i}>
              <line
                x1={x}
                y1={pad}
                x2={x}
                y2={weftY - sw * 0.6}
                stroke={color}
                strokeWidth={sw}
                strokeLinecap="square"
              />
              <line
                x1={x}
                y1={weftY + sw * 0.6}
                x2={x}
                y2={size - pad}
                stroke={color}
                strokeWidth={sw}
                strokeLinecap="square"
              />
            </g>
          );
        }
        return (
          <line
            key={i}
            x1={x}
            y1={pad}
            x2={x}
            y2={size - pad}
            stroke={color}
            strokeWidth={sw}
            strokeLinecap="square"
          />
        );
      })}
    </svg>
  );
}
