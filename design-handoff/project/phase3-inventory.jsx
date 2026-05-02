// phase3-inventory.jsx — SCR-INV-001 Stock Explorer, SCR-INV-002 Adjustment.
// Owns the Stages Timeline (the hero moment).

const { useState: useStateI } = React;

/* ─────────────────────────────────────────────────────────────
   Stage palette — built from sanctioned semantic tokens.
   We use exactly three "phases of life" plus terminal:
     in_firm  → info slate
     with_kgr → karigar warm
     done     → accent emerald
     packed   → success deep
   This keeps the brief's anti-pattern honoured (no 7-color mess).
───────────────────────────────────────────────────────────── */
const STAGE_META = {
  RAW:           { label: 'Raw',          phase: 'in_firm',  short: 'RAW' },
  CUT:           { label: 'Cut',          phase: 'in_firm',  short: 'CUT' },
  AT_DYEING:     { label: 'Dyeing',       phase: 'with_kgr', short: 'DYE' },
  AT_EMBROIDERY: { label: 'Embroidery',   phase: 'with_kgr', short: 'EMB' },
  AT_HANDWORK:   { label: 'Handwork',     phase: 'with_kgr', short: 'HND' },
  AT_STITCHING:  { label: 'Stitching',    phase: 'with_kgr', short: 'STI' },
  AT_WASHING:    { label: 'Washing',      phase: 'with_kgr', short: 'WSH' },
  QC_PENDING:    { label: 'QC',           phase: 'in_firm',  short: 'QC'  },
  FINISHED:      { label: 'Finished',     phase: 'done',     short: 'FIN' },
  PACKED:        { label: 'Packed',       phase: 'packed',   short: 'PKD' },
};

const PHASE_TOKENS = {
  in_firm:  { fg: 'var(--info-text)',     bg: 'var(--info-subtle)',     accent: '#3F4C5A' },
  with_kgr: { fg: 'var(--warning-text)',  bg: 'var(--warning-subtle)',  accent: '#A26710' },
  done:     { fg: 'var(--accent)',        bg: 'var(--accent-subtle)',   accent: '#0F7A4E' },
  packed:   { fg: 'var(--success-text)',  bg: 'var(--success-subtle)',  accent: '#137A48' },
};

function StagePill({ stage, size = 'sm' }) {
  const m = STAGE_META[stage] || STAGE_META.RAW;
  const t = PHASE_TOKENS[m.phase];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      height: size === 'sm' ? 22 : 26, padding: size === 'sm' ? '0 8px' : '0 10px',
      borderRadius: 4,
      background: t.bg, color: t.fg,
      fontSize: size === 'sm' ? 11 : 12, fontWeight: 600,
      letterSpacing: '0.04em', textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>{m.label}</span>
  );
}

