// phase4-purchase.jsx — PO list, PO create, GRN with 3-way match, Purchase Invoice.

const { useState: useStateP } = React;

/* ─────────────────────────────────────────────────────────────
   SCR-PUR-001 — PO List
───────────────────────────────────────────────────────────── */

const POS = [
  { id: 'PO/25-26/00128', supplier: 'Reliance Industries Ltd',  date: '24-Apr', expected: '02-May', items: 4, amount: '4,82,000', status: 'sent',     daysOpen: 4,  starred: false },
  { id: 'PO/25-26/00127', supplier: 'Sangam Mills',             date: '22-Apr', expected: '28-Apr', items: 7, amount: '2,16,400', status: 'partial', daysOpen: 6,  starred: true  },
  { id: 'PO/25-26/00126', supplier: 'Welspun Yarn',             date: '20-Apr', expected: '25-Apr', items: 3, amount: '1,42,800', status: 'received',daysOpen: 0,  starred: false },
  { id: 'PO/25-26/00125', supplier: 'Banarasi Weavers',         date: '18-Apr', expected: '02-May', items: 5, amount: '6,80,000', status: 'sent',     daysOpen: 10, starred: false },
  { id: 'PO/25-26/00124', supplier: 'Anand Trims',              date: '17-Apr', expected: '21-Apr', items: 12,amount: '38,200',   status: 'partial', daysOpen: 11, starred: false },
  { id: 'PO/25-26/00123', supplier: 'Khurana Embroidery Wires', date: '14-Apr', expected: '20-Apr', items: 2, amount: '24,800',    status: 'received',daysOpen: 0,  starred: false },
  { id: 'PO/25-26/00122', supplier: 'Reliance Industries Ltd',  date: '12-Apr', expected: '18-Apr', items: 6, amount: '5,16,200', status: 'closed',  daysOpen: 0,  starred: false },
  { id: 'PO/25-26/00121', supplier: 'Hira Lal & Sons (Dyeing)', date: '10-Apr', expected: '14-Apr', items: 1, amount: '62,400',    status: 'closed',  daysOpen: 0,  starred: false },
  { id: 'PO/25-26/00120', supplier: 'Surat Trim Centre',        date: '08-Apr', expected: '12-Apr', items: 8, amount: '14,520',    status: 'draft',   daysOpen: 0,  starred: false },
];

const STATUS_PILLS = {
  draft:    { label: 'Draft',    bg: 'var(--bg-sunken)',         fg: 'var(--text-secondary)' },
  sent:     { label: 'Sent',     bg: 'var(--info-subtle)',       fg: 'var(--info-text)' },
  partial:  { label: 'Partial',  bg: 'var(--warning-subtle)',    fg: 'var(--warning-text)' },
  received: { label: 'Received', bg: 'var(--accent-subtle)',     fg: 'var(--accent)' },
  closed:   { label: 'Closed',   bg: 'var(--success-subtle)',    fg: 'var(--success-text)' },
};

function POStatusPill({ kind }) {
  const s = STATUS_PILLS[kind] || STATUS_PILLS.draft;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 8px',
      borderRadius: 4, background: s.bg, color: s.fg,
      fontSize: 11, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase',
    }}>{s.label}</span>
  );
}

