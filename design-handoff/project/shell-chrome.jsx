// shell-chrome.jsx — Taana persistent app shell.
// TopBar, Sidebar (240/64), BottomNav, FirmSwitcher popover, AuthFrame.

const { useState: useStateSh } = React;

const FIRMS = [
  { id: 'rt', name: 'Rajesh Textiles, Surat',  gstin: '24ABCDE1234F1Z5', state: 'Gujarat',     role: 'Owner',       last: '2m ago',  isCurrent: true,  nonGst: false },
  { id: 'kt', name: 'Khan Trading Co., Mumbai', gstin: '27FGHIJ5678K2L9', state: 'Maharashtra', role: 'Accountant',  last: 'Yesterday', isCurrent: false, nonGst: false },
  { id: 'as', name: 'Ahmedabad Silk Mills',    gstin: null,              state: 'Gujarat',     role: 'Salesperson', last: '4 days ago', isCurrent: false, nonGst: true  },
];

const NAV = [
  { id: 'home',     icon: 'home',          label: 'Home',          sub: null },
  { id: 'sales',    icon: 'shopping-bag',  label: 'Sales',         sub: ['Invoices', 'Quotes', 'Sales orders', 'Delivery challans', 'Returns', 'Credit control'] },
  { id: 'purchase', icon: 'truck',         label: 'Purchase',      sub: null },
  { id: 'invent',   icon: 'package',       label: 'Inventory',     sub: null },
  { id: 'mfg',      icon: 'cog',           label: 'Manufacturing', sub: null },
  { id: 'jw',       icon: 'tool',          label: 'Job work',      sub: null },
  { id: 'acct',     icon: 'wallet',        label: 'Accounts',      sub: null },
  { id: 'rep',      icon: 'bar-chart',     label: 'Reports',       sub: null },
  { id: 'mast',     icon: 'database',      label: 'Masters',       sub: null },
  { id: 'admin',    icon: 'shield',        label: 'Admin',         sub: null },
];

/* ── Monogram chip — used for user avatar + party initials ── */
function Monogram({ initials, size = 28, tone = 'neutral' }) {
  const tones = {
    neutral: { bg: '#E5E2D6', fg: '#4A4840' },
    accent:  { bg: '#D7E9DF', fg: '#0A4A2B' },
    info:    { bg: '#DEE3EA', fg: '#283038' },
  };
  const c = tones[tone] || tones.neutral;
  return (
    <span style={{
      width: size, height: size, borderRadius: 999,
      background: c.bg, color: c.fg,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.42, fontWeight: 600, letterSpacing: '0.005em',
      flexShrink: 0,
    }}>{initials}</span>
  );
}

/* ── Firm Switcher popover ─────────────────────────────────── */
function FirmSwitcher({ inline = false, mobile = false, open = true }) {
  if (!open) return null;
  const W = mobile ? 'auto' : 380;
  return (
    <div style={{
      width: W, minWidth: mobile ? 0 : 320,
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-default)',
      borderRadius: mobile ? '12px 12px 0 0' : 12,
      boxShadow: 'var(--shadow-3)',
      overflow: 'hidden',
      position: inline ? 'static' : 'absolute',
      top: 50, left: 0, zIndex: 10,
    }}>
      <div style={{ padding: '12px 14px 8px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600 }}>Switch firm</span>
        <span style={{ fontSize: 11, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>FY 2025-26</span>
      </div>
      {/* Search appears at ≥4 firms — we have 3, so it doesn't render. */}
      <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
        {FIRMS.map(f => (
          <div key={f.id} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '12px 14px',
            background: f.isCurrent ? 'var(--accent-subtle)' : 'transparent',
            borderBottom: '1px solid var(--border-subtle)',
            minHeight: 56,
          }}>
            <Monogram initials={f.name.split(' ').map(w => w[0]).slice(0,2).join('')} size={36} tone={f.isCurrent ? 'accent' : 'neutral'} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 13.5, fontWeight: 600, color: 'var(--text-primary)',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>{f.name}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2 }}>
                <span className="mono" style={{
                  fontSize: 11, color: 'var(--text-secondary)',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  maxWidth: '60%',
                }}>{f.gstin || '—'}</span>
                {f.nonGst && <Pill kind="scrap">Non-GST</Pill>}
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)', marginLeft: 'auto', whiteSpace: 'nowrap' }}>{f.last}</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{f.role}</div>
            </div>
            {f.isCurrent && <Icon name="check" size={16} color="var(--accent)" />}
          </div>
        ))}
      </div>
      <div style={{
        padding: '10px 14px', borderTop: '1px solid var(--border-subtle)',
        background: 'var(--bg-sunken)',
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <Icon name="plus" size={14} color="var(--accent)" />
        <span style={{ fontSize: 13, color: 'var(--accent)', fontWeight: 500 }}>Add a firm</span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-tertiary)' }}>Owner only</span>
      </div>
    </div>
  );
}

