// components.jsx — Taana ERP design-system primitives.
// Loaded after React + Babel; exports components onto window.

const { useState, useMemo } = React;

/* ─────────────────────────────────────────────────────────────
   Mark — the warp + one weft. Geometric, ownable, scales.
   props: size (px), color
───────────────────────────────────────────────────────────── */
function TaanaMark({ size = 32, color = 'currentColor', stroke }) {
  const s = size;
  // Stroke width scales with size but stays crisp at 16/32/96.
  const sw = stroke ?? Math.max(1.5, s / 18);
  // 5 vertical warp threads + 1 horizontal weft, with the centre warp
  // crossing in front of the weft (the over-under that defines weave).
  const pad = s * 0.18;
  const inner = s - pad * 2;
  const cols = 5;
  const gap = inner / (cols - 1);
  const weftY = pad + inner * 0.58;
  return (
    <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} aria-hidden="true">
      {/* weft (horizontal) — drawn first so warps overlap it */}
      <line x1={pad} y1={weftY} x2={s - pad} y2={weftY}
        stroke={color} strokeWidth={sw} strokeLinecap="square" />
      {/* warp (vertical) — but the centre one is broken to show under-over */}
      {Array.from({ length: cols }).map((_, i) => {
        const x = pad + gap * i;
        const isCenter = i === 2;
        if (isCenter) {
          // centre warp goes UNDER the weft: draw two segments
          return (
            <g key={i}>
              <line x1={x} y1={pad} x2={x} y2={weftY - sw * 0.6}
                stroke={color} strokeWidth={sw} strokeLinecap="square" />
              <line x1={x} y1={weftY + sw * 0.6} x2={x} y2={s - pad}
                stroke={color} strokeWidth={sw} strokeLinecap="square" />
            </g>
          );
        }
        return (
          <line key={i} x1={x} y1={pad} x2={x} y2={s - pad}
            stroke={color} strokeWidth={sw} strokeLinecap="square" />
        );
      })}
    </svg>
  );
}

/* ─────────────────────────────────────────────────────────────
   Wordmark — Hanken Grotesk, 580 weight, slightly tightened.
   The 'a' pair and the 'a' final get standard treatment; the
   double-a forms a visual rhythm that echoes the warp.
───────────────────────────────────────────────────────────── */
function Wordmark({ size = 48 }) {
  return (
    <span style={{
      fontFamily: 'var(--font-ui)',
      fontWeight: 600,
      fontSize: size,
      letterSpacing: '-0.02em',
      lineHeight: 1,
      color: 'var(--text-primary)',
      display: 'inline-flex',
      alignItems: 'baseline',
      gap: size * 0.18,
    }}>
      <TaanaMark size={size * 0.95} color="var(--accent)" />
      <span>taana</span>
    </span>
  );
}