function POList() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Purchase orders</h1>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
            9 total · 5 open · ₹19,77,420 in flight
          </div>
        </div>
        <Button variant="secondary" size="sm" icon="download">Export</Button>
        <Button variant="primary" size="sm" icon="plus">New PO</Button>
      </div>

      <div style={{ padding: '10px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ width: 240 }}>
          <Input placeholder="Search PO #, supplier, item…" prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
        </div>
        <FilterChip label="All" active count={9} />
        <FilterChip label="Draft" count={1} />
        <FilterChip label="Sent" count={2} />
        <FilterChip label="Partial" count={2} />
        <FilterChip label="Received" count={2} />
        <FilterChip label="Closed" count={2} />
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-tertiary)' }}>FY 25-26 · April</span>
      </div>

      <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg-surface)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-sunken)' }}>
              <th style={thPO}>PO #</th>
              <th style={thPO}>Supplier</th>
              <th style={thPO}>PO date</th>
              <th style={thPO}>Expected</th>
              <th style={{...thPO, textAlign: 'right'}}>Items</th>
              <th style={{...thPO, textAlign: 'right'}}>Amount ₹</th>
              <th style={thPO}>Status</th>
              <th style={{...thPO, textAlign: 'right'}}>Days open</th>
              <th style={{...thPO, width: 36}}></th>
            </tr>
          </thead>
          <tbody>
            {POS.map((po, i) => (
              <tr key={po.id} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                <td className="mono" style={{...tdPO, color: 'var(--accent)', fontWeight: 600, fontSize: 12}}>{po.id}</td>
                <td style={{...tdPO, fontWeight: 500}}>{po.supplier}</td>
                <td style={{...tdPO, color: 'var(--text-secondary)'}}>{po.date}</td>
                <td style={{...tdPO, color: po.daysOpen > 7 ? 'var(--warning-text)' : 'var(--text-secondary)'}}>{po.expected}</td>
                <td className="num" style={{...tdPO, textAlign: 'right'}}>{po.items}</td>
                <td className="num" style={{...tdPO, textAlign: 'right', fontWeight: 500}}>₹{po.amount}</td>
                <td style={tdPO}><POStatusPill kind={po.status} /></td>
                <td className="num" style={{...tdPO, textAlign: 'right', color: po.daysOpen > 7 ? 'var(--warning-text)' : 'var(--text-tertiary)', fontWeight: po.daysOpen > 7 ? 600 : 400}}>
                  {po.daysOpen > 0 ? `${po.daysOpen}d` : '—'}
                </td>
                <td style={tdPO}><button style={iconBtnPO} aria-label="More"><Icon name="menu-more" size={14} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const thPO = { fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '8px 12px', textAlign: 'left', whiteSpace: 'nowrap' };
const tdPO = { padding: '12px 12px', verticalAlign: 'middle' };
const iconBtnPO = { width: 24, height: 24, borderRadius: 4, border: 'none', background: 'transparent', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-tertiary)', cursor: 'pointer' };

/* ─────────────────────────────────────────────────────────────
   SCR-PUR-002 — PO Create
───────────────────────────────────────────────────────────── */
function POCreate() {
  const lines = [
    { sno: 1, item: 'Silk Georgette 60GSM White',  hsn: '5407', qty: 250, uom: 'm',  rate: 185,  disc: 0,  tax: 5, amount: 46250, lastCost: 182, lastSup: 'Reliance', stock: 248 },
    { sno: 2, item: 'Banarasi Silk 90GSM Maroon',  hsn: '5407', qty: 150, uom: 'm',  rate: 620,  disc: 2,  tax: 5, amount: 91140, lastCost: 615, lastSup: 'Banarasi Weavers', stock: 184 },
    { sno: 3, item: 'Crepe Double 42 Blush',       hsn: '5407', qty: 200, uom: 'm',  rate: 138,  disc: 0,  tax: 5, amount: 27600, lastCost: 142, lastSup: 'Reliance', stock: 320 },
    { sno: 4, item: 'Zari Trim Gold 2 cm',         hsn: '5808', qty: 40,  uom: 'rl', rate: 1240, disc: 5,  tax: 12,amount: 47120, lastCost: 1240, lastSup: 'Khurana', stock: 18 },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '16px 24px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Purchase › New PO</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>New purchase order</h1>
            <Pill kind="draft">Draft</Pill>
          </div>
        </div>
        <Button variant="secondary" size="sm">Save draft</Button>
        <span title="Coming soon — Phase 4 of platform" style={{ display: 'inline-flex' }}>
          <Button variant="secondary" size="sm" icon="message" state="disabled">Send via WhatsApp</Button>
        </span>
        <Button variant="primary" size="sm" icon="send">Send to supplier</Button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, padding: 24 }}>
        {/* form */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Field label="Supplier" required>
            <SupplierComboboxValue />
          </Field>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <Field label="PO date">
              <Input value="27-Apr-2026" suffix={<Icon name="calendar" size={14} />} />
            </Field>
            <Field label="Expected delivery" hint="2-day window">
              <Input value="04-May → 06-May" suffix={<Icon name="calendar" size={14} />} />
            </Field>
            <Field label="Reference" helper="Linked SO / MO">
              <div style={{
                border: '1px solid var(--border-default)', borderRadius: 6, padding: '0 10px',
                height: 40, display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span className="mono" style={{ fontSize: 11.5, padding: '2px 6px', borderRadius: 4, background: 'var(--accent-subtle)', color: 'var(--accent)', fontWeight: 600 }}>MO/000041</span>
                <span style={{ fontSize: 12.5, color: 'var(--text-secondary)', flex: 1 }}>A-402 Bridal Suit</span>
                <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
              </div>
            </Field>
          </div>

          {/* line items */}
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
              <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Items</h3>
              <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>4 lines · 640 m + 40 rl total</span>
            </div>
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-sunken)' }}>
                    <th style={thPO}>#</th>
                    <th style={thPO}>Item</th>
                    <th style={thPO}>HSN</th>
                    <th style={{...thPO, textAlign: 'right'}}>Qty</th>
                    <th style={thPO}>UOM</th>
                    <th style={{...thPO, textAlign: 'right'}}>Rate</th>
                    <th style={{...thPO, textAlign: 'right'}}>Disc %</th>
                    <th style={{...thPO, textAlign: 'right'}}>Tax %</th>
                    <th style={{...thPO, textAlign: 'right'}}>Amount</th>
                    <th style={{...thPO, width: 24}}></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => (
                    <tr key={l.sno} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                      <td style={{...tdPO, padding: '8px 12px', color: 'var(--text-tertiary)'}}>{l.sno}</td>
                      <td style={{...tdPO, padding: '8px 12px'}}>
                        <div style={{ fontWeight: 500 }}>{l.item}</div>
                        <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 1 }}>
                          Last ₹{l.lastCost} · {l.lastSup} · stock {l.stock}{l.uom}
                        </div>
                      </td>
                      <td className="mono" style={{...tdPO, padding: '8px 12px', fontSize: 11.5, color: 'var(--text-secondary)'}}>{l.hsn}</td>
                      <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right', fontWeight: 500}}>{l.qty}</td>
                      <td style={{...tdPO, padding: '8px 12px', color: 'var(--text-tertiary)', fontSize: 11}}>{l.uom}</td>
                      <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right'}}>
                        ₹{l.rate}
                        {l.lastCost !== l.rate && (
                          <div style={{ fontSize: 10, color: l.rate > l.lastCost ? 'var(--danger-text)' : 'var(--success-text)', fontWeight: 500 }}>
                            {l.rate > l.lastCost ? '↑' : '↓'} {Math.abs(((l.rate - l.lastCost) / l.lastCost) * 100).toFixed(1)}%
                          </div>
                        )}
                      </td>
                      <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right', color: l.disc ? 'var(--accent)' : 'var(--text-tertiary)'}}>{l.disc ? `${l.disc}%` : '—'}</td>
                      <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right', color: 'var(--text-secondary)'}}>{l.tax}%</td>
                      <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right', fontWeight: 600}}>₹{l.amount.toLocaleString('en-IN')}</td>
                      <td style={{...tdPO, padding: '8px 12px'}}><button style={iconBtnPO} aria-label="Remove"><Icon name="x" size={12} /></button></td>
                    </tr>
                  ))}
                  <tr style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td colSpan="10" style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-tertiary)', fontStyle: 'italic' }}>+ Add line — type item code or name</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <Field label="Terms & conditions" helper="Default: Net 30 · Delivery at warehouse · GST extra">
            <textarea readOnly defaultValue="Payment: Net 30 from invoice date. Delivery FOR Surat warehouse, GST extra at applicable rates. Goods to be accompanied by mill test certificate and dye lot card. Quantity tolerance ±2%." style={{
              width: '100%', minHeight: 80, padding: 12, fontFamily: 'inherit', fontSize: 12.5,
              border: '1px solid var(--border-default)', borderRadius: 6, resize: 'vertical', color: 'var(--text-primary)',
            }} />
          </Field>
        </div>

        {/* totals card */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
            borderRadius: 8, padding: 16, position: 'sticky', top: 0,
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>Totals</div>
            <Row k="Subtotal" v="₹2,12,110.00" />
            <Row k="Discount" v={<span style={{ color: 'var(--accent)' }}>−₹4,179.20</span>} />
            <Row k="Taxable value" v="₹2,07,930.80" />
            <Row k="CGST + SGST" v="₹14,283.06" />
            <Row k="Round-off" v="₹0.14" />
            <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 10, marginTop: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Total</span>
              <span className="num" style={{ fontSize: 22, fontWeight: 700 }}>₹2,22,214</span>
            </div>
          </div>

          <div style={{
            background: 'var(--warning-subtle)', border: '1px solid #E8C880',
            borderRadius: 8, padding: 14,
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--warning-text)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>Reliance — running balance</div>
            <div className="num" style={{ fontSize: 22, fontWeight: 700, color: 'var(--warning-text)' }}>₹4,82,000</div>
            <div style={{ fontSize: 11.5, color: 'var(--warning-text)', marginTop: 4 }}>
              Payable on PO/00128 · due 15-May. Last GRN 02-Apr.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SupplierComboboxValue() {
  return (
    <div style={{
      border: '1.5px solid var(--accent)', borderRadius: 6, padding: '8px 12px',
      background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <Monogram initials="RI" size={32} tone="indigo" />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>Reliance Industries Ltd</span>
          <span className="mono" style={{ fontSize: 10.5, padding: '1px 6px', borderRadius: 3, background: 'var(--bg-sunken)' }}>27AAACR5055K1Z2</span>
          <Pill kind="info">Registered</Pill>
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 2 }}>
          Mumbai, Maharashtra · Last GRN 02-Apr · <span style={{ color: 'var(--warning-text)', fontWeight: 500 }}>₹4,82,000 payable</span>
        </div>
      </div>
      <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 12.5 }}>
      <span style={{ color: 'var(--text-tertiary)' }}>{k}</span>
      <span className="num" style={{ color: 'var(--text-primary)' }}>{v}</span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-PUR-003 — GRN with 3-way match
───────────────────────────────────────────────────────────── */

const GRN_LINES = [
  { sno: 1, item: 'Silk Georgette 60GSM White',  poQty: 250, recv: 248, lot: 'LT-2026-0042', width: '44 in', gsm: 60, shade: 'Off-white', dye: 'DB-2026-014', qc: 'accept' },
  { sno: 2, item: 'Banarasi Silk 90GSM Maroon',  poQty: 150, recv: 152, lot: 'LT-2026-0058', width: '44 in', gsm: 90, shade: 'Deep maroon', dye: 'DB-2026-019', qc: 'accept' },
  { sno: 3, item: 'Crepe Double 42 Blush',       poQty: 200, recv: 188, lot: 'LT-2026-0061', width: '42 in', gsm: 65, shade: 'Light blush', dye: 'DB-2026-022', qc: 'reject', reason: 'Shade variation, lot 2 of 3 differs from approved swatch' },
  { sno: 4, item: 'Zari Trim Gold 2 cm',         poQty: 40,  recv: 40,  lot: 'TRM-2026-008', width: '2 cm',  gsm: '—',shade: 'Gold',        dye: '—',           qc: 'accept' },
];

function GRNScreen() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '16px 24px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Purchase › Goods Receipt Note</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>GRN/25-26/00094</h1>
            <Pill kind="draft">Draft</Pill>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>against</span>
            <span className="mono" style={{ fontSize: 11.5, padding: '3px 8px', background: 'var(--accent-subtle)', color: 'var(--accent)', borderRadius: 4, fontWeight: 600 }}>PO/25-26/00128</span>
          </div>
        </div>
        <Button variant="secondary" size="sm">Save draft</Button>
        <Button variant="primary" size="sm" icon="check">Post & receive into stock</Button>
      </div>

      {/* meta strip */}
      <div style={{ padding: '14px 24px', background: 'var(--bg-sunken)', borderBottom: '1px solid var(--border-subtle)', display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 18 }}>
        <SmallStatP k="Supplier"        v="Reliance Industries Ltd" />
        <SmallStatP k="Supplier challan #" v="DC-9871" mono />
        <SmallStatP k="Vehicle #"       v="GJ 05 KH 4421" mono />
        <SmallStatP k="Transporter"     v="Patel Roadways" />
        <SmallStatP k="Received on"     v="27-Apr · 16:42" sub="by Naseem" />
      </div>

      {/* body grid */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 360px', minHeight: 0 }}>
        {/* receipt table */}
        <div style={{ overflow: 'auto', padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Receipt</h3>
            <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>4 PO lines · 1 short, 1 excess, 1 reject</span>
          </div>
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ background: 'var(--bg-sunken)' }}>
                  <th style={thPO}>#</th>
                  <th style={thPO}>Item · Lot</th>
                  <th style={{...thPO, textAlign: 'right'}}>PO qty</th>
                  <th style={{...thPO, textAlign: 'right'}}>Received</th>
                  <th style={{...thPO, textAlign: 'right'}}>Δ</th>
                  <th style={thPO}>Attributes</th>
                  <th style={thPO}>QC</th>
                </tr>
              </thead>
              <tbody>
                {GRN_LINES.map((l, i) => {
                  const delta = l.recv - l.poQty;
                  const reject = l.qc === 'reject';
                  return (
                    <tr key={l.sno} style={{
                      borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                      background: reject ? 'rgba(181,49,30,0.04)' : 'transparent',
                    }}>
                      <td style={{...tdPO, padding: '10px 12px', color: 'var(--text-tertiary)'}}>{l.sno}</td>
                      <td style={{...tdPO, padding: '10px 12px'}}>
                        <div style={{ fontWeight: 500 }}>{l.item}</div>
                        <div className="mono" style={{ fontSize: 10.5, color: 'var(--accent)', marginTop: 2, fontWeight: 600 }}>{l.lot}</div>
                      </td>
                      <td className="num" style={{...tdPO, padding: '10px 12px', textAlign: 'right', color: 'var(--text-secondary)'}}>{l.poQty}</td>
                      <td className="num" style={{...tdPO, padding: '10px 12px', textAlign: 'right', fontWeight: 600}}>{l.recv}</td>
                      <td className="num" style={{...tdPO, padding: '10px 12px', textAlign: 'right'}}>
                        <DeltaPill delta={delta} />
                      </td>
                      <td style={{...tdPO, padding: '10px 12px'}}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {[
                            ['W', l.width], ['GSM', l.gsm], ['Shade', l.shade], ['Dye', l.dye],
                          ].map(([k, v]) => v !== '—' && (
                            <span key={k} style={{
                              fontSize: 10.5, padding: '1px 6px', borderRadius: 3,
                              background: 'var(--bg-sunken)', color: 'var(--text-secondary)',
                              border: '1px solid var(--border-subtle)',
                            }}>
                              <span style={{ color: 'var(--text-tertiary)' }}>{k} </span>{v}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td style={{...tdPO, padding: '10px 12px'}}>
                        <QCToggle accept={!reject} reason={l.reason} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* 3-way match rail */}
        <div style={{ borderLeft: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', padding: 24, overflow: 'auto' }}>
          <h3 style={{ margin: '0 0 14px', fontSize: 14, fontWeight: 600 }}>Three-way match</h3>
          <div style={{
            background: 'var(--bg-canvas)', border: '1px solid var(--border-subtle)',
            borderRadius: 10, padding: 16,
          }}>
            <ThreeWayMatch />
          </div>

          <div style={{
            marginTop: 14, padding: 12, borderRadius: 8,
            background: 'var(--warning-subtle)', border: '1px solid #E8C880',
          }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <Icon name="alert" size={16} color="var(--warning-text)" />
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--warning-text)' }}>Mismatch with PO</div>
                <div style={{ fontSize: 11.5, color: 'var(--warning-text)', marginTop: 3, lineHeight: 1.5 }}>
                  Crepe Double Blush short by 12 m and rejected on shade. PI will need to be raised for 628 m, not 640 m.
                </div>
                <button style={{
                  marginTop: 6, background: 'transparent', border: 'none', cursor: 'pointer',
                  fontSize: 11.5, fontWeight: 600, color: 'var(--warning-text)', textDecoration: 'underline',
                  padding: 0,
                }}>Open discrepancy report →</button>
              </div>
            </div>
          </div>

          <div style={{ marginTop: 18 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>What happens next</div>
            <ol style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: 12, color: 'var(--text-secondary)' }}>
              <Step n={1} t="Accepted lots flow into Raw stock with auto-generated lot IDs" />
              <Step n={2} t="Rejected lot held in QC bay; debit note draft created against supplier" />
              <Step n={3} t="3-way match panel updates when PI is created" />
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}

function DeltaPill({ delta }) {
  if (delta === 0) return <span style={{ fontSize: 11.5, color: 'var(--success-text)', fontWeight: 600 }}>match</span>;
  const over = delta > 0;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 2,
      padding: '2px 6px', borderRadius: 3,
      background: over ? 'var(--info-subtle)' : 'var(--danger-subtle)',
      color: over ? 'var(--info-text)' : 'var(--danger-text)',
      fontSize: 11, fontWeight: 600,
    }}>
      {over ? '+' : ''}{delta}
    </span>
  );
}

function QCToggle({ accept, reason }) {
  return (
    <div>
      <div style={{
        display: 'inline-flex', borderRadius: 4, overflow: 'hidden',
        border: '1px solid var(--border-default)', background: 'var(--bg-surface)',
      }}>
        <span style={{
          padding: '3px 8px', fontSize: 10.5, fontWeight: 600,
          background: accept ? 'var(--accent)' : 'transparent',
          color: accept ? '#FFF' : 'var(--text-secondary)',
          letterSpacing: '0.04em', textTransform: 'uppercase',
        }}>Accept</span>
        <span style={{
          padding: '3px 8px', fontSize: 10.5, fontWeight: 600,
          background: !accept ? 'var(--danger)' : 'transparent',
          color: !accept ? '#FFF' : 'var(--text-secondary)',
          letterSpacing: '0.04em', textTransform: 'uppercase',
        }}>Reject</span>
      </div>
      {reason && <div style={{ fontSize: 10.5, color: 'var(--danger-text)', marginTop: 4, maxWidth: 180, lineHeight: 1.4 }}>{reason}</div>}
    </div>
  );
}

function ThreeWayMatch({ poStatus = 'matched', grnStatus = 'mismatched', piStatus = 'pending', poAmt = '2,22,214', grnAmt = '2,07,930', piAmt = null }) {
  const docs = [
    { id: 'PO', label: 'Purchase Order', sub: 'PO/25-26/00128', amt: poAmt, status: poStatus },
    { id: 'GRN', label: 'Goods Receipt', sub: 'GRN/25-26/00094', amt: grnAmt, status: grnStatus },
    { id: 'PI', label: 'Purchase Invoice', sub: piStatus === 'pending' ? 'Not yet created' : 'PI/25-26/00072', amt: piAmt, status: piStatus },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {docs.map((d, i) => {
        const active = d.status !== 'pending';
        const ok = d.status === 'matched';
        const mismatched = d.status === 'mismatched';
        return (
          <div key={d.id}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 0',
              opacity: active ? 1 : 0.45,
            }}>
              <div style={{
                width: 36, height: 36, borderRadius: '50%',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                background: ok ? 'var(--accent)' : mismatched ? 'var(--warning-subtle)' : 'transparent',
                color: ok ? '#FFF' : mismatched ? 'var(--warning-text)' : 'var(--text-tertiary)',
                border: ok ? 'none' : mismatched ? '2px solid var(--warning)' : '1.5px dashed var(--border-strong)',
                flexShrink: 0,
              }}>
                {ok && <Icon name="check" size={16} />}
                {mismatched && <Icon name="alert" size={16} />}
                {!active && <span className="mono" style={{ fontSize: 11, fontWeight: 600 }}>{d.id}</span>}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: active ? 'var(--text-primary)' : 'var(--text-tertiary)' }}>{d.label}</div>
                <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 1 }}>{d.sub}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                {d.amt && <div className="num" style={{ fontSize: 14, fontWeight: 600 }}>₹{d.amt}</div>}
                {!d.amt && <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>—</div>}
                <div style={{
                  fontSize: 9.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                  color: ok ? 'var(--accent)' : mismatched ? 'var(--warning-text)' : 'var(--text-tertiary)',
                  marginTop: 2,
                }}>{d.status === 'matched' ? 'matched' : d.status === 'mismatched' ? 'mismatch' : 'pending'}</div>
              </div>
            </div>
            {i < docs.length - 1 && (
              <div style={{ marginLeft: 17, paddingLeft: 0, height: 14, borderLeft: i === 0 ? '2px solid var(--accent)' : '1.5px dashed var(--border-strong)' }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function SmallStatP({ k, v, sub, mono }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{k}</div>
      <div className={mono ? 'mono' : ''} style={{ fontSize: 13, fontWeight: 600, marginTop: 2 }}>{v}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{sub}</div>}
    </div>
  );
}

function Step({ n, t }) {
  return (
    <li style={{ display: 'flex', gap: 8, padding: '4px 0' }}>
      <span style={{
        width: 16, height: 16, borderRadius: '50%', background: 'var(--accent-subtle)', color: 'var(--accent)',
        fontSize: 10, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}>{n}</span>
      <span>{t}</span>
    </li>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-PUR-004 — Purchase Invoice
───────────────────────────────────────────────────────────── */
function PurchaseInvoice() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '16px 24px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Purchase › Purchase invoice</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>PI/25-26/00072</h1>
            <Pill kind="draft">Draft</Pill>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>linked</span>
            <span className="mono" style={{ fontSize: 11.5, padding: '3px 8px', background: 'var(--accent-subtle)', color: 'var(--accent)', borderRadius: 4, fontWeight: 600 }}>PO/00128</span>
            <span className="mono" style={{ fontSize: 11.5, padding: '3px 8px', background: 'var(--accent-subtle)', color: 'var(--accent)', borderRadius: 4, fontWeight: 600 }}>GRN/00094</span>
          </div>
        </div>
        <Button variant="secondary" size="sm">Hold for clarification</Button>
        <Button variant="primary" size="sm" icon="check">Accept & post</Button>
      </div>

      {/* FY warning */}
      <div style={{
        padding: '12px 24px', background: 'var(--warning-subtle)',
        borderBottom: '1px solid #E8C880', display: 'flex', gap: 10, alignItems: 'center',
      }}>
        <Icon name="alert" size={16} color="var(--warning-text)" />
        <div style={{ fontSize: 12.5, color: 'var(--warning-text)' }}>
          <strong>FY mismatch:</strong> Supplier invoice dated <span className="mono">23-Mar-2026</span> belongs to FY 25-26, but goods received <span className="mono">27-Apr-2026</span> falls in FY 26-27.
          Will be booked to <strong>FY 25-26</strong> per invoice date.
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'grid', gridTemplateColumns: '1fr 380px', gap: 20, padding: 24 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <Field label="Supplier invoice #" required>
              <Input value="RIL/INV/89421" />
            </Field>
            <Field label="Supplier invoice date" required hint="FY 25-26">
              <Input value="23-Mar-2026" />
            </Field>
            <Field label="Place of supply">
              <Input value="Maharashtra (27)" />
            </Field>
          </div>

          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <h3 style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>Lines · auto-pulled from GRN</h3>
              <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>4 lines · accepted only</span>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-sunken)' }}>
                  <th style={thPO}>#</th>
                  <th style={thPO}>Item</th>
                  <th style={{...thPO, textAlign: 'right'}}>Qty</th>
                  <th style={{...thPO, textAlign: 'right'}}>Rate</th>
                  <th style={{...thPO, textAlign: 'right'}}>Taxable</th>
                  <th style={{...thPO, textAlign: 'right'}}>IGST 5%</th>
                  <th style={{...thPO, textAlign: 'right'}}>Amount</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['Silk Georgette 60GSM',  '248 m', '₹185',  45880, 2294, 48174],
                  ['Banarasi Silk 90GSM',   '152 m', '₹620',  94240, 4712, 98952],
                  ['Crepe Double 42 Blush — REJECTED', '0 m','₹138',  0,     0,    0],
                  ['Zari Trim Gold 2 cm',   '40 rl','₹1,178',47120, 5654, 52774],
                ].map((r, i) => (
                  <tr key={i} style={{
                    borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                    opacity: r[0].includes('REJECTED') ? 0.45 : 1,
                  }}>
                    <td style={{...tdPO, padding: '8px 12px', color: 'var(--text-tertiary)'}}>{i+1}</td>
                    <td style={{...tdPO, padding: '8px 12px'}}>{r[0]}</td>
                    <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right', color: 'var(--text-secondary)'}}>{r[1]}</td>
                    <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right', color: 'var(--text-secondary)'}}>{r[2]}</td>
                    <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right'}}>₹{r[3].toLocaleString('en-IN')}</td>
                    <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right', color: 'var(--text-secondary)'}}>₹{r[4].toLocaleString('en-IN')}</td>
                    <td className="num" style={{...tdPO, padding: '8px 12px', textAlign: 'right', fontWeight: 600}}>₹{r[5].toLocaleString('en-IN')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 3-way match panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
            borderRadius: 10, padding: 16,
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 12 }}>3-way match</div>
            <ThreeWayMatch
              poStatus="matched" grnStatus="matched" piStatus="mismatched"
              poAmt="2,22,214" grnAmt="2,07,930" piAmt="1,99,900"
            />
            <div style={{
              marginTop: 14, padding: 10, borderRadius: 6,
              background: 'var(--warning-subtle)', border: '1px solid #E8C880',
              fontSize: 12, color: 'var(--warning-text)',
            }}>
              <strong>PI ₹8,030 below GRN.</strong> Supplier honoured 5% short-shipment discount on Crepe Double — verify before accepting.
            </div>
          </div>

          <div style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
            borderRadius: 10, padding: 16,
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Supplier ledger impact</div>
            <Row k="Existing payable" v="₹4,82,000" />
            <Row k="This invoice" v="+ ₹1,99,900" />
            <Row k="Less: rejected (debit note)" v={<span style={{ color: 'var(--accent)' }}>− ₹0</span>} />
            <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 8, marginTop: 6 }}>
              <Row k="New payable" v={<span style={{ fontWeight: 700, fontSize: 14 }}>₹6,81,900</span>} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  POList, POCreate, GRNScreen, PurchaseInvoice, ThreeWayMatch, POStatusPill,
});
