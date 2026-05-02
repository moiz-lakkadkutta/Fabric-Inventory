// phase2-dashboard.jsx — SCR-DASH-001 owner dashboard / daybook.

const { useState: useStateD } = React;

const DASH_DATA = {
  outstanding: { value: '₹12.40L', sub: '67 invoices · 12 overdue', spark: [42,40,44,46,43,41,48,52,49,55,52,58,61,57,63,68,66,72,70,75,79,82,78,84,88,86,92,95,99,103] },
  sales:       { value: '₹8.65L',  sub: 'vs last month +18%',     spark: [12,15,11,18,22,16,24,20,28,26,32,30,38,34,42,38,46,44,52,48,56,52,60,58,66,62,70,68,76,72] },
  lowStock:    { value: '14',      sub: 'across 4 categories',     dot: true },
  cash:        { value: '₹3.20L',  sub: 'across 3 banks + register' },
};

const HOURLY = [
  { h: '10am', v: 0.32, n: 4 }, { h: '11', v: 0.55, n: 7 }, { h: '12pm', v: 0.78, n: 11 },
  { h: '1', v: 0.45, n: 6 }, { h: '2', v: 0.92, n: 14 }, { h: '3', v: 1.00, n: 18 },
  { h: '4', v: 0.84, n: 12 }, { h: '5', v: 0.68, n: 9 }, { h: '6', v: 0.58, n: 8 },
  { h: '7', v: 0.42, n: 6 }, { h: '8', v: 0.28, n: 4 }, { h: '9pm', v: 0.18, n: 3 },
];

const RECENT_INVOICES = [
  { id: 'TI/25-26/000846', cust: 'Khan Sarees Pvt Ltd',     city: 'Mumbai',    date: '27-Apr-2026', amt: '1,80,000.00', status: 'paid' },
  { id: 'TI/25-26/000845', cust: 'Patel Fabrics',           city: 'Surat',     date: '27-Apr-2026', amt: '46,250.00',   status: 'finalized' },
  { id: 'TI/25-26/000844', cust: 'New Era Garments',        city: 'Delhi',     date: '27-Apr-2026', amt: '2,12,400.00', status: 'overdue' },
  { id: 'TI/25-26/000843', cust: 'Manish Creations',        city: 'Mumbai',    date: '26-Apr-2026', amt: '88,400.00',   status: 'finalized' },
  { id: 'CM/25-26/000118', cust: 'Walk-in (Vimal Shah)',    city: 'Surat',     date: '26-Apr-2026', amt: '12,500.00',   status: 'paid' },
  { id: 'TI/25-26/000842', cust: 'Lakhani Textiles',        city: 'Ahmedabad', date: '26-Apr-2026', amt: '3,42,000.00', status: 'overdue' },
  { id: 'TI/25-26/000841', cust: 'Ahmedabad Silk Mills',    city: 'Ahmedabad', date: '25-Apr-2026', amt: '1,24,500.00', status: 'paid' },
  { id: 'EST/25-26/000067', cust: 'Roshan Boutique',        city: 'Mumbai',    date: '25-Apr-2026', amt: '58,200.00',   status: 'draft' },
];

const ACTIONS = [
  { sev: 'danger',  count: 5,  label: 'over credit limit awaiting approval', cta: 'Review' },
  { sev: 'warning', count: 3,  label: 'GRNs pending 3-way match',            cta: 'Match' },
  { sev: 'danger',  count: 2,  label: 'cheques bouncing today',              cta: 'Re-deposit' },
  { sev: 'info',    count: 12, label: 'lots aging > 90 days at karigars',    cta: 'Check' },
];

const TOP_CUSTOMERS = [
  { name: 'Khan Sarees Pvt Ltd', city: 'Mumbai',   amt: '2,42,000', share: 0.28 },
  { name: 'Lakhani Textiles',     city: 'Ahmedabad', amt: '1,86,500', share: 0.22 },
  { name: 'Manish Creations',     city: 'Mumbai',   amt: '1,22,400', share: 0.14 },
  { name: 'Patel Fabrics',        city: 'Surat',    amt: '94,800',   share: 0.11 },
  { name: 'New Era Garments',     city: 'Delhi',    amt: '78,200',   share: 0.09 },
];

