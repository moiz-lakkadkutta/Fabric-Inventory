// phase3-mfg.jsx — Pipeline Kanban + MO List + MO Detail.

const { useState: useStateM, useMemo: useMemoM } = React;

const KANBAN_COLS = [
  { id: 'RAW',           label: 'Raw',          phase: 'in_firm' },
  { id: 'CUT',           label: 'Cut',          phase: 'in_firm' },
  { id: 'AT_DYEING',     label: 'Dyeing',       phase: 'with_kgr' },
  { id: 'AT_EMBROIDERY', label: 'Embroidery',   phase: 'with_kgr' },
  { id: 'AT_HANDWORK',   label: 'Handwork',     phase: 'with_kgr' },
  { id: 'AT_STITCHING',  label: 'Stitching',    phase: 'with_kgr' },
  { id: 'AT_WASHING',    label: 'Washing',      phase: 'with_kgr' },
  { id: 'QC_PENDING',    label: 'QC',           phase: 'in_firm' },
  { id: 'FINISHED',      label: 'Finished',     phase: 'done' },
  { id: 'PACKED',        label: 'Packed',       phase: 'packed' },
];

// per-col standard cycle time (days), used for age tinting in bottleneck mode
const STANDARDS = {
  RAW: 2, CUT: 1, AT_DYEING: 5, AT_EMBROIDERY: 8, AT_HANDWORK: 10,
  AT_STITCHING: 4, AT_WASHING: 2, QC_PENDING: 1, FINISHED: 2, PACKED: 1,
};

const KCARDS = [
  // RAW
  { id: 'LT-2026-0099', stage: 'RAW',           item: 'Muslin Voile 58 Mint',         qty: '156 m',  age: 4,  who: 'Naseem',   value: 11232, mo: 'MO/000045' },
  { id: 'LT-2026-0102', stage: 'RAW',           item: 'Crepe Double Blush',           qty: '120 m',  age: 1,  who: 'Naseem',   value: 16560, mo: 'MO/000046' },
  // CUT
  { id: 'LT-2026-0090', stage: 'CUT',           item: 'Silk Georgette panels',        qty: '50 panels', age: 3, who: 'Naseem', value: 9250,  mo: 'MO/000041' },
  { id: 'LT-2026-0094', stage: 'CUT',           item: 'Banarasi panels',              qty: '24 panels', age: 0, who: 'Naseem', value: 14880, mo: 'MO/000042' },
  // DYEING
  { id: 'LT-2026-0084', stage: 'AT_DYEING',     item: 'Chanderi Cotton Off-white',    qty: '100 m',  age: 6,  who: 'Salim',     value: 9500,  mo: 'MO/000040' },
  // EMBROIDERY
  { id: 'LT-2026-0042', stage: 'AT_EMBROIDERY', item: 'Silk Georgette · Aari',        qty: '40 m',   age: 39, who: 'Imran',     value: 7400,  mo: 'MO/000041' },
  { id: 'LT-2026-0058', stage: 'AT_EMBROIDERY', item: 'Banarasi Maroon · Zardosi',    qty: '60 m',   age: 12, who: 'Imran',     value: 37200, mo: 'MO/000042' },
  { id: 'LT-2026-0061', stage: 'AT_EMBROIDERY', item: 'Dola Champagne · Mukaish',     qty: '80 m',   age: 5,  who: 'Yasin',     value: 29200, mo: 'MO/000043' },
  // HANDWORK
  { id: 'LT-2026-0033', stage: 'AT_HANDWORK',   item: 'Katan Silk Indigo · Cutdana',  qty: '64 m',   age: 22, who: 'Anwar',     value: 26240, mo: 'MO/000038' },
  { id: 'LT-2026-0072', stage: 'AT_HANDWORK',   item: 'Dola Silk · Stone work',       qty: '40 m',   age: 8,  who: 'Anwar',     value: 14600, mo: 'MO/000043' },
  // STITCHING
  { id: 'LT-2026-0019', stage: 'AT_STITCHING',  item: 'Tussar Raw · Anarkali',        qty: '42 pcs', age: 3,  who: 'Salim',     value: 11970, mo: 'MO/000037' },
  { id: 'LT-2026-0027', stage: 'AT_STITCHING',  item: 'Crepe · Co-ord set',           qty: '24 pcs', age: 1,  who: 'Rajesh',    value: 7200,  mo: 'MO/000039' },
  // WASHING
  { id: 'LT-2026-0008', stage: 'AT_WASHING',    item: 'Cotton blocks · Pre-wash',     qty: '60 m',   age: 1,  who: 'Salim',     value: 4200,  mo: 'MO/000035' },
  // QC
  { id: 'LT-2026-0042-QC', stage: 'QC_PENDING', item: 'Silk Georgette returned',      qty: '38 m',   age: 1,  who: 'Pooja',     value: 7030,  mo: 'MO/000041' },
  { id: 'LT-2026-0006', stage: 'QC_PENDING',    item: 'Crepe · Anarkali QC',          qty: '18 pcs', age: 2,  who: 'Pooja',     value: 9000,  mo: 'MO/000033' },
  // FINISHED
  { id: 'LT-2026-0003', stage: 'FINISHED',      item: 'Tussar set · MO/35',           qty: '60 pcs', age: 0,  who: '—',         value: 36000, mo: 'MO/000035' },
  // PACKED
  { id: 'LT-2026-0001', stage: 'PACKED',        item: 'Khan Sarees order · 24 sets',  qty: '24 sets',age: 0,  who: '—',         value: 96000, mo: 'MO/000028' },
];

