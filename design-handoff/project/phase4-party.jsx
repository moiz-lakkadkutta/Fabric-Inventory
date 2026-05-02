// phase4-party.jsx — Party list, Party detail (khata, ledger hero), Party edit.

const { useState: useStateY, useMemo: useMemoY } = React;

/* ─────────────────────────────────────────────────────────────
   SCR-PARTY-001 — Party List
───────────────────────────────────────────────────────────── */

const PARTY_TONES = ['indigo', 'rose', 'olive', 'amber', 'teal', 'plum', 'neutral', 'sand', 'sage', 'rust', 'sky', 'gold'];
const partyTone = (i) => PARTY_TONES[i % PARTY_TONES.length];
const initialsOf = (s) => s.split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase();

const PARTIES = [
  // customers
  { name: 'Khan Sarees Pvt Ltd',          type: 'customer', gst: '27AAACK5821L1Z3', city: 'Mumbai',     out: 640000,   limit: 1000000, last: '24-Apr', status: 'active', overdue: true, days: 32 },
  { name: 'Aza Couture',                  type: 'customer', gst: '27AAACA8821B1Z9', city: 'Mumbai',     out: 280000,   limit: 500000,  last: '22-Apr', status: 'active', overdue: false },
  { name: "Pernia's Pop-up Studio",       type: 'customer', gst: '07AAACP4421J1Z2', city: 'Delhi',      out: 0,        limit: 800000,  last: '21-Apr', status: 'active', overdue: false },
  { name: 'Lehenga Lounge',               type: 'customer', gst: '24ABEFL2891Q1ZJ', city: 'Surat',      out: 92000,    limit: 200000,  last: '18-Apr', status: 'on_hold', overdue: false },
  { name: 'Drape Story',                  type: 'customer', gst: '27AHCPS9821B1Z6', city: 'Pune',       out: 0,        limit: 250000,  last: '14-Apr', status: 'active', overdue: false },
  { name: 'Heritage Boutique',            type: 'customer', gst: '03AHFPB1821G1Z2', city: 'Amritsar',   out: 154000,   limit: 200000,  last: '12-Apr', status: 'active', overdue: true, days: 18 },
  { name: 'Ritu & Co.',                   type: 'customer', gst: '24BAEPC8721H1Z9', city: 'Vadodara',   out: 38000,    limit: 150000,  last: '08-Apr', status: 'active', overdue: false },
  // suppliers
  { name: 'Reliance Industries Ltd',      type: 'supplier', gst: '27AAACR5055K1Z2', city: 'Mumbai',     out: 482000,   limit: null,    last: '02-Apr', status: 'active', overdue: false },
  { name: 'Banarasi Weavers',             type: 'supplier', gst: '09AAACB4421H1Z0', city: 'Varanasi',   out: 312000,   limit: null,    last: '20-Apr', status: 'active', overdue: false },
  { name: 'Khurana Embroidery Wires',     type: 'supplier', gst: '07AAACK0021P1Z6', city: 'Delhi',      out: 24800,    limit: null,    last: '14-Apr', status: 'active', overdue: false },
  { name: 'Hira Lal & Sons (Dyeing)',     type: 'both',     gst: '27AAFFH8881B1Z4', city: 'Surat',      out: 62400,    limit: 100000,  last: '10-Apr', status: 'active', overdue: false },
];

