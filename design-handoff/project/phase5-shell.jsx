// phase5-shell.jsx — shared Reports shell + Indian-format helpers + report-switcher tabs.

/* ─────────────────────────────────────────────────────────────
   Indian number grouping (lakhs / crores). Always 2 decimals.
   inr(123456.78)        → "1,23,456.78"
   inrSign(-123456.78)   → "−1,23,456.78"  (uses real minus glyph)
   inrShort(48200000)    → "₹4.82 Cr"
───────────────────────────────────────────────────────────── */
function inr(n, opts = {}) {
  const { decimals = 2, signed = false } = opts;
  if (n == null || n === '' || isNaN(n)) return '—';
  const abs = Math.abs(n);
  const fixed = abs.toFixed(decimals);
  // Indian grouping: last 3 digits, then groups of 2.
  const [intPart, decPart] = fixed.split('.');
  const lastThree = intPart.slice(-3);
  const rest = intPart.slice(0, -3);
  const groupedRest = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  const grouped = rest ? `${groupedRest},${lastThree}` : lastThree;
  const sign = n < 0 ? '−' : (signed && n > 0 ? '+' : '');
  return `${sign}${grouped}${decPart ? '.' + decPart : ''}`;
}
function inrShort(n) {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  const sign = n < 0 ? '−' : '';
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
  if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(1)} K`;
  return `${sign}₹${abs.toFixed(0)}`;
}

/* ─────────────────────────────────────────────────────────────
   Toast — fired on Export / Print / Email actions in click-dummy.
   Brief slide-in at bottom-right. Auto-dismisses.
───────────────────────────────────────────────────────────── */
const ToastCtx = React.createContext(() => {});
function ToastHost({ children }) {
  const [toasts, setToasts] = React.useState([]);
  const fire = (msg, kind = 'info') => {
    const id = Date.now() + Math.random();
    setToasts(t => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 2800);
  };
  return (
    <ToastCtx.Provider value={fire}>
      {children}
      <div style={{
        position: 'absolute', right: 24, bottom: 24, zIndex: 50,
        display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: 'none',
      }}>
        {toasts.map(t => (
          <div key={t.id} style={{
            background: 'var(--text-primary)', color: 'var(--text-inverse)',
            padding: '10px 14px', borderRadius: 6, fontSize: 12.5,
            boxShadow: 'var(--shadow-3)', minWidth: 220, display: 'flex', alignItems: 'center', gap: 10,
            animation: 'rpt-toast 0.18s ease-out',
          }}>
            <Icon name={t.kind === 'success' ? 'check-circle' : 'download'} size={14} color="var(--accent-subtle)" />
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
function useToast() { return React.useContext(ToastCtx); }

/* ─────────────────────────────────────────────────────────────
   ReportShell — top bar + sidebar (Reports active) + page header.
   Slot in any report body via {children}.
───────────────────────────────────────────────────────────── */

const REPORT_TABS = [
  { id: 'pnl',   label: 'Profit & Loss' },
  { id: 'tb',    label: 'Trial Balance' },
  { id: 'gstr1', label: 'GSTR-1 Prep' },
  { id: 'stock', label: 'Stock Valuation' },
  { id: 'day',   label: 'Day Book' },
];

function ReportTabs({ active }) {
  return (
    <div style={{
      display: 'flex', gap: 4, padding: '0 32px',
      background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-default)',
    }}>
      {REPORT_TABS.map(t => {
        const a = t.id === active;
        return (
          <div key={t.id} style={{
            padding: '10px 14px', position: 'relative',
            fontSize: 13, fontWeight: a ? 600 : 500,
            color: a ? 'var(--text-primary)' : 'var(--text-secondary)',
            cursor: 'default',
          }}>
            {t.label}
            {a && <span style={{
              position: 'absolute', left: 14, right: 14, bottom: -1, height: 2,
              background: 'var(--accent)', borderRadius: '2px 2px 0 0',
            }} />}
          </div>
        );
      })}
      <div style={{ flex: 1 }}></div>
      <div style={{ alignSelf: 'center', fontSize: 11, color: 'var(--text-tertiary)' }}>
        Showing for <strong style={{ color: 'var(--text-secondary)' }}>Khan Textiles Pvt Ltd</strong> · Surat
      </div>
    </div>
  );
}

function ReportPageHeader({ title, period, comparePeriod, onExportPdf, onExportXl, onPrint, filters, periodLocked }) {
  const fire = useToast();
  return (
    <>
      <div style={{
        padding: '20px 32px 16px', background: 'var(--bg-surface)',
        borderBottom: filters ? 'none' : '1px solid var(--border-default)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.012em' }}>{title}</h1>
        </div>
        <PeriodPill period={period} locked={periodLocked} />
        <ComparePill label={comparePeriod} />
        <div style={{ width: 1, height: 24, background: 'var(--border-default)', margin: '0 4px' }}></div>
        <span onClick={() => fire('Saved to Downloads · ' + title + '.pdf', 'success')} style={{ cursor: 'pointer' }}>
          <Button variant="secondary" size="sm" icon="download">Export PDF</Button>
        </span>
        <span onClick={() => fire('Saved to Downloads · ' + title + '.xlsx', 'success')} style={{ cursor: 'pointer' }}>
          <Button variant="secondary" size="sm" icon="download">Export Excel</Button>
        </span>
        <span onClick={() => fire('Sent to printer', 'success')} style={{ cursor: 'pointer' }}>
          <Button variant="ghost" size="sm" icon="file">Print</Button>
        </span>
      </div>
      {filters && (
        <div style={{
          padding: '10px 32px', background: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border-default)',
          display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        }}>{filters}</div>
      )}
    </>
  );
}

function PeriodPill({ period, locked }) {
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 8, height: 32, padding: '0 12px',
      background: 'var(--bg-sunken)', border: '1px solid var(--border-default)',
      borderRadius: 999, fontSize: 12.5, fontWeight: 500,
    }}>
      <Icon name="calendar" size={14} color="var(--text-secondary)" />
      <span>{period}</span>
      {locked
        ? <Icon name="lock" size={12} color="var(--text-tertiary)" />
        : <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />}
    </div>
  );
}

function ComparePill({ label }) {
  if (!label) return null;
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 8, height: 32, padding: '0 10px 0 8px',
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 6, fontSize: 12, color: 'var(--text-secondary)',
    }}>
      <span style={{
        width: 16, height: 16, borderRadius: 3, background: 'var(--accent-subtle)',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Icon name="check" size={11} color="var(--accent)" />
      </span>
      <span>Compare: <strong style={{ color: 'var(--text-primary)' }}>{label}</strong></span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   ReportShell — wraps a report body in topbar + sidebar.
   Body gets full width of the work area minus sidebar.
───────────────────────────────────────────────────────────── */
function ReportShell({ active, children }) {
  return (
    <ToastHost>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)', position: 'relative' }}>
        <TopBar device="desktop" breadcrumb={['Reports', REPORT_TABS.find(t => t.id === active)?.label]} />
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          <Sidebar active="rep" activeSub={null} />
          <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            <ReportTabs active={active} />
            <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>{children}</div>
          </div>
        </div>
      </div>
    </ToastHost>
  );
}

/* ─────────────────────────────────────────────────────────────
   Variance arrow — for P&L. Direction is meaningful.
   For revenue rows: up=positive (good), down=negative (bad).
   For expense rows: up=negative (bad), down=positive (good).
   Pass kind: 'revenue' | 'expense' | 'neutral'
───────────────────────────────────────────────────────────── */
function VarianceArrow({ delta, pct, kind = 'revenue' }) {
  if (delta === 0 || delta == null) {
    return <span style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>—</span>;
  }
  const up = delta > 0;
  const isPositive = (kind === 'revenue' && up) || (kind === 'expense' && !up);
  const color = isPositive ? 'var(--data-positive)' : kind === 'neutral' ? 'var(--data-neutral)' : 'var(--data-negative)';
  return (
    <span className="num" style={{
      display: 'inline-flex', alignItems: 'center', gap: 3,
      color, fontWeight: 600, fontSize: 11.5,
    }}>
      <span style={{ fontSize: 10 }}>{up ? '▲' : '▼'}</span>
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

/* ─────────────────────────────────────────────────────────────
   Skeleton row — shimmer-y placeholder for loading states.
───────────────────────────────────────────────────────────── */
function SkeletonBar({ w = '100%', h = 12, dark = false }) {
  return (
    <span style={{
      display: 'inline-block', width: w, height: h,
      borderRadius: 3, background: dark ? '#DDDAD0' : '#E8E5DA',
      animation: 'rpt-shimmer 1.4s ease-in-out infinite',
      verticalAlign: 'middle',
    }} />
  );
}

/* ─────────────────────────────────────────────────────────────
   Stacked bar — used for P&L Revenue/Expense breakdown.
   data: [{ label, value, color }]
───────────────────────────────────────────────────────────── */
function StackedBar({ data, total, height = 28 }) {
  const sum = total ?? data.reduce((s, d) => s + d.value, 0);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{
        display: 'flex', height, borderRadius: 4, overflow: 'hidden',
        background: 'var(--bg-sunken)',
      }}>
        {data.map((d, i) => (
          <div key={d.label} style={{
            width: `${(d.value / sum) * 100}%`,
            background: d.color,
            borderRight: i < data.length - 1 ? '1px solid var(--bg-surface)' : 'none',
          }} />
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px', fontSize: 11.5 }}>
        {data.map(d => (
          <div key={d.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: d.color, flexShrink: 0 }}></span>
            <span style={{ color: 'var(--text-secondary)' }}>{d.label}</span>
            <span className="num" style={{ color: 'var(--text-primary)', fontWeight: 500 }}>₹{inr(d.value, { decimals: 0 })}</span>
            <span style={{ color: 'var(--text-tertiary)', fontSize: 10.5 }}>{((d.value / sum) * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* shimmer keyframes */
if (typeof document !== 'undefined' && !document.getElementById('rpt-keyframes')) {
  const s = document.createElement('style');
  s.id = 'rpt-keyframes';
  s.textContent = `
    @keyframes rpt-shimmer {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.55; }
    }
    @keyframes rpt-toast {
      from { transform: translateY(8px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
    .rpt-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .rpt-th { font-size: 10.5px; font-weight: 600; color: var(--text-tertiary);
      letter-spacing: 0.06em; text-transform: uppercase;
      padding: 10px 14px; text-align: left; white-space: nowrap;
      border-bottom: 1px solid var(--border-default); background: var(--bg-sunken); }
    .rpt-td { padding: 9px 14px; border-bottom: 1px solid var(--border-subtle); }
    .rpt-num { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; text-align: right; }
    .rpt-row-hover:hover { background: var(--bg-sunken); cursor: default; }
  `;
  document.head.appendChild(s);
}

Object.assign(window, {
  inr, inrShort,
  ToastHost, useToast,
  ReportShell, ReportPageHeader, ReportTabs,
  PeriodPill, ComparePill,
  VarianceArrow, SkeletonBar, StackedBar,
});