/* ─────────────────────────────────────────────────────────────
   SCR-MFG-001 — Pipeline Kanban
───────────────────────────────────────────────────────────── */
function PipelineKanban({ bottleneck = false }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <KanbanHeader bottleneck={bottleneck} />
      <div style={{
        flex: 1, overflow: 'auto', padding: '14px 16px',
        background: 'var(--bg-canvas)',
      }}>
        <div style={{ display: 'flex', gap: 10, minWidth: 'max-content', height: '100%' }}>
          {KANBAN_COLS.map(col => (
            <KanbanColumn key={col.id} col={col} bottleneck={bottleneck} />
          ))}
        </div>
      </div>
    </div>
  );
}

function KanbanHeader({ bottleneck }) {
  return (
    <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 14 }}>
      <div style={{ flex: 1 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Pipeline</h1>
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
          17 active lots · 8 MOs in flight · ₹3,42,300 of WIP value
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <FilterChip label="All MOs" active count={8} />
        <FilterChip label="Mine" />
        <FilterChip label="Overdue" count={3} />
        <div style={{ width: 1, height: 24, background: 'var(--border-default)', margin: '0 4px' }} />
        <div style={{
          display: 'inline-flex', height: 32, borderRadius: 6, overflow: 'hidden',
          border: '1px solid var(--border-default)',
        }}>
          <div style={{
            padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6,
            background: !bottleneck ? 'var(--bg-sunken)' : 'transparent',
            color: !bottleneck ? 'var(--text-primary)' : 'var(--text-secondary)',
            fontWeight: !bottleneck ? 600 : 500, fontSize: 12.5,
          }}>
            <Icon name="columns" size={13} />Default
          </div>
          <div style={{
            padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 6,
            background: bottleneck ? 'var(--bg-sunken)' : 'transparent',
            color: bottleneck ? 'var(--text-primary)' : 'var(--text-secondary)',
            fontWeight: bottleneck ? 600 : 500, fontSize: 12.5,
            borderLeft: '1px solid var(--border-default)',
          }}>
            <Icon name="flame" size={13} />Bottleneck
          </div>
        </div>
        <Button variant="secondary" size="sm" icon="filter">More filters</Button>
      </div>
    </div>
  );
}

