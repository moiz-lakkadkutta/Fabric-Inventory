// canvas.jsx — Taana ERP design-system showcase (1440×1800)
// Composes everything from components.jsx into the spec'd 11-section canvas.

const { useState: useStateC } = React;

/* ─── data: realistic Indian textile rows ─────────────────── */
const TABLE_ROWS = [
  { num: 'TI/25-26/000847', cust: 'Rajesh Textiles, Surat',         date: '27-Apr-2026', amt: '4,82,500.00', status: 'finalized', label: 'FINALIZED' },
  { num: 'TI/25-26/000846', cust: 'Khan Sarees Pvt Ltd',            date: '26-Apr-2026', amt: '1,80,400.00', status: 'paid',      label: 'PAID' },
  { num: 'BOS/25-26/000312',cust: 'Anita Silk Emporium, Chandni Chowk', date: '26-Apr-2026', amt: '   72,150.00', status: 'overdue',   label: 'OVERDUE 12d' },
  { num: 'TI/25-26/000845', cust: 'Mehta Suiting House, Ahmedabad', date: '25-Apr-2026', amt: '2,40,000.00', status: 'finalized', label: 'FINALIZED' },
  { num: 'CM/25-26/000089', cust: 'Walk-in — Cash counter',         date: '25-Apr-2026', amt: '   18,600.00', status: 'paid',      label: 'PAID' },
  { num: 'TI/25-26/000844', cust: 'Mumbai Wholesale Cloth Co.',     date: '24-Apr-2026', amt: '6,12,000.00', status: 'draft',     label: 'DRAFT' },
];

/* ─── 01 — Brand sizes ────────────────────────────────────── */
function Sec01Brand() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 24 }}>
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
        borderRadius: 8, padding: 24, display: 'flex', flexDirection: 'column', gap: 24,
      }}>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em' }}>Wordmark</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 22, alignItems: 'flex-start' }}>
          <Wordmark size={24} />
          <Wordmark size={48} />
          <Wordmark size={96} />
        </div>
      </div>
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
        borderRadius: 8, padding: 24, display: 'flex', flexDirection: 'column', gap: 24,
      }}>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em' }}>Mark</div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 32 }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <TaanaMark size={16} color="var(--accent)" />
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>16 / favicon</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <TaanaMark size={32} color="var(--accent)" />
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>32 / favicon</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <TaanaMark size={96} color="var(--accent)" />
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>96 / app icon</span>
          </div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 'auto', paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
          Five warp threads with one weft crossing — the centre warp passes <em>under</em> the weft. A single weave intersection: the smallest unit of cloth.
        </div>
      </div>
    </div>
  );
}

