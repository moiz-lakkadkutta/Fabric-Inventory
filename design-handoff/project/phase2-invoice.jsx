// phase2-invoice.jsx — SCR-SALES-001 list, SCR-SALES-002 create (6 states), SCR-SALES-003 PDF preview.

const { useState: useStateInv } = React;

/* ── INVOICE LIST DATA ─────────────────────────────────────── */
const INV_LIST = [
  { n: 'TI/25-26/000847', date: '27-Apr-2026', cust: 'Khan Sarees Pvt Ltd',     city: 'Mumbai',    amt: '3,42,500.00', status: 'draft',     out: '—',  sp: 'Anil R.',  type: 'TI' },
  { n: 'TI/25-26/000846', date: '27-Apr-2026', cust: 'Patel Fabrics',           city: 'Surat',    amt: '46,250.00',   status: 'finalized', out: '7d', sp: 'Moiz L.',  type: 'TI' },
  { n: 'TI/25-26/000845', date: '27-Apr-2026', cust: 'New Era Garments',        city: 'Delhi',    amt: '2,12,400.00', status: 'overdue',   out: '38d',sp: 'Anil R.',  type: 'TI' },
  { n: 'TI/25-26/000844', date: '26-Apr-2026', cust: 'Manish Creations',        city: 'Mumbai',   amt: '88,400.00',   status: 'finalized', out: '8d', sp: 'Bhavna P.',type: 'TI' },
  { n: 'CM/25-26/000118', date: '26-Apr-2026', cust: 'Walk-in (Vimal Shah)',    city: 'Surat',    amt: '12,500.00',   status: 'paid',      out: '—',  sp: 'Moiz L.',  type: 'CM' },
  { n: 'TI/25-26/000843', date: '26-Apr-2026', cust: 'Lakhani Textiles',        city: 'Ahmedabad',amt: '3,42,000.00', status: 'overdue',   out: '21d',sp: 'Anil R.',  type: 'TI' },
  { n: 'EST/25-26/000067',date: '25-Apr-2026', cust: 'Roshan Boutique',         city: 'Mumbai',   amt: '58,200.00',   status: 'draft',     out: '—',  sp: 'Bhavna P.',type: 'EST'},
  { n: 'TI/25-26/000842', date: '25-Apr-2026', cust: 'Ahmedabad Silk Mills',    city: 'Ahmedabad',amt: '1,24,500.00', status: 'paid',      out: '—',  sp: 'Moiz L.',  type: 'TI' },
  { n: 'BoS/25-26/000034',date: '24-Apr-2026', cust: 'Jamil Tailors',           city: 'Hyderabad',amt: '34,800.00',   status: 'finalized', out: '11d',sp: 'Anil R.',  type: 'BoS'},
  { n: 'TI/25-26/000841', date: '24-Apr-2026', cust: 'Mehta Garment House',     city: 'Mumbai',   amt: '1,68,900.00', status: 'paid',      out: '—',  sp: 'Bhavna P.',type: 'TI' },
];

function FilterChip({ label, value, active, hasMenu = true }) {
  return (
    <div style={{
      height: 32, padding: '0 10px',
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: active ? 'var(--accent-subtle)' : 'var(--bg-surface)',
      border: '1px solid ' + (active ? 'var(--accent)' : 'var(--border-default)'),
      borderRadius: 16, fontSize: 12.5,
      color: active ? 'var(--accent)' : 'var(--text-secondary)',
      fontWeight: active ? 600 : 500, whiteSpace: 'nowrap',
    }}>
      <span>{label}</span>
      {value && <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>· {value}</span>}
      {hasMenu && <Icon name="chevron-down" size={11} color="currentColor" />}
    </div>
  );
}