function KanbanColumn({ col, bottleneck }) {
  const cards = KCARDS.filter(c => c.stage === col.id);
  const totalQty = cards.length;
  const totalValue = cards.reduce((s, c) => s + c.value, 0);
  const std = STANDARDS[col.id];
  const ages = cards.map(c => c.age);
  const median = ages.length ? ages.sort((a, b) => a - b)[Math.floor(ages.length / 2)] : 0;
  const isHotColumn = bottleneck && median > std * 1.5;
  const phaseTok = PHASE_TOKENS[col.phase];

  return (
    <div style={{
      width: 248, flexShrink: 0,
      background: isHotColumn ? '#FBEDE6' : 'var(--bg-surface)',
      border: `1px solid ${isHotColumn ? '#E5B3A8' : 'var(--border-subtle)'}`,
      borderRadius: 8,
      display: 'flex', flexDirection: 'column',
      maxHeight: '100%',
    }}>
      {/* column header */}
      <div style={{
        padding: '10px 12px',
        borderBottom: `1px solid ${isHotColumn ? '#E5B3A8' : 'var(--border-subtle)'}`,
        display: 'flex', flexDirection: 'column', gap: 6,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: phaseTok.accent }} />
          <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-primary)' }}>{col.label}</span>
          <span className="num" style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 600 }}>{totalQty}</span>
          {isHotColumn && <Icon name="flame" size={13} color="var(--danger)" />}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--text-tertiary)' }}>
          <span>₹{(totalValue / 1000).toFixed(1)}k value</span>
          <span style={{ color: median > std ? 'var(--warning-text)' : 'var(--text-tertiary)', fontWeight: median > std ? 600 : 400 }}>
            median {median}d / std {std}d
          </span>
        </div>
      </div>

      {/* cards scrollable */}
      <div style={{ flex: 1, padding: 8, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {cards.map((c, i) => (
          <KanbanCard key={c.id} card={c} std={std} bottleneck={bottleneck} highlighted={i === 0 && col.id === 'AT_EMBROIDERY'} />
        ))}
        {cards.length === 0 && (
          <div style={{ padding: '20px 8px', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: 11.5, border: '1px dashed var(--border-default)', borderRadius: 6 }}>
            No lots in {col.label.toLowerCase()}
          </div>
        )}
      </div>
    </div>
  );
}

