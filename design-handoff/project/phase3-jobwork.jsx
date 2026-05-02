// phase3-jobwork.jsx — Job work send-out, receive-back, karigar list.

const { useState: useStateJ } = React;

const KARIGARS = [
  { id: 'IMR', name: 'Imran Sheikh',     ops: ['Embroidery'],          city: 'Surat',     atQty: 40, outLabour: 28500, lastAct: '2h ago',  std: 5.0, photo: false, kyc: true,  whatsapp: true },
  { id: 'SAL', name: 'Salim Ansari',     ops: ['Stitching'],           city: 'Mumbai',    atQty: 24, outLabour: 18200, lastAct: '5h ago',  std: 3.5, photo: false, kyc: true,  whatsapp: true },
  { id: 'ANW', name: 'Anwar Quraishi',   ops: ['Handwork'],            city: 'Bareilly',  atQty: 64, outLabour: 41800, lastAct: '1d ago',  std: 4.0, photo: false, kyc: true,  whatsapp: false },
  { id: 'POO', name: 'Pooja Devi',       ops: ['QC'],                  city: 'Surat',     atQty: 0,  outLabour: 4200,  lastAct: '20m ago', std: 0,   photo: false, kyc: true,  whatsapp: true },
  { id: 'NAS', name: 'Naseem Bibi',      ops: ['Cutting'],             city: 'Surat',     atQty: 0,  outLabour: 0,     lastAct: '10m ago', std: 1.5, photo: false, kyc: true,  whatsapp: false },
  { id: 'YAS', name: 'Yasin Khan',       ops: ['Embroidery','Handwork'],city:'Lucknow',   atQty: 18, outLabour: 12400, lastAct: '3d ago',  std: 6.0, photo: false, kyc: false, whatsapp: true },
  { id: 'RAJ', name: 'Rajesh Tailor',    ops: ['Stitching'],           city: 'Surat',     atQty: 32, outLabour: 9600,  lastAct: '6h ago',  std: 4.5, photo: false, kyc: true,  whatsapp: true },
  { id: 'FAR', name: 'Farida Begum',     ops: ['Handwork'],            city: 'Bhopal',    atQty: 0,  outLabour: 0,     lastAct: '30d ago', std: 5.0, photo: false, kyc: true,  whatsapp: false },
];

const opTokens = {
  Cutting:    { fg: 'var(--info-text)',     bg: 'var(--info-subtle)' },
  Dyeing:     { fg: 'var(--info-text)',     bg: 'var(--info-subtle)' },
  Embroidery: { fg: 'var(--warning-text)',  bg: 'var(--warning-subtle)' },
  Handwork:   { fg: 'var(--warning-text)',  bg: 'var(--warning-subtle)' },
  Stitching:  { fg: 'var(--accent)',        bg: 'var(--accent-subtle)' },
  Washing:    { fg: 'var(--info-text)',     bg: 'var(--info-subtle)' },
  QC:         { fg: 'var(--text-secondary)',bg: 'var(--bg-sunken)' },
};
function OpChip({ name, size = 'sm' }) {
  const t = opTokens[name] || opTokens.QC;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: size === 'sm' ? 20 : 24,
      padding: size === 'sm' ? '0 7px' : '0 10px',
      borderRadius: 4, background: t.bg, color: t.fg,
      fontSize: size === 'sm' ? 10.5 : 11.5, fontWeight: 600,
      letterSpacing: '0.04em', textTransform: 'uppercase',
    }}>{name}</span>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-JOB-001 — Send Out form