function InvoiceListDesktop() {
  return (
    <div style={{ background: 'var(--bg-canvas)' }}>
      <div style={{
        padding: '20px 32px', borderBottom: '1px solid var(--border-default)',
        background: 'var(--bg-surface)',
        display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Sales › Invoices</div>
          <h1 style={{ fontSize: 24, fontWeight: 600, margin: 0 }}>Invoices</h1>
        </div>
        <Button variant="ghost" size="md">Import</Button>
        <Button variant="primary" size="md" icon={<Icon name="plus" size={14} color="currentColor" />}>New invoice</Button>
      </div>

      {/* Toolbar */}
      <div style={{ padding: '14px 32px', display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', borderBottom: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}>
        <div style={{
          height: 32, padding: '0 12px', minWidth: 280,
          background: 'var(--bg-sunken)', border: '1px solid var(--border-default)',
          borderRadius: 6, display: 'inline-flex', alignItems: 'center', gap: 8,
          color: 'var(--text-tertiary)', fontSize: 13,
        }}>
          <Icon name="search" size={14} />
          <span>Search invoice #, customer, amount…</span>
        </div>
        <div style={{ width: 1, height: 24, background: 'var(--border-default)', margin: '0 4px' }} />
        <FilterChip label="Type" value="All" />
        <FilterChip label="Status" value="Any" />
        <FilterChip label="Date" value="Last 30 days" />
        <FilterChip label="Customer" />
        <FilterChip label="Salesperson" />
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-tertiary)' }} className="num">10 of 247 invoices · ₹13.42L total</span>
      </div>

      {/* Table */}
      <div style={{ padding: 24 }}>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-sunken)', borderBottom: '1px solid var(--border-default)' }}>
                <th style={{...thStyle, width: 36, textAlign: 'center'}}>
                  <span style={{ display: 'inline-block', width: 14, height: 14, border: '1.5px solid var(--border-strong)', borderRadius: 3 }} />
                </th>
                <th style={{...thStyle, width: 36}}>#</th>
                <th style={thStyle}>Invoice number</th>
                <th style={{...thStyle, width: 110}}>Date</th>
                <th style={thStyle}>Customer</th>
                <th style={{...thStyle, textAlign: 'right', width: 130}}>Amount</th>
                <th style={{...thStyle, width: 110}}>Status</th>
                <th style={{...thStyle, width: 90, textAlign: 'right'}}>Days out</th>
                <th style={{...thStyle, width: 110}}>Salesperson</th>
                <th style={{...thStyle, width: 40}}></th>
              </tr>
            </thead>
            <tbody>
              {INV_LIST.map((r, i) => (
                <tr key={r.n} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td style={{...tdStyle, textAlign: 'center'}}>
                    <span style={{ display: 'inline-block', width: 14, height: 14, border: '1.5px solid var(--border-strong)', borderRadius: 3 }} />
                  </td>
                  <td className="num" style={{...tdStyle, color: 'var(--text-tertiary)'}}>{i + 1}</td>
                  <td className="mono" style={tdStyle}>{r.n}</td>
                  <td className="num" style={{...tdStyle, color: 'var(--text-secondary)', whiteSpace: 'nowrap'}}>{r.date}</td>
                  <td style={tdStyle}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Monogram initials={r.cust.split(' ').map(w => w[0]).slice(0,2).join('')} size={24} />
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>{r.cust}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{r.city}</div>
                      </div>
                    </div>
                  </td>
                  <td className="num" style={{...tdStyle, textAlign: 'right', fontWeight: 500}}>₹{r.amt}</td>
                  <td style={tdStyle}><Pill kind={r.status}>{cap(r.status)}</Pill></td>
                  <td className="num" style={{...tdStyle, textAlign: 'right', color: r.status === 'overdue' ? 'var(--danger-text)' : r.status === 'paid' ? 'var(--text-disabled)' : 'var(--text-secondary)', fontWeight: r.status === 'overdue' ? 600 : 400}}>{r.out}</td>
                  <td style={{...tdStyle, fontSize: 12, color: 'var(--text-secondary)'}}>{r.sp}</td>
                  <td style={tdStyle}><Icon name="more" size={14} color="var(--text-tertiary)" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function cap(s) { return s[0].toUpperCase() + s.slice(1); }

function InvoiceListEmpty() {
  return (
    <div style={{ background: 'var(--bg-canvas)', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '20px 32px', borderBottom: '1px solid var(--border-default)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Sales › Invoices</div>
          <h1 style={{ fontSize: 24, fontWeight: 600, margin: 0 }}>Invoices</h1>
        </div>
        <Button variant="primary" size="md" icon={<Icon name="plus" size={14} color="currentColor" />}>New invoice</Button>
      </div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 32 }}>
        <div style={{ textAlign: 'center', maxWidth: 380 }}>
          <svg width="120" height="120" viewBox="0 0 120 120" style={{ marginBottom: 16, color: 'var(--text-tertiary)' }} fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="24" y="32" width="64" height="80" rx="3" />
            <rect x="32" y="24" width="64" height="80" rx="3" fill="var(--bg-sunken)" />
            <rect x="40" y="16" width="64" height="80" rx="3" fill="var(--bg-surface)" />
            <line x1="48" y1="32" x2="92" y2="32" />
            <line x1="48" y1="44" x2="92" y2="44" />
            <line x1="48" y1="56" x2="80" y2="56" />
            <line x1="48" y1="76" x2="92" y2="76" strokeWidth="2" stroke="var(--accent)" />
          </svg>
          <h3 style={{ fontSize: 18, fontWeight: 600, margin: 0, marginBottom: 6 }}>No invoices yet</h3>
          <p style={{ fontSize: 13.5, color: 'var(--text-secondary)', margin: 0, marginBottom: 18, lineHeight: 1.55 }}>Create your first one to start your day book. Invoices count, ledger entries, and GST returns flow from here.</p>
          <Button variant="primary" size="md" icon={<Icon name="plus" size={14} color="currentColor" />}>New invoice</Button>
        </div>
      </div>
    </div>
  );
}

/* ── INVOICE CREATE ──────────────────────────────────────── */

const LINE_ITEMS = [
  { code: 'SLK-GEO-60', name: 'Silk Georgette 60GSM White', lot: 'LT-2026-0042', hsn: '5407', qty: '50.00', uom: 'm',  rate: '185.00', disc: '0', tax: '5%', amt: '9,250.00' },
  { code: 'BNS-SLK-90', name: 'Banarasi Silk 90GSM Maroon', lot: 'LT-2026-0043', hsn: '5407', qty: '24.00', uom: 'm',  rate: '620.00', disc: '0', tax: '5%', amt: '14,880.00' },
];

function DocTab({ children, active }) {
  return (
    <div style={{
      padding: '10px 14px', fontSize: 13, fontWeight: active ? 600 : 500,
      color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
      borderBottom: '2px solid ' + (active ? 'var(--accent)' : 'transparent'),
      cursor: 'default', whiteSpace: 'nowrap', marginBottom: -1,
    }}>{children}</div>
  );
}

function ModeToggle({ mode = 'quick' }) {
  return (
    <div style={{ display: 'inline-flex', height: 30, background: 'var(--bg-sunken)', border: '1px solid var(--border-default)', borderRadius: 6, padding: 2, gap: 2 }}>
      {['Quick', 'Detailed'].map((m, i) => (
        <div key={m} style={{
          padding: '0 12px', display: 'inline-flex', alignItems: 'center',
          background: (mode === 'quick' ? i === 0 : i === 1) ? 'var(--bg-surface)' : 'transparent',
          color: (mode === 'quick' ? i === 0 : i === 1) ? 'var(--text-primary)' : 'var(--text-secondary)',
          fontWeight: (mode === 'quick' ? i === 0 : i === 1) ? 600 : 500, fontSize: 12.5,
          borderRadius: 4, boxShadow: (mode === 'quick' ? i === 0 : i === 1) ? 'var(--shadow-1)' : 'none',
        }}>{m}</div>
      ))}
    </div>
  );
}

function LiveTotalsCard({ state = 'normal', invalid }) {
  if (state === 'loading') {
    return (
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 18 }}>
        {['Subtotal', 'Discount', 'Taxable', 'CGST 9%', 'SGST 9%', 'Round off'].map((l, i) => (
          <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', alignItems: 'center' }}>
            <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>{l}</span>
            <span style={{ width: 80, height: 14, borderRadius: 4, background: 'linear-gradient(90deg, #EFEDE6 0%, #F7F6F2 50%, #EFEDE6 100%)', backgroundSize: '200% 100%', animation: 'taanaShimmer 1.4s linear infinite' }} />
          </div>
        ))}
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-default)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 600 }}>Total</span>
          <span style={{ width: 110, height: 22, borderRadius: 4, background: 'linear-gradient(90deg, #EFEDE6 0%, #F7F6F2 50%, #EFEDE6 100%)', backgroundSize: '200% 100%', animation: 'taanaShimmer 1.4s linear infinite' }} />
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
          <Icon name="spinner" size={11} color="var(--text-tertiary)" />
          <span>Recalculating tax…</span>
        </div>
      </div>
    );
  }
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 18 }}>
      <Row label="Subtotal"   value="₹24,130.00" />
      <Row label="Discount"   value="−₹0.00" muted />
      <Row label="Taxable"    value="₹24,130.00" />
      <Row label="CGST 9%"    value="₹2,171.70" muted />
      <Row label="SGST 9%"    value="₹2,171.70" muted hint="Intrastate · Maharashtra→Maharashtra" />
      <Row label="Round off"  value="−₹0.40" muted />
      <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-default)', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>Total</span>
        <span className="num" style={{ fontSize: 28, fontWeight: 700, color: 'var(--accent)', letterSpacing: '-0.012em' }}>₹28,473.00</span>
      </div>
    </div>
  );
}