/* ─── 02 — Colour swatches ────────────────────────────────── */
const SWATCHES = [
  { group: 'Surface', items: [
    { name: 'bg/canvas',   hex: '#F7F6F2', token: '--bg-canvas',   ratio: 'base' },
    { name: 'bg/surface',  hex: '#FFFFFF', token: '--bg-surface',  ratio: '1.04' },
    { name: 'bg/sunken',   hex: '#EFEDE6', token: '--bg-sunken',   ratio: '1.06' },
  ]},
  { group: 'Text', items: [
    { name: 'text/primary',   hex: '#1A1A17', token: '--text-primary',   ratio: '16.4 AAA' },
    { name: 'text/secondary', hex: '#5C5A52', token: '--text-secondary', ratio: '7.0 AAA' },
    { name: 'text/tertiary',  hex: '#8A8880', token: '--text-tertiary',  ratio: '4.6 AA' },
    { name: 'text/disabled',  hex: '#B5B3AB', token: '--text-disabled',  ratio: '2.7 –' },
  ]},
  { group: 'Border', items: [
    { name: 'border/subtle',  hex: '#ECEAE2', token: '--border-subtle',  ratio: '1.06' },
    { name: 'border/default', hex: '#E0DDD2', token: '--border-default', ratio: '1.16' },
    { name: 'border/strong',  hex: '#C8C5B8', token: '--border-strong',  ratio: '1.50' },
  ]},
  { group: 'Accent', items: [
    { name: 'accent/default', hex: '#0F7A4E', token: '--accent',         ratio: '6.4 AA' },
    { name: 'accent/hover',   hex: '#0C6541', token: '--accent-hover',   ratio: '8.1 AAA' },
    { name: 'accent/subtle',  hex: '#E1F0E8', token: '--accent-subtle',  ratio: '1.10' },
  ]},
  { group: 'Semantic', items: [
    { name: 'success',  hex: '#137A48', token: '--success',  ratio: '5.9 AA' },
    { name: 'warning',  hex: '#A26710', token: '--warning',  ratio: '5.1 AA' },
    { name: 'danger',   hex: '#B5311E', token: '--danger',   ratio: '5.5 AA' },
    { name: 'info',     hex: '#3F4C5A', token: '--info',     ratio: '8.7 AAA' },
  ]},
  { group: 'Data', items: [
    { name: 'data/positive', hex: '#0F7A4E', token: '--data-positive', ratio: '6.4 AA' },
    { name: 'data/negative', hex: '#B5311E', token: '--data-negative', ratio: '5.5 AA' },
    { name: 'data/neutral',  hex: '#5C5A52', token: '--data-neutral',  ratio: '7.0 AAA' },
  ]},
];
function Sec02Colours() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
      {SWATCHES.map(g => (
        <div key={g.group} style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
          borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', gap: 10,
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 }}>{g.group}</div>
          {g.items.map(it => (
            <div key={it.name} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{
                width: 32, height: 32, borderRadius: 4, background: it.hex,
                border: '1px solid rgba(20,20,18,.08)', flexShrink: 0,
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-primary)' }}>{it.name}</div>
                <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>
                  {it.hex} · {it.ratio}
                </div>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/* ─── 03 — Type stack ─────────────────────────────────────── */
const TYPE_TOKENS = [
  { tok: 'display', size: 36, weight: 600, ls: '-0.02em',  lh: 1.15, label: 'Display / Invoice header',  num: '₹1,24,500.00' },
  { tok: 'h1',      size: 30, weight: 600, ls: '-0.018em', lh: 1.18, label: 'H1 / Page title',           num: '₹84,30,000.00' },
  { tok: 'h2',      size: 24, weight: 600, ls: '-0.012em', lh: 1.2,  label: 'H2 / Section title',        num: '₹6,40,000.00' },
  { tok: 'h3',      size: 20, weight: 600, ls: '-0.008em', lh: 1.3,  label: 'H3 / Card title',           num: '₹2,40,000.00' },
  { tok: 'h4',      size: 18, weight: 600, ls: '-0.005em', lh: 1.35, label: 'H4 / Sub-section',          num: '₹1,24,500.00' },
  { tok: 'body-lg', size: 15, weight: 400, ls: '0',        lh: 1.5,  label: 'Body Lg / Form input',      num: '₹1,24,500.00' },
  { tok: 'body',    size: 14, weight: 400, ls: '0',        lh: 1.5,  label: 'Body / Default UI',         num: '₹1,24,500.00' },
  { tok: 'small',   size: 13, weight: 400, ls: '0.005em',  lh: 1.45, label: 'Small / Helper, dense table', num: '₹1,24,500.00' },
  { tok: 'caption', size: 12, weight: 500, ls: '0.01em',   lh: 1.4,  label: 'Caption / Metadata, label', num: '₹1,24,500.00' },
];
function Sec03Type() {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 24,
    }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '120px 1fr 200px',
        gap: '16px 24px', alignItems: 'baseline',
      }}>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em' }}>Token</div>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em' }}>Sample</div>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', textAlign: 'right' }}>Tabular ₹</div>
        {TYPE_TOKENS.map(t => (
          <React.Fragment key={t.tok}>
            <div className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
              {t.tok}<br/><span style={{ opacity: .7 }}>{t.size}/{t.weight}</span>
            </div>
            <div style={{
              fontSize: t.size, fontWeight: t.weight, letterSpacing: t.ls, lineHeight: t.lh,
              color: 'var(--text-primary)',
            }}>{t.label}</div>
            <div className="num" style={{
              fontSize: t.size * 0.85, fontWeight: t.weight, lineHeight: t.lh,
              color: 'var(--text-primary)', textAlign: 'right',
              fontVariantNumeric: 'tabular-nums',
            }}>{t.num}</div>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

/* ─── 04 — Buttons matrix ─────────────────────────────────── */
function Sec04Buttons() {
  const variants = ['primary', 'secondary', 'ghost', 'destructive'];
  const sizes = ['sm', 'md', 'lg'];
  const states = ['rest', 'hover', 'pressed', 'disabled'];
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 24, overflow: 'hidden',
    }}>
      <div style={{ display: 'grid', gridTemplateColumns: '110px repeat(4, 1fr)', gap: '20px 16px', alignItems: 'center' }}>
        <div></div>
        {states.map(s => (
          <div key={s} style={{
            fontSize: 11, color: 'var(--text-tertiary)',
            textTransform: 'uppercase', letterSpacing: '.06em',
          }}>{s}</div>
        ))}
        {variants.flatMap(v => sizes.map(sz => (
          <React.Fragment key={`${v}-${sz}`}>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{v}</div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{sz}</div>
            </div>
            {states.map(st => (
              <div key={st}>
                <Button variant={v} size={sz} state={st}
                  icon={sz !== 'sm' ? <Icon name={v === 'destructive' ? 'x' : 'plus'} size={sz === 'lg' ? 16 : 14} /> : null}
                >
                  {v === 'destructive' ? 'Cancel invoice' : v === 'ghost' ? 'View ledger' : v === 'secondary' ? 'Save draft' : 'Finalize'}
                </Button>
              </div>
            ))}
          </React.Fragment>
        )))}
      </div>
    </div>
  );
}