function PartyList() {
  const [tab, setTab] = useStateY('all');
  const filtered = PARTIES.filter(p => tab === 'all' ? true : tab === 'both' ? p.type === 'both' : p.type === tab);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Parties</h1>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
            {PARTIES.length} parties · ₹{(PARTIES.filter(p => p.type !== 'supplier').reduce((s,p) => s + p.out, 0) / 100000).toFixed(1)}L receivable · ₹{(PARTIES.filter(p => p.type === 'supplier' || p.type === 'both').reduce((s,p) => s + p.out, 0) / 100000).toFixed(1)}L payable
          </div>
        </div>
        <Button variant="secondary" size="sm" icon="upload">Import</Button>
        <Button variant="primary" size="sm" icon="plus">New party</Button>
      </div>

      {/* tabs */}
      <div style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', padding: '0 24px', display: 'flex', gap: 4 }}>
        {[
          ['all', 'All', PARTIES.length],
          ['customer', 'Customers', PARTIES.filter(p => p.type === 'customer').length],
          ['supplier', 'Suppliers', PARTIES.filter(p => p.type === 'supplier').length],
          ['both', 'Both', PARTIES.filter(p => p.type === 'both').length],
          ['karigars', 'Karigars', 14],
        ].map(([k, l, n]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            padding: '12px 14px', background: 'transparent', border: 'none', cursor: 'pointer',
            fontSize: 13, fontWeight: 500,
            color: tab === k ? 'var(--text-primary)' : 'var(--text-tertiary)',
            borderBottom: tab === k ? '2px solid var(--accent)' : '2px solid transparent',
            marginBottom: -1,
          }}>
            {l} <span style={{ color: 'var(--text-tertiary)', fontWeight: 400, marginLeft: 4 }}>{n}</span>
          </button>
        ))}
      </div>

      <div style={{ padding: '10px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 8 }}>
        <div style={{ width: 280 }}>
          <Input placeholder="Search name, GSTIN, city, phone…" prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
        </div>
        <FilterChip label="Has outstanding" />
        <FilterChip label="Overdue" />
        <FilterChip label="Inactive 90d+" />
      </div>

      <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg-surface)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--bg-sunken)' }}>
              <th style={thPO}>Party</th>
              <th style={thPO}>Type</th>
              <th style={thPO}>GSTIN</th>
              <th style={thPO}>City</th>
              <th style={{...thPO, textAlign: 'right'}}>Outstanding ₹</th>
              <th style={{...thPO, textAlign: 'right'}}>Credit limit</th>
              <th style={thPO}>Last activity</th>
              <th style={thPO}>Status</th>
              <th style={{...thPO, width: 36}}></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p, i) => (
              <tr key={p.name} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                <td style={tdPO}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Monogram initials={initialsOf(p.name)} size={28} tone={partyTone(i)} />
                    <span style={{ fontWeight: 500 }}>{p.name}</span>
                  </div>
                </td>
                <td style={{...tdPO, fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600}}>{p.type}</td>
                <td className="mono" style={{...tdPO, fontSize: 11.5, color: 'var(--text-secondary)'}}>{p.gst}</td>
                <td style={{...tdPO, color: 'var(--text-secondary)'}}>{p.city}</td>
                <td className="num" style={{...tdPO, textAlign: 'right', fontWeight: 600, color: p.overdue ? 'var(--danger-text)' : p.out > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)'}}>
                  {p.out > 0 ? `₹${p.out.toLocaleString('en-IN')}` : '—'}
                  {p.overdue && <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--danger-text)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{p.days}d overdue</div>}
                </td>
                <td className="num" style={{...tdPO, textAlign: 'right', color: 'var(--text-tertiary)'}}>{p.limit ? `₹${(p.limit / 100000).toFixed(1)}L` : '—'}</td>
                <td style={{...tdPO, color: 'var(--text-secondary)'}}>{p.last}</td>
                <td style={tdPO}>
                  {p.status === 'on_hold'
                    ? <Pill kind="overdue">On hold</Pill>
                    : <Pill kind="paid">Active</Pill>}
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

/* ─────────────────────────────────────────────────────────────
   SCR-PARTY-002 — Party Detail (the khata)
───────────────────────────────────────────────────────────── */

// 25 ledger rows for Khan Sarees — opening balance, 12 invoices, 8 receipts, 2 credit notes, 1 adjustment, plus 1 advance recd.
const LEDGER = [
  { d: '01-Apr-25', t: 'opening', doc: '—',                  prt: 'Opening balance carried forward',                              dr: 162000, cr: 0,      bal:  162000, days: null, st: 'posted' },
  { d: '04-Apr-25', t: 'invoice', doc: 'INV/24-25/001284',   prt: 'Bridal lehenga set · 4 pcs',                                   dr: 248000, cr: 0,      bal:  410000, days:387, st: 'paid' },
  { d: '12-Apr-25', t: 'receipt', doc: 'RCT/25-26/000041',   prt: 'NEFT IMPS — HDFC ****8921',                                   dr: 0,      cr: 162000, bal:  248000, days:null,st: 'posted' },
  { d: '03-May-25', t: 'invoice', doc: 'INV/25-26/000091',   prt: 'Tussar anarkali · 12 sets',                                    dr: 184000, cr: 0,      bal:  432000, days:358, st: 'paid' },
  { d: '24-May-25', t: 'receipt', doc: 'RCT/25-26/000058',   prt: 'Cheque #381204 — Kotak Bank',                                  dr: 0,      cr: 248000, bal:  184000, days:null,st: 'posted' },
  { d: '14-Jun-25', t: 'invoice', doc: 'INV/25-26/000122',   prt: 'Banarasi silk · 18 sets',                                      dr: 312000, cr: 0,      bal:  496000, days:316, st: 'paid' },
  { d: '02-Jul-25', t: 'credit',  doc: 'CN/25-26/000008',    prt: 'Return — 2 pcs shade variation',                               dr: 0,      cr: 28000,  bal:  468000, days:null,st: 'posted' },
  { d: '12-Jul-25', t: 'receipt', doc: 'RCT/25-26/000089',   prt: 'NEFT — HDFC ****8921',                                         dr: 0,      cr: 184000, bal:  284000, days:null,st: 'posted' },
  { d: '04-Aug-25', t: 'invoice', doc: 'INV/25-26/000178',   prt: 'Champagne anarkali · 15 sets',                                 dr: 264000, cr: 0,      bal:  548000, days:265, st: 'paid' },
  { d: '24-Aug-25', t: 'receipt', doc: 'RCT/25-26/000124',   prt: 'NEFT — HDFC ****8921',                                         dr: 0,      cr: 284000, bal:  264000, days:null,st: 'posted' },
  { d: '12-Sep-25', t: 'invoice', doc: 'INV/25-26/000241',   prt: 'Cotton co-ord · 36 pcs',                                       dr: 144000, cr: 0,      bal:  408000, days:226, st: 'paid' },
  { d: '02-Oct-25', t: 'receipt', doc: 'RCT/25-26/000168',   prt: 'NEFT — HDFC ****8921',                                         dr: 0,      cr: 264000, bal:  144000, days:null,st: 'posted' },
  { d: '14-Oct-25', t: 'invoice', doc: 'INV/25-26/000291',   prt: 'Indigo katan · 10 sets',                                       dr: 244000, cr: 0,      bal:  388000, days:194, st: 'paid' },
  { d: '08-Nov-25', t: 'receipt', doc: 'RCT/25-26/000211',   prt: 'NEFT — HDFC ****8921',                                         dr: 0,      cr: 144000, bal:  244000, days:null,st: 'posted' },
  { d: '24-Nov-25', t: 'adjust',  doc: 'JV/25-26/000018',    prt: 'Rounding adjustment write-off',                                dr: 0,      cr: 200,    bal:  243800, days:null,st: 'posted' },
  { d: '02-Dec-25', t: 'invoice', doc: 'INV/25-26/000338',   prt: 'Off-white chanderi · 24 sets',                                 dr: 312000, cr: 0,      bal:  555800, days:145, st: 'partial' },
  { d: '14-Dec-25', t: 'receipt', doc: 'RCT/25-26/000262',   prt: 'NEFT — HDFC ****8921 · partial',                              dr: 0,      cr: 200000, bal:  355800, days:null,st: 'posted' },
  { d: '04-Jan-26', t: 'invoice', doc: 'INV/25-26/000412',   prt: 'Velvet bridal · 6 pcs',                                        dr: 188000, cr: 0,      bal:  543800, days:112, st: 'overdue' },
  { d: '02-Feb-26', t: 'invoice', doc: 'INV/25-26/000489',   prt: 'Tussar saree · 24 pcs',                                        dr: 96000,  cr: 0,      bal:  639800, days: 84, st: 'overdue' },
  { d: '18-Feb-26', t: 'credit',  doc: 'CN/25-26/000019',    prt: 'Return — 1 lehenga shade',                                     dr: 0,      cr: 12000,  bal:  627800, days:null,st: 'posted' },
  { d: '24-Feb-26', t: 'receipt', doc: 'RCT/25-26/000341',   prt: 'NEFT — HDFC ****8921',                                         dr: 0,      cr: 84000,  bal:  543800, days:null,st: 'posted' },
  { d: '12-Mar-26', t: 'invoice', doc: 'INV/25-26/000581',   prt: 'Mixed batch — Holi collection · 28 pcs',                       dr: 248000, cr: 0,      bal:  791800, days: 46, st: 'overdue' },
  { d: '02-Apr-26', t: 'invoice', doc: 'INV/25-26/000642',   prt: 'Silk gharchola · 8 sets',                                      dr: 124000, cr: 0,      bal:  915800, days: 25, st: 'partial' },
  { d: '14-Apr-26', t: 'receipt', doc: 'RCT/25-26/000408',   prt: 'NEFT — HDFC ****8921 · UNALLOCATED',                          dr: 0,      cr: 184000, bal:  731800, days:null,st: 'unallocated' },
  { d: '24-Apr-26', t: 'invoice', doc: 'INV/25-26/000718',   prt: 'Cotton co-ord set · 60 pcs',                                   dr: 76000,  cr: 0,      bal:  807800, days:  3, st: 'sent' },
];

const TXN_META = {
  opening:     { label: 'Opening',  color: '#605D52', bg: '#EAE7DD' },
  invoice:     { label: 'Invoice',  color: 'var(--accent)',       bg: 'var(--accent-subtle)' },
  receipt:     { label: 'Receipt',  color: 'var(--success-text)', bg: 'var(--success-subtle)' },
  credit:      { label: 'Credit',   color: 'var(--info-text)',    bg: 'var(--info-subtle)' },
  debit:       { label: 'Debit',    color: 'var(--warning-text)', bg: 'var(--warning-subtle)' },
  adjust:      { label: 'Adjust',   color: '#605D52',              bg: '#EAE7DD' },
};

function PartyDetail({ tinted = false, restricted = false }) {
  const [tab, setTab] = useStateY('ledger');
  const [page, setPage] = useStateY(1);
  const PER_PAGE = 25;
  const totalPages = Math.ceil(LEDGER.length / PER_PAGE);
  const visible = LEDGER.slice((page - 1) * PER_PAGE, page * PER_PAGE);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: tinted ? 'rgba(176, 138, 76, 0.06)' : 'var(--bg-canvas)' }}>
      {tinted && (
        <div style={{
          padding: '10px 24px', background: 'var(--warning-subtle)',
          borderBottom: '1px solid #E8C880', display: 'flex', gap: 10, alignItems: 'center',
        }}>
          <Icon name="alert" size={16} color="var(--warning-text)" />
          <div style={{ fontSize: 12.5, color: 'var(--warning-text)' }}>
            <strong>This party is on hold.</strong> New invoices require Sales Manager approval.
          </div>
          <Button variant="secondary" size="sm" style={{ marginLeft: 'auto' }}>Request approval</Button>
        </div>
      )}

      {/* header */}
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
          <Monogram initials="KS" size={56} tone="indigo" />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
              <a href="#" style={{ color: 'inherit' }}>Parties</a> ›  <a href="#" style={{ color: 'inherit' }}>Customers</a> › Khan Sarees
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
              <h1 style={{ margin: 0, fontSize: 26, fontWeight: 700, letterSpacing: '-0.01em' }}>Khan Sarees Pvt Ltd</h1>
              <Pill kind="info">Customer</Pill>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                background: 'var(--success-subtle)', color: 'var(--success-text)',
                letterSpacing: '0.04em', textTransform: 'uppercase',
              }}>
                <Icon name="check" size={11} /> Registered · 27AAACK5821L1Z3
              </span>
              {tinted && <Pill kind="overdue">On hold</Pill>}
              {!tinted && <Pill kind="paid">Active</Pill>}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>
              Linking Rd, Bandra W, Mumbai 400050 · GSTIN 27AAACK5821L1Z3 · Customer since Jun 2018
            </div>
          </div>
          {!restricted && <>
            <Button variant="secondary" size="sm" icon="edit">Edit</Button>
            <Button variant="secondary" size="sm" icon="menu-more">More</Button>
            <Button variant="primary" size="sm" icon="plus">Record receipt</Button>
          </>}
        </div>

        {/* KPIs */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginTop: 18 }}>
          <KhataKPI
            label="Outstanding"
            value="₹6,40,000"
            danger
            sub={<><span className="num">₹1,40,000</span> over 90 days</>}
          />
          <KhataKPI
            label="Credit limit"
            value="₹10,00,000"
            sub={
              <div>
                <div style={{ height: 6, borderRadius: 3, background: 'var(--bg-sunken)', overflow: 'hidden', marginBottom: 4 }}>
                  <div style={{ height: '100%', width: '64%', background: 'var(--warning)' }} />
                </div>
                <span><span className="num" style={{ fontWeight: 600 }}>64%</span> used · ₹3,60,000 available</span>
              </div>
            }
          />
          <KhataKPI label="Lifetime sales" value="₹84,30,000" sub="324 invoices since Jun-2018" />
          <KhataKPI
            label="Avg days to pay"
            value="28"
            sub={<><span style={{ color: 'var(--success-text)', fontWeight: 600 }}>↓ 4d</span> vs prior 90 days</>}
          />
        </div>
      </div>

      {/* tabs */}
      <div style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', padding: '0 24px', display: 'flex', gap: 4, position: 'sticky', top: 0, zIndex: 5 }}>
        {(restricted
          ? [['ledger','Ledger'], ['invoices','Invoices', 12]]
          : [
              ['ledger','Ledger', 25],
              ['statement','Statement'],
              ['invoices','Invoices', 12],
              ['receipts','Receipts', 9],
              ['returns','Returns', 2],
              ['contact','Contact info'],
              ['notes','Notes', 3],
              ['audit','Audit'],
            ]
        ).map(([k, l, n]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            padding: '12px 14px', background: 'transparent', border: 'none', cursor: 'pointer',
            fontSize: 13, fontWeight: 500,
            color: tab === k ? 'var(--text-primary)' : 'var(--text-tertiary)',
            borderBottom: tab === k ? '2px solid var(--accent)' : '2px solid transparent',
            marginBottom: -1,
          }}>
            {l}{n != null && <span style={{ color: 'var(--text-tertiary)', fontWeight: 400, marginLeft: 4 }}>{n}</span>}
          </button>
        ))}
      </div>

      {/* body */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {tab === 'ledger' && <LedgerTab visible={visible} page={page} setPage={setPage} totalPages={totalPages} />}
        {tab === 'statement' && <StatementTab />}
        {tab === 'audit' && <AuditTab />}
        {tab !== 'ledger' && tab !== 'statement' && tab !== 'audit' && <PlaceholderTab name={tab} />}
      </div>
    </div>
  );
}