function Row({ label, value, muted, hint }) {
  return (
    <div style={{ padding: '5px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <span style={{
          fontSize: 12.5, color: 'var(--text-tertiary)',
          whiteSpace: 'nowrap',
        }}>{label}</span>
        <span className="num" style={{
          fontSize: 13.5, color: muted ? 'var(--text-secondary)' : 'var(--text-primary)',
          fontWeight: muted ? 400 : 500, whiteSpace: 'nowrap', flexShrink: 0,
        }}>{value}</span>
      </div>
      {hint && <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 1 }}>{hint}</div>}
    </div>
  );
}

function CreditLimitBar({ used = 0.48, limit = '₹5,00,000', current = '₹2,40,000', state = 'ok' }) {
  const color = state === 'breach' ? 'var(--danger)' : used >= 0.8 ? 'var(--warning)' : 'var(--accent)';
  const bg    = state === 'breach' ? 'var(--danger-subtle)' : used >= 0.8 ? 'var(--warning-subtle)' : 'var(--accent-subtle)';
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8, gap: 8, minWidth: 0 }}>
        <span style={{
          fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase',
          letterSpacing: '.04em', fontWeight: 600, whiteSpace: 'nowrap',
        }}>Credit limit</span>
        <span className="num" style={{ fontSize: 12, color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>{Math.round(used * 100)}% used</span>
      </div>
      <div style={{ height: 6, borderRadius: 999, background: bg, overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(used, 1) * 100}%`, height: '100%', background: color, borderRadius: 999 }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12.5, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}><span className="num" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{current}</span> of <span className="num">{limit}</span></span>
        {state === 'breach' && <span style={{ fontSize: 11, color: 'var(--danger-text)', fontWeight: 600, whiteSpace: 'nowrap' }}>Over by ₹40,000</span>}
      </div>
    </div>
  );
}

function LineItemsTable({ rows = LINE_ITEMS, errorRow = -1, hideTax = false }) {
  const empties = Array.from({ length: 6 - rows.length });
  return (
    <div style={{ border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg-surface)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'var(--bg-sunken)' }}>
            <th style={{...thStyle, width: 36}}>#</th>
            <th style={thStyle}>Item</th>
            <th style={{...thStyle, width: 70}}>HSN</th>
            <th style={{...thStyle, width: 80, textAlign: 'right'}}>Qty</th>
            <th style={{...thStyle, width: 56}}>UOM</th>
            <th style={{...thStyle, width: 90, textAlign: 'right'}}>Rate</th>
            <th style={{...thStyle, width: 70, textAlign: 'right'}}>Disc %</th>
            {!hideTax && <th style={{...thStyle, width: 70}}>Tax</th>}
            <th style={{...thStyle, width: 110, textAlign: 'right'}}>Amount</th>
            <th style={{...thStyle, width: 32}}></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <React.Fragment key={i}>
              <tr style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td className="num" style={{...tdStyle, color: 'var(--text-tertiary)'}}>{i + 1}</td>
                <td style={tdStyle}>
                  <div style={{ fontWeight: 500 }}>{r.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }} className="mono">
                    {r.code} · lot <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{r.lot}</span>
                  </div>
                </td>
                <td className="mono" style={{...tdStyle, color: 'var(--text-secondary)'}}>{r.hsn}</td>
                <td className="num" style={{...tdStyle, textAlign: 'right'}}>{r.qty}</td>
                <td style={{...tdStyle, color: 'var(--text-secondary)'}}>{r.uom}</td>
                <td className="num" style={{...tdStyle, textAlign: 'right'}}>{r.rate}</td>
                <td className="num" style={{...tdStyle, textAlign: 'right', color: 'var(--text-tertiary)'}}>{r.disc}</td>
                {!hideTax && <td className="mono" style={{...tdStyle, color: 'var(--text-secondary)'}}>{r.tax}</td>}
                <td className="num" style={{...tdStyle, textAlign: 'right', fontWeight: 500}}>{r.amt}</td>
                <td style={{...tdStyle, textAlign: 'center'}}><Icon name="x" size={12} color="var(--text-tertiary)" /></td>
              </tr>
              {errorRow === i && (
                <tr style={{ background: 'var(--danger-subtle)' }}>
                  <td colSpan={!hideTax ? 10 : 9} style={{ padding: '10px 16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12.5, color: 'var(--danger-text)' }}>
                      <Icon name="alert" size={14} color="var(--danger)" />
                      <span style={{ flex: 1 }}>Only <strong className="num">12.5 m</strong> of <span className="mono">LT-2026-0042</span> available. Pick another lot or reduce quantity.</span>
                      <button style={{ height: 26, padding: '0 10px', background: 'var(--bg-surface)', border: '1px solid var(--danger)', color: 'var(--danger-text)', borderRadius: 4, fontSize: 11.5, fontWeight: 600 }}>Pick another lot</button>
                      <button style={{ height: 26, padding: '0 10px', background: 'var(--danger)', border: 0, color: '#FAFAF7', borderRadius: 4, fontSize: 11.5, fontWeight: 600 }}>Reduce qty to 12.5 m</button>
                    </div>
                  </td>
                </tr>
              )}
            </React.Fragment>
          ))}
          {empties.map((_, j) => (
            <tr key={'e' + j} style={{ borderTop: '1px solid var(--border-subtle)', height: 38 }}>
              <td className="num" style={{...tdStyle, color: 'var(--text-disabled)'}}>{rows.length + j + 1}</td>
              <td style={{...tdStyle, color: 'var(--text-disabled)', fontStyle: 'italic'}}>{j === 0 ? 'Add item — start typing item code or name' : ''}</td>
              <td colSpan={!hideTax ? 8 : 7} style={tdStyle}></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ActivityRail({ state = 'draft' }) {
  return (
    <aside style={{
      width: 320, flexShrink: 0,
      background: 'var(--bg-surface)', borderLeft: '1px solid var(--border-default)',
      padding: 20, position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600, marginBottom: 14 }}>Activity & history</div>
      {state === 'paid' && (
        <div style={{
          position: 'absolute', top: 60, right: 24, transform: 'rotate(-12deg)',
          padding: '6px 18px', border: '2px solid var(--success)', color: 'var(--success-text)',
          fontWeight: 700, fontSize: 14, letterSpacing: '.08em', borderRadius: 4,
          opacity: 0.55, background: 'var(--success-subtle)', zIndex: 1,
        }}>PAID</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <ActivityItem dot="accent" label="Created 2 min ago" sub="by Moiz Lakkadkutta" />
        {state !== 'draft' && <ActivityItem dot="info" label="Customer notified via WhatsApp" sub="27-Apr-2026 · 14:38" />}
        {state === 'paid' && <ActivityItem dot="success" label="Payment received" sub="₹3,42,500 via NEFT · 27-Apr-2026 · linked to RC/25-26/000412" />}
        <div style={{ paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600, marginBottom: 8 }}>Customer pulse</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.55 }}>
            Last invoice <span className="mono" style={{ color: 'var(--text-primary)' }}>TI/25-26/000846</span> of <span className="num" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>₹1,80,000</span>, paid 4 days ago.
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.55, marginTop: 8 }}>
            Currently outstanding <span className="num" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>₹2,40,000</span> across 3 invoices.
          </div>
        </div>
      </div>
    </aside>
  );
}

function ActivityItem({ dot, label, sub }) {
  const c = dot === 'accent' ? 'var(--accent)' : dot === 'success' ? 'var(--success)' : 'var(--info)';
  return (
    <div style={{ display: 'flex', gap: 10 }}>
      <span style={{ width: 8, height: 8, borderRadius: 999, background: c, marginTop: 6, flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>
      </div>
    </div>
  );
}

function CustomerHeader({ outstanding = '₹2,40,000' }) {
  return (
    <Field label="Customer" required>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', border: '1.5px solid var(--accent)', borderRadius: 6, background: 'var(--bg-surface)' }}>
        <Monogram initials="KS" size={32} tone="accent" />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Khan Sarees Pvt Ltd</div>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
            <span className="mono">27AAAAA0000A1Z5</span> · Mumbai · Outstanding <span className="num" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{outstanding}</span>
          </div>
        </div>
        <Icon name="x" size={14} color="var(--text-tertiary)" />
      </div>
    </Field>
  );
}

function FooterHints() {
  const items = [['⌘S', 'Save'], ['⌘↵', 'Finalize'], ['⌘K', 'Search'], ['Tab', 'Next'], ['↑↓', 'Rows'], ['⌘⌫', 'Delete row']];
  return (
    <div style={{
      borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-sunken)',
      padding: '8px 24px', display: 'flex', gap: 16, fontSize: 11, color: 'var(--text-tertiary)',
    }}>
      {items.map(([k, l]) => (
        <span key={k}>
          <span className="mono" style={{ padding: '1px 5px', borderRadius: 3, background: 'var(--bg-surface)', border: '1px solid var(--border-default)', color: 'var(--text-secondary)', fontWeight: 600 }}>{k}</span>
          <span style={{ marginLeft: 6 }}>{l}</span>
        </span>
      ))}
    </div>
  );
}

/* The 6 invoice variants. Each renders as a complete page block. */
function InvoiceCreate({ variant = 'draft' }) {
  const isDraft     = variant === 'draft';
  const isConfirmed = variant === 'confirmed';
  const isPaid      = variant === 'paid';
  const isCreditErr = variant === 'credit-error';
  const isStockErr  = variant === 'stock-error';
  const isLoading   = variant === 'loading';

  const headerPill =
    isDraft     ? <Pill kind="draft">Draft</Pill> :
    isConfirmed ? <Pill kind="finalized">Confirmed · TI/25-26/000847</Pill> :
    isPaid      ? <Pill kind="paid">Paid · TI/25-26/000847</Pill> :
    isCreditErr ? <Pill kind="overdue">Approval needed</Pill> :
    isStockErr  ? <Pill kind="draft">Draft · stock issue</Pill> :
                  <Pill kind="draft">Draft · recalculating</Pill>;

  return (
    <div style={{ background: 'var(--bg-canvas)', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        padding: '16px 24px', borderBottom: '1px solid var(--border-default)',
        background: 'var(--bg-surface)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>Sales › Invoices › New</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0, whiteSpace: 'nowrap' }}>{isConfirmed || isPaid ? 'Invoice' : 'New invoice'}</h1>
            {headerPill}
          </div>
        </div>
        {(isConfirmed || isPaid) && (
          <>
            <Button variant="ghost" size="md">Edit</Button>
            <Button variant="ghost" size="md">Cancel</Button>
            <Button variant="secondary" size="md" icon={<Icon name="message" size={14} color="currentColor" />}>WhatsApp</Button>
            <Button variant="secondary" size="md" icon={<Icon name="download" size={14} color="currentColor" />}>Print</Button>
          </>
        )}
        {isCreditErr && (
          <>
            <Button variant="secondary" size="md">Save draft</Button>
            <button style={{
              height: 40, padding: '0 16px', borderRadius: 6,
              background: 'var(--warning)', color: '#fff', border: 0, fontWeight: 600, fontSize: 14,
              display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'default',
            }}><Icon name="shield" size={14} color="#fff" /> Request approval</button>
          </>
        )}
        {isDraft && (
          <>
            <Button variant="secondary" size="md">Save draft</Button>
            <Button variant="primary" size="md" icon={<Icon name="check" size={14} color="currentColor" />}>Finalize & print</Button>
          </>
        )}
        {(isStockErr || isLoading) && (
          <>
            <Button variant="secondary" size="md">Save draft</Button>
            <Button variant="primary" size="md" state={isStockErr ? 'disabled' : 'rest'} icon={<Icon name="check" size={14} color="currentColor" />}>Finalize & print</Button>
          </>
        )}
      </div>

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <main style={{ flex: 1, padding: 24, display: 'flex', flexDirection: 'column', gap: 18, overflow: 'hidden' }}>
          <ModeToggle />

          {/* Doc-type tabs */}
          <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border-default)' }}>
            <DocTab active>Tax invoice</DocTab>
            <DocTab>Bill of supply</DocTab>
            <DocTab>Cash memo</DocTab>
            <DocTab>Estimate</DocTab>
          </div>

          {/* 60 / 40 form */}
          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 20 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <CustomerHeader outstanding={isCreditErr ? '₹5,40,000' : '₹2,40,000'} />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Field label="Invoice date"><Input value="27-Apr-2026" suffix={<Icon name="calendar" size={14} />} state={isConfirmed || isPaid ? 'disabled' : 'default'} /></Field>
                <Field label="Due date"      hint="Net 15"><Input value="12-May-2026" suffix={<Icon name="calendar" size={14} />} state={isConfirmed || isPaid ? 'disabled' : 'default'} /></Field>
                <Field label="Reference"><Input value="PO-KS/2026/118" /></Field>
                <Field label="Place of supply" helper="Auto-derived from customer">
                  <Input value="Maharashtra (27)" state="disabled" />
                </Field>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {isCreditErr && (
                <div style={{
                  padding: 14, borderRadius: 8, background: 'var(--danger-subtle)',
                  borderLeft: '3px solid var(--danger)', display: 'flex', gap: 10, alignItems: 'flex-start',
                }}>
                  <Icon name="alert" size={16} color="var(--danger)" />
                  <div style={{ fontSize: 12.5, color: 'var(--danger-text)', lineHeight: 1.5 }}>
                    <strong>Khan Sarees Pvt Ltd</strong> is over credit limit by <span className="num" style={{ fontWeight: 700 }}>₹40,000</span>. Finalize requires Sales Manager approval.
                  </div>
                </div>
              )}
              <LiveTotalsCard state={isLoading ? 'loading' : 'normal'} />
              <CreditLimitBar
                used={isCreditErr ? 1.08 : 0.48}
                state={isCreditErr ? 'breach' : 'ok'}
                limit={isCreditErr ? '₹5,00,000' : '₹5,00,000'}
                current={isCreditErr ? '₹5,40,000' : '₹2,40,000'}
              />
            </div>
          </div>

          {/* Line items */}
          <LineItemsTable rows={LINE_ITEMS} errorRow={isStockErr ? 0 : -1} />

          {/* Notes / Terms */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Field label="Customer notes" hint="Visible on the invoice">
              <textarea readOnly value={'Goods once sold will not be taken back.\nPayment by RTGS to HDFC a/c · 50100245678901, IFSC HDFC0001234.'} style={{
                width: '100%', height: 70, padding: 10, fontFamily: 'inherit', fontSize: 13, lineHeight: 1.45,
                border: '1px solid var(--border-default)', borderRadius: 6, background: 'var(--bg-surface)',
                color: 'var(--text-primary)', resize: 'none',
              }} />
            </Field>
            <Field label="Terms" hint="Defaults from firm settings">
              <textarea readOnly value={'Net 15. Interest @18% p.a. on overdue amounts.\nLot identifier mandatory for any return.'} style={{
                width: '100%', height: 70, padding: 10, fontFamily: 'inherit', fontSize: 13, lineHeight: 1.45,
                border: '1px solid var(--border-default)', borderRadius: 6, background: 'var(--bg-surface)',
                color: 'var(--text-primary)', resize: 'none',
              }} />
            </Field>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Icon name="lock" size={11} color="var(--text-tertiary)" />
            <span>Internal note (staff-only) ·</span>
            <span style={{ color: 'var(--accent)', fontWeight: 500 }}>Add</span>
          </div>
        </main>

        <ActivityRail state={isPaid ? 'paid' : isConfirmed ? 'confirmed' : 'draft'} />
      </div>

      <FooterHints />
    </div>
  );
}

/* ── PDF preview sheet ───────────────────────────────────── */
function PdfSheet({ docType = 'TI' }) {
  const isTI  = docType === 'TI';
  const isBoS = docType === 'BoS';
  const isCM  = docType === 'CM';
  const isEST = docType === 'EST';

  return (
    <div style={{
      background: 'rgba(20,20,18,.32)', height: '100%',
      display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
      padding: 24, overflow: 'auto', position: 'relative',
    }}>
      {/* Sheet */}
      <div style={{
        background: 'var(--bg-surface)', width: 720, borderRadius: 12,
        boxShadow: 'var(--shadow-4)', overflow: 'hidden',
      }}>
        {/* Sheet header */}
        <div style={{
          padding: '14px 20px', borderBottom: '1px solid var(--border-default)',
          display: 'flex', alignItems: 'center', gap: 12, background: 'var(--bg-sunken)',
        }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Preview</div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              {isTI ? 'Tax invoice' : isBoS ? 'Bill of supply' : isCM ? 'Cash memo' : 'Estimate'} · TI/25-26/000847
            </div>
          </div>
          <Button variant="ghost" size="sm" icon={<Icon name="message" size={13} color="currentColor" />}>WhatsApp</Button>
          <Button variant="secondary" size="sm" icon={<Icon name="download" size={13} color="currentColor" />}>Download</Button>
          <Button variant="primary" size="sm" icon={<Icon name="check" size={13} color="currentColor" />}>Print</Button>
          <Icon name="x" size={16} color="var(--text-tertiary)" />
        </div>

        {/* A4 — 80% scale */}
        <div style={{ background: 'var(--bg-sunken)', padding: 24, display: 'flex', justifyContent: 'center' }}>
          <div style={{
            width: 595 * 0.95, minHeight: 842 * 0.85, background: '#FFFFFF',
            border: '1px solid var(--border-default)', boxShadow: 'var(--shadow-2)',
            padding: 32, fontSize: 11, lineHeight: 1.5, color: '#1A1A17', position: 'relative',
          }}>
            {isEST && (
              <div style={{
                position: 'absolute', top: '40%', left: '50%', transform: 'translate(-50%, -50%) rotate(-22deg)',
                fontSize: 64, fontWeight: 800, color: '#1A1A17', opacity: 0.06, letterSpacing: '0.04em', whiteSpace: 'nowrap',
              }}>NOT A TAX INVOICE</div>
            )}
            {/* Letterhead */}
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, paddingBottom: 14, borderBottom: '1.5px solid #1A1A17' }}>
              <TaanaMark size={28} color="#0F7A4E" />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.01em' }}>Rajesh Textiles</div>
                <div style={{ fontSize: 10, color: '#5C5A52' }}>Shop 12, Ring Road, Surat · Gujarat 395002 · India</div>
                <div style={{ fontSize: 10, color: '#5C5A52' }}>GSTIN <span className="mono" style={{ color: '#1A1A17' }}>24ABCDE1234F1Z5</span> · PAN <span className="mono">ABCDE1234F</span></div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em' }}>{isTI ? 'TAX INVOICE' : isBoS ? 'BILL OF SUPPLY' : isCM ? 'CASH MEMO' : 'ESTIMATE'}</div>
                <div style={{ fontSize: 10, color: '#5C5A52' }}>Original for recipient</div>
              </div>
            </div>

            {/* Customer + meta */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginTop: 14 }}>
              <div>
                <div style={{ fontSize: 9, color: '#8A8880', textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600 }}>Bill to</div>
                <div style={{ fontSize: 12, fontWeight: 700, marginTop: 2 }}>{isCM ? 'Walk-in customer' : 'Khan Sarees Pvt Ltd'}</div>
                {!isCM && <div style={{ fontSize: 10 }}>Plot 4, Mangaldas Market, Mumbai 400002</div>}
                {!isCM && <div style={{ fontSize: 10 }}>GSTIN <span className="mono">27AAAAA0000A1Z5</span></div>}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 10, rowGap: 3, fontSize: 10, alignContent: 'start' }}>
                <span style={{ color: '#8A8880' }}>Invoice no.</span><span className="mono" style={{ fontWeight: 600 }}>TI/25-26/000847</span>
                <span style={{ color: '#8A8880' }}>Date</span><span className="num">27-Apr-2026</span>
                <span style={{ color: '#8A8880' }}>Due</span><span className="num">12-May-2026</span>
                <span style={{ color: '#8A8880' }}>Place of supply</span><span>Maharashtra (27)</span>
                <span style={{ color: '#8A8880' }}>Reference</span><span className="mono">PO-KS/2026/118</span>
              </div>
            </div>

            {/* Line items */}
            <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 14, fontSize: 10 }}>
              <thead>
                <tr style={{ background: '#F7F6F2', borderTop: '1px solid #1A1A17', borderBottom: '1px solid #1A1A17' }}>
                  <th style={pdfTh}>#</th>
                  <th style={{...pdfTh, textAlign: 'left'}}>Description</th>
                  {!isCM && <th style={pdfTh}>HSN</th>}
                  <th style={{...pdfTh, textAlign: 'right'}}>Qty</th>
                  <th style={{...pdfTh, textAlign: 'right'}}>Rate</th>
                  {(isTI) && <th style={{...pdfTh, textAlign: 'right'}}>Tax</th>}
                  <th style={{...pdfTh, textAlign: 'right'}}>Amount</th>
                </tr>
              </thead>
              <tbody>
                {LINE_ITEMS.map((r, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #ECEAE2' }}>
                    <td className="num" style={pdfTd}>{i + 1}</td>
                    <td style={pdfTd}>
                      <div style={{ fontWeight: 600 }}>{r.name}</div>
                      <div style={{ fontSize: 9, color: '#5C5A52' }} className="mono">Lot {r.lot}</div>
                    </td>
                    {!isCM && <td className="mono" style={{...pdfTd, textAlign: 'center'}}>{r.hsn}</td>}
                    <td className="num" style={{...pdfTd, textAlign: 'right'}}>{r.qty} {r.uom}</td>
                    <td className="num" style={{...pdfTd, textAlign: 'right'}}>{r.rate}</td>
                    {(isTI) && <td className="mono" style={{...pdfTd, textAlign: 'right'}}>{r.tax}</td>}
                    <td className="num" style={{...pdfTd, textAlign: 'right', fontWeight: 600}}>{r.amt}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Tax block */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
              <table style={{ borderCollapse: 'collapse', fontSize: 10, minWidth: 280 }}>
                <tbody>
                  <tr><td style={pdfTd}>Subtotal</td><td className="num" style={{...pdfTd, textAlign: 'right'}}>24,130.00</td></tr>
                  {isTI && <tr><td style={pdfTd}>CGST 9%</td><td className="num" style={{...pdfTd, textAlign: 'right'}}>2,171.70</td></tr>}
                  {isTI && <tr><td style={pdfTd}>SGST 9%</td><td className="num" style={{...pdfTd, textAlign: 'right'}}>2,171.70</td></tr>}
                  <tr><td style={pdfTd}>Round off</td><td className="num" style={{...pdfTd, textAlign: 'right'}}>−0.40</td></tr>
                  <tr style={{ borderTop: '1.5px solid #1A1A17' }}>
                    <td style={{...pdfTd, fontWeight: 700, fontSize: 12}}>Total</td>
                    <td className="num" style={{...pdfTd, textAlign: 'right', fontWeight: 700, fontSize: 12}}>₹{isTI ? '28,473.00' : '24,130.00'}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {isBoS && (
              <div style={{ marginTop: 12, padding: 8, fontSize: 9.5, color: '#5C5A52', background: '#F7F6F2', borderRadius: 4 }}>
                Tax not applicable — composition scheme / unregistered dealer. CGST and SGST not chargeable.
              </div>
            )}

            {/* Total in words */}
            <div style={{ marginTop: 12, padding: '8px 0', borderTop: '1px solid #ECEAE2', fontSize: 10 }}>
              <span style={{ color: '#8A8880' }}>Amount in words: </span>
              <span style={{ fontWeight: 600, fontStyle: 'italic' }}>
                {isTI ? 'Rupees Twenty Eight Thousand Four Hundred Seventy Three Only' : 'Rupees Twenty Four Thousand One Hundred Thirty Only'}
              </span>
            </div>

            {/* Footer */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 14, paddingTop: 12, borderTop: '1px solid #ECEAE2' }}>
              <div>
                <div style={{ fontSize: 9, color: '#8A8880', textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600 }}>Bank details</div>
                <div style={{ fontSize: 10, marginTop: 2 }} className="mono">HDFC Bank · 50100245678901 · IFSC HDFC0001234</div>
                <div style={{ fontSize: 10, color: '#5C5A52' }}>RTGS / NEFT · Beneficiary: Rajesh Textiles</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 9, color: '#8A8880' }}>For Rajesh Textiles</div>
                <div style={{ height: 38 }} />
                <div style={{ borderTop: '1px solid #1A1A17', fontSize: 9, paddingTop: 4 }}>Authorised signatory</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

const pdfTh = { padding: '6px 8px', fontSize: 9, fontWeight: 700, color: '#1A1A17', textTransform: 'uppercase', letterSpacing: '.04em' };
const pdfTd = { padding: '6px 8px', verticalAlign: 'top' };

Object.assign(window, {
  InvoiceListDesktop, InvoiceListEmpty, InvoiceCreate, PdfSheet, FilterChip, LINE_ITEMS,
});