───────────────────────────────────────────────────────────── */
function JobSendOut() {
  const lots = [
    { lot: 'LT-2026-0042', item: 'Silk Georgette 60GSM White',  qty: 40, rate: 95,  total: 3800 },
    { lot: 'LT-2026-0058', item: 'Banarasi Silk 90GSM Maroon',  qty: 24, rate: 145, total: 3480 },
    { lot: 'LT-2026-0061', item: 'Dola Silk 44 Champagne',      qty: 18, rate: 110, total: 1980 },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      {/* header */}
      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Job work › New</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Send out to karigar</h1>
            <Pill kind="draft">Draft</Pill>
          </div>
        </div>
        <Button variant="secondary" size="sm">Save draft</Button>
        <Button variant="primary" size="sm" icon="send">Send out & print challan</Button>
      </div>

      {/* body */}
      <div style={{ flex: 1, padding: 24, display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, minHeight: 0, overflow: 'auto' }}>
        {/* form column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Field label="Karigar" required>
            <KarigarComboboxValue />
          </Field>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Field label="Operation" required>
              <div style={{
                border: '1px solid var(--border-default)', borderRadius: 6, padding: '0 12px',
                height: 40, display: 'flex', alignItems: 'center', gap: 10, background: 'var(--bg-surface)',
              }}>
                <OpChip name="Embroidery" />
                <span style={{ fontSize: 13, color: 'var(--text-secondary)', flex: 1 }}>Aari work</span>
                <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
              </div>
            </Field>
            <Field label="Expected return" hint="Imran's standard 8 days">
              <Input value="06-May-2026" suffix={<Icon name="calendar" size={14} />} />
            </Field>
          </div>

          <Field label="Instructions" helper="Visible on the karigar's WhatsApp message and on the printed challan">
            <textarea readOnly defaultValue="Aari work on bridal motif as per design A-402. Match dye batch DB-2026-014 — no shade variation across pieces. Photo of first piece before scaling up." style={{
              width: '100%', minHeight: 80, padding: 12, fontFamily: 'inherit', fontSize: 13,
              border: '1px solid var(--border-default)', borderRadius: 6, resize: 'vertical', color: 'var(--text-primary)',
            }} />
          </Field>

          {/* lot table */}
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
              <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Lots being sent</h3>
              <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>3 lots · 82.00 m total</span>
            </div>
            <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-sunken)' }}>
                    <th style={thJob}>#</th>
                    <th style={thJob}>Lot</th>
                    <th style={thJob}>Item</th>
                    <th style={{...thJob, textAlign: 'right'}}>Qty out</th>
                    <th style={{...thJob, textAlign: 'right'}}>Rate</th>
                    <th style={{...thJob, textAlign: 'right'}}>Estimated</th>
                    <th style={{...thJob, width: 28}}></th>
                  </tr>
                </thead>
                <tbody>
                  {lots.map((l, i) => (
                    <tr key={l.lot} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                      <td style={{...tdJob, color: 'var(--text-tertiary)'}}>{i+1}</td>
                      <td className="mono" style={{...tdJob, color: 'var(--accent)', fontWeight: 600}}>{l.lot}</td>
                      <td style={tdJob}>{l.item}</td>
                      <td className="num" style={{...tdJob, textAlign: 'right', fontWeight: 500}}>{l.qty.toFixed(2)} m</td>
                      <td className="num" style={{...tdJob, textAlign: 'right', color: 'var(--text-secondary)'}}>₹{l.rate}</td>
                      <td className="num" style={{...tdJob, textAlign: 'right', fontWeight: 500}}>₹{l.total.toLocaleString('en-IN')}</td>
                      <td style={tdJob}><button style={iconBtnJ} aria-label="Remove"><Icon name="x" size={12} /></button></td>
                    </tr>
                  ))}
                  <tr style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td colSpan="7" style={{ padding: '10px 12px', color: 'var(--text-tertiary)', fontSize: 12.5, fontStyle: 'italic' }}>+ Add another lot — pick by code or lot ID</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* totals card column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
            borderRadius: 8, padding: 16,
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>This send-out</div>
            <Row k="Total qty" v={<><span className="num" style={{ fontWeight: 600 }}>82.00</span> m</>} />
            <Row k="Estimated cost" v={<span className="num" style={{ fontWeight: 600 }}>₹9,260</span>} />
            <Row k="Operation" v="Embroidery" />
          </div>

          <div style={{
            background: 'var(--warning-subtle)', border: '1px solid #E8C880',
            borderRadius: 8, padding: 14,
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--warning-text)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>Imran's running balance</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="num" style={{ fontSize: 22, fontWeight: 700, color: 'var(--warning-text)' }}>122.00</span>
              <span style={{ color: 'var(--warning-text)', fontSize: 13 }}>m at karigar after this send-out</span>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--warning-text)', marginTop: 6, lineHeight: 1.55 }}>
              Imran's average return cycle is 8 days. 4 lots already with him, oldest 18-Mar.
            </div>
          </div>

          <div style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
            borderRadius: 8, padding: 14,
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>What happens next</div>
            <ul style={{ margin: 0, padding: 0, listStyle: 'none', fontSize: 12.5, color: 'var(--text-secondary)' }}>
              <Step n={1} t="JOB/25-26/000063 challan generated" />
              <Step n={2} t="Stock moves Cut → At embroidery" />
              <Step n={3} t="WhatsApp sent to Imran with PDF" />
              <Step n={4} t="Lot ages start counting from today" />
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function Step({ n, t }) {
  return (
    <li style={{ display: 'flex', gap: 8, padding: '4px 0' }}>
      <span style={{
        width: 16, height: 16, borderRadius: '50%', background: 'var(--accent-subtle)', color: 'var(--accent)',
        fontSize: 10, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>{n}</span>
      <span>{t}</span>
    </li>
  );
}

function Row({ k, v }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 13 }}>
      <span style={{ color: 'var(--text-tertiary)' }}>{k}</span>
      <span style={{ color: 'var(--text-primary)' }}>{v}</span>
    </div>
  );
}