function KanbanCard({ card, std, bottleneck, highlighted }) {
  // age tint scale
  const ratio = card.age / std;
  let tint = null;
  let leftBorder = null;
  if (bottleneck) {
    if (ratio < 1)      tint = '#F2F8F4';
    else if (ratio < 2) tint = '#FBF6E9';
    else                tint = '#FBEDE6';
    if (ratio >= 2) leftBorder = '3px solid var(--danger)';
    else if (ratio >= 1) leftBorder = '3px solid var(--warning)';
    else leftBorder = '3px solid var(--success)';
  }

  return (
    <div style={{
      background: tint || 'var(--bg-surface)',
      border: '1px solid var(--border-subtle)',
      borderLeft: leftBorder || '1px solid var(--border-subtle)',
      borderRadius: 6, padding: '8px 10px',
      cursor: 'pointer',
      boxShadow: highlighted ? '0 0 0 2px var(--accent)' : 'none',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span className="mono" style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--accent)' }}>{card.id}</span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 10.5, fontWeight: 600,
          color: card.age > std ? 'var(--warning-text)' : 'var(--text-tertiary)',
        }}>{card.age}d</span>
      </div>
      <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text-primary)', lineHeight: 1.35, marginBottom: 5 }}>{card.item}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-tertiary)' }}>
        <span className="num" style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>{card.qty}</span>
        {card.who !== '—' && (
          <>
            <span>·</span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Monogram initials={card.who[0]} size={14} />
              {card.who}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/* Pipeline card slide-over — what opens when a card is tapped */
function PipelineCardSlideOver() {
  return (
    <div style={{ height: '100%', background: 'var(--bg-surface)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mono" style={{
            fontSize: 12, fontWeight: 600,
            padding: '3px 8px', borderRadius: 4,
            background: 'var(--accent-subtle)', color: 'var(--accent)',
          }}>LT-2026-0042</span>
          <StagePill stage="AT_EMBROIDERY" />
          <span style={{ fontSize: 11, color: 'var(--warning-text)', marginLeft: 'auto', fontWeight: 600 }}>39d in stage · 31d over</span>
        </div>
        <div style={{ fontSize: 15, fontWeight: 600, marginTop: 6 }}>Silk Georgette · Aari work</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>40 m at Karigar Imran · MO/25-26/000041 · for Khan Sarees</div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 18, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Section title="Quick actions">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <Button variant="primary" size="sm" icon="check">Receive back</Button>
            <Button variant="secondary" size="sm" icon="phone">Remind Imran</Button>
            <Button variant="secondary" size="sm" icon="message">WhatsApp photo</Button>
            <Button variant="secondary" size="sm" icon="alert">Flag rework</Button>
          </div>
        </Section>

        <Section title="Operations done">
          <ol style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: 12.5, color: 'var(--text-secondary)' }}>
            <OpDone done t="GRN intake · 12-Mar · 50 m" />
            <OpDone done t="Cut to pattern · 18-Mar · A-402" />
            <OpDone done={false} active t="Embroidery · since 18-Mar · Imran" />
            <OpDone done={false} t="QC review" />
            <OpDone done={false} t="Stitching · planned with Salim" />
          </ol>
        </Section>

        <Section title="Cost so far">
          <div style={{ background: 'var(--bg-sunken)', borderRadius: 6, padding: 12 }}>
            <CostRow k="Material" v="₹9,250" />
            <CostRow k="Cut labour" v="₹450" />
            <CostRow k="Embroidery (estimate)" v="₹3,800" />
            <div style={{ borderTop: '1px solid var(--border-default)', marginTop: 6, paddingTop: 6 }}>
              <CostRow k="Cost so far" v={<span style={{ fontWeight: 700 }}>₹13,500</span>} />
              <CostRow k="vs MO budget" v={<span style={{ color: 'var(--success-text)' }}>₹4,500 below</span>} small />
            </div>
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}
function OpDone({ done, active, t }) {
  return (
    <li style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0' }}>
      <span style={{
        width: 14, height: 14, borderRadius: '50%',
        background: done ? 'var(--accent)' : active ? 'transparent' : 'transparent',
        border: done ? 'none' : active ? '2px solid var(--warning)' : '1.5px dashed var(--border-strong)',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {done && <Icon name="check" size={9} color="#FFF" />}
      </span>
      <span style={{ color: done ? 'var(--text-primary)' : active ? 'var(--warning-text)' : 'var(--text-tertiary)', fontWeight: active ? 600 : 400 }}>{t}</span>
    </li>
  );
}
function CostRow({ k, v, small }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: small ? 11 : 12.5 }}>
      <span style={{ color: 'var(--text-tertiary)' }}>{k}</span>
      <span style={{ color: 'var(--text-primary)' }}>{v}</span>
    </div>
  );
}