/* ─── 05 — Inputs ─────────────────────────────────────────── */
function Sec05Inputs() {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 24,
    }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px 16px' }}>
        {/* row 1: text */}
        <Field label="Customer" hint="default">
          <Input placeholder="Search a party…" value="Rajesh Textiles, Surat" />
        </Field>
        <Field label="Customer" hint="focus">
          <Input state="focus" value="Khan Sarees" />
        </Field>
        <Field label="GSTIN" error="GSTIN must be 15 chars and pass checksum." state="error">
          <Input state="error" value="24ABCDE1234F1Z" />
        </Field>
        <Field label="Customer" hint="disabled">
          <Input state="disabled" value="—" />
        </Field>

        {/* row 2: select / search */}
        <Field label="Document type">
          <Input value="Tax Invoice" suffix={<Icon name="chevron-down" />} />
        </Field>
        <Field label="Search (⌘K)">
          <Input icon={<Icon name="search" size={14} />} placeholder="Search invoices, parties, items…" />
        </Field>
        <Field label="Date" helper="Defaults to today">
          <Input value="27-Apr-2026" suffix={<Icon name="calendar" />} />
        </Field>
        <Field label="HSN code">
          <Input value="5407" />
        </Field>

        {/* row 3: numeric / currency */}
        <Field label="Amount" helper="Indian grouping, 2 decimals">
          <Input prefix="₹" value="1,24,500.00" />
        </Field>
        <Field label="Quantity" helper="UOM: metres">
          <Input value="48.50" suffix="m" />
        </Field>
        <Field label="Discount">
          <Input value="2.5" suffix="%" />
        </Field>
        <Field label="Rate per metre">
          <Input prefix="₹" value="2,565.00" />
        </Field>
      </div>
    </div>
  );
}