function KhataKPI({ label, value, sub, danger }) {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, padding: 14, height: 110, display: 'flex', flexDirection: 'column',
    }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
      <div className="num" style={{ fontSize: 26, fontWeight: 700, color: danger ? 'var(--danger-text)' : 'var(--text-primary)', marginTop: 6, lineHeight: 1, letterSpacing: '-0.01em' }}>{value}</div>
      <div style={{ fontSize: 11.5, color: danger ? 'var(--danger-text)' : 'var(--text-tertiary)', marginTop: 'auto' }}>{sub}</div>
    </div>
  );
}

function LedgerTab({ visible, page, setPage, totalPages }) {
  const [typeFilter, setTypeFilter] = useStateY('all');
  return (
    <div style={{ padding: 24 }}>
      {/* aging bar — the at-a-glance story */}
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
        borderRadius: 8, padding: 18, marginBottom: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Aging — receivable</div>
            <div className="num" style={{ fontSize: 26, fontWeight: 700, marginTop: 4, color: 'var(--danger-text)' }}>₹6,40,000</div>
          </div>
          <Button variant="secondary" size="sm" icon="send">Send statement</Button>
        </div>
        <AgingBar />
      </div>

      {/* filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <div style={{ width: 220 }}>
          <Input placeholder="Search doc # or particulars" prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
        </div>
        <span style={{ width: 1, height: 22, background: 'var(--border-subtle)' }} />
        <FilterChip label="All" active={typeFilter === 'all'} onClick={() => setTypeFilter('all')} count={LEDGER.length} />
        <FilterChip label="Invoice" count={12} onClick={() => setTypeFilter('invoice')} active={typeFilter === 'invoice'} />
        <FilterChip label="Receipt" count={9} onClick={() => setTypeFilter('receipt')} active={typeFilter === 'receipt'} />
        <FilterChip label="Credit note" count={2} />
        <FilterChip label="Adjustment" count={1} />
        <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--text-tertiary)' }}>
          From <strong>01-Apr-25</strong> to <strong>27-Apr-26</strong> · FY 25-26
        </span>
      </div>

      {/* ledger table */}
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr style={{ background: 'var(--bg-sunken)' }}>
              <th style={thPO}>Date</th>
              <th style={thPO}>Type</th>
              <th style={thPO}>Doc #</th>
              <th style={thPO}>Particulars</th>
              <th style={{...thPO, textAlign: 'right'}}>Debit ₹</th>
              <th style={{...thPO, textAlign: 'right'}}>Credit ₹</th>
              <th style={{...thPO, textAlign: 'right'}}>Balance ₹</th>
              <th style={{...thPO, textAlign: 'right'}}>Days out</th>
              <th style={thPO}>Status</th>
              <th style={{...thPO, width: 36}}></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => (
              <LedgerRow key={i} r={r} idx={i} />
            ))}
          </tbody>
        </table>
        <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 10, background: 'var(--bg-sunken)' }}>
          <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>Page {page} of {totalPages} · 25 of 25 entries shown</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
            <Button variant="secondary" size="sm">‹ Prev</Button>
            <Button variant="secondary" size="sm">Next ›</Button>
          </span>
        </div>
      </div>
    </div>
  );
}