/* ─────────────────────────────────────────────────────────────
   Status mix bar — 80px wide stacked horizontal bar showing
   how an item's qty splits across stages. Tooltip on hover.
───────────────────────────────────────────────────────────── */
function StatusMixBar({ mix, w = 80 }) {
  // mix: [{ stage, qty }]
  const total = mix.reduce((s, m) => s + m.qty, 0) || 1;
  return (
    <div title={mix.map(m => `${STAGE_META[m.stage]?.label || m.stage}: ${m.qty}`).join(' · ')}
      style={{ display: 'flex', width: w, height: 8, borderRadius: 2, overflow: 'hidden', background: 'var(--border-subtle)' }}>
      {mix.map((m, i) => {
        const meta = STAGE_META[m.stage] || STAGE_META.RAW;
        const t = PHASE_TOKENS[meta.phase];
        return <div key={i} style={{ flex: m.qty / total, background: t.accent, opacity: meta.phase === 'in_firm' ? 0.55 : 1 }} />;
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Stock Explorer — desktop 1440 (frame inside is ~1280)
───────────────────────────────────────────────────────────── */

const STOCK_ROWS = [
  { sku: 'SLK-GEO-60', item: 'Silk Georgette 60GSM White',     uom: 'm',  total: 248,  free: 38, alloc: 60, kgr: 150, cost: 185, val: '45,880', mix: [{stage:'RAW',qty:38},{stage:'CUT',qty:60},{stage:'AT_EMBROIDERY',qty:120},{stage:'AT_HANDWORK',qty:30}] },
  { sku: 'BNS-SLK-90', item: 'Banarasi Silk 90GSM Maroon',     uom: 'm',  total: 184,  free: 24, alloc: 80, kgr: 80,  cost: 620, val: '1,14,080', mix: [{stage:'RAW',qty:24},{stage:'CUT',qty:80},{stage:'AT_EMBROIDERY',qty:60},{stage:'AT_STITCHING',qty:20}] },
  { sku: 'CHN-CTN-44', item: 'Chanderi Cotton 44 in Off-white', uom: 'm', total: 412,  free: 220, alloc: 92, kgr: 100, cost: 95,  val: '39,140', mix: [{stage:'RAW',qty:220},{stage:'CUT',qty:92},{stage:'AT_DYEING',qty:100}] },
  { sku: 'KAT-SLK-50', item: 'Katan Silk 50GSM Indigo',        uom: 'm',  total: 96,   free: 8,  alloc: 24, kgr: 64,  cost: 410, val: '39,360', mix: [{stage:'RAW',qty:8},{stage:'CUT',qty:24},{stage:'AT_HANDWORK',qty:64}] },
  { sku: 'MUS-VOL-58', item: 'Muslin Voile 58 in Mint',         uom: 'm',  total: 156,  free: 156, alloc: 0,  kgr: 0,   cost: 72,  val: '11,232', mix: [{stage:'RAW',qty:156}] },
  { sku: 'CRP-DBL-42', item: 'Crepe Double 42 in Blush',        uom: 'm',  total: 320,  free: 120, alloc: 50, kgr: 150, cost: 138, val: '44,160', mix: [{stage:'RAW',qty:120},{stage:'CUT',qty:50},{stage:'AT_DYEING',qty:90},{stage:'AT_EMBROIDERY',qty:60}] },
  { sku: 'TUS-RAW-08', item: 'Tussar Raw 80GSM Natural',        uom: 'm',  total: 72,   free: 12, alloc: 18, kgr: 42,  cost: 285, val: '20,520', mix: [{stage:'RAW',qty:12},{stage:'CUT',qty:18},{stage:'AT_STITCHING',qty:42}] },
  { sku: 'DOL-SLK-44', item: 'Dola Silk 44 in Champagne',       uom: 'm',  total: 208,  free: 48, alloc: 40, kgr: 120, cost: 365, val: '75,920', mix: [{stage:'RAW',qty:48},{stage:'CUT',qty:40},{stage:'AT_EMBROIDERY',qty:80},{stage:'AT_HANDWORK',qty:40}] },
  { sku: 'TRM-ZRI-G2', item: 'Zari Trim Gold 2 cm',             uom: 'rl', total: 18,   free: 12, alloc: 0,  kgr: 6,   cost: 1240,val: '22,320', mix: [{stage:'RAW',qty:12},{stage:'AT_EMBROIDERY',qty:6}] },
  { sku: 'TRM-LCE-C1', item: 'Cotton Lace 1 cm Ivory',          uom: 'rl', total: 36,   free: 24, alloc: 4,  kgr: 8,   cost: 480, val: '17,280', mix: [{stage:'RAW',qty:24},{stage:'CUT',qty:4},{stage:'AT_HANDWORK',qty:8}] },
];

// FilterChip moved to components.jsx (shared across phases)

function StockToolbar({ view = 'list' }) {
  return (
    <div style={{
      padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 12,
      borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: '-0.01em' }}>Stock Explorer</h1>
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
          1,860 m fabric · 54 trims · ₹4,29,892 inventory value
        </div>
      </div>

      {/* view toggle */}
      <div style={{
        display: 'inline-flex', height: 32, borderRadius: 6, overflow: 'hidden',
        border: '1px solid var(--border-default)', background: 'var(--bg-surface)',
      }}>
        {[
          { v: 'list', label: 'List', icon: 'menu' },
          { v: 'grid', label: 'Grid', icon: 'grid' },
          { v: 'kanban', label: 'Kanban', icon: 'columns' },
        ].map((o, i) => (
          <div key={o.v} style={{
            padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6,
            background: view === o.v ? 'var(--bg-sunken)' : 'transparent',
            color: view === o.v ? 'var(--text-primary)' : 'var(--text-secondary)',
            fontWeight: view === o.v ? 600 : 500, fontSize: 12.5,
            borderLeft: i > 0 ? '1px solid var(--border-default)' : 'none',
          }}>
            <Icon name={o.icon} size={13} />
            <span>{o.label}</span>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <Button variant="secondary" size="sm" icon="adjust">Adjust</Button>
        <Button variant="secondary" size="sm" icon="transfer">Transfer</Button>
        <Button variant="secondary" size="sm" icon="clipboard">Stock Take</Button>
      </div>
    </div>
  );
}

function StockFilterBar() {
  return (
    <div style={{
      padding: '10px 20px', display: 'flex', alignItems: 'center', gap: 16,
      borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-canvas)',
      position: 'sticky', top: 0, zIndex: 1, flexWrap: 'wrap',
    }}>
      <div style={{ flexShrink: 0, width: 220 }}>
        <Input placeholder="Search SKU, item, lot…" prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)', marginRight: 4 }}>Category</span>
        <FilterChip label="Fabric" active count={42} />
        <FilterChip label="Trims" count={18} />
        <FilterChip label="Finished suits" count={6} />
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)', marginRight: 4 }}>Stage</span>
        <FilterChip label="Raw" />
        <FilterChip label="Cut" />
        <FilterChip label="At karigar" active count={8} />
        <FilterChip label="QC" />
        <FilterChip label="Finished" />
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)', marginRight: 4 }}>Aging</span>
        <FilterChip label="0–30" />
        <FilterChip label="31–60" />
        <FilterChip label="61–90" />
        <FilterChip label="90+" active count={3} />
      </div>
    </div>
  );
}

function StockTable({ selectedSku = 'SLK-GEO-60' }) {
  return (
    <div style={{ overflow: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'var(--bg-sunken)', textAlign: 'left' }}>
            <th style={thInv}>SKU</th>
            <th style={thInv}>Item</th>
            <th style={{...thInv, textAlign: 'right'}}>Total</th>
            <th style={{...thInv, textAlign: 'right', color: 'var(--accent)'}}>Free</th>
            <th style={{...thInv, textAlign: 'right'}}>Alloc.</th>
            <th style={{...thInv, textAlign: 'right'}}>At kgr</th>
            <th style={{...thInv, textAlign: 'right'}}>Avg cost</th>
            <th style={{...thInv, textAlign: 'right'}}>Value ₹</th>
            <th style={thInv}>Status mix</th>
          </tr>
        </thead>
        <tbody>
          {STOCK_ROWS.map((r, i) => {
            const sel = r.sku === selectedSku;
            return (
              <tr key={r.sku} style={{
                borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                background: sel ? 'var(--accent-subtle)' : 'transparent',
                cursor: 'pointer',
              }}>
                <td className="mono" style={{...tdInv, color: 'var(--text-secondary)', fontSize: 12}}>{r.sku}</td>
                <td style={tdInv}>
                  <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{r.item}</div>
                </td>
                <td className="num" style={{...tdInv, textAlign: 'right', fontWeight: 500}}>{r.total} <span style={{ color: 'var(--text-tertiary)', fontWeight: 400, fontSize: 11 }}>{r.uom}</span></td>
                <td className="num" style={{...tdInv, textAlign: 'right', color: r.free > 0 ? 'var(--accent)' : 'var(--text-tertiary)', fontWeight: 600}}>{r.free}</td>
                <td className="num" style={{...tdInv, textAlign: 'right', color: 'var(--text-secondary)'}}>{r.alloc || '—'}</td>
                <td className="num" style={{...tdInv, textAlign: 'right', color: r.kgr ? 'var(--warning-text)' : 'var(--text-tertiary)'}}>{r.kgr || '—'}</td>
                <td className="num" style={{...tdInv, textAlign: 'right', color: 'var(--text-secondary)'}}>₹{r.cost}</td>
                <td className="num" style={{...tdInv, textAlign: 'right', fontWeight: 500}}>₹{r.val}</td>
                <td style={tdInv}><StatusMixBar mix={r.mix} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const thInv = {
  fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)',
  letterSpacing: '0.06em', textTransform: 'uppercase',
  padding: '8px 12px', borderBottom: '1px solid var(--border-default)', whiteSpace: 'nowrap',
};
const tdInv = { padding: '10px 12px', verticalAlign: 'middle' };

/* ─────────────────────────────────────────────────────────────
   Lot Detail panel — 5 tabs
───────────────────────────────────────────────────────────── */

function LotDetailPanel({ initialTab = 'timeline' }) {
  const [tab, setTab] = useStateI(initialTab);
  return (
    <div style={{
      background: 'var(--bg-surface)',
      borderLeft: '1px solid var(--border-default)',
      display: 'flex', flexDirection: 'column', height: '100%',
    }}>
      <LotHeader />
      <LotTabs tab={tab} onChange={setTab} />
      <div style={{ flex: 1, overflow: 'auto' }}>
        {tab === 'overview' && <LotOverview />}
        {tab === 'movements' && <LotMovements />}
        {tab === 'timeline' && <LotStagesTimeline />}
        {tab === 'allocations' && <LotAllocations />}
        {tab === 'qc' && <LotQC />}
      </div>
    </div>
  );
}

function LotHeader() {
  return (
    <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <span className="mono" style={{
          fontSize: 13, fontWeight: 600, letterSpacing: '0.02em',
          padding: '3px 8px', borderRadius: 4,
          background: 'var(--accent-subtle)', color: 'var(--accent)',
        }}>LT-2026-0042</span>
        <StagePill stage="AT_EMBROIDERY" />
        <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>since 18-Mar · 39d in stage</span>
        <button style={iconBtn} aria-label="Close"><Icon name="x" size={14} /></button>
      </div>
      <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>Silk Georgette 60GSM White</div>
      <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
        SKU SLK-GEO-60 · Width 44 in · Shade Off-white · Dye batch DB-2026-014
      </div>
    </div>
  );
}

const iconBtn = {
  marginLeft: 'auto', height: 24, width: 24,
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  background: 'transparent', border: 'none', cursor: 'pointer',
  color: 'var(--text-tertiary)', borderRadius: 4,
};

function LotTabs({ tab, onChange }) {
  const tabs = [
    { id: 'overview',    label: 'Overview' },
    { id: 'movements',   label: 'Movements' },
    { id: 'timeline',    label: 'Stages' },
    { id: 'allocations', label: 'Allocations' },
    { id: 'qc',          label: 'QC' },
  ];
  return (
    <div style={{ display: 'flex', borderBottom: '1px solid var(--border-default)', padding: '0 20px', background: 'var(--bg-surface)' }}>
      {tabs.map(t => {
        const active = tab === t.id;
        return (
          <button key={t.id} onClick={() => onChange?.(t.id)} style={{
            border: 'none', background: 'transparent', cursor: 'pointer',
            padding: '12px 14px', fontSize: 13,
            fontWeight: active ? 600 : 500,
            color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
            borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
            marginBottom: -1,
          }}>{t.label}</button>
        );
      })}
    </div>
  );
}

/* ── Tab 1: Overview ── */
function LotOverview() {
  return (
    <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, fontSize: 13 }}>
        <KV k="Supplier"      v="Reliance Industries Ltd · GST 27AAACR5055K1Z2" />
        <KV k="GRN reference" v={<span className="mono">GRN/25-26/00318</span>} />
        <KV k="Received on"   v="12-Mar-2026 by Naseem" />
        <KV k="Opening qty"   v={<span><span className="num" style={{fontWeight:600}}>50.00</span> m</span>} />
        <KV k="Current qty"   v={<span><span className="num" style={{fontWeight:600, color:'var(--accent)'}}>38.00</span> m · 76%</span>} />
        <KV k="Avg cost"      v="₹185.00 / m" />
        <KV k="Total value"   v="₹7,030.00" />
        <KV k="Storage bin"   v="W-1 / Rack-3 / Shelf-B" />
      </div>

      <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 14 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)', marginBottom: 8 }}>
          Attributes
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {[
            ['Width', '44 in'], ['GSM', '60'], ['Shade', 'Off-white'],
            ['Dye batch', 'DB-2026-014'], ['Fibre', 'Pure mulberry silk'], ['HSN', '5407'],
          ].map(([k, v]) => (
            <span key={k} style={{
              fontSize: 11.5, padding: '4px 10px', borderRadius: 4,
              background: 'var(--bg-sunken)', color: 'var(--text-secondary)',
              border: '1px solid var(--border-subtle)',
            }}>
              <span style={{ color: 'var(--text-tertiary)' }}>{k} </span><span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{v}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function KV({ k, v }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)' }}>{k}</div>
      <div style={{ fontSize: 13, color: 'var(--text-primary)', marginTop: 2 }}>{v}</div>
    </div>
  );
}

/* ── Tab 2: Movements ── */
const MOVEMENTS = [
  { ts: '26-Apr  16:42', evt: 'RECEIVE_FROM_KARIGAR', from: 'AT_EMBROIDERY', to: 'QC_PENDING',    qty: '+38.00', bal: '38.00', ref: 'JBI/25-26/000059', user: 'Naseem' },
  { ts: '26-Apr  16:42', evt: 'WASTAGE_LOGGED',       from: 'AT_EMBROIDERY', to: 'AT_EMBROIDERY', qty: '−2.00',  bal: '38.00', ref: 'JBI/25-26/000059', user: 'Naseem' },
  { ts: '18-Mar  11:08', evt: 'SEND_TO_KARIGAR',      from: 'CUT',           to: 'AT_EMBROIDERY', qty: '−40.00', bal: '0.00',  ref: 'JOB/25-26/000063', user: 'Moiz' },
  { ts: '18-Mar  11:08', evt: 'SEND_TO_KARIGAR',      from: 'CUT',           to: 'AT_EMBROIDERY', qty: '−10.00', bal: '40.00', ref: 'JOB/25-26/000064', user: 'Moiz' },
  { ts: '18-Mar  09:31', evt: 'CUT_OPERATION',        from: 'RAW',           to: 'CUT',           qty: '50.00',  bal: '50.00', ref: 'MO/25-26/000041',  user: 'Naseem' },
  { ts: '12-Mar  14:20', evt: 'GRN_RECEIVE',          from: '—',             to: 'RAW',           qty: '+50.00', bal: '50.00', ref: 'GRN/25-26/00318',  user: 'Naseem' },
];

function LotMovements() {
  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 10, alignItems: 'center' }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)' }}>Filter</span>
        <FilterChip label="All" active count={6} />
        <FilterChip label="Receive" />
        <FilterChip label="Send" />
        <FilterChip label="Wastage" />
      </div>
      <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-sunken)' }}>
              <th style={thInv}>When</th>
              <th style={thInv}>Event · From → To</th>
              <th style={{...thInv, textAlign: 'right'}}>Qty</th>
              <th style={{...thInv, textAlign: 'right'}}>Bal</th>
              <th style={thInv}>Ref</th>
              <th style={thInv}>User</th>
            </tr>
          </thead>
          <tbody>
            {MOVEMENTS.map((m, i) => (
              <tr key={i} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                <td className="mono" style={{...tdInv, fontSize: 11.5, color: 'var(--text-secondary)', whiteSpace: 'nowrap'}}>{m.ts}</td>
                <td style={tdInv}>
                  <div style={{ fontWeight: 500 }}>{m.evt.replace(/_/g, ' ').toLowerCase()}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                    {m.from} → <span style={{ color: 'var(--text-secondary)' }}>{m.to}</span>
                  </div>
                </td>
                <td className="num" style={{
                  ...tdInv, textAlign: 'right', fontWeight: 500,
                  color: m.qty.startsWith('−') ? 'var(--danger-text)' : 'var(--accent)',
                  whiteSpace: 'nowrap',
                }}>{m.qty}</td>
                <td className="num" style={{...tdInv, textAlign: 'right'}}>{m.bal}</td>
                <td className="mono" style={{...tdInv, fontSize: 11, color: 'var(--text-secondary)'}}>{m.ref}</td>
                <td style={{...tdInv, fontSize: 12, color: 'var(--text-secondary)'}}>{m.user}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Tab 3: STAGES TIMELINE — THE HERO ── */

const TIMELINE = [
  {
    stage: 'RAW', state: 'done',
    title: 'Received',
    when: '12-Mar-2026',
    duration: '6d',
    qty: '50.00 m',
    counterparty: 'GRN/25-26/00318 · Reliance Industries',
    detail: { op: 'GRN intake', cost: '₹185/m × 50m', note: 'Bin W-1 / Rack-3 / Shelf-B. QC sample passed. ' },
  },
  {
    stage: 'CUT', state: 'done',
    title: 'Cut to pattern',
    when: '18-Mar-2026',
    duration: '0d',
    qty: '50.00 m → 50.00 m',
    counterparty: 'MO/25-26/000041 · Naseem (in-house)',
    detail: { op: 'Pattern A-402 · 25 panels', cost: '₹450 added (labour)', note: 'No wastage at cutting.' },
  },
  {
    stage: 'AT_EMBROIDERY', state: 'active',
    title: 'At embroidery',
    when: '18-Mar-2026',
    duration: '39d in stage',
    qty: '40.00 m · split sent',
    counterparty: 'Karigar Imran · Surat · ₹95/m',
    splits: [
      { who: 'Karigar Imran',  qty: '40.00 m', since: '18-Mar', state: 'returning' },
      { who: 'Karigar Salim',  qty: '10.00 m', since: '18-Mar', state: 'returning' },
    ],
    detail: { op: 'Aari work — bridal motif', cost: '₹95/m × 40m = ₹3,800 estimated', note: 'Imran returned 38m · 2m wastage logged 26-Apr (5%). Salim batch in progress, ETA 02-May.' },
  },
  {
    stage: 'QC_PENDING', state: 'active',
    title: 'QC review',
    when: '26-Apr-2026',
    duration: 'in progress',
    qty: '38.00 m',
    counterparty: 'Karigar Pooja',
    detail: { op: 'Visual + measure', cost: '—', note: 'First 12m passed. Remaining 26m queued for inspection.' },
  },
  { stage: 'AT_STITCHING', state: 'future', title: 'Stitching',  qty: '—', counterparty: 'Karigar Salim (planned)' },
  { stage: 'FINISHED',     state: 'future', title: 'Finished',   qty: '—', counterparty: 'Goes to MO/25-26/000041' },
  { stage: 'PACKED',       state: 'future', title: 'Packed',     qty: '—', counterparty: 'Dispatch to Khan Sarees' },
];

function LotStagesTimeline() {
  // Track expanded node — default to active stage
  const [expandedIdx, setExpandedIdx] = useStateI(2);

  return (
    <div style={{ padding: '20px 24px 32px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 18 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>Journey of this lot</div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
            From GRN to dispatch · 50 m opening, 38 m current
          </div>
        </div>
        <div style={{ display: 'flex', gap: 14, fontSize: 11, color: 'var(--text-tertiary)' }}>
          <LegendDot kind="done" label="Completed" />
          <LegendDot kind="active" label="In progress" />
          <LegendDot kind="future" label="Not yet" />
        </div>
      </div>

      <div style={{ position: 'relative', paddingLeft: 4 }}>
        {TIMELINE.map((node, i) => (
          <TimelineNode
            key={i}
            idx={i}
            node={node}
            isLast={i === TIMELINE.length - 1}
            expanded={expandedIdx === i}
            onToggle={() => setExpandedIdx(expandedIdx === i ? -1 : i)}
          />
        ))}
      </div>
    </div>
  );
}

function LegendDot({ kind, label }) {
  const colors = {
    done:   { fill: 'var(--accent)',         ring: 'var(--accent)' },
    active: { fill: 'var(--warning)',        ring: 'var(--warning)' },
    future: { fill: 'transparent',           ring: 'var(--border-strong)' },
  }[kind];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: colors.fill, border: `1.5px solid ${colors.ring}`,
      }} />
      {label}
    </span>
  );
}

function TimelineNode({ idx, node, isLast, expanded, onToggle }) {
  const meta = STAGE_META[node.stage];
  const phaseTok = PHASE_TOKENS[meta.phase];

  // visual encoding by node state
  const isDone   = node.state === 'done';
  const isActive = node.state === 'active';
  const isFuture = node.state === 'future';

  // connector to NEXT node
  const connectorStyle = {
    position: 'absolute',
    left: 13.5,
    top: 28,
    bottom: -16,
    width: 0,
    transformOrigin: 'top',
    animation: `timelineConnectorIn 320ms ease-out ${idx * 90 + 80}ms backwards`,
  };
  let connectorBorder;
  if (isDone) connectorBorder = '2px solid var(--accent)';
  else if (isActive) connectorBorder = '1.5px dashed var(--text-tertiary)';
  else connectorBorder = '1px dotted var(--border-strong)';

  return (
    <div style={{
      position: 'relative', paddingLeft: 40, paddingBottom: isLast ? 0 : 20,
      animation: `timelineNodeIn 280ms ease-out ${idx * 90}ms backwards`,
    }}>
      {/* connector down */}
      {!isLast && (
        <div style={{
          ...connectorStyle,
          borderLeft: connectorBorder,
        }} />
      )}

      {/* node circle */}
      <div style={{
        position: 'absolute', left: 0, top: 4,
        width: 28, height: 28, borderRadius: '50%',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        background: isDone ? 'var(--accent)' : isActive ? 'var(--bg-surface)' : 'var(--bg-surface)',
        border: isDone ? '2px solid var(--accent)'
              : isActive ? '2px solid var(--warning)'
              : '1.5px dashed var(--border-strong)',
        boxShadow: isActive ? '0 0 0 4px rgba(162,103,16,0.10)' : 'none',
        animation: isActive ? 'timelinePulse 2.4s ease-in-out infinite' : 'none',
        zIndex: 1,
      }}>
        {isDone && <Icon name="check" size={14} color="#FFF" />}
        {isActive && <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--warning)' }} />}
        {isFuture && <span className="mono" style={{ fontSize: 10, color: 'var(--text-tertiary)', fontWeight: 600 }}>{idx + 1}</span>}
      </div>

      {/* node card */}
      <div
        onClick={onToggle}
        style={{
          background: isFuture ? 'transparent' : 'var(--bg-surface)',
          border: isFuture ? '1px dashed var(--border-default)' : '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: '12px 14px',
          cursor: 'pointer',
          transition: 'border-color 0.2s, box-shadow 0.2s',
          boxShadow: expanded ? 'var(--shadow-2)' : 'none',
          opacity: isFuture ? 0.7 : 1,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.3, flex: 1, minWidth: 0 }}>{node.title}</span>
          <span style={{ flexShrink: 0, marginTop: 1 }}><StagePill stage={node.stage} /></span>
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)', whiteSpace: 'nowrap', flexShrink: 0, marginTop: 4 }}>
            {node.when || '—'}{node.duration ? ` · ${node.duration}` : ''}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, fontSize: 12.5, color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
          <span className="num" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{node.qty}</span>
          <span>{node.counterparty}</span>
        </div>

        {/* split sub-flows */}
        {node.splits && (
          <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border-subtle)' }}>
            {node.splits.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0' }}>
                <SplitGlyph state={s.state} />
                <Monogram initials={s.who.split(' ')[1]?.[0] || '?'} size={20} />
                <span style={{ fontSize: 12.5, color: 'var(--text-primary)', fontWeight: 500 }}>{s.who}</span>
                <span className="num" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{s.qty}</span>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>since {s.since}</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--warning-text)', fontWeight: 500 }}>
                  {s.state === 'returning' ? 'Returning' : s.state}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* expanded detail */}
        {expanded && node.detail && (
          <div style={{
            marginTop: 12, padding: 12, borderRadius: 6,
            background: 'var(--bg-sunken)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 16px',
          }}>
            <DKV k="Operation" v={node.detail.op} />
            <DKV k="Cost added" v={node.detail.cost} />
            <DKV k="Note" v={node.detail.note} full />
          </div>
        )}
      </div>
    </div>
  );
}

function SplitGlyph({ state }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M2 2 V7 H10" stroke={state === 'returning' ? 'var(--warning)' : 'var(--text-tertiary)'} strokeWidth="1.25" strokeLinecap="round" />
      <path d="M8 5 L11 7 L8 9" stroke={state === 'returning' ? 'var(--warning)' : 'var(--text-tertiary)'} strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
    </svg>
  );
}

function DKV({ k, v, full }) {
  return (
    <div style={{ gridColumn: full ? '1 / -1' : 'auto' }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)' }}>{k}</div>
      <div style={{ fontSize: 12.5, color: 'var(--text-primary)', marginTop: 1 }}>{v}</div>
    </div>
  );
}

/* ── Tab 4: Allocations ── */
function LotAllocations() {
  const rows = [
    { ref: 'SO/25-26/000128', cust: 'Khan Sarees Pvt Ltd', qty: '40.00 m', date: '20-Apr', status: 'finalized' },
    { ref: 'MO/25-26/000041', cust: 'Internal · Rajwadi A-402', qty: '20.00 m', date: '18-Mar', status: 'finalized' },
  ];
  return (
    <div style={{ padding: 20 }}>
      <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 8 }}>
        2 reservations totalling <span className="num" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>60.00 m</span> against 38.00 m on hand —
        <span style={{ color: 'var(--danger-text)', fontWeight: 500 }}> 22.00 m short</span>.
      </div>
      <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-sunken)' }}>
              <th style={thInv}>Doc</th>
              <th style={thInv}>Customer / MO</th>
              <th style={{...thInv, textAlign: 'right'}}>Qty</th>
              <th style={thInv}>Reserved</th>
              <th style={thInv}>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                <td className="mono" style={{...tdInv, fontSize: 12, color: 'var(--text-secondary)'}}>{r.ref}</td>
                <td style={tdInv}>{r.cust}</td>
                <td className="num" style={{...tdInv, textAlign: 'right', fontWeight: 500}}>{r.qty}</td>
                <td style={{...tdInv, fontSize: 12, color: 'var(--text-secondary)'}}>{r.date}</td>
                <td style={tdInv}><Pill kind={r.status}>{r.status}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Tab 5: QC History ── */
function LotQC() {
  return (
    <div style={{ padding: 20 }}>
      <div style={{
        background: 'var(--warning-subtle)',
        border: '1px solid #E8C880',
        borderRadius: 6, padding: 12,
        display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 14,
      }}>
        <Icon name="alert" size={18} color="var(--warning-text)" />
        <div style={{ fontSize: 12.5, color: 'var(--warning-text)' }}>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>QC pending — 26 m queued</div>
          <div>First sample (12 m) passed. Pooja to inspect remainder by 30-Apr.</div>
        </div>
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
        QC checks for this lot will appear here as inspections are logged.
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-INV-001 — full layout (desktop) with split view
───────────────────────────────────────────────────────────── */
function StockExplorerDesktop() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <StockToolbar />
      <StockFilterBar />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1px 520px', flex: 1, minHeight: 0 }}>
        <div style={{ overflow: 'auto', background: 'var(--bg-surface)' }}>
          <StockTable />
        </div>
        <div style={{ background: 'var(--border-subtle)' }} />
        <div style={{ overflow: 'hidden' }}>
          <LotDetailPanel initialTab="timeline" />
        </div>
      </div>
    </div>
  );
}

/* Tablet 1024 — same split but 60/40, narrower right */
function StockExplorerTablet() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <StockToolbar />
      <StockFilterBar />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1px 380px', flex: 1, minHeight: 0 }}>
        <div style={{ overflow: 'auto', background: 'var(--bg-surface)' }}>
          <StockTableCompact />
        </div>
        <div style={{ background: 'var(--border-subtle)' }} />
        <div style={{ overflow: 'hidden' }}>
          <LotDetailPanel initialTab="timeline" />
        </div>
      </div>
    </div>
  );
}

function StockTableCompact() {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead>
        <tr style={{ background: 'var(--bg-sunken)', textAlign: 'left' }}>
          <th style={thInv}>Item</th>
          <th style={{...thInv, textAlign: 'right'}}>Total</th>
          <th style={{...thInv, textAlign: 'right'}}>At kgr</th>
          <th style={thInv}>Mix</th>
        </tr>
      </thead>
      <tbody>
        {STOCK_ROWS.map((r, i) => (
          <tr key={r.sku} style={{
            borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
            background: r.sku === 'SLK-GEO-60' ? 'var(--accent-subtle)' : 'transparent',
          }}>
            <td style={tdInv}>
              <div style={{ fontWeight: 500 }}>{r.item}</div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{r.sku}</div>
            </td>
            <td className="num" style={{...tdInv, textAlign: 'right', fontWeight: 500}}>{r.total}</td>
            <td className="num" style={{...tdInv, textAlign: 'right', color: r.kgr ? 'var(--warning-text)' : 'var(--text-tertiary)'}}>{r.kgr || '—'}</td>
            <td style={tdInv}><StatusMixBar mix={r.mix} w={64} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* Mobile 390 — list of stock cards. Tap → opens detail full-screen */
function StockExplorerMobile() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Stock</h1>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>1,860 m · ₹4.30L</div>
      </div>
      <div style={{ padding: '10px 12px', display: 'flex', gap: 6, overflow: 'auto', borderBottom: '1px solid var(--border-subtle)' }}>
        <FilterChip label="All" active count={66} />
        <FilterChip label="Low" />
        <FilterChip label="At kgr" count={8} />
        <FilterChip label="QC" />
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {STOCK_ROWS.slice(0, 6).map(r => (
          <div key={r.sku} style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
            borderRadius: 8, padding: 12,
          }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
              <div style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.item}</div>
              <div className="num" style={{ fontSize: 14, fontWeight: 700 }}>{r.total}<span style={{ fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 400 }}> {r.uom}</span></div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-secondary)' }}>
              <span className="mono" style={{ color: 'var(--text-tertiary)' }}>{r.sku}</span>
              <span>·</span>
              <span><span style={{ color: 'var(--accent)', fontWeight: 600 }}>{r.free}</span> free</span>
              <span>·</span>
              <span style={{ color: r.kgr ? 'var(--warning-text)' : 'var(--text-tertiary)' }}>{r.kgr ? `${r.kgr} at kgr` : 'all in firm'}</span>
            </div>
            <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {r.mix.map((m, i) => {
                const meta = STAGE_META[m.stage] || STAGE_META.RAW;
                const tok = PHASE_TOKENS[meta.phase];
                return (
                  <span key={i} style={{
                    fontSize: 10.5, fontWeight: 600, padding: '2px 6px', borderRadius: 4,
                    background: tok.bg, color: tok.fg,
                    letterSpacing: '0.04em', textTransform: 'uppercase',
                  }}>
                    <span className="num" style={{ marginRight: 4 }}>{m.qty}</span>{meta.short}
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-INV-002 — Stock Adjustment modal/sheet
───────────────────────────────────────────────────────────── */
function StockAdjustModal() {
  return (
    <div style={{
      width: 520, background: 'var(--bg-surface)',
      borderRadius: 10, boxShadow: 'var(--shadow-4)', overflow: 'hidden',
      border: '1px solid var(--border-default)',
    }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>Adjust stock</div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Records a one-off correction with reason</div>
        </div>
        <button style={iconBtn} aria-label="Close"><Icon name="x" size={14} /></button>
      </div>

      <div style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Lot" required>
          <div style={{
            border: '1px solid var(--border-default)', borderRadius: 6, padding: '8px 10px',
            display: 'flex', alignItems: 'center', gap: 10, background: 'var(--bg-surface)',
          }}>
            <span className="mono" style={{
              fontSize: 11.5, fontWeight: 600,
              padding: '2px 6px', borderRadius: 4,
              background: 'var(--accent-subtle)', color: 'var(--accent)',
            }}>LT-2026-0042</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 500 }}>Silk Georgette 60GSM White</div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Currently 38.00 m · at embroidery (Karigar Imran)</div>
            </div>
            <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
          </div>
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="Current qty">
            <Input value="38.00 m" state="disabled" />
          </Field>
          <Field label="New qty" required hint="Δ −5.00 m (−13%)">
            <Input value="33.00 m" />
          </Field>
        </div>

        <Field label="Reason" required>
          <div style={{
            border: '1px solid var(--border-default)', borderRadius: 6, padding: '0 10px',
            height: 40, display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ fontSize: 13, flex: 1 }}>Wastage during embroidery</span>
            <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
          </div>
        </Field>

        <Field label="Notes" helper="Visible to Owner during approval">
          <textarea readOnly value="Karigar Imran's batch returned with 2m more wastage than the agreed 5%. Logging the surplus 5m as wastage so book stock matches floor." style={{
            width: '100%', minHeight: 70, padding: 10, fontFamily: 'inherit', fontSize: 13,
            border: '1px solid var(--border-default)', borderRadius: 6, resize: 'none', color: 'var(--text-primary)',
          }} />
        </Field>

        <div style={{
          padding: 10, borderRadius: 6, background: 'var(--warning-subtle)',
          display: 'flex', alignItems: 'center', gap: 8,
          border: '1px solid #E8C880',
        }}>
          <Icon name="shield" size={14} color="var(--warning-text)" />
          <span style={{ fontSize: 12, color: 'var(--warning-text)', fontWeight: 500 }}>
            Owner approval required — delta exceeds 5%.
          </span>
        </div>
      </div>

      <div style={{
        padding: '12px 18px', borderTop: '1px solid var(--border-subtle)',
        display: 'flex', justifyContent: 'flex-end', gap: 8, background: 'var(--bg-canvas)',
      }}>
        <Button variant="secondary" size="md">Cancel</Button>
        <Button variant="primary" size="md" icon="send">Submit for approval</Button>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   States: Loading skeleton + Empty + Error/alert (Lot stale)
───────────────────────────────────────────────────────────── */
function StockExplorerLoading() {
  const Sk = ({ w, h = 12 }) => (
    <div style={{
      width: w, height: h, borderRadius: 4,
      background: 'linear-gradient(90deg, #ECEAE2 25%, #F5F3EC 50%, #ECEAE2 75%)',
      backgroundSize: '200% 100%',
      animation: 'taanaShimmer 1.4s linear infinite',
    }} />
  );
  return (
    <div style={{ background: 'var(--bg-canvas)', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}>
        <Sk w={180} h={20} />
        <div style={{ marginTop: 6 }}><Sk w={240} h={11} /></div>
      </div>
      <div style={{ padding: 20, background: 'var(--bg-surface)', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border-subtle)' }}>
            <Sk w={70} />
            <Sk w={210} />
            <div style={{ flex: 1 }} />
            <Sk w={60} />
            <Sk w={60} />
            <Sk w={80} />
          </div>
        ))}
      </div>
    </div>
  );
}

function StockExplorerEmpty() {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 12, padding: '56px 32px',
      display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 16,
    }}>
      <EmptyStockArt />
      <div>
        <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--text-primary)' }}>No stock yet</div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 6, maxWidth: 380, lineHeight: 1.55 }}>
          Receive your first GRN to start counting. Or import opening stock from Vyapar / Excel — we map SKU, qty, lot, and avg cost in one pass.
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Button variant="primary" size="md" icon="plus">Receive GRN</Button>
        <Button variant="secondary" size="md" icon="upload">Import opening stock</Button>
      </div>
    </div>
  );
}

function EmptyStockArt() {
  // Simple line-art shelves stack. No emoji.
  return (
    <svg width="120" height="96" viewBox="0 0 120 96" fill="none" stroke="#C8C5B8" strokeWidth="1.5">
      <rect x="10" y="20" width="100" height="20" rx="2" />
      <rect x="10" y="46" width="100" height="20" rx="2" />
      <rect x="10" y="72" width="100" height="20" rx="2" />
      <line x1="20" y1="20" x2="20" y2="92" />
      <line x1="100" y1="20" x2="100" y2="92" />
      <path d="M30 28 H50 M30 33 H44" stroke="#E0DDD2" />
      <path d="M30 54 H46 M30 59 H38" stroke="#E0DDD2" />
      <path d="M30 80 H58 M30 85 H50" stroke="#E0DDD2" />
    </svg>
  );
}

/* Stale lot alert — lives at top of Stages timeline when applicable */
function StaleLotAlert({ lot = 'LT-2026-0099', kgr = 'Karigar Imran', last = '12-Feb-2026', qty = '25m', age = 76 }) {
  return (
    <div style={{
      background: 'var(--danger-subtle)', border: '1px solid #E5B3A8',
      borderRadius: 8, padding: 14,
      display: 'flex', alignItems: 'flex-start', gap: 12,
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: '50%',
        background: 'var(--danger)', color: '#FFF',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}><Icon name="alert" size={16} /></div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--danger-text)' }}>
          Lot {lot} hasn't moved in {age} days
        </div>
        <div style={{ fontSize: 12, color: 'var(--danger-text)', marginTop: 3, lineHeight: 1.5 }}>
          Last seen at {kgr} on {last} with {qty}. No GRN, wastage log, or photo since.
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        <Button variant="secondary" size="sm" icon="phone">Send reminder</Button>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Exports
───────────────────────────────────────────────────────────── */
Object.assign(window, {
  StockExplorerDesktop, StockExplorerTablet, StockExplorerMobile,
  StockExplorerLoading, StockExplorerEmpty,
  StockAdjustModal, StaleLotAlert,
  LotDetailPanel, LotStagesTimeline,
  StagePill, StatusMixBar,
  STAGE_META, PHASE_TOKENS,
});