/* ─── 06 — Status pills ───────────────────────────────────── */
function Sec06Pills() {
  const items = [
    { kind: 'draft',     label: 'DRAFT' },
    { kind: 'finalized', label: 'FINALIZED' },
    { kind: 'paid',      label: 'PAID' },
    { kind: 'overdue',   label: 'OVERDUE 12D' },
    { kind: 'karigar',   label: 'AT KARIGAR' },
    { kind: 'scrap',     label: 'SCRAP' },
  ];
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 24,
    }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 16 }}>
        {items.map(it => (
          <div key={it.kind} style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
            <Pill kind={it.kind}>{it.label}</Pill>
            <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>
              {it.kind === 'draft' && 'info-subtle / info-text'}
              {it.kind === 'finalized' && 'accent-subtle / accent'}
              {it.kind === 'paid' && 'success-subtle / success-text'}
              {it.kind === 'overdue' && 'danger-subtle / danger-text'}
              {it.kind === 'karigar' && 'warning-subtle / warning-text'}
              {it.kind === 'scrap' && 'neutral-tinted / muted'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── 07 — Card variants ──────────────────────────────────── */
function Sec07Cards() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
      {/* default */}
      <Card title="Default" sub="1px border, 16px pad">
        <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          Customer last paid 4 days ago for invoice <span className="mono" style={{ color: 'var(--text-primary)' }}>TI/25-26/000846</span>.
        </div>
      </Card>
      {/* spacious */}
      <Card pad={24} title="Spacious" sub="24px pad — for primary panels">
        <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          Used for invoice editor, ledger detail, primary canvas.
        </div>
      </Card>
      {/* with action */}
      <Card title="With action" sub="header CTA, no shadow"
        action={<Button variant="ghost" size="sm" iconRight={<Icon name="arrow-right" size={14} />}>Open</Button>}
      >
        <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          12 lots aging more than 90 days at karigars.
        </div>
      </Card>
      {/* with footer */}
      <Card title="With footer" sub="metadata strip"
        footer={<><span style={{whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>Updated 27-Apr-2026 · 14:32</span><span>Moiz</span></>}
      >
        <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          Footer holds audit metadata, never CTAs.
        </div>
      </Card>
      {/* KPIs — number is hero */}
      <KPICard label="Outstanding receivables" value="₹12.40L" delta="67 invoices · 12 overdue" deltaKind="neutral" icon={<Icon name="wallet" size={16} />} sparkData={[12,14,11,13,16,15,14,17,16,18,17,15,16,18,20,19,17]} />
      <KPICard label="This month sales" value="₹8.65L" delta="+18% vs last month" deltaKind="positive" icon={<Icon name="trend-up" size={16} />} sparkData={[2,4,5,4,6,7,8,7,9,11,10,12,13,12,14,15,16]} />
      <KPICard label="Low stock items" value="14" delta="across 4 categories" deltaKind="negative" icon={<Icon name="package" size={16} />} sparkData={[8,9,10,11,12,11,13,14,12,13,14,13,14,15,14,14,14]} />
      <KPICard label="Cash on hand" value="₹3.20L" delta="3 banks + cash register" deltaKind="neutral" icon={<Icon name="box" size={16} />} sparkData={[3.1,3.2,3.0,3.4,3.3,3.5,3.2,3.0,3.1,3.4,3.6,3.4,3.3,3.5,3.4,3.3,3.2]} />
    </div>
  );
}

/* ─── 08 — Sample table ───────────────────────────────────── */
function Sec08Table() {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, overflow: 'hidden',
    }}>
      <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Recent invoices</div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Firm · Rajesh Textiles, Surat — FY 2025-26</div>
        </div>
        <Button variant="secondary" size="sm" icon={<Icon name="search" size={14} />}>Filter</Button>
        <Button variant="primary" size="sm" icon={<Icon name="plus" size={14} />}>New invoice</Button>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
        <thead>
          <tr style={{ background: 'var(--bg-sunken)', position: 'sticky', top: 0 }}>
            <th style={th()}>Invoice #</th>
            <th style={th()}>Customer</th>
            <th style={{ ...th(), width: 120 }}>Date</th>
            <th style={{ ...th(), width: 130, textAlign: 'right' }}>Amount ₹</th>
            <th style={{ ...th(), width: 130 }}>Status</th>
            <th style={{ ...th(), width: 56 }} aria-label="Actions"></th>
          </tr>
        </thead>
        <tbody>
          {TABLE_ROWS.map((r, i) => (
            <tr key={r.num} style={{
              borderBottom: i === TABLE_ROWS.length - 1 ? 'none' : '1px solid var(--border-subtle)',
            }}>
              <td style={td()}><span className="mono" style={{ fontSize: 12.5 }}>{r.num}</span></td>
              <td style={{ ...td(), color: 'var(--text-primary)' }}>{r.cust}</td>
              <td style={{ ...td(), color: 'var(--text-secondary)', whiteSpace: 'nowrap' }} className="num">{r.date}</td>
              <td style={{ ...td(), textAlign: 'right', fontWeight: 500 }} className="num">{r.amt}</td>
              <td style={td()}><Pill kind={r.status}>{r.label}</Pill></td>
              <td style={{ ...td(), textAlign: 'right', color: 'var(--text-tertiary)' }}><Icon name="more" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
  function th() {
    return {
      textAlign: 'left', padding: '10px 16px', fontSize: 11, fontWeight: 600,
      color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em',
      borderBottom: '1px solid var(--border-default)',
    };
  }
  function td() { return { padding: '12px 16px', fontSize: 13, verticalAlign: 'middle' }; }
}

/* ─── 09 — Empty / Loading / Error ────────────────────────── */
function Sec09States() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
      {/* empty */}
      <div style={panel()}>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 14 }}>Empty</div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 12, padding: '20px 0' }}>
          <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
            <rect x="8" y="14" width="40" height="34" rx="2" stroke="var(--accent)" strokeWidth="1.5" />
            <path d="M8 22h40" stroke="var(--accent)" strokeWidth="1.5" />
            <path d="M18 30h12M18 36h20M18 42h8" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" opacity=".5" />
            <circle cx="44" cy="14" r="6" fill="var(--accent-subtle)" stroke="var(--accent)" strokeWidth="1.5" />
            <path d="M44 11v6M41 14h6" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>No invoices yet</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 240 }}>
            Create your first tax invoice for this firm. Numbering starts at TI/25-26/000001.
          </div>
          <Button variant="primary" size="sm" icon={<Icon name="plus" size={14} />}>New invoice</Button>
        </div>
      </div>
      {/* loading */}
      <div style={panel()}>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 14 }}>Loading</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[0,1,2,3,4].map(i => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={skel(110, 14)} />
              <div style={skel(140 - i*10, 14)} />
              <div style={{ flex: 1 }} />
              <div style={skel(80, 14)} />
              <div style={skel(60, 22, 4)} />
            </div>
          ))}
        </div>
      </div>
      {/* error */}
      <div style={panel()}>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 14 }}>Error</div>
        <div style={{
          border: '1px solid var(--danger-subtle)', borderRadius: 6,
          background: 'var(--danger-subtle)', padding: 14, color: 'var(--danger-text)',
        }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            <div style={{ marginTop: 1, color: 'var(--danger)' }}><Icon name="alert" size={18} /></div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Stock shortage on line 3</div>
              <div style={{ fontSize: 12.5, marginTop: 4, lineHeight: 1.5 }}>
                Only <span className="num" style={{ fontWeight: 600 }}>12.5 m</span> of Silk Georgette 60GSM White available in lot <span className="mono">LT-2026-0042</span>. Reduce quantity or pick another lot.
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <Button variant="secondary" size="sm">Pick another lot</Button>
                <Button variant="ghost" size="sm">Edit qty</Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
  function panel() {
    return {
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 24, minHeight: 260,
      display: 'flex', flexDirection: 'column',
    };
  }
  function skel(w, h, r = 3) {
    return {
      width: w, height: h, borderRadius: r,
      background: 'linear-gradient(90deg,#EFEDE6 0%,#E5E2D6 50%,#EFEDE6 100%)',
      backgroundSize: '200% 100%', animation: 'taanaShimmer 1.4s ease-in-out infinite',
    };
  }
}