function AgingBar() {
  const buckets = [
    { range: '0–30',     amt: 200000, color: '#A8A89F' },
    { range: '31–60',    amt: 150000, color: '#C8B27A' },
    { range: '61–90',    amt: 90000,  color: '#B08A4C' },
    { range: '91–120',   amt: 60000,  color: '#9B5A3D' },
    { range: '120+',     amt: 140000, color: 'var(--danger)' },
  ];
  const total = buckets.reduce((s, b) => s + b.amt, 0);
  return (
    <div>
      {/* THE BAR */}
      <div style={{ display: 'flex', height: 28, borderRadius: 4, overflow: 'hidden', boxShadow: 'inset 0 0 0 1px var(--border-subtle)' }}>
        {buckets.map((b, i) => (
          <div key={i} style={{
            flex: b.amt / total,
            background: b.color,
            position: 'relative',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#FFF', fontSize: 11, fontWeight: 600,
            borderRight: i < buckets.length - 1 ? '1px solid rgba(255,255,255,0.4)' : 'none',
          }}>
            {b.amt / total > 0.10 && `₹${(b.amt / 1000).toFixed(0)}k`}
          </div>
        ))}
      </div>
      {/* legend */}
      <div style={{ display: 'flex', marginTop: 10 }}>
        {buckets.map((b, i) => (
          <div key={i} style={{ flex: b.amt / total, paddingRight: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: b.color }} />
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>{b.range} d</span>
            </div>
            <div className="num" style={{ fontSize: 13, fontWeight: 600, marginTop: 2 }}>₹{b.amt.toLocaleString('en-IN')}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LedgerRow({ r, idx }) {
  const [open, setOpen] = useStateY(idx === 23); // expand the unallocated receipt by default
  const meta = TXN_META[r.t];
  const isUnalloc = r.st === 'unallocated';
  const isOverdue = r.st === 'overdue';
  return (
    <React.Fragment>
      <tr onClick={() => setOpen(!open)} style={{
        borderTop: '1px solid var(--border-subtle)',
        background: isUnalloc ? 'rgba(58,107,162,0.05)' : open ? 'var(--bg-sunken)' : 'transparent',
        cursor: 'pointer',
      }}>
        <td className="mono" style={{...tdPO, padding: '10px 12px', color: 'var(--text-secondary)', fontSize: 11.5}}>{r.d}</td>
        <td style={{...tdPO, padding: '10px 12px'}}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', height: 20, padding: '0 7px',
            borderRadius: 3, background: meta.bg, color: meta.color,
            fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>{meta.label}</span>
        </td>
        <td className="mono" style={{...tdPO, padding: '10px 12px', fontSize: 11.5, color: 'var(--accent)', fontWeight: 600}}>{r.doc}</td>
        <td style={{...tdPO, padding: '10px 12px', color: 'var(--text-primary)'}}>
          {r.prt}
          {isUnalloc && <Pill kind="overdue" style={{ marginLeft: 6 }}>UNALLOCATED</Pill>}
        </td>
        <td className="num" style={{...tdPO, padding: '10px 12px', textAlign: 'right', color: r.dr ? 'var(--text-primary)' : 'var(--text-tertiary)'}}>{r.dr ? r.dr.toLocaleString('en-IN') : '—'}</td>
        <td className="num" style={{...tdPO, padding: '10px 12px', textAlign: 'right', color: r.cr ? 'var(--success-text)' : 'var(--text-tertiary)', fontWeight: r.cr ? 500 : 400}}>{r.cr ? r.cr.toLocaleString('en-IN') : '—'}</td>
        <td className="num" style={{...tdPO, padding: '10px 12px', textAlign: 'right', fontWeight: 700, color: r.bal < 0 ? 'var(--danger-text)' : 'var(--text-primary)'}}>{r.bal.toLocaleString('en-IN')}</td>
        <td className="num" style={{...tdPO, padding: '10px 12px', textAlign: 'right', color: isOverdue ? 'var(--danger-text)' : 'var(--text-tertiary)', fontWeight: isOverdue ? 600 : 400}}>{r.days != null ? `${r.days}d` : '—'}</td>
        <td style={{...tdPO, padding: '10px 12px'}}>
          {isUnalloc ? <Pill kind="overdue">Unallocated</Pill> :
           r.st === 'paid' ? <Pill kind="paid">Paid</Pill> :
           r.st === 'overdue' ? <Pill kind="overdue">Overdue</Pill> :
           r.st === 'partial' ? <Pill kind="partial">Partial</Pill> :
           r.st === 'sent' ? <Pill kind="info">Sent</Pill> :
           <Pill kind="paid">Posted</Pill>}
        </td>
        <td style={{...tdPO, padding: '10px 12px'}}>
          <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan="10" style={{ padding: 0, background: 'var(--bg-sunken)', borderTop: '1px solid var(--border-subtle)' }}>
            <div style={{ padding: '14px 16px 16px 56px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
              <div>
                <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Line summary</div>
                {isUnalloc ? (
                  <div style={{ fontSize: 12.5, marginTop: 6 }}>
                    NEFT credit received in bank reconciliation. <strong>Not yet allocated</strong> to any invoice — the cash is sitting as an advance.
                  </div>
                ) : (
                  <div style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.5 }}>
                    {r.t === 'invoice' ? 'Invoice booked. Tax: CGST 9% + SGST 9%. Payment terms Net 30.' : r.t === 'receipt' ? 'Receipt posted. Allocated against earlier invoice.' : r.t === 'credit' ? 'Credit note for return; offset against next invoice.' : 'Manual journal voucher. Approved by Owner.'}
                  </div>
                )}
              </div>
              <div>
                <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Allocations</div>
                {isUnalloc ? (
                  <div style={{ marginTop: 6 }}>
                    <div style={{ fontSize: 12, color: 'var(--danger-text)', fontWeight: 600 }}>0 / ₹1,84,000 allocated</div>
                    <Button variant="primary" size="sm" style={{ marginTop: 6 }} icon="link">Allocate now</Button>
                  </div>
                ) : (
                  <div style={{ fontSize: 12, marginTop: 6 }}>
                    {r.t === 'receipt' ? '1 invoice · ₹' + (r.cr || 0).toLocaleString('en-IN') + ' fully allocated' : 'n/a'}
                  </div>
                )}
              </div>
              <div>
                <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Related docs</div>
                <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
                  <Button variant="secondary" size="sm" icon="file">Open</Button>
                  <Button variant="secondary" size="sm" icon="download">PDF</Button>
                  <Button variant="secondary" size="sm" icon="copy">Duplicate</Button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </React.Fragment>
  );
}

function StatementTab() {
  return (
    <div style={{ padding: 24, display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20 }}>
      <div style={{
        background: '#FFF', border: '1px solid var(--border-default)', borderRadius: 6,
        boxShadow: '0 4px 16px rgba(40,38,32,0.08)',
        padding: 32, fontSize: 11, color: '#2A2820',
      }}>
        <div style={{ borderBottom: '2px solid #2A2820', paddingBottom: 14, marginBottom: 14 }}>
          <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '0.04em' }}>STATEMENT OF ACCOUNT</div>
          <div style={{ marginTop: 6, fontSize: 11, color: '#6B6859' }}>From <strong>01-Apr-2025</strong> to <strong>27-Apr-2026</strong></div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', color: '#6B6859' }}>FROM</div>
            <div style={{ fontSize: 13, fontWeight: 600, marginTop: 3 }}>Maaya Textiles</div>
            <div style={{ fontSize: 10, color: '#6B6859' }}>Surat, Gujarat · GSTIN 24AAACM1234F1Z3</div>
          </div>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', color: '#6B6859' }}>TO</div>
            <div style={{ fontSize: 13, fontWeight: 600, marginTop: 3 }}>Khan Sarees Pvt Ltd</div>
            <div style={{ fontSize: 10, color: '#6B6859' }}>Bandra W, Mumbai · GSTIN 27AAACK5821L1Z3</div>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, padding: '10px 12px', background: '#F4F1E6', borderRadius: 4 }}>
          <Mini k="Opening" v="₹1,62,000" />
          <Mini k="Total billed" v="₹26,40,000" />
          <Mini k="Total received" v="− ₹19,32,000" green />
          <Mini k="Closing" v="₹6,40,000" big />
        </div>
        <div style={{ marginTop: 14, fontSize: 10, color: '#6B6859', textAlign: 'center' }}>—— preview · 25 transactions on full statement ——</div>
      </div>

      <div>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, padding: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>Period</div>
          <Field label="From"><Input value="01-Apr-2025" /></Field>
          <div style={{ height: 8 }} />
          <Field label="To"><Input value="27-Apr-2026" /></Field>
          <div style={{ height: 12 }} />
          <Button variant="primary" size="sm" icon="download" style={{ width: '100%' }}>Download PDF</Button>
          <div style={{ height: 6 }} />
          <Button variant="secondary" size="sm" icon="send" style={{ width: '100%' }}>Email statement</Button>
        </div>
      </div>
    </div>
  );
}

function Mini({ k, v, big, green }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', color: '#6B6859' }}>{k.toUpperCase()}</div>
      <div className="num" style={{ fontSize: big ? 16 : 13, fontWeight: 700, marginTop: 3, color: green ? '#2D7A56' : '#2A2820' }}>{v}</div>
    </div>
  );
}