/* ─────────────────────────────────────────────────────────────
   Section header — used between every showcase block.
───────────────────────────────────────────────────────────── */
function SectionHead({ num, title, sub }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 12,
        borderBottom: '1px solid var(--border-default)', paddingBottom: 10,
      }}>
        <span className="mono" style={{
          fontSize: 11, color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
        }}>{String(num).padStart(2, '0')}</span>
        <h2 style={{
          fontSize: 18, fontWeight: 600, margin: 0,
          color: 'var(--text-primary)', letterSpacing: '-0.01em',
          whiteSpace: 'nowrap',
        }}>{title}</h2>
        {sub && <span style={{
          fontSize: 12, color: 'var(--text-tertiary)', marginLeft: 'auto',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>{sub}</span>}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Buttons
───────────────────────────────────────────────────────────── */
const btnSize = {
  sm: { h: 32, px: 12, font: 13, gap: 6, radius: 6 },
  md: { h: 40, px: 16, font: 14, gap: 8, radius: 6 },
  lg: { h: 48, px: 20, font: 15, gap: 10, radius: 8 },
};
function Button({ variant = 'primary', size = 'md', state = 'rest', children, icon, iconRight }) {
  const sz = btnSize[size];
  const styles = {
    primary: {
      rest:    { bg: 'var(--accent)',          fg: 'var(--accent-text)', bd: 'var(--accent)' },
      hover:   { bg: 'var(--accent-hover)',    fg: 'var(--accent-text)', bd: 'var(--accent-hover)' },
      pressed: { bg: 'var(--accent-pressed)',  fg: 'var(--accent-text)', bd: 'var(--accent-pressed)' },
      disabled:{ bg: '#D8D5C8',                fg: '#8A8880',            bd: '#D8D5C8' },
    },
    secondary: {
      rest:    { bg: 'var(--bg-surface)',  fg: 'var(--text-primary)',   bd: 'var(--border-default)' },
      hover:   { bg: 'var(--bg-sunken)',   fg: 'var(--text-primary)',   bd: 'var(--border-strong)' },
      pressed: { bg: '#E5E2D6',            fg: 'var(--text-primary)',   bd: 'var(--border-strong)' },
      disabled:{ bg: 'var(--bg-surface)',  fg: 'var(--text-disabled)',  bd: 'var(--border-subtle)' },
    },
    ghost: {
      rest:    { bg: 'transparent',        fg: 'var(--text-primary)',   bd: 'transparent' },
      hover:   { bg: 'var(--bg-sunken)',   fg: 'var(--text-primary)',   bd: 'transparent' },
      pressed: { bg: '#E5E2D6',            fg: 'var(--text-primary)',   bd: 'transparent' },
      disabled:{ bg: 'transparent',        fg: 'var(--text-disabled)',  bd: 'transparent' },
    },
    destructive: {
      rest:    { bg: 'var(--danger)',     fg: '#FAFAF7',  bd: 'var(--danger)' },
      hover:   { bg: '#962918',           fg: '#FAFAF7',  bd: '#962918' },
      pressed: { bg: '#7A1F12',           fg: '#FAFAF7',  bd: '#7A1F12' },
      disabled:{ bg: '#E5C9C2',           fg: '#FAFAF7',  bd: '#E5C9C2' },
    },
  };
  const c = styles[variant][state];
  const focusShadow = state === 'focus'
    ? '0 0 0 2px var(--bg-canvas), 0 0 0 4px var(--accent)' : 'none';
  return (
    <button style={{
      height: sz.h, padding: `0 ${sz.px}px`, fontSize: sz.font, gap: sz.gap,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
      borderRadius: sz.radius, fontWeight: 500, cursor: state === 'disabled' ? 'not-allowed' : 'default',
      letterSpacing: '-0.005em', boxShadow: focusShadow, whiteSpace: 'nowrap',
    }}>
      {icon && <span style={{ display: 'inline-flex' }}>{typeof icon === 'string' ? <Icon name={icon} size={sz.font} /> : icon}</span>}
      {children}
      {iconRight && <span style={{ display: 'inline-flex' }}>{typeof iconRight === 'string' ? <Icon name={iconRight} size={sz.font} /> : iconRight}</span>}
    </button>
  );
}

/* ─────────────────────────────────────────────────────────────
   Inputs
───────────────────────────────────────────────────────────── */
function Field({ label, helper, error, state = 'default', children, required, hint }) {
  const errored = state === 'error';
  return (
    <label style={{ display: 'block', minWidth: 0 }}>
      <div style={{
        fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)',
        marginBottom: 6, letterSpacing: '0.005em',
        display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8,
      }}>
        <span style={{ whiteSpace: 'nowrap' }}>
          {label}{required && <span style={{ color: 'var(--danger)' }}>*</span>}
        </span>
        {hint && <span style={{
          color: 'var(--text-tertiary)', fontSize: 11,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          minWidth: 0,
        }}>{hint}</span>}
      </div>
      {children}
      {(helper || error) && (
        <div style={{
          fontSize: 12, marginTop: 6,
          color: errored ? 'var(--danger)' : 'var(--text-tertiary)',
        }}>{errored ? error : helper}</div>
      )}
    </label>
  );
}

function inputBase(state) {
  const base = {
    height: 40, width: '100%', borderRadius: 6, padding: '0 12px',
    fontSize: 14, fontFamily: 'inherit',
    background: 'var(--bg-surface)', color: 'var(--text-primary)',
    border: '1px solid var(--border-default)', outline: 'none',
    transition: 'border-color .15s ease, box-shadow .15s ease',
    letterSpacing: '-0.005em',
  };
  if (state === 'focus') return {
    ...base, borderColor: 'var(--accent)',
    boxShadow: '0 0 0 3px rgba(15,122,78,.16)',
  };
  if (state === 'error') return {
    ...base, borderColor: 'var(--danger)',
    boxShadow: '0 0 0 3px rgba(181,49,30,.14)',
  };
  if (state === 'disabled') return {
    ...base, background: 'var(--bg-sunken)', color: 'var(--text-disabled)',
    borderColor: 'var(--border-subtle)', cursor: 'not-allowed',
  };
  return base;
}

function Input({ state = 'default', value, placeholder, prefix, suffix, icon }) {
  const s = inputBase(state);
  return (
    <div style={{ position: 'relative', ...s, display: 'flex', alignItems: 'center', padding: 0 }}>
      {prefix && <span style={{
        paddingLeft: 12, color: 'var(--text-tertiary)', fontSize: 14,
        borderRight: '1px solid var(--border-subtle)', height: '70%',
        display: 'inline-flex', alignItems: 'center', paddingRight: 10, marginRight: 4,
      }}>{prefix}</span>}
      {icon && <span style={{ paddingLeft: 12, color: 'var(--text-tertiary)', display: 'inline-flex' }}>{icon}</span>}
      <input
        readOnly value={value ?? ''} placeholder={placeholder}
        style={{
          flex: 1, background: 'transparent', border: 0, outline: 'none',
          padding: prefix ? '0 12px 0 4px' : '0 12px',
          fontFamily: 'inherit', fontSize: 14, color: 'inherit',
          fontVariantNumeric: 'tabular-nums',
        }}
      />
      {suffix && <span style={{ paddingRight: 12, color: 'var(--text-tertiary)', fontSize: 13 }}>{suffix}</span>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Status pill
───────────────────────────────────────────────────────────── */
const pillStyles = {
  draft:      { bg: 'var(--info-subtle)',    fg: 'var(--info-text)' },
  finalized:  { bg: 'var(--accent-subtle)',  fg: 'var(--accent)' },
  paid:       { bg: 'var(--success-subtle)', fg: 'var(--success-text)' },
  overdue:    { bg: 'var(--danger-subtle)',  fg: 'var(--danger-text)' },
  karigar:    { bg: 'var(--warning-subtle)', fg: 'var(--warning-text)' },
  scrap:      { bg: '#EAE7DD',                fg: '#605D52' },
  due:        { bg: 'var(--info-subtle)',    fg: 'var(--info-text)' },
  info:       { bg: 'var(--info-subtle)',    fg: 'var(--info-text)' },
  consumed:   { bg: 'var(--accent-subtle)',  fg: 'var(--accent)' },
  partial:    { bg: 'var(--warning-subtle)', fg: 'var(--warning-text)' },
  pending:    { bg: '#EAE7DD',                fg: '#605D52' },
  on_track:   { bg: 'var(--info-subtle)',    fg: 'var(--info-text)' },
};
function Pill({ kind, children }) {
  const c = pillStyles[kind] || pillStyles.draft;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      height: 22, padding: '0 8px', borderRadius: 4,
      background: c.bg, color: c.fg,
      fontSize: 11, fontWeight: 600, letterSpacing: '0.04em',
      textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

/* ─────────────────────────────────────────────────────────────
   Card variants
───────────────────────────────────────────────────────────── */
function Card({ pad = 16, children, footer, action, title, sub }) {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column',
    }}>
      {(title || action) && (
        <div style={{
          padding: `${pad - 4}px ${pad}px`,
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            {title && <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>}
            {sub && <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{sub}</div>}
          </div>
          {action}
        </div>
      )}
      <div style={{ padding: pad, flex: 1 }}>{children}</div>
      {footer && (
        <div style={{
          padding: `10px ${pad}px`,
          borderTop: '1px solid var(--border-subtle)',
          background: 'var(--bg-sunken)',
          fontSize: 12, color: 'var(--text-secondary)',
          display: 'flex', justifyContent: 'space-between',
        }}>{footer}</div>
      )}
    </div>
  );
}

/* KPI: number is the hero. */
function KPICard({ label, value, delta, deltaKind = 'positive', icon, sparkData }) {
  const deltaColor = deltaKind === 'positive' ? 'var(--data-positive)'
                   : deltaKind === 'negative' ? 'var(--data-negative)'
                   : 'var(--data-neutral)';
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 16, position: 'relative',
      display: 'flex', flexDirection: 'column', gap: 6, minHeight: 140,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <span style={{
          fontSize: 12, color: 'var(--text-secondary)',
          fontWeight: 500, letterSpacing: '0.005em',
          lineHeight: 1.35, flex: 1, minWidth: 0,
        }}>{label}</span>
        {icon && <span style={{ color: 'var(--text-tertiary)', display: 'inline-flex', flexShrink: 0 }}>{icon}</span>}
      </div>
      <div className="num" style={{
        fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em',
        color: 'var(--text-primary)', lineHeight: 1.15,
        marginTop: 4,
      }}>{value}</div>
      {delta && (
        <div style={{ fontSize: 12, color: deltaColor, fontWeight: 500 }}>
          <span className="num">{delta}</span>
        </div>
      )}
      {sparkData && <Sparkline data={sparkData} />}
    </div>
  );
}

function Sparkline({ data, w = 240, h = 28, color = 'var(--text-tertiary)' }) {
  const max = Math.max(...data), min = Math.min(...data);
  const range = max - min || 1;
  const stepX = w / (data.length - 1);
  const pts = data.map((v, i) => `${i * stepX},${h - ((v - min) / range) * h}`).join(' ');
  return (
    <svg width={w} height={h} style={{ marginTop: 'auto' }} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.25" />
    </svg>
  );
}

/* ─────────────────────────────────────────────────────────────
   Tiny lucide-style inline icons. 1.5px stroke.
───────────────────────────────────────────────────────────── */
function Icon({ name, size = 16, color = 'currentColor' }) {
  const props = {
    width: size, height: size, viewBox: '0 0 24 24',
    fill: 'none', stroke: color, strokeWidth: 1.5,
    strokeLinecap: 'round', strokeLinejoin: 'round',
  };
  switch (name) {
    case 'plus': return <svg {...props}><path d="M12 5v14M5 12h14"/></svg>;
    case 'search': return <svg {...props}><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>;
    case 'arrow-right': return <svg {...props}><path d="M5 12h14M13 6l6 6-6 6"/></svg>;
    case 'arrow-up': return <svg {...props}><path d="M12 19V5M6 11l6-6 6 6"/></svg>;
    case 'arrow-down': return <svg {...props}><path d="M12 5v14M6 13l6 6 6-6"/></svg>;
    case 'check': return <svg {...props}><path d="M5 12l5 5L20 7"/></svg>;
    case 'check-circle': return <svg {...props}><circle cx="12" cy="12" r="9"/><path d="m9 12 2 2 4-4"/></svg>;
    case 'alert': return <svg {...props}><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/></svg>;
    case 'x-circle': return <svg {...props}><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/></svg>;
    case 'info': return <svg {...props}><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg>;
    case 'x': return <svg {...props}><path d="M18 6 6 18M6 6l12 12"/></svg>;
    case 'more': return <svg {...props}><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>;
    case 'chevron-down': return <svg {...props}><path d="m6 9 6 6 6-6"/></svg>;
    case 'chevron-right': return <svg {...props}><path d="m9 18 6-6-6-6"/></svg>;
    case 'calendar': return <svg {...props}><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>;
    case 'inbox': return <svg {...props}><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/></svg>;
    case 'rotate': return <svg {...props}><path d="M3 12a9 9 0 1 0 9-9"/><path d="M3 4v5h5"/></svg>;
    case 'trend-up': return <svg {...props}><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>;
    case 'box': return <svg {...props}><path d="M21 8v13H3V8M1 3h22v5H1z"/><path d="M10 12h4"/></svg>;
    case 'wallet': return <svg {...props}><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/></svg>;
    case 'users': return <svg {...props}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>;
    case 'file': return <svg {...props}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>;
    case 'package': return <svg {...props}><path d="m7.5 4.27 9 5.15"/><path d="M21 8 12 13 3 8"/><path d="M21 8v8a2 2 0 0 1-1 1.73l-7 4a2 2 0 0 1-2 0l-7-4A2 2 0 0 1 3 16V8a2 2 0 0 1 1-1.73l7-4a2 2 0 0 1 2 0l7 4A2 2 0 0 1 21 8Z"/><path d="M12 22V13"/></svg>;
    case 'corner-down': return <svg {...props}><polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/></svg>;
    case 'lock': return <svg {...props}><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>;
    case 'mail': return <svg {...props}><rect x="2" y="5" width="20" height="14" rx="2"/><path d="m2 7 10 7 10-7"/></svg>;
    case 'eye': return <svg {...props}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>;
    case 'shield': return <svg {...props}><path d="M12 2 4 6v6c0 5 3.5 9 8 10 4.5-1 8-5 8-10V6l-8-4Z"/></svg>;
    case 'building': return <svg {...props}><rect x="4" y="3" width="16" height="18" rx="1"/><path d="M9 7h.01M15 7h.01M9 11h.01M15 11h.01M9 15h.01M15 15h.01M10 21v-3h4v3"/></svg>;
    case 'home': return <svg {...props}><path d="M3 11 12 3l9 8"/><path d="M5 10v10h14V10"/></svg>;
    case 'shopping-bag': return <svg {...props}><path d="M5 7h14l-1 13H6L5 7Z"/><path d="M9 7V5a3 3 0 0 1 6 0v2"/></svg>;
    case 'truck': return <svg {...props}><path d="M2 17V6h12v11"/><path d="M14 9h4l3 4v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>;
    case 'cog': return <svg {...props}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h.1a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>;
    case 'tool': return <svg {...props}><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-2.5 2.5-2.5Z"/></svg>;
    case 'briefcase': return <svg {...props}><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>;
    case 'bar-chart': return <svg {...props}><path d="M3 21h18"/><rect x="6" y="12" width="3" height="7"/><rect x="11" y="7" width="3" height="12"/><rect x="16" y="4" width="3" height="15"/></svg>;
    case 'database': return <svg {...props}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/></svg>;
    case 'menu-more': return <svg {...props}><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></svg>;
    case 'bell': return <svg {...props}><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>;
    case 'upload-cloud': return <svg {...props}><path d="M16 16l-4-4-4 4"/><path d="M12 12v9"/><path d="M20 16.6A5 5 0 0 0 18 7h-1.3A8 8 0 1 0 4 15.3"/><path d="M16 16l-4-4-4 4"/></svg>;
    case 'check-square': return <svg {...props}><path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>;
    case 'spinner': return <svg {...props}><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>;
    case 'help': return <svg {...props}><circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>;
    case 'menu': return <svg {...props}><path d="M3 6h18M3 12h18M3 18h18"/></svg>;
    case 'grid': return <svg {...props}><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>;
    case 'columns': return <svg {...props}><rect x="3" y="3" width="6" height="18" rx="1"/><rect x="11" y="3" width="6" height="18" rx="1"/><rect x="19" y="3" width="2" height="18" rx="1"/></svg>;
    case 'adjust': return <svg {...props}><path d="M4 6h11M4 12h7M4 18h13"/><circle cx="18" cy="6" r="2"/><circle cx="14" cy="12" r="2"/><circle cx="20" cy="18" r="2"/></svg>;
    case 'transfer': return <svg {...props}><path d="M16 3l4 4-4 4M20 7H8"/><path d="M8 21l-4-4 4-4M4 17h12"/></svg>;
    case 'clipboard': return <svg {...props}><rect x="6" y="4" width="12" height="18" rx="2"/><path d="M9 4V3a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1"/><path d="M9 12h6M9 16h4"/></svg>;
    case 'upload': return <svg {...props}><path d="M12 17V3M7 8l5-5 5 5"/><path d="M3 17v3a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-3"/></svg>;
    case 'send': return <svg {...props}><path d="m22 2-11 11"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/></svg>;
    case 'phone': return <svg {...props}><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/></svg>;
    case 'truck': return <svg {...props}><rect x="1" y="6" width="14" height="11" rx="1"/><path d="M15 9h4l3 3v5h-7"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="19" r="2"/></svg>;
    case 'cut': return <svg {...props}><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12"/></svg>;
    case 'image': return <svg {...props}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/></svg>;
    case 'tag': return <svg {...props}><path d="M20.59 13.41 12 22l-9-9V3h10l8.59 8.59a2 2 0 0 1 0 2.82Z"/><circle cx="7.5" cy="7.5" r="1"/></svg>;
    case 'message': return <svg {...props}><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z"/></svg>;
    case 'list-checks': return <svg {...props}><path d="M3 5l2 2 4-4M3 13l2 2 4-4M3 21l2 2 4-4"/><path d="M13 6h8M13 14h8M13 22h8"/></svg>;
    case 'flame': return <svg {...props}><path d="M8.5 14.5A2.5 2.5 0 0 0 11 17c1.4 0 2.5-1.1 2.5-2.5 0-2-2-3-2.5-5 .5 1 4.5 2 4.5 6 0 2.8-2.2 5-5 5s-5-2.2-5-5c0-2.5 2-3 2-5.5 0-1 .5-2 1-2.5.5 2 2 3 2 5Z"/></svg>;
    case 'download': return <svg {...props}><path d="M12 3v14M7 12l5 5 5-5"/><path d="M3 21h18"/></svg>;
    case 'share': return <svg {...props}><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5 8.6 10.5"/></svg>;
    case 'sparkles': return <svg {...props}><path d="m12 3 1.9 4.6L18 9.5l-4.1 1.9L12 16l-1.9-4.6L6 9.5l4.1-1.9z"/><path d="M19 14l1 2.5L22 17l-2 .5L19 20l-1-2.5L16 17l2-.5z"/></svg>;
    default: return null;
  }
}

function FilterChip({ label, active, count, onClick }) {
  return (
    <button onClick={onClick} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px',
      border: `1px solid ${active ? 'var(--accent)' : 'var(--border-default)'}`,
      background: active ? 'var(--accent-subtle)' : 'var(--bg-surface)',
      color: active ? 'var(--accent)' : 'var(--text-secondary)',
      borderRadius: 999, fontSize: 12.5, fontWeight: active ? 600 : 500, cursor: 'pointer',
    }}>
      <span>{label}</span>
      {count != null && <span style={{ opacity: .7, fontSize: 11 }}>{count}</span>}
    </button>
  );
}

Object.assign(window, {
  TaanaMark, Wordmark, SectionHead, Button, Input, Field, Pill,
  Card, KPICard, Sparkline, Icon, FilterChip,
});