/* ── Top bar ──────────────────────────────────────────────── */
function TopBar({ device = 'desktop', firmOpen = false, breadcrumb = ['Sales', 'Invoices', 'New'] }) {
  const compact = device === 'mobile';
  const h = compact ? 48 : 56;
  return (
    <div style={{
      height: h, background: 'var(--bg-surface)',
      borderBottom: '1px solid var(--border-default)',
      display: 'flex', alignItems: 'center',
      padding: compact ? '0 12px' : '0 16px',
      gap: compact ? 8 : 14, position: 'relative',
    }}>
      {/* Logo + wordmark */}
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <TaanaMark size={22} color="var(--accent)" />
        {!compact && <span style={{ fontSize: 17, fontWeight: 600, letterSpacing: '-0.02em' }}>taana</span>}
      </div>

      {/* Firm switcher trigger */}
      <button style={{
        display: 'inline-flex', alignItems: 'center', gap: 8,
        height: 36, padding: '0 10px',
        background: firmOpen ? 'var(--bg-sunken)' : 'transparent',
        border: '1px solid ' + (firmOpen ? 'var(--border-strong)' : 'var(--border-default)'),
        borderRadius: 6, cursor: 'default', color: 'var(--text-primary)',
        marginLeft: compact ? 0 : 8, minWidth: 0, maxWidth: compact ? 200 : 320,
      }}>
        <Icon name="building" size={14} color="var(--text-secondary)" />
        <span style={{
          fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap',
          overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0,
        }}>Rajesh Textiles, Surat</span>
        {!compact && (
          <span className="mono" style={{
            fontSize: 11, color: 'var(--text-tertiary)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            maxWidth: 130,
          }}>· 24ABCDE1234F1Z5</span>
        )}
        <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
      </button>

      {/* Breadcrumb (desktop / tablet) */}
      {!compact && (
        <nav style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-tertiary)', fontSize: 13, minWidth: 0 }}>
          {breadcrumb.map((b, i) => (
            <React.Fragment key={b}>
              {i > 0 && <Icon name="chevron-right" size={12} color="var(--text-tertiary)" />}
              <span style={{
                color: i === breadcrumb.length - 1 ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontWeight: i === breadcrumb.length - 1 ? 500 : 400,
                whiteSpace: 'nowrap',
              }}>{b}</span>
            </React.Fragment>
          ))}
        </nav>
      )}

      {/* Right cluster */}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: compact ? 4 : 8 }}>
        {!compact && (
          <button style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            height: 36, padding: '0 10px 0 12px', minWidth: 220,
            background: 'var(--bg-sunken)', border: '1px solid var(--border-default)',
            borderRadius: 6, color: 'var(--text-tertiary)', fontSize: 13, fontFamily: 'inherit',
          }}>
            <Icon name="search" size={14} />
            <span style={{ flex: 1, textAlign: 'left' }}>Search invoices, parties…</span>
            <span className="mono" style={{
              fontSize: 11, padding: '1px 5px', borderRadius: 3,
              background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
              color: 'var(--text-tertiary)',
            }}>⌘K</span>
          </button>
        )}
        {compact && <IconButton name="search" />}
        <IconButton name="bell" badge="3" />
        <button aria-label="User menu" style={{
          width: 36, height: 36, padding: 0, background: 'transparent',
          border: '1px solid var(--border-default)', borderRadius: 999, cursor: 'default',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Monogram initials="ML" size={28} tone="info" />
        </button>
      </div>

      {firmOpen && !compact && (
        <div style={{ position: 'absolute', top: h - 4, left: 178 }}>
          <FirmSwitcher />
        </div>
      )}
    </div>
  );
}