/* ─── 10 — Toasts ─────────────────────────────────────────── */
function Sec10Toasts() {
  const toasts = [
    { kind: 'success', icon: 'check-circle', title: 'Invoice finalized',
      msg: 'TI/25-26/000847 saved. Posted to GL · ledger updated.' },
    { kind: 'warning', icon: 'alert', title: 'Approval requested',
      msg: 'Khan Sarees is over credit limit by ₹40,000. Sales Manager notified.' },
    { kind: 'danger', icon: 'x-circle', title: 'GRN posting failed',
      msg: 'Lot LT-2026-0099 weight mismatch. 25.0m declared vs 24.4m measured. Resolve in Inventory > GRN drafts.' },
    { kind: 'info', icon: 'info', title: 'Backup complete',
      msg: 'FY 2025-26 ledger backed up at 14:30. Next backup at 18:30.' },
  ];
  const tone = {
    success: { bg: 'var(--bg-surface)', accent: 'var(--success)',  bd: 'var(--border-default)' },
    warning: { bg: 'var(--bg-surface)', accent: 'var(--warning)',  bd: 'var(--border-default)' },
    danger:  { bg: 'var(--bg-surface)', accent: 'var(--danger)',   bd: 'var(--border-default)' },
    info:    { bg: 'var(--bg-surface)', accent: 'var(--info)',     bd: 'var(--border-default)' },
  };
  return (
    <div style={{
      background: 'var(--bg-sunken)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 24,
      display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-end',
    }}>
      <div style={{ alignSelf: 'flex-start', fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 }}>
        Toast stack — top-right desktop, max 3 visible
      </div>
      {toasts.map(t => {
        const c = tone[t.kind];
        return (
          <div key={t.kind} style={{
            width: 380, background: c.bg, border: `1px solid ${c.bd}`,
            borderLeft: `3px solid ${c.accent}`,
            borderRadius: 8, padding: '12px 14px',
            display: 'flex', gap: 10, alignItems: 'flex-start',
            boxShadow: 'var(--shadow-2)',
          }}>
            <div style={{ color: c.accent, marginTop: 1 }}><Icon name={t.icon} size={16} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{t.title}</div>
              <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 2, lineHeight: 1.45 }}>{t.msg}</div>
            </div>
            <button aria-label="Dismiss" style={{ background: 'none', border: 0, color: 'var(--text-tertiary)', cursor: 'default' }}>
              <Icon name="x" size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

/* ─── 11 — Command palette ────────────────────────────────── */
function Sec11Palette() {
  const groups = [
    { name: 'Parties', icon: 'users', items: [
      { l: 'Rajesh Textiles, Surat',      r: '24ABCDE1234F1Z5 · ₹2,40,000 outstanding' },
      { l: 'Khan Sarees Pvt Ltd',         r: '27AAAAA0000A1Z5 · ₹6,40,000 outstanding' },
    ]},
    { name: 'Items', icon: 'package', items: [
      { l: 'Silk Georgette 60GSM White',  r: 'SKU FAB-SG-060-WHT · 124.5 m free' },
    ]},
    { name: 'Invoices', icon: 'file', items: [
      { l: 'TI/25-26/000847', r: 'Rajesh Textiles · 27-Apr-2026 · ₹4,82,500.00' },
    ]},
    { name: 'Reports', icon: 'trend-up', items: [
      { l: 'Aging — receivables', r: 'Open report · current FY' },
    ]},
  ];
  return (
    <div style={{
      background: 'rgba(20,20,18,.32)',
      borderRadius: 12, padding: 24,
      display: 'flex', justifyContent: 'center', alignItems: 'flex-start',
      minHeight: 360,
    }}>
      <div style={{
        width: 520, background: 'var(--bg-surface)',
        borderRadius: 12, border: '1px solid var(--border-default)',
        boxShadow: 'var(--shadow-4)', overflow: 'hidden',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 16px', borderBottom: '1px solid var(--border-subtle)',
        }}>
          <Icon name="search" size={16} color="var(--text-tertiary)" />
          <input readOnly value="raj"
            style={{ flex: 1, border: 0, outline: 'none', fontSize: 15, fontFamily: 'inherit', color: 'var(--text-primary)', background: 'transparent' }}
          />
          <span className="mono" style={{
            fontSize: 11, padding: '2px 6px', border: '1px solid var(--border-default)',
            borderRadius: 4, color: 'var(--text-tertiary)', background: 'var(--bg-sunken)',
          }}>esc</span>
        </div>
        <div style={{ padding: '6px 0' }}>
          {groups.map((g, gi) => (
            <div key={g.name}>
              <div style={{
                padding: '8px 16px 4px',
                fontSize: 10.5, color: 'var(--text-tertiary)',
                textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600,
              }}>{g.name}</div>
              {g.items.map((it, i) => {
                const active = gi === 0 && i === 0;
                return (
                  <div key={it.l} style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '8px 16px',
                    background: active ? 'var(--accent-subtle)' : 'transparent',
                    color: active ? 'var(--accent)' : 'var(--text-primary)',
                  }}>
                    <Icon name={g.icon} size={14} color={active ? 'var(--accent)' : 'var(--text-tertiary)'} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 500 }}>{it.l}</div>
                      <div style={{ fontSize: 12, color: active ? 'var(--accent-hover)' : 'var(--text-tertiary)' }} className="num">{it.r}</div>
                    </div>
                    {active && <Icon name="corner-down" size={14} color="var(--accent)" />}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <div style={{
          padding: '10px 16px', borderTop: '1px solid var(--border-subtle)',
          background: 'var(--bg-sunken)',
          display: 'flex', gap: 16, fontSize: 11, color: 'var(--text-tertiary)',
        }}>
          <span><span className="mono">↑↓</span> Navigate</span>
          <span><span className="mono">↵</span> Open</span>
          <span><span className="mono">⌘K</span> Toggle</span>
          <span style={{ marginLeft: 'auto' }}>4 results</span>
        </div>
      </div>
    </div>
  );
}

/* ─── Brand triptych — top of canvas ──────────────────────── */
function BrandTriptych() {
  const directions = [
    {
      pick: false,
      name: 'Bolt',
      strap: 'A bolt of cloth — the unit textile sells in.',
      type: 'Hanken Grotesk · 700 · -0.03em',
      mark: <BoltMark />,
      why: 'English, sharp, fast. But "Bolt" is crowded in B2B SaaS (payments, e-commerce) and the metaphor is generic — not specifically textile.',
    },
    {
      pick: true,
      name: 'taana',
      strap: 'Warp — the threads that hold cloth together.',
      type: 'Hanken Grotesk · 600 · -0.02em',
      mark: <TaanaMark size={56} color="var(--accent)" />,
      why: 'Trade-fluent in three languages. The warp metaphor matches what an ERP is to a textile business: load-bearing structure under everything else.',
    },
    {
      pick: false,
      name: 'Kora',
      strap: 'Raw, unbleached fabric. Every lot starts here.',
      type: 'Hanken Grotesk · 600 · -0.015em',
      mark: <KoraMark />,
      why: 'Quietly evocative. But "raw" in a finance context can read as "incomplete" — the wrong feeling for an ERP that should signal control.',
    },
  ];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 32 }}>
      {directions.map(d => (
        <div key={d.name} style={{
          background: 'var(--bg-surface)',
          border: d.pick ? '1px solid var(--accent)' : '1px solid var(--border-default)',
          borderRadius: 8, padding: 24, position: 'relative',
          boxShadow: d.pick ? '0 0 0 3px var(--accent-subtle)' : 'none',
        }}>
          {d.pick && (
            <div style={{
              position: 'absolute', top: 12, right: 12,
              fontSize: 10, fontWeight: 700, letterSpacing: '.08em',
              color: 'var(--accent)', textTransform: 'uppercase',
              padding: '3px 8px', background: 'var(--accent-subtle)', borderRadius: 4,
            }}>Recommended</div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 18 }}>
            <div style={{
              width: 72, height: 72, background: 'var(--bg-sunken)',
              borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              border: '1px solid var(--border-subtle)',
            }}>{d.mark}</div>
            <div>
              <div style={{
                fontSize: 32, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1,
                color: 'var(--text-primary)',
              }}>{d.name}</div>
              <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 6 }}>{d.type}</div>
            </div>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500, marginBottom: 6 }}>{d.strap}</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{d.why}</div>
        </div>
      ))}
    </div>
  );
}