/* Mobile pipeline — accordion */
function PipelineMobile() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '14px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)' }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Pipeline</h1>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>17 lots in flight</div>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {KANBAN_COLS.slice(0, 8).map((col, i) => {
          const cards = KCARDS.filter(c => c.stage === col.id);
          const expanded = col.id === 'AT_EMBROIDERY';
          const std = STANDARDS[col.id];
          const phaseTok = PHASE_TOKENS[col.phase];
          return (
            <div key={col.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10, background: expanded ? 'var(--bg-surface)' : 'transparent' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: phaseTok.accent }} />
                <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>{col.label}</span>
                <span className="num" style={{ fontSize: 12, color: 'var(--text-tertiary)', fontWeight: 600 }}>{cards.length}</span>
                <Icon name={expanded ? 'chevron-up' : 'chevron-down'} size={14} color="var(--text-tertiary)" />
              </div>
              {expanded && (
                <div style={{ padding: '0 12px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {cards.slice(0, 3).map(c => <KanbanCard key={c.id} card={c} std={std} bottleneck={false} />)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-MFG-002 — MO list
───────────────────────────────────────────────────────────── */
const MOS = [
  { id: 'MO/25-26/000041', sku: 'A-402 Bridal Suit',     qty: '20 sets', stage: 'AT_EMBROIDERY', start: '18-Mar', due: '08-May', cost: 13500, budget: 18000, prog: 0.55, customer: 'Khan Sarees',     state: 'on_track' },
  { id: 'MO/25-26/000042', sku: 'Maroon Banarasi Lehenga', qty: '12 sets', stage: 'AT_EMBROIDERY', start: '20-Mar', due: '12-May', cost: 22400, budget: 28000, prog: 0.45, customer: 'Tilfi Mumbai',    state: 'on_track' },
  { id: 'MO/25-26/000043', sku: 'Champagne Anarkali',    qty: '15 sets', stage: 'AT_HANDWORK',   start: '22-Mar', due: '02-May', cost: 18800, budget: 22000, prog: 0.70, customer: 'Aza Couture',     state: 'on_track' },
  { id: 'MO/25-26/000040', sku: 'Off-white Chanderi',    qty: '24 sets', stage: 'AT_DYEING',     start: '14-Mar', due: '28-Apr', cost: 7600,  budget: 14400, prog: 0.30, customer: 'Stock',           state: 'overdue', daysOver: 4 },
  { id: 'MO/25-26/000038', sku: 'Indigo Katan',          qty: '10 sets', stage: 'AT_HANDWORK',   start: '01-Mar', due: '20-Apr', cost: 24800, budget: 26000, prog: 0.85, customer: 'Pernia\'s Pop-up', state: 'overdue', daysOver: 7 },
  { id: 'MO/25-26/000037', sku: 'Tussar Anarkali',       qty: '20 sets', stage: 'AT_STITCHING',  start: '02-Mar', due: '24-Apr', cost: 9600,  budget: 16000, prog: 0.92, customer: 'Khan Sarees',     state: 'overdue', daysOver: 3 },
  { id: 'MO/25-26/000035', sku: 'Cotton Co-ord set',     qty: '60 pcs',  stage: 'FINISHED',      start: '20-Feb', due: '05-Apr', cost: 32400, budget: 36000, prog: 1.0,  customer: 'Stock',           state: 'done' },
  { id: 'MO/25-26/000028', sku: 'Bridal · Khan order',   qty: '24 sets', stage: 'PACKED',        start: '10-Feb', due: '20-Mar', cost: 78000, budget: 96000, prog: 1.0,  customer: 'Khan Sarees',     state: 'done' },
];

function MOList() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Manufacturing orders</h1>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>8 total · 5 in flight · 3 overdue · ₹2,07,100 cost-to-date</div>
        </div>
        <Button variant="secondary" size="sm" icon="download">Export</Button>
        <Button variant="primary" size="sm" icon="plus">New MO</Button>
      </div>

      <div style={{ padding: '10px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', background: 'var(--bg-canvas)' }}>
        <div style={{ width: 220 }}>
          <Input placeholder="Search MO, SKU, customer…" prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
        </div>
        <FilterChip label="All" active count={8} />
        <FilterChip label="In flight" count={5} />
        <FilterChip label="Overdue" count={3} />
        <FilterChip label="Done this month" count={2} />
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-tertiary)' }}>Sort by <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>Due date ↑</span></span>
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-sunken)' }}>
              <th style={thMO}>MO #</th>
              <th style={thMO}>SKU / Item</th>
              <th style={thMO}>Customer</th>
              <th style={thMO}>Stage</th>
              <th style={{...thMO, minWidth: 200}}>Progress</th>
              <th style={{...thMO, textAlign: 'right'}}>Qty</th>
              <th style={{...thMO, textAlign: 'right'}}>Cost / Budget</th>
              <th style={thMO}>Due</th>
              <th style={thMO}>Status</th>
            </tr>
          </thead>
          <tbody>
            {MOS.map((m, i) => (
              <tr key={m.id} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                <td className="mono" style={{...tdMO, color: 'var(--accent)', fontWeight: 600, fontSize: 12}}>{m.id}</td>
                <td style={{...tdMO, fontWeight: 500}}>{m.sku}</td>
                <td style={{...tdMO, color: 'var(--text-secondary)'}}>{m.customer}</td>
                <td style={tdMO}><StagePill stage={m.stage} /></td>
                <td style={tdMO}><MOProgress prog={m.prog} state={m.state} /></td>
                <td className="num" style={{...tdMO, textAlign: 'right'}}>{m.qty}</td>
                <td className="num" style={{...tdMO, textAlign: 'right'}}>
                  <div style={{ fontWeight: 500 }}>₹{m.cost.toLocaleString('en-IN')}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>of ₹{m.budget.toLocaleString('en-IN')}</div>
                </td>
                <td style={{...tdMO, color: 'var(--text-secondary)', whiteSpace: 'nowrap'}}>{m.due}</td>
                <td style={tdMO}><MOStatusPill state={m.state} daysOver={m.daysOver} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MOProgress({ prog, state }) {
  const color = state === 'overdue' ? 'var(--danger)' : state === 'done' ? 'var(--success)' : 'var(--accent)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--border-subtle)', borderRadius: 3, overflow: 'hidden', maxWidth: 140 }}>
        <div style={{ width: `${prog * 100}%`, height: '100%', background: color }} />
      </div>
      <span className="num" style={{ fontSize: 11.5, color: 'var(--text-secondary)', fontWeight: 500, minWidth: 32, textAlign: 'right' }}>{Math.round(prog * 100)}%</span>
    </div>
  );
}

function MOStatusPill({ state, daysOver }) {
  if (state === 'overdue') return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '3px 8px', borderRadius: 4, background: 'var(--danger-subtle)', color: 'var(--danger-text)', fontSize: 11, fontWeight: 600 }}>
      <Icon name="alert" size={11} />Overdue {daysOver}d
    </span>
  );
  if (state === 'done') return <Pill kind="finalized">Done</Pill>;
  return <Pill kind="info">On track</Pill>;
}

const thMO = { fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '8px 12px', textAlign: 'left', whiteSpace: 'nowrap' };
const tdMO = { padding: '12px 12px', verticalAlign: 'middle' };

/* ─────────────────────────────────────────────────────────────
   SCR-MFG-003 — MO Detail
───────────────────────────────────────────────────────────── */
function MODetail() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      {/* header */}
      <div style={{ padding: '16px 24px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>MOs › In flight</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>A-402 Bridal Suit</h1>
            <span className="mono" style={{ fontSize: 12, padding: '3px 8px', background: 'var(--bg-sunken)', borderRadius: 4 }}>MO/25-26/000041</span>
            <Pill kind="info">In progress</Pill>
            <StagePill stage="AT_EMBROIDERY" />
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>
            For Khan Sarees · 20 sets · started 18-Mar · due 08-May · 11 days remaining
          </div>
        </div>
        <Button variant="secondary" size="sm" icon="share">Share</Button>
        <Button variant="primary" size="sm" icon="send">Send out next op</Button>
      </div>

      {/* kpi strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}>
        <KPIBox k="Progress" v={<><span style={{ fontSize: 24, fontWeight: 700 }}>55<span style={{ fontSize: 14, color: 'var(--text-tertiary)' }}>%</span></span></>} sub="11 of 20 sets through embroidery" />
        <KPIBox k="Cost so far" v={<><span style={{ fontSize: 24, fontWeight: 700 }}>₹13,500</span></>} sub="of ₹18,000 budget · 25% headroom" />
        <KPIBox k="Wastage" v={<><span style={{ fontSize: 24, fontWeight: 700 }}>3.2<span style={{ fontSize: 14, color: 'var(--text-tertiary)' }}>%</span></span></>} sub="against 5% standard · within band" />
        <KPIBox k="At karigar" v={<><span style={{ fontSize: 24, fontWeight: 700 }}>40<span style={{ fontSize: 14, color: 'var(--text-tertiary)' }}>m</span></span></>} sub="Imran Sheikh · since 18-Mar" last />
      </div>

      {/* 3-column body */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1.1fr 1.4fr 1fr', minHeight: 0 }}>
        <MOBOM />
        <MOOps />
        <MOCost />
      </div>
    </div>
  );
}

function KPIBox({ k, v, sub, last }) {
  return (
    <div style={{ padding: '14px 18px', borderRight: last ? 'none' : '1px solid var(--border-subtle)' }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{k}</div>
      <div style={{ marginTop: 4 }}>{v}</div>
      <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 4 }}>{sub}</div>
    </div>
  );
}

function MOBOM() {
  const items = [
    { lot: 'LT-2026-0042', item: 'Silk Georgette 60GSM', need: '50 m',  used: '50 m',  state: 'consumed' },
    { lot: 'LT-2026-0043', item: 'Banarasi border',       need: '12 m', used: '12 m',  state: 'consumed' },
    { lot: 'LT-2026-0061', item: 'Inner lining',          need: '60 m', used: '40 m',  state: 'partial' },
    { lot: '—',            item: 'Zari trim 2cm',         need: '30 rl',used: '8 rl',   state: 'partial' },
    { lot: '—',            item: 'Fall hooks',            need: '40',   used: '0',     state: 'pending' },
  ];
  return (
    <div style={{ borderRight: '1px solid var(--border-subtle)', padding: 20, overflow: 'auto' }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-tertiary)' }}>BOM · materials</h3>
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
        {items.map((it, i) => (
          <div key={i} style={{
            padding: '10px 12px',
            borderBottom: i === items.length - 1 ? 'none' : '1px solid var(--border-subtle)',
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{it.item}</div>
              <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>{it.lot}</div>
            </div>
            <div className="num" style={{ fontSize: 11.5, color: 'var(--text-secondary)', textAlign: 'right' }}>
              {it.used} <span style={{ color: 'var(--text-tertiary)' }}>/ {it.need}</span>
            </div>
            <Pill kind={it.state}>{it.state}</Pill>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 14, padding: 12, borderRadius: 6, background: 'var(--bg-sunken)' }}>
        <Row k="Material cost (planned)" v="₹14,200" />
        <Row k="Material cost (actual)" v={<span style={{ color: 'var(--accent)', fontWeight: 600 }}>₹9,250</span>} />
      </div>
    </div>
  );
}

function MOOps() {
  const ops = [
    { name: 'Cutting',    who: 'Naseem (in-house)',  state: 'done',    qty: '50 m', t: '18-Mar', cost: '₹450' },
    { name: 'Embroidery', who: 'Karigar Imran',      state: 'active',  qty: '40 m at kgr', t: 'since 18-Mar · 39d', cost: '₹3,800 est' },
    { name: 'Embroidery', who: 'Karigar Salim (split)', state: 'active', qty: '10 m at kgr', t: 'since 18-Mar · 39d', cost: '₹950 est' },
    { name: 'QC',         who: 'Pooja',              state: 'queued',  qty: '12 m queued', t: '—', cost: '—' },
    { name: 'Stitching',  who: 'Karigar Salim',      state: 'planned', qty: '50 m planned', t: 'planned 06-May', cost: '₹6,500 budgeted' },
    { name: 'Finishing',  who: 'In-house',           state: 'planned', qty: '20 sets', t: 'planned 14-May', cost: '₹2,000 budgeted' },
  ];
  return (
    <div style={{ borderRight: '1px solid var(--border-subtle)', padding: 20, overflow: 'auto' }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-tertiary)' }}>Operations · timeline</h3>
      <div style={{ position: 'relative' }}>
        {ops.map((o, i) => <MOOpRow key={i} op={o} idx={i} isLast={i === ops.length - 1} />)}
      </div>
    </div>
  );
}

function MOOpRow({ op, idx, isLast }) {
  const isDone = op.state === 'done';
  const isActive = op.state === 'active';
  return (
    <div style={{ position: 'relative', paddingLeft: 32, paddingBottom: isLast ? 0 : 14 }}>
      {!isLast && (
        <div style={{
          position: 'absolute', left: 9, top: 22, bottom: 0, width: 0,
          borderLeft: isDone ? '2px solid var(--accent)'
                    : isActive ? '1.5px dashed var(--text-tertiary)'
                    : '1px dotted var(--border-strong)',
        }} />
      )}
      <div style={{
        position: 'absolute', left: 0, top: 4, width: 20, height: 20,
        borderRadius: '50%',
        background: isDone ? 'var(--accent)' : 'var(--bg-surface)',
        border: isDone ? '2px solid var(--accent)' : isActive ? '2px solid var(--warning)' : '1.5px dashed var(--border-strong)',
        boxShadow: isActive ? '0 0 0 3px rgba(162,103,16,0.10)' : 'none',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {isDone && <Icon name="check" size={11} color="#FFF" />}
        {isActive && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--warning)' }} />}
      </div>
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
        borderRadius: 6, padding: '10px 12px',
        opacity: op.state === 'planned' ? 0.7 : 1,
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{op.name}</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-tertiary)' }}>{op.t}</span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>{op.who}</div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 11.5 }}>
          <span style={{ color: 'var(--text-tertiary)' }}>{op.qty}</span>
          <span className="num" style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>{op.cost}</span>
        </div>
      </div>
    </div>
  );
}

function MOCost() {
  return (
    <div style={{ padding: 20, overflow: 'auto', background: 'var(--bg-surface)' }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-tertiary)' }}>Cost rollup</h3>
      <div style={{ background: 'var(--bg-sunken)', borderRadius: 8, padding: 14 }}>
        <CostBar label="Material" used={9250} budget={14200} color="var(--accent)" />
        <CostBar label="Cutting" used={450} budget={500} color="var(--info)" />
        <CostBar label="Embroidery" used={3800} budget={5500} color="var(--warning)" />
        <CostBar label="Stitching" used={0} budget={6500} color="var(--text-tertiary)" planned />
        <CostBar label="Finishing" used={0} budget={2000} color="var(--text-tertiary)" planned />
      </div>
      <div style={{ marginTop: 16, padding: 14, background: 'var(--bg-canvas)', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Forecast cost</span>
          <span className="num" style={{ fontSize: 18, fontWeight: 700 }}>₹17,200</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 4 }}>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Budget</span>
          <span className="num" style={{ fontSize: 14, color: 'var(--text-secondary)' }}>₹18,000</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 4 }}>
          <span style={{ fontSize: 12, color: 'var(--success-text)', fontWeight: 600 }}>Margin headroom</span>
          <span className="num" style={{ fontSize: 14, color: 'var(--success-text)', fontWeight: 700 }}>₹800 · 4%</span>
        </div>
      </div>
      <div style={{ marginTop: 16, padding: 14, borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>Selling price target</div>
        <div className="num" style={{ fontSize: 22, fontWeight: 700 }}>₹38,000 / set</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>Set cost ₹860 · GM 54%</div>
      </div>
    </div>
  );
}

function CostBar({ label, used, budget, color, planned }) {
  const pct = (used / budget) * 100;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, marginBottom: 4 }}>
        <span style={{ color: planned ? 'var(--text-tertiary)' : 'var(--text-secondary)', fontWeight: 500 }}>{label}{planned && ' (planned)'}</span>
        <span className="num" style={{ color: 'var(--text-secondary)' }}>
          ₹{used.toLocaleString('en-IN')} <span style={{ color: 'var(--text-tertiary)' }}>/ ₹{budget.toLocaleString('en-IN')}</span>
        </span>
      </div>
      <div style={{ height: 6, background: 'var(--border-subtle)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: color, opacity: planned ? 0.4 : 1 }} />
      </div>
    </div>
  );
}

Object.assign(window, {
  PipelineKanban, PipelineCardSlideOver, PipelineMobile,
  MOList, MODetail,
  KANBAN_COLS, KCARDS,
});