function IconButton({ name, badge }) {
  return (
    <button aria-label={name} style={{
      width: 36, height: 36, padding: 0, background: 'transparent',
      border: '1px solid transparent', borderRadius: 6, cursor: 'default',
      color: 'var(--text-secondary)', position: 'relative',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <Icon name={name} size={16} />
      {badge && (
        <span style={{
          position: 'absolute', top: 6, right: 6,
          minWidth: 16, height: 16, padding: '0 4px',
          borderRadius: 999, background: 'var(--danger)', color: '#fff',
          fontSize: 10, fontWeight: 600, lineHeight: '16px', textAlign: 'center',
          border: '1.5px solid var(--bg-surface)',
        }}>{badge}</span>
      )}
    </button>
  );
}

/* ── Sidebar ──────────────────────────────────────────────── */
function Sidebar({ collapsed = false, active = 'sales', activeSub = 'Invoices' }) {
  const W = collapsed ? 64 : 240;
  return (
    <aside style={{
      width: W, flexShrink: 0,
      background: 'var(--bg-surface)',
      borderRight: '1px solid var(--border-default)',
      display: 'flex', flexDirection: 'column',
      padding: '12px 0', gap: 2,
      transition: 'width .25s ease',
    }}>
      {NAV.map(it => {
        const isActive = it.id === active;
        return (
          <div key={it.id}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10,
              height: 40, padding: collapsed ? '0' : '0 14px 0 12px',
              justifyContent: collapsed ? 'center' : 'flex-start',
              margin: '0 8px', borderRadius: 6,
              background: isActive ? 'var(--accent-subtle)' : 'transparent',
              color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
              fontWeight: isActive ? 600 : 500, fontSize: 13.5,
              position: 'relative', cursor: 'default',
            }}>
              {isActive && (
                <span style={{
                  position: 'absolute', left: -8, top: 6, bottom: 6, width: 2,
                  background: 'var(--accent)', borderRadius: '0 2px 2px 0',
                }} />
              )}
              <Icon name={it.icon} size={16} color={isActive ? 'var(--accent)' : 'var(--text-secondary)'} />
              {!collapsed && <span>{it.label}</span>}
            </div>
            {!collapsed && isActive && it.sub && (
              <div style={{ display: 'flex', flexDirection: 'column', padding: '4px 0 6px 38px' }}>
                {it.sub.map(s => (
                  <div key={s} style={{
                    height: 32, display: 'flex', alignItems: 'center', padding: '0 12px',
                    borderRadius: 4, fontSize: 12.5,
                    color: s === activeSub ? 'var(--text-primary)' : 'var(--text-secondary)',
                    fontWeight: s === activeSub ? 600 : 400,
                    background: s === activeSub ? 'var(--bg-sunken)' : 'transparent',
                  }}>{s}</div>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {!collapsed && (
        <div style={{ marginTop: 'auto', padding: '12px 16px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="help" size={14} color="var(--text-tertiary)" />
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Help & shortcuts</span>
          <span className="mono" style={{ fontSize: 10, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>?</span>
        </div>
      )}
    </aside>
  );
}

/* ── Bottom nav (mobile) ──────────────────────────────────── */
function BottomNav({ active = 'home' }) {
  const items = [
    { id: 'home',   icon: 'home',         label: 'Home' },
    { id: 'sales',  icon: 'shopping-bag', label: 'Sales' },
    { id: 'inv',    icon: 'package',      label: 'Inventory' },
    { id: 'rep',    icon: 'bar-chart',    label: 'Reports' },
    { id: 'more',   icon: 'menu-more',    label: 'More' },
  ];
  return (
    <nav style={{
      height: 56, background: 'var(--bg-surface)',
      borderTop: '1px solid var(--border-default)',
      display: 'flex', alignItems: 'stretch',
    }}>
      {items.map(it => {
        const a = it.id === active;
        return (
          <div key={it.id} style={{
            flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2,
            color: a ? 'var(--accent)' : 'var(--text-secondary)',
          }}>
            <Icon name={it.icon} size={18} color={a ? 'var(--accent)' : 'var(--text-secondary)'} />
            <span style={{ fontSize: 10.5, fontWeight: a ? 600 : 500 }}>{it.label}</span>
          </div>
        );
      })}
    </nav>
  );
}

/* ── Page header pattern ──────────────────────────────────── */
function PageHeader({ title, pill, secondary, primary, sub }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '20px 32px', borderBottom: '1px solid var(--border-default)',
      background: 'var(--bg-surface)',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <h1 style={{ fontSize: 24, fontWeight: 600, margin: 0, letterSpacing: '-0.012em' }}>{title}</h1>
          {pill}
        </div>
        {sub && <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>}
      </div>
      {secondary}
      {primary}
    </div>
  );
}

/* ── Subtle textile weave background SVG (4% opacity) ─────── */
function WeaveBg({ opacity = 0.045 }) {
  // Tiling 24px weave: vertical warps every 6px, two horizontal wefts.
  const id = 'weave-' + Math.random().toString(36).slice(2, 8);
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <defs>
        <pattern id={id} width="24" height="24" patternUnits="userSpaceOnUse">
          <line x1="3"  y1="0" x2="3"  y2="24" stroke="#1A1A17" strokeWidth="1" />
          <line x1="9"  y1="0" x2="9"  y2="24" stroke="#1A1A17" strokeWidth="1" />
          <line x1="15" y1="0" x2="15" y2="24" stroke="#1A1A17" strokeWidth="1" />
          <line x1="21" y1="0" x2="21" y2="24" stroke="#1A1A17" strokeWidth="1" />
          <line x1="0" y1="6"  x2="24" y2="6"  stroke="#1A1A17" strokeWidth="1" />
          <line x1="0" y1="18" x2="24" y2="18" stroke="#1A1A17" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} style={{ opacity }} />
    </svg>
  );
}

function WeaveSurface({ children, height = 520 }) {
  return (
    <div style={{
      position: 'relative', height, overflow: 'hidden',
      background: 'var(--bg-canvas)',
      border: '1px solid var(--border-default)', borderRadius: 8,
    }}>
      <svg
        width="100%" height="100%" aria-hidden="true"
        style={{ position: 'absolute', inset: 0, opacity: 0.04 }}
      >
        <defs>
          <pattern id="taana-weave" width="24" height="24" patternUnits="userSpaceOnUse">
            <line x1="3"  y1="0" x2="3"  y2="24" stroke="#1A1A17" strokeWidth="1" />
            <line x1="9"  y1="0" x2="9"  y2="24" stroke="#1A1A17" strokeWidth="1" />
            <line x1="15" y1="0" x2="15" y2="24" stroke="#1A1A17" strokeWidth="1" />
            <line x1="21" y1="0" x2="21" y2="24" stroke="#1A1A17" strokeWidth="1" />
            <line x1="0" y1="6"  x2="24" y2="6"  stroke="#1A1A17" strokeWidth="1" />
            <line x1="0" y1="18" x2="24" y2="18" stroke="#1A1A17" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#taana-weave)" />
      </svg>
      <div style={{ position: 'relative', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        {children}
      </div>
    </div>
  );
}

Object.assign(window, {
  FirmSwitcher, TopBar, Sidebar, BottomNav, PageHeader,
  WeaveSurface, Monogram, FIRMS, NAV,
});