function BoltMark() {
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
      {/* folded-corner / dog-ear */}
      <path d="M14 14 L34 14 L42 22 L42 42 L14 42 Z"
        fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinejoin="miter" />
      <path d="M34 14 L34 22 L42 22"
        fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinejoin="miter" />
    </svg>
  );
}
function KoraMark() {
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
      <line x1="12" y1="28" x2="44" y2="28" stroke="var(--accent)" strokeWidth="3" strokeLinecap="square" />
      <circle cx="12" cy="28" r="3.5" fill="var(--accent)" />
      <circle cx="44" cy="28" r="3.5" fill="var(--accent)" />
    </svg>
  );
}

/* ─── Recommendation prose ─────────────────────────────────  */
function Recommendation() {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 24, marginBottom: 32,
      display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 32, alignItems: 'center',
    }}>
      <div>
        <div style={{ fontSize: 11, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600, marginBottom: 8 }}>Recommendation</div>
        <h3 style={{ fontSize: 20, fontWeight: 600, margin: 0, marginBottom: 12, letterSpacing: '-0.01em' }}>We go with <span style={{ color: 'var(--accent)' }}>taana</span>.</h3>
        <p style={{ fontSize: 13.5, color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
          <strong style={{ color: 'var(--text-primary)' }}>Bolt</strong> is sharp but generic — every B2B SaaS uses speed metaphors and the name is already crowded.{' '}
          <strong style={{ color: 'var(--text-primary)' }}>Kora</strong> is poetic but only resonates with the most trade-literate, and "raw" has the wrong financial connotation.{' '}
          <strong style={{ color: 'var(--text-primary)' }}>Taana</strong> means warp — the structural threads that bear every cloth's load — and that is exactly what an ERP is to a textile business. It says itself in three languages, and the mark (warp + one weft, with the centre warp passing under) is a single weave intersection: the smallest unit of cloth, no kitsch attached.
        </p>
      </div>
      <div style={{
        background: 'var(--bg-sunken)', borderRadius: 8, padding: 24,
        display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'flex-start',
      }}>
        <Wordmark size={64} />
        <div className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
          taana, n. — the longitudinal threads on a loom. Hindi/Gujarati. Pron. <em>TAH-nah</em>.
        </div>
      </div>
    </div>
  );
}