/* Sparkline — slate-400, 32 tall, no axis labels */
function Sparkline({ data, w = 200, h = 32, color = '#94908A', emerald }) {
  if (!data || !data.length) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const r = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / r) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const c = emerald ? 'var(--accent)' : color;
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <polyline fill="none" stroke={c} strokeWidth="1.5" points={pts} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* KPI — number hero, monochrome icon top-right, NO coloured circle */
function DashKPI({ label, value, sub, icon, spark, deltaKind, dot, onClick }) {
  return (
    <div style={{
      flex: 1, minWidth: 0,
      background: 'var(--bg-surface)',
      border: '1px solid var(--border-default)',
      borderRadius: 10, padding: 18,
      display: 'flex', flexDirection: 'column', gap: 10,
      cursor: 'default', overflow: 'hidden',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, minWidth: 0 }}>
        <div style={{
          fontSize: 12.5, color: 'var(--text-tertiary)', fontWeight: 500, letterSpacing: '0.005em',
          minWidth: 0, flex: 1,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>{label}</div>
        <Icon name={icon} size={14} color="var(--text-tertiary)" />
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, lineHeight: 1.15 }}>
        <div className="num" style={{ fontSize: 30, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.15 }}>{value}</div>
        {dot && <span style={{ width: 7, height: 7, borderRadius: 999, background: 'var(--danger)', display: 'inline-block', alignSelf: 'center' }} />}
      </div>
      <div style={{
        fontSize: 12,
        color: deltaKind === 'positive' ? 'var(--success-text)' : deltaKind === 'negative' ? 'var(--danger-text)' : 'var(--text-tertiary)',
        display: 'flex', alignItems: 'center', gap: 4,
        lineHeight: 1.4,
      }}>
        {deltaKind && (
          <Icon name={deltaKind === 'positive' ? 'arrow-up' : 'arrow-down'} size={11} color={deltaKind === 'positive' ? 'var(--success)' : 'var(--danger)'} />
        )}
        <span>{sub}</span>
      </div>
      {spark && (
        <div style={{ marginTop: 'auto', paddingTop: 8 }}>
          <Sparkline data={spark} w={260} h={28} />
        </div>
      )}
    </div>
  );
}

function DateRangePill() {
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'stretch',
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, overflow: 'hidden', height: 36,
    }}>
      {['Today', 'Week', 'Month', 'FY', 'Custom'].map((l, i) => (
        <div key={l} style={{
          padding: '0 14px',
          background: l === 'Month' ? 'var(--bg-sunken)' : 'transparent',
          color: l === 'Month' ? 'var(--text-primary)' : 'var(--text-secondary)',
          fontWeight: l === 'Month' ? 600 : 500, fontSize: 13,
          display: 'inline-flex', alignItems: 'center',
          borderLeft: i > 0 ? '1px solid var(--border-default)' : 'none',
        }}>{l}</div>
      ))}
    </div>
  );
}