function KarigarComboboxValue() {
  return (
    <div style={{
      border: '1.5px solid var(--accent)', borderRadius: 6, padding: '8px 12px',
      background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <Monogram initials="IS" size={32} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>Karigar Imran Sheikh</span>
          <OpChip name="Embroidery" />
          <span style={{
            fontSize: 10, fontWeight: 600, padding: '2px 6px', borderRadius: 4,
            background: 'var(--accent-subtle)', color: 'var(--accent)', letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>KYC ✓</span>
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 2, display: 'flex', gap: 10 }}>
          <span>Surat · 8.2 km</span>
          <span>·</span>
          <span style={{ color: 'var(--warning-text)' }}>40 m outstanding · 4 lots</span>
        </div>
      </div>
      <Icon name="message" size={14} color="var(--accent)" />
      <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
    </div>
  );
}

const thJob = {
  fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)',
  letterSpacing: '0.06em', textTransform: 'uppercase',
  padding: '8px 12px', textAlign: 'left', whiteSpace: 'nowrap',
};
const tdJob = { padding: '10px 12px', verticalAlign: 'middle' };
const iconBtnJ = {
  width: 22, height: 22, borderRadius: 4, border: 'none', background: 'transparent',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  color: 'var(--text-tertiary)', cursor: 'pointer',
};

/* ─────────────────────────────────────────────────────────────
   Job Work Challan — print preview
───────────────────────────────────────────────────────────── */
function JobChallan() {
  const lots = [
    { sno: 1, lot: 'LT-2026-0042', item: 'Silk Georgette 60GSM White',  qty: '40.00 m', rate: '₹95',  amount: '₹3,800.00' },
    { sno: 2, lot: 'LT-2026-0058', item: 'Banarasi Silk 90GSM Maroon',  qty: '24.00 m', rate: '₹145', amount: '₹3,480.00' },
    { sno: 3, lot: 'LT-2026-0061', item: 'Dola Silk 44 Champagne',      qty: '18.00 m', rate: '₹110', amount: '₹1,980.00' },
  ];
  return (
    <div style={{ background: '#F2F0E9', padding: 24, height: '100%', overflow: 'auto' }}>
      <div style={{
        background: '#FFF', maxWidth: 680, margin: '0 auto',
        boxShadow: 'var(--shadow-3)', padding: '32px 36px', fontSize: 12,
      }}>
        {/* header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid #DDD', paddingBottom: 14, marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.005em' }}>Rajesh Textiles</div>
            <div style={{ fontSize: 10.5, color: '#666', marginTop: 2 }}>Plot 14, Ring Road, Surat 395002</div>
            <div style={{ fontSize: 10.5, color: '#666' }}>GSTIN 27AAAAA000A1Z5 · +91 98250 12345</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{
              fontSize: 14, fontWeight: 700, padding: '4px 10px',
              background: '#EFEDE6', borderRadius: 4, letterSpacing: '0.05em',
            }}>JOB WORK CHALLAN</div>
            <div style={{ fontSize: 10.5, color: '#666', marginTop: 4 }}>Not a tax invoice · GST not applicable</div>
          </div>
        </div>

        {/* meta row */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 10, color: '#999', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Sent to (job worker)</div>
            <div style={{ fontWeight: 600, fontSize: 13 }}>Imran Sheikh</div>
            <div style={{ color: '#444', fontSize: 11.5 }}>Block 7, Ratanpur Mohalla, Surat</div>
            <div style={{ color: '#666', fontSize: 11 }}>Operation: Embroidery (Aari)</div>
          </div>
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px', fontSize: 11.5 }}>
              <span style={{ color: '#999' }}>Challan #</span><span className="mono">JOB/25-26/000063</span>
              <span style={{ color: '#999' }}>Issued</span><span>27-Apr-2026</span>
              <span style={{ color: '#999' }}>Expected return</span><span>06-May-2026</span>
              <span style={{ color: '#999' }}>For MO</span><span className="mono">MO/25-26/000041</span>
            </div>
          </div>
        </div>

        {/* table */}
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
          <thead>
            <tr style={{ background: '#F2F0E9' }}>
              <th style={{ padding: 6, textAlign: 'left', fontSize: 10, color: '#666', textTransform: 'uppercase', letterSpacing: '0.06em' }}>#</th>
              <th style={{ padding: 6, textAlign: 'left', fontSize: 10, color: '#666', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Lot</th>
              <th style={{ padding: 6, textAlign: 'left', fontSize: 10, color: '#666', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Description</th>
              <th style={{ padding: 6, textAlign: 'right', fontSize: 10, color: '#666', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Qty</th>
              <th style={{ padding: 6, textAlign: 'right', fontSize: 10, color: '#666', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Rate</th>
              <th style={{ padding: 6, textAlign: 'right', fontSize: 10, color: '#666', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {lots.map(l => (
              <tr key={l.sno} style={{ borderBottom: '1px solid #EEE' }}>
                <td style={{ padding: 7 }}>{l.sno}</td>
                <td className="mono" style={{ padding: 7, fontSize: 10.5 }}>{l.lot}</td>
                <td style={{ padding: 7 }}>{l.item}</td>
                <td className="num" style={{ padding: 7, textAlign: 'right' }}>{l.qty}</td>
                <td className="num" style={{ padding: 7, textAlign: 'right' }}>{l.rate}</td>
                <td className="num" style={{ padding: 7, textAlign: 'right', fontWeight: 500 }}>{l.amount}</td>
              </tr>
            ))}
            <tr>
              <td colSpan="3" style={{ padding: '12px 7px 7px', textAlign: 'right', color: '#666' }}>Total quantity dispatched</td>
              <td className="num" style={{ padding: '12px 7px 7px', textAlign: 'right', fontWeight: 600 }}>82.00 m</td>
              <td></td>
              <td className="num" style={{ padding: '12px 7px 7px', textAlign: 'right', fontWeight: 700, fontSize: 13 }}>₹9,260.00</td>
            </tr>
          </tbody>
        </table>

        {/* instructions */}
        <div style={{ marginTop: 18, padding: 12, background: '#F8F6EF', borderLeft: '3px solid #0F7A4E', fontSize: 11.5, lineHeight: 1.6 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Instructions</div>
          Aari work on bridal motif as per design A-402. Match dye batch DB-2026-014 — no shade variation across pieces. Photo of first piece before scaling up.
        </div>

        {/* footer */}
        <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', fontSize: 11, color: '#666' }}>
          <div>
            <div>Goods sent for job work under Sec 143 of CGST Act.</div>
            <div>Return within 1 year, in lots if needed.</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ borderTop: '1px solid #999', paddingTop: 4, marginTop: 32, minWidth: 160 }}>
              Authorised signatory
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-JOB-002 — Receive back with parts tracking
───────────────────────────────────────────────────────────── */
const RECEIVE_PARTS_OK = [
  { sno: 1, lot: 'LT-2026-0042', part: 'Kameez front', qty: 18.50, sent: 19, waste: 0.50, rework: 0,    rate: 95, amt: 1757.50 },
  { sno: 2, lot: 'LT-2026-0042', part: 'Kameez back',  qty: 18.20, sent: 19, waste: 0.80, rework: 0,    rate: 95, amt: 1729.00 },
  { sno: 3, lot: 'LT-2026-0042', part: 'Dupatta',      qty: 11.30, sent: 12, waste: 0.70, rework: 0,    rate: 95, amt: 1073.50 },
  { sno: 4, lot: 'LT-2026-0058', part: 'Bottom',       qty: 22.00, sent: 24, waste: 0.50, rework: 1.50, rate: 145, amt: 3190.00 },
];
const RECEIVE_PARTS_BREACH = [
  { sno: 1, lot: 'LT-2026-0042', part: 'Kameez front', qty: 17.30, sent: 19, waste: 1.70, rework: 0,    rate: 95, amt: 1643.50 },
  { sno: 2, lot: 'LT-2026-0042', part: 'Kameez back',  qty: 17.10, sent: 19, waste: 1.20, rework: 0.70, rate: 95, amt: 1624.50 },
  { sno: 3, lot: 'LT-2026-0042', part: 'Dupatta',      qty: 10.40, sent: 12, waste: 1.20, rework: 0.40, rate: 95, amt: 988.00 },
  { sno: 4, lot: 'LT-2026-0058', part: 'Bottom',       qty: 21.20, sent: 24, waste: 1.80, rework: 1.00, rate: 145, amt: 3074.00 },
];

function JobReceiveBack({ variant = 'ok' }) {
  const breach = variant === 'breach';
  const parts = breach ? RECEIVE_PARTS_BREACH : RECEIVE_PARTS_OK;
  const sentTotal = parts.reduce((s, p) => s + p.sent, 0);
  const recv = parts.reduce((s, p) => s + p.qty, 0);
  const waste = parts.reduce((s, p) => s + p.waste, 0);
  const wasteRate = (waste / sentTotal) * 100;
  const labour = parts.reduce((s, p) => s + p.amt, 0);
  const std = 5;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Job work › Receive back</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Receive back</h1>
            <span className="mono" style={{ fontSize: 12, padding: '3px 8px', background: 'var(--bg-sunken)', borderRadius: 4 }}>JOB/25-26/000063</span>
          </div>
        </div>
        <Button variant="secondary" size="sm">Cancel</Button>
        <Button variant="primary" size="sm" icon="check">Confirm receipt</Button>
      </div>

      {/* job summary strip */}
      <div style={{ padding: '14px 24px', background: 'var(--bg-sunken)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 28, alignItems: 'center' }}>
        <Monogram initials="IS" size={36} />
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Karigar Imran Sheikh</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>Surat · Embroidery (Aari) · Personal standard <strong style={{ color: 'var(--text-secondary)' }}>{std}%</strong></div>
        </div>
        <div style={{ width: 1, height: 32, background: 'var(--border-default)' }} />
        <SmallStat k="Sent" v="82.00 m" sub="27-Apr · 9 days ago" />
        <SmallStat k="MO" v="MO/25-26/000041" mono />
        <SmallStat k="Operation" v="Embroidery" />
      </div>

      {/* body */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 320px', minHeight: 0 }}>
        {/* parts table */}
        <div style={{ overflow: 'auto', padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Parts received</h3>
            <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>4 parts across 2 lots · photo upload optional per part</span>
          </div>
          <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg-surface)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--bg-sunken)' }}>
                  <th style={thJob}>#</th>
                  <th style={thJob}>Lot</th>
                  <th style={thJob}>Part</th>
                  <th style={{...thJob, textAlign: 'right'}}>Sent</th>
                  <th style={{...thJob, textAlign: 'right'}}>Qty in</th>
                  <th style={{...thJob, textAlign: 'right'}}>Wastage</th>
                  <th style={{...thJob, textAlign: 'right'}}>Rework</th>
                  <th style={{...thJob, textAlign: 'right'}}>Rate</th>
                  <th style={{...thJob, textAlign: 'right'}}>Amount</th>
                  <th style={thJob}>Photo</th>
                </tr>
              </thead>
              <tbody>
                {parts.map((p, i) => {
                  const wRate = (p.waste / p.sent) * 100;
                  const partBreach = wRate > std;
                  return (
                    <tr key={p.sno} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                      <td style={{...tdJob, color: 'var(--text-tertiary)'}}>{p.sno}</td>
                      <td className="mono" style={{...tdJob, fontSize: 11.5, color: 'var(--accent)'}}>{p.lot}</td>
                      <td style={{...tdJob, fontWeight: 500}}>{p.part}</td>
                      <td className="num" style={{...tdJob, textAlign: 'right', color: 'var(--text-secondary)'}}>{p.sent.toFixed(2)}</td>
                      <td className="num" style={{...tdJob, textAlign: 'right', fontWeight: 600}}>{p.qty.toFixed(2)}</td>
                      <td style={{...tdJob, textAlign: 'right'}}>
                        <WastageCell qty={p.waste} sent={p.sent} std={std} />
                      </td>
                      <td className="num" style={{...tdJob, textAlign: 'right', color: p.rework ? 'var(--warning-text)' : 'var(--text-tertiary)'}}>{p.rework ? p.rework.toFixed(2) : '—'}</td>
                      <td className="num" style={{...tdJob, textAlign: 'right', color: 'var(--text-secondary)'}}>₹{p.rate}</td>
                      <td className="num" style={{...tdJob, textAlign: 'right', fontWeight: 500}}>₹{p.amt.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                      <td style={tdJob}>
                        <div style={{
                          width: 32, height: 32, borderRadius: 4,
                          border: '1px dashed var(--border-default)',
                          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                          color: 'var(--text-tertiary)', cursor: 'pointer',
                        }}>
                          <Icon name="image" size={14} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* threshold bar */}
          <div style={{
            marginTop: 16, padding: 14, borderRadius: 8,
            background: breach ? 'var(--danger-subtle)' : 'var(--success-subtle)',
            border: `1px solid ${breach ? '#E5B3A8' : '#C7E0CE'}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: breach ? 'var(--danger-text)' : 'var(--success-text)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                {breach ? 'Wastage breach' : 'Within standard'}
              </div>
              <div style={{ fontSize: 13, color: breach ? 'var(--danger-text)' : 'var(--success-text)' }}>
                <span className="num" style={{ fontWeight: 700, fontSize: 18 }}>{wasteRate.toFixed(1)}%</span>
                <span> on this batch · Imran's standard {std}%</span>
              </div>
            </div>
            <WastageThreshold rate={wasteRate} std={std} max={10} breach={breach} />
            <div style={{ fontSize: 11.5, color: breach ? 'var(--danger-text)' : 'var(--success-text)', marginTop: 8 }}>
              {breach
                ? `Surplus wastage of ${(waste - sentTotal * std / 100).toFixed(2)} m. Recovery options: deduct from labour, raise debit note, or accept and note.`
                : `Wastage is ${(waste).toFixed(2)} m of ${sentTotal} m sent — well within Imran's track record.`
              }
            </div>
          </div>
        </div>

        {/* totals card */}
        <div style={{ background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-subtle)', padding: 20, display: 'flex', flexDirection: 'column', gap: 14, overflow: 'auto' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Net received</div>
            <div className="num" style={{ fontSize: 28, fontWeight: 700, marginTop: 2 }}>{recv.toFixed(2)} <span style={{ fontSize: 14, color: 'var(--text-tertiary)', fontWeight: 400 }}>m</span></div>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>of {sentTotal.toFixed(2)} m sent</div>
          </div>
          <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 14 }}>
            <Row k="Wastage logged" v={<span className="num">{waste.toFixed(2)} m</span>} />
            <Row k="Rework lots" v={<span className="num">{parts.filter(p => p.rework).length}</span>} />
            <Row k="Labour to pay" v={<span className="num" style={{ fontWeight: 600 }}>₹{labour.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>} />
          </div>

          <div style={{
            border: '1px solid var(--border-default)', borderRadius: 6,
          }}>
            <div style={{ padding: 10, borderBottom: '1px solid var(--border-subtle)' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input type="radio" defaultChecked={!breach} name="settle" />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>Settle now</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Pay ₹{labour.toLocaleString('en-IN')} via UPI</div>
                </div>
              </label>
            </div>
            <div style={{ padding: 10 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input type="radio" defaultChecked={breach} name="settle" />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>Accrue to ledger</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Outstanding labour: ₹28,500 → ₹{(28500 + labour).toLocaleString('en-IN')}</div>
                </div>
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function WastageCell({ qty, sent, std }) {
  const rate = (qty / sent) * 100;
  const breach = rate > std;
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 36, height: 4, borderRadius: 2, background: 'var(--border-subtle)', overflow: 'hidden' }}>
        <div style={{
          width: `${Math.min(100, rate * (100 / (std * 2)))}%`, height: '100%',
          background: breach ? 'var(--danger)' : 'var(--success)',
        }} />
      </div>
      <span className="num" style={{ fontSize: 12.5, color: breach ? 'var(--danger-text)' : 'var(--success-text)', fontWeight: breach ? 600 : 500 }}>
        {qty.toFixed(2)}
      </span>
    </div>
  );
}

function WastageThreshold({ rate, std, max, breach }) {
  const w = Math.min(100, (rate / max) * 100);
  const stdPos = (std / max) * 100;
  return (
    <div style={{ position: 'relative', height: 12, borderRadius: 6, background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}>
      {/* the bar fill */}
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0, width: `${w}%`,
        background: breach ? 'linear-gradient(90deg, #137A48 0%, #137A48 50%, #B5311E 100%)' : 'var(--success)',
        borderRadius: 6,
      }} />
      {/* threshold marker */}
      <div style={{
        position: 'absolute', left: `${stdPos}%`, top: -4, bottom: -4, width: 0,
        borderLeft: '2px dashed var(--text-secondary)',
      }} />
      <div style={{
        position: 'absolute', left: `${stdPos}%`, top: -16, transform: 'translateX(-50%)',
        fontSize: 9.5, fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap',
      }}>std {std}%</div>
    </div>
  );
}

function SmallStat({ k, v, sub, mono }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{k}</div>
      <div className={mono ? 'mono' : ''} style={{ fontSize: 13, fontWeight: 600, marginTop: 2 }}>{v}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{sub}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-JOB-003 — Karigar list (card grid)
───────────────────────────────────────────────────────────── */
function KarigarGrid({ cols = 4, mobile }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: mobile ? '14px 16px' : '14px 24px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h1 style={{ margin: 0, fontSize: mobile ? 18 : 22, fontWeight: 700, flex: 1 }}>Karigars</h1>
          {!mobile && <Button variant="secondary" size="sm" icon="plus">Add karigar</Button>}
          {!mobile && <Button variant="primary" size="sm" icon="send">Send out</Button>}
          {mobile && <Button variant="primary" size="sm" icon="plus">New</Button>}
        </div>
        <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ width: mobile ? '100%' : 240 }}>
            <Input placeholder="Search karigar, city, op…" prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
          </div>
          <FilterChip label="All" active count={KARIGARS.length} />
          <FilterChip label="Embroidery" count={2} />
          <FilterChip label="Stitching" count={2} />
          <FilterChip label="Has outstanding" count={5} />
        </div>
      </div>

      <div style={{ flex: 1, padding: mobile ? 12 : 20, overflow: 'auto' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
          gap: mobile ? 10 : 14,
        }}>
          {KARIGARS.map(k => <KarigarCard key={k.id} k={k} mobile={mobile} />)}
        </div>
      </div>
    </div>
  );
}

function KarigarCard({ k, mobile }) {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 10, padding: mobile ? 12 : 14,
      display: 'flex', flexDirection: 'column', gap: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Monogram initials={k.name.split(' ').map(w => w[0]).slice(0, 2).join('')} size={mobile ? 36 : 40} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{k.name}</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>{k.city}{k.kyc ? ' · KYC ✓' : ' · KYC pending'}</div>
        </div>
        {k.whatsapp && (
          <div style={{ width: 26, height: 26, borderRadius: '50%', background: 'var(--accent-subtle)', color: 'var(--accent)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="message" size={13} />
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {k.ops.map(o => <OpChip key={o} name={o} />)}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderTop: '1px solid var(--border-subtle)', borderBottom: '1px solid var(--border-subtle)', gap: 8 }}>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>At kgr</div>
          <div className="num" style={{ fontSize: 15, fontWeight: 600, color: k.atQty ? 'var(--warning-text)' : 'var(--text-tertiary)' }}>{k.atQty ? `${k.atQty} m` : '—'}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Labour due</div>
          <div className="num" style={{ fontSize: 15, fontWeight: 600 }}>{k.outLabour ? `₹${(k.outLabour/1000).toFixed(1)}k` : '—'}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Last act</div>
          <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text-secondary)' }}>{k.lastAct}</div>
        </div>
      </div>

      <Button variant="secondary" size="sm" icon="send">Send out</Button>
    </div>
  );
}

Object.assign(window, {
  JobSendOut, JobChallan, JobReceiveBack, KarigarGrid, OpChip, KARIGARS,
});