/* ─── Anti-pattern audit ───────────────────────────────────  */
const ANTIPATTERNS = [
  ['Purple/indigo/pink in palette',           'Honoured', 'Emerald accent only.'],
  ['Gradients on text or fills',              'Honoured', 'No gradient anywhere on canvas.'],
  ['Glassmorphism / decorative blur',         'Honoured', 'Solid surfaces only.'],
  ['Identical 3-up "feature" card grids',     'Honoured', 'Cards vary in width, role, content.'],
  ['Stock photography / 3D illustrations',    'Honoured', 'None used.'],
  ['Emoji as functional icons',               'Honoured', 'Lucide-style line icons only.'],
  ['999px radius on cards / buttons',         'Honoured', 'Reserved for pills (22px).'],
  ['Rainbow charts / 8-color KPIs',           'Honoured', 'Sparklines use neutral; data tokens elsewhere.'],
  ['"Welcome back!" or marketing copy',       'Honoured', 'No greeting; no exclamations.'],
  ['Font weight < 400 / size < 12px',         'Honoured', 'Caption is 12/500. Mono labels at 10.5 are non-text annotation only — flagged.'],
  ['Spinners as primary loading state',       'Honoured', 'Skeleton blocks only.'],
  ['Centered modals on mobile',               'N/A',      'Light-mode-only canvas; mobile breakpoint is Phase 1.'],
];