function HourlyChart({ height = 200 }) {
  const max = Math.max(...HOURLY.map(d => d.v));
  const tooltipIdx = 5; // 3pm spike — peak
  return (
    <div style={{ position: 'relative', padding: '12px 0 4px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height }}>
        {HOURLY.map((b, i) => {
          const isPeak = i === tooltipIdx;
          return (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, position: 'relative' }}>
              {isPeak && (
                <div style={{
                  position: 'absolute', bottom: `calc(${(b.v / max) * 100}% + 24px)`, left: '50%', transform: 'translateX(-50%)',
                  background: 'var(--text-primary)', color: '#FAFAF7',
                  padding: '6px 10px', borderRadius: 6, fontSize: 11, whiteSpace: 'nowrap',
                  boxShadow: 'var(--shadow-2)', zIndex: 2,
                }}>
                  <div className="num" style={{ fontWeight: 600 }}>₹1,42,400</div>
                  <div style={{ opacity: .8 }}>{b.n} orders · 3pm</div>
                </div>
              )}
              <div style={{
                width: '100%', height: `${(b.v / max) * 100}%`,
                background: isPeak ? 'var(--accent-pressed)' : 'var(--accent)',
                borderRadius: '3px 3px 0 0', minHeight: 2,
                opacity: isPeak ? 1 : 0.92,
              }} />
              <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>{b.h}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RecentInvoicesTable() {
  return (
    <div style={{ overflow: 'hidden', borderRadius: 6, border: '1px solid var(--border-subtle)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'var(--bg-sunken)', textAlign: 'left' }}>
            <th style={thStyle}>Invoice #</th>
            <th style={thStyle}>Customer</th>
            <th style={{...thStyle, width: 110}}>Date</th>
            <th style={{...thStyle, textAlign: 'right', width: 130}}>Amount</th>
            <th style={{...thStyle, width: 110}}>Status</th>
          </tr>
        </thead>
        <tbody>
          {RECENT_INVOICES.map((r, i) => (
            <tr key={r.id} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
              <td className="mono" style={tdStyle}>{r.id}</td>
              <td style={tdStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Monogram initials={r.cust.split(' ').map(w => w[0]).slice(0,2).join('')} size={22} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 220 }}>{r.cust}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{r.city}</div>
                  </div>
                </div>
              </td>
              <td className="num" style={{...tdStyle, color: 'var(--text-secondary)', whiteSpace: 'nowrap'}}>{r.date}</td>
              <td className="num" style={{...tdStyle, textAlign: 'right', fontWeight: 500}}>₹{r.amt}</td>
              <td style={tdStyle}><Pill kind={r.status}>{r.status === 'finalized' ? 'Finalized' : r.status === 'paid' ? 'Paid' : r.status === 'overdue' ? 'Overdue' : 'Draft'}</Pill></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const thStyle = { padding: '10px 12px', fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.04em' };
const tdStyle = { padding: '10px 12px', verticalAlign: 'middle' };

function ActionTriage() {
  const sevColor = {
    danger:  { bd: 'var(--danger)',  bg: 'var(--danger-subtle)',  fg: 'var(--danger-text)' },
    warning: { bd: 'var(--warning)', bg: 'var(--warning-subtle)', fg: 'var(--warning-text)' },
    info:    { bd: 'var(--info)',    bg: 'var(--info-subtle)',    fg: 'var(--info-text)' },
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {ACTIONS.map((a, i) => {
        const c = sevColor[a.sev];
        return (
          <div key={i} style={{
            background: c.bg, borderLeft: '3px solid ' + c.bd,
            borderRadius: '6px', padding: '12px 14px',
            display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <div className="num" style={{ fontSize: 22, fontWeight: 700, color: c.fg, minWidth: 32, textAlign: 'right' }}>{a.count}</div>
            <div style={{ flex: 1, fontSize: 13, color: c.fg, lineHeight: 1.4 }}>{a.label}</div>
            <button style={{
              height: 30, padding: '0 12px', borderRadius: 5,
              background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
              color: 'var(--text-primary)', fontWeight: 500, fontSize: 12,
              cursor: 'default',
            }}>{a.cta}</button>
          </div>
        );
      })}
    </div>
  );
}

function TopCustomers() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {TOP_CUSTOMERS.map((c, i) => (
        <div key={c.name} style={{
          display: 'grid', gridTemplateColumns: '28px 1fr 100px',
          gap: 12, alignItems: 'center', padding: '10px 0',
          borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
        }}>
          <Monogram initials={c.name.split(' ').map(w => w[0]).slice(0,2).join('')} size={28} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.name}</div>
            <div style={{ height: 4, background: 'var(--bg-sunken)', borderRadius: 999, marginTop: 6, overflow: 'hidden' }}>
              <div style={{ width: `${c.share * 100}%`, height: '100%', background: 'var(--accent)', borderRadius: 999 }} />
            </div>
          </div>
          <div className="num" style={{ fontSize: 13, fontWeight: 600, textAlign: 'right' }}>₹{c.amt}</div>
        </div>
      ))}
    </div>
  );
}

/* SectionTitle reused */
function SecTitle({ children, action }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 12, minWidth: 0 }}>
      <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0, letterSpacing: '0.005em', flex: 1, minWidth: 0 }}>{children}</h3>
      {action && <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>{action}</span>}
    </div>
  );
}

function DashboardDesktop() {
  return (
    <div style={{ background: 'var(--bg-canvas)', minHeight: 900 }}>
      {/* Page header */}
      <div style={{
        padding: '20px 32px', borderBottom: '1px solid var(--border-default)',
        background: 'var(--bg-surface)',
        display: 'flex', alignItems: 'flex-end', gap: 16,
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 4 }}>Rajesh Textiles, Surat · FY 2025–26</div>
          <h1 style={{ fontSize: 24, fontWeight: 600, margin: 0, letterSpacing: '-0.012em' }}>Daybook</h1>
        </div>
        <DateRangePill />
        <button style={iconBtn}><Icon name="refresh" size={14} color="var(--text-secondary)" /></button>
        <Button variant="secondary" size="md" icon={<Icon name="download" size={14} color="currentColor" />}>Export PDF</Button>
      </div>

      <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 24 }}>
        {/* KPI strip */}
        <div style={{ display: 'flex', gap: 24 }}>
          <DashKPI label="Outstanding receivables" value={DASH_DATA.outstanding.value} sub={DASH_DATA.outstanding.sub} icon="wallet"  spark={DASH_DATA.outstanding.spark} />
          <DashKPI label="This month sales"        value={DASH_DATA.sales.value}       sub={DASH_DATA.sales.sub}       icon="trending-up" spark={DASH_DATA.sales.spark} deltaKind="positive" />
          <DashKPI label="Low stock items"         value={DASH_DATA.lowStock.value}    sub={DASH_DATA.lowStock.sub}    icon="package" dot />
          <DashKPI label="Cash on hand"            value={DASH_DATA.cash.value}        sub={DASH_DATA.cash.sub}        icon="rupee" />
        </div>

        {/* 60/40 area */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 24 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 20 }}>
              <SecTitle action="View hourly →">Sales today</SecTitle>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
                <span className="num" style={{ fontSize: 22, fontWeight: 600 }}>₹4,82,300</span>
                <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>112 orders · peak at 3pm</span>
              </div>
              <HourlyChart />
            </div>
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 20 }}>
              <SecTitle action="See all →">Recent invoices</SecTitle>
              <RecentInvoicesTable />
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 20 }}>
              <SecTitle>Action required</SecTitle>
              <ActionTriage />
            </div>
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 20 }}>
              <SecTitle action="View all →">Top customers · this month</SecTitle>
              <TopCustomers />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