function AuditTab() {
  const events = [
    { ts: '27-Apr-26 · 11:42', who: 'Asha P.', what: 'Created invoice INV/25-26/000718', detail: '60 pcs · ₹76,000' },
    { ts: '24-Apr-26 · 16:08', who: 'Naseem',  what: 'Recorded receipt RCT/25-26/000408', detail: '₹1,84,000 NEFT — UNALLOCATED' },
    { ts: '14-Apr-26 · 14:22', who: 'Asha P.', what: 'Edited credit limit', detail: '₹8,00,000 → ₹10,00,000' },
    { ts: '02-Apr-26 · 10:11', who: 'Asha P.', what: 'Created invoice INV/25-26/000642' },
    { ts: '12-Mar-26 · 17:55', who: 'Owner',   what: 'Approved over-credit invoice', detail: 'INV/25-26/000581 · ₹2,48,000 above limit' },
    { ts: '24-Feb-26 · 09:30', who: 'Naseem',  what: 'Recorded receipt RCT/25-26/000341' },
    { ts: '18-Feb-26 · 12:14', who: 'Asha P.', what: 'Created credit note CN/25-26/000019' },
    { ts: '01-Apr-25 · 09:00', who: 'system',  what: 'Opening balance carried forward from FY 24-25', detail: '₹1,62,000' },
  ];
  return (
    <div style={{ padding: 24 }}>
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 18 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 14 }}>Append-only event log</div>
        <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {events.map((e, i) => (
            <li key={i} style={{ display: 'grid', gridTemplateColumns: '170px 1fr', gap: 16, padding: '10px 0', borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
              <div className="mono" style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>{e.ts}</div>
              <div>
                <div style={{ fontSize: 12.5 }}><strong>{e.who}</strong> {e.what}</div>
                {e.detail && <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 2 }}>{e.detail}</div>}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function PlaceholderTab({ name }) {
  return (
    <div style={{ padding: 60, textAlign: 'center', color: 'var(--text-tertiary)' }}>
      <Icon name="file" size={32} color="var(--text-tertiary)" />
      <div style={{ fontSize: 14, marginTop: 8 }}>{name} tab — full implementation in interactive prototype</div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-PARTY-003 — Party Edit (sheet)
───────────────────────────────────────────────────────────── */
function PartyEdit() {
  return (
    <div style={{
      background: 'var(--bg-surface)', borderRadius: 12,
      boxShadow: 'var(--shadow-3)', overflow: 'hidden',
      width: 720, maxHeight: '90vh', display: 'flex', flexDirection: 'column',
    }}>
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Edit party</h2>
        <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>· Khan Sarees Pvt Ltd</span>
        <button style={{ marginLeft: 'auto', background: 'transparent', border: 'none', cursor: 'pointer' }}>
          <Icon name="x" size={18} color="var(--text-tertiary)" />
        </button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
          <Field label="Party name" required>
            <Input value="Khan Sarees Pvt Ltd" />
          </Field>
          <Field label="Type">
            <SegmentedControl options={['Customer', 'Supplier', 'Both']} active="Customer" />
          </Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="GSTIN" required hint="Auto-validated">
            <div style={{ position: 'relative' }}>
              <Input value="27AAACK5821L1Z3" />
              <span style={{
                position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
                display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--success-text)', fontWeight: 600,
              }}><Icon name="check" size={12} /> Verified</span>
            </div>
          </Field>
          <Field label="PAN">
            <Input value="AAACK5821L" />
          </Field>
        </div>

        <Field label="Billing address">
          <textarea readOnly defaultValue={"Shop 14, Linking Rd, Bandra W,\nMumbai 400050, Maharashtra"} style={{
            width: '100%', minHeight: 70, padding: 10, fontSize: 12.5, fontFamily: 'inherit',
            border: '1px solid var(--border-default)', borderRadius: 6, color: 'var(--text-primary)', resize: 'vertical',
          }} />
        </Field>

        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Contacts</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[
              ['Salim Khan', 'Owner', '+91 98201 12121'],
              ['Asma Khan', 'Accounts', '+91 98201 88282'],
            ].map(([name, role, ph]) => (
              <div key={name} style={{ display: 'grid', gridTemplateColumns: '1fr 120px 160px 32px', gap: 8, alignItems: 'center' }}>
                <Input value={name} />
                <Input value={role} />
                <Input value={ph} />
                <button style={iconBtnPO}><Icon name="x" size={12} /></button>
              </div>
            ))}
            <button style={{
              padding: '8px 12px', textAlign: 'left', border: '1px dashed var(--border-default)', borderRadius: 6,
              fontSize: 12, color: 'var(--text-tertiary)', cursor: 'pointer', background: 'transparent',
            }}>+ Add contact</button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          <Field label="Credit limit"><Input value="10,00,000" prefix={<span>₹</span>} /></Field>
          <Field label="Payment terms"><Input value="Net 30" /></Field>
          <Field label="Opening balance" hint="As on 01-Apr-2025">
            <div style={{ display: 'flex', gap: 4 }}>
              <Input value="1,62,000" prefix={<span>₹</span>} />
              <SegmentedControl options={['Dr', 'Cr']} active="Dr" />
            </div>
          </Field>
        </div>
      </div>

      <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-sunken)', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button variant="ghost" size="sm">Cancel</Button>
        <Button variant="primary" size="sm">Save changes</Button>
      </div>
    </div>
  );
}

function SegmentedControl({ options, active }) {
  return (
    <div style={{
      display: 'inline-flex', borderRadius: 6, border: '1px solid var(--border-default)',
      background: 'var(--bg-sunken)', padding: 2, height: 40,
    }}>
      {options.map(o => (
        <span key={o} style={{
          padding: '0 12px',
          display: 'inline-flex', alignItems: 'center',
          borderRadius: 4, fontSize: 12.5, fontWeight: 500, cursor: 'pointer',
          background: o === active ? 'var(--bg-surface)' : 'transparent',
          color: o === active ? 'var(--text-primary)' : 'var(--text-tertiary)',
          boxShadow: o === active ? '0 1px 2px rgba(40,38,32,0.08)' : 'none',
        }}>{o}</span>
      ))}
    </div>
  );
}

Object.assign(window, {
  PartyList, PartyDetail, PartyEdit,
});