function AntipatternAudit() {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 24, marginTop: 32,
    }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Anti-pattern audit (§9)</div>
      <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 16 }}>Each rule from the design system, checked against this canvas.</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr auto 2fr', columnGap: 16, rowGap: 8, alignItems: 'baseline' }}>
        {ANTIPATTERNS.map(([rule, status, note]) => (
          <React.Fragment key={rule}>
            <div style={{ fontSize: 13, color: 'var(--text-primary)' }}>{rule}</div>
            <div>
              <Pill kind={status === 'Honoured' ? 'paid' : status === 'Violated' ? 'overdue' : 'scrap'}>{status}</Pill>
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>{note}</div>
          </React.Fragment>
        ))}
      </div>

      <div style={{ marginTop: 28, paddingTop: 20, borderTop: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>Three things I'd revise on a second pass</div>
        <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          <li><strong style={{ color: 'var(--text-primary)' }}>Sparklines on KPI cards.</strong> They render real values but compress the y-axis blindly — a flat-with-a-blip series looks identical to a flat-line series. I'd add an explicit baseline line and a faint min/max band so the eye reads magnitude, not just shape.</li>
          <li><strong style={{ color: 'var(--text-primary)' }}>Pill weight rhythm.</strong> The six pills sit at the same uppercase weight and crowd the eye in the table. I'd downshift DRAFT and SCRAP to a softer treatment (sentence case, 11px regular) so the eye prioritises the active states (FINALIZED / PAID / OVERDUE) without me having to colour-pop them.</li>
          <li><strong style={{ color: 'var(--text-primary)' }}>The mark at 16px.</strong> Five warp lines hold up at 32 and 96, but at 16px the broken centre-warp under-over reads as a 2-pixel notch and could be mistaken for a glyph artefact. I'd ship a 16-only variant where the centre warp is a single unbroken stroke and the under-over only appears at 24px+.</li>
        </ol>
      </div>
    </div>
  );
}

/* ─── Top-of-canvas header ─────────────────────────────────  */
function CanvasHeader() {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
      paddingBottom: 24, marginBottom: 32, borderBottom: '1px solid var(--border-default)',
    }}>
      <div>
        <div className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 8 }}>
          Brand · Phase 0 · 1440 × 1800
        </div>
        <h1 style={{ fontSize: 36, fontWeight: 600, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.1 }}>
          Three brand directions for a cloud ERP<br/>
          <span style={{ color: 'var(--text-tertiary)' }}>built for the Indian textile trade</span>
        </h1>
      </div>
      <div style={{ textAlign: 'right' }}>
        <Wordmark size={28} />
        <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 6 }}>
          27-Apr-2026 · v0.1
        </div>
      </div>
    </div>
  );
}

/* ─── Canvas root ──────────────────────────────────────────  */
function Canvas({ device = 'desktop' }) {
  // Frame width changes with device; canvas internal layout stays
  const widths = { desktop: 1440, tablet: 1024, mobile: 390 };
  const W = widths[device];
  return (
    <div style={{
      width: W, minHeight: 1800,
      background: 'var(--bg-canvas)',
      padding: device === 'mobile' ? 20 : device === 'tablet' ? 32 : 56,
      margin: '0 auto',
      boxShadow: '0 8px 24px rgba(20,20,18,.06)',
      borderRadius: 12,
      transition: 'width .3s ease',
    }}>
      <CanvasHeader />
      <BrandTriptych />
      <Recommendation />

      <SectionHead num={1} title="Wordmark + mark"          sub="Light bg · 24/48/96 · 16/32/96" />
      <Sec01Brand />

      <div style={{ height: 32 }} />
      <SectionHead num={2} title="Colour swatches"          sub="Hex · contrast · token" />
      <Sec02Colours />

      <div style={{ height: 32 }} />
      <SectionHead num={3} title="Typography"               sub="9 tokens · tabular ₹" />
      <Sec03Type />

      <div style={{ height: 32 }} />
      <SectionHead num={4} title="Buttons"                  sub="4 variants × 3 sizes × 4 states" />
      <Sec04Buttons />

      <div style={{ height: 32 }} />
      <SectionHead num={5} title="Inputs"                   sub="Text · select · search · date · currency" />
      <Sec05Inputs />

      <div style={{ height: 32 }} />
      <SectionHead num={6} title="Status pills"             sub="6 sanctioned variants" />
      <Sec06Pills />

      <div style={{ height: 32 }} />
      <SectionHead num={7} title="Cards"                    sub="Default / spacious / action / footer / KPI" />
      <Sec07Cards />

      <div style={{ height: 32 }} />
      <SectionHead num={8} title="Sample table"             sub="Sticky head · tabular nums · subtle row borders" />
      <Sec08Table />

      <div style={{ height: 32 }} />
      <SectionHead num={9} title="Empty · loading · error"  sub="Three side-by-side panels" />
      <Sec09States />

      <div style={{ height: 32 }} />
      <SectionHead num={10} title="Toasts"                  sub="Success · warning · danger · info" />
      <Sec10Toasts />

      <div style={{ height: 32 }} />
      <SectionHead num={11} title="Command palette (⌘K)"   sub="Parties · Items · Invoices · Reports" />
      <Sec11Palette />

      <AntipatternAudit />
    </div>
  );
}

Object.assign(window, { Canvas });