const iconBtn = {
  width: 36, height: 36, borderRadius: 6, border: '1px solid var(--border-default)',
  background: 'var(--bg-surface)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  cursor: 'default',
};

function DashboardTablet() {
  return (
    <div style={{ background: 'var(--bg-canvas)', minHeight: 900 }}>
      <div style={{
        padding: '16px 24px', borderBottom: '1px solid var(--border-default)',
        background: 'var(--bg-surface)', display: 'flex', flexDirection: 'column', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Rajesh Textiles, Surat · FY 2025–26</div>
            <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Daybook</h1>
          </div>
          <Button variant="secondary" size="md">Export PDF</Button>
        </div>
        <DateRangePill />
      </div>
      <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <DashKPI label="Outstanding receivables" value={DASH_DATA.outstanding.value} sub={DASH_DATA.outstanding.sub} icon="wallet" spark={DASH_DATA.outstanding.spark} />
          <DashKPI label="This month sales" value={DASH_DATA.sales.value} sub={DASH_DATA.sales.sub} icon="trending-up" spark={DASH_DATA.sales.spark} deltaKind="positive" />
          <DashKPI label="Low stock items" value={DASH_DATA.lowStock.value} sub={DASH_DATA.lowStock.sub} icon="package" dot />
          <DashKPI label="Cash on hand" value={DASH_DATA.cash.value} sub={DASH_DATA.cash.sub} icon="rupee" />
        </div>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 18 }}>
          <SecTitle>Sales today · ₹4,82,300</SecTitle>
          <HourlyChart height={160} />
        </div>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 18 }}>
          <SecTitle>Action required</SecTitle>
          <ActionTriage />
        </div>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 18 }}>
          <SecTitle>Recent invoices</SecTitle>
          <RecentInvoicesTable />
        </div>
      </div>
    </div>
  );
}

function DashboardMobile() {
  return (
    <div style={{ background: 'var(--bg-canvas)', minHeight: 700 }}>
      <div style={{ padding: 16, borderBottom: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Rajesh Textiles · FY 25-26</div>
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>Daybook</h1>
      </div>
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Snap-scroll KPI carousel */}
        <div style={{ position: 'relative' }}>
          <div style={{ display: 'flex', gap: 12, overflowX: 'auto', scrollSnapType: 'x mandatory', paddingBottom: 4, margin: '0 -16px', padding: '0 16px 4px' }}>
            {[
              { l: 'Receivables', v: '₹12.40L', s: '67 inv · 12 overdue', i: 'wallet', sk: DASH_DATA.outstanding.spark },
              { l: 'This month', v: '₹8.65L', s: '+18% MoM', i: 'trending-up', sk: DASH_DATA.sales.spark, k: 'positive' },
              { l: 'Low stock', v: '14', s: '4 categories', i: 'package', dot: true },
              { l: 'Cash', v: '₹3.20L', s: '3 banks + register', i: 'rupee' },
            ].map((c, i) => (
              <div key={i} style={{ flex: '0 0 240px', scrollSnapAlign: 'start' }}>
                <DashKPI label={c.l} value={c.v} sub={c.s} icon={c.i} spark={c.sk} deltaKind={c.k} dot={c.dot} />
              </div>
            ))}
          </div>
        </div>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 14 }}>
          <SecTitle>Sales today</SecTitle>
          <HourlyChart height={120} />
        </div>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 14 }}>
          <SecTitle>Action required</SecTitle>
          <ActionTriage />
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DashboardDesktop, DashboardTablet, DashboardMobile, RECENT_INVOICES, Sparkline });
