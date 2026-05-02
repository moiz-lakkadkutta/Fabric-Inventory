// phase5-gstr1.jsx — SCR-RPT-003 GSTR-1 Prep with validation issues side panel.

const { useState: useStateP } = React;

const GSTR1_TABS = [
  { id: 'b2b',     label: 'B2B',           sub: 'Registered',         count: 142, value: '52.18 L' },
  { id: 'b2cl',    label: 'B2C-Large',     sub: '> ₹2.5 L · Inter',   count: 8,   value: '24.40 L' },
  { id: 'b2cs',    label: 'B2C-Small',     sub: 'Other unregistered', count: 312, value: '8.42 L' },
  { id: 'exp',     label: 'Exports',       sub: 'With/without IGST',  count: 4,   value: '6.84 L' },
  { id: 'cdn',     label: 'Credit/Debit',  sub: 'CDNR · CDNUR',       count: 11,  value: '−1.18 L' },
  { id: 'adv',     label: 'Advances',      sub: 'AT · ATA',           count: 3,   value: '0.84 L' },
  { id: 'amend',   label: 'Amendments',    sub: 'B2BA · CDNRA',       count: 2,   value: '0.42 L' },
];

const B2B_INVOICES = [
  { gstin: '24AAACL5421R1Z9', party: 'Lehenga Lounge LLP',    inv: 'TI/00821', date: '24-Apr', val: 184200, taxable: 175428.57, rate: 5,  cgst: 4385.71, sgst: 4385.71, igst: 0,        pos: 'Gujarat (24)',     issue: null },
  { gstin: '27AAACK4521P1Z5', party: 'Khan Sarees Pvt Ltd',   inv: 'TI/00822', date: '24-Apr', val: 64800,  taxable: 61714.29,  rate: 5,  cgst: 0,       sgst: 0,       igst: 3085.71,  pos: 'Maharashtra (27)', issue: null },
  { gstin: '24AABCB1234R1Z5', party: 'Bridal Couture',        inv: 'TI/00819', date: '23-Apr', val: 240800, taxable: 229333.33, rate: 5,  cgst: 5733.33, sgst: 5733.33, igst: 0,        pos: 'Gujarat (24)',     issue: null },
  { gstin: '06AABCS9012N1Z2', party: 'Sangam Wholesale',      inv: 'TI/00824', date: '24-Apr', val: 380400, taxable: 339642.86, rate: 12, cgst: 0,       sgst: 0,       igst: 40757.14, pos: 'Haryana (06)',     issue: null },
  { gstin: 'PENDING',          party: 'Anand Boutique',        inv: 'TI/00823', date: '24-Apr', val: 240800, taxable: 229333.33, rate: 5,  cgst: 5733.33, sgst: 5733.33, igst: 0,        pos: 'Gujarat (24)',     issue: 'missing-gstin' },
  { gstin: '08AABCC3456D1Z9', party: 'Marwar Textiles',       inv: 'TI/00815', date: '22-Apr', val: 142800, taxable: 136000,    rate: 5,  cgst: 3400,    sgst: 3400,    igst: 0,        pos: 'Gujarat (24)',     issue: 'pos-mismatch' },
  { gstin: '24AABCD7890E1Z3', party: 'Surat Saree House',     inv: 'TI/00812', date: '21-Apr', val: 89200,  taxable: 84952.38,  rate: 5,  cgst: 2123.81, sgst: 2123.81, igst: 0,        pos: 'Gujarat (24)',     issue: null },
  { gstin: '03AABCP4567Q1Z1', party: 'Punjab Bridal',         inv: 'TI/00808', date: '20-Apr', val: 116400, taxable: 110857.14, rate: 5,  cgst: 0,       sgst: 0,       igst: 5542.86,  pos: 'Punjab (03)',      issue: null },
  { gstin: '24INVALID00X1Z9', party: 'Heritage Weaves',       inv: 'TI/00805', date: '19-Apr', val: 64200,  taxable: 61142.86,  rate: 5,  cgst: 1528.57, sgst: 1528.57, igst: 0,        pos: 'Gujarat (24)',     issue: 'gstin-invalid' },
];

function GSTR1Screen() {
  const [activeTab, setActiveTab] = useStateP('b2b');
  const [issuesOpen, setIssuesOpen] = useStateP(true);
  const issues = B2B_INVOICES.filter(i => i.issue);

  return (
    <ReportShell active="gstr1">
      <ReportPageHeader
        title="GSTR-1 Prep"
        period="Apr 2026 · Monthly"
        periodLocked
        comparePeriod={null}
        filters={
          <>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Filing cadence</span>
            <SegToggle options={['Monthly', 'Quarterly (QRMP)']} active="Monthly" />
            <span style={{ width: 1, height: 18, background: 'var(--border-default)', margin: '0 8px' }}></span>
            <FilterChip label="Apr 2026" active />
            <FilterChip label="Mar 2026" />
            <FilterChip label="Feb 2026" />
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-tertiary)' }}>
              GSTIN <strong className="mono" style={{ color: 'var(--text-secondary)' }}>24AAACK4521P1Z5</strong> · Due 11-May-2026
            </span>
          </>
        }
      />

      {/* KPI strip */}
      <div style={{ padding: '16px 24px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-default)' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 0,
          background: 'var(--bg-canvas)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden',
        }}>
          <KPI label="Total taxable value" value="₹84,18,420" sub="382 invoices" />
          <KPI label="CGST" value="₹2,10,460" sub="@ 2.5–9%" divider />
          <KPI label="SGST" value="₹2,10,460" sub="@ 2.5–9%" divider />
          <KPI label="IGST" value="₹3,84,200" sub="Inter-state" divider />
          <KPI label="Total invoices" value="382" sub="9 with issues" issues divider />
        </div>
      </div>

      {/* Tabs */}
      <div style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-default)', padding: '0 24px', display: 'flex', gap: 2, overflow: 'auto' }}>
        {GSTR1_TABS.map(t => {
          const a = t.id === activeTab;
          return (
            <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
              border: 'none', background: 'transparent', cursor: 'pointer',
              padding: '12px 16px 14px', position: 'relative', minWidth: 0,
              textAlign: 'left',
            }}>
              <div style={{ fontSize: 13, fontWeight: a ? 700 : 500, color: a ? 'var(--text-primary)' : 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                {t.label}
                <span style={{ marginLeft: 6, fontSize: 11, fontWeight: 600, color: a ? 'var(--accent)' : 'var(--text-tertiary)' }}>{t.count}</span>
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 2, whiteSpace: 'nowrap' }}>{t.sub} · ₹{t.value}</div>
              {a && <span style={{
                position: 'absolute', left: 16, right: 16, bottom: 0, height: 2,
                background: 'var(--accent)', borderRadius: '2px 2px 0 0',
              }} />}
            </button>
          );
        })}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: issuesOpen ? '1fr 360px' : '1fr', minHeight: 0 }}>
        {/* Invoice table */}
        <div style={{ padding: 24, paddingBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>B2B invoices · 142</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <FilterChip label="All rates" active />
              <FilterChip label="5%" />
              <FilterChip label="12%" />
              <FilterChip label="18%" />
              {!issuesOpen && (
                <button onClick={() => setIssuesOpen(true)} style={{
                  border: '1px solid var(--warning)', background: 'var(--warning-subtle)',
                  color: 'var(--warning-text)', borderRadius: 999, padding: '4px 12px',
                  fontSize: 12, fontWeight: 600, cursor: 'pointer',
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                }}>
                  <Icon name="alert" size={12} /> {issues.length} validation issues
                </button>
              )}
            </div>
          </div>

          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden' }}>
            <table className="rpt-table">
              <thead>
                <tr>
                  <th className="rpt-th" style={{ width: 170 }}>GSTIN / UIN</th>
                  <th className="rpt-th">Party</th>
                  <th className="rpt-th" style={{ width: 100 }}>Invoice #</th>
                  <th className="rpt-th" style={{ width: 70 }}>Date</th>
                  <th className="rpt-th" style={{ width: 130 }}>Place of supply</th>
                  <th className="rpt-th rpt-num" style={{ width: 100 }}>Invoice ₹</th>
                  <th className="rpt-th rpt-num" style={{ width: 60 }}>Rate</th>
                  <th className="rpt-th rpt-num" style={{ width: 90 }}>Taxable</th>
                  <th className="rpt-th rpt-num" style={{ width: 80 }}>CGST</th>
                  <th className="rpt-th rpt-num" style={{ width: 80 }}>SGST</th>
                  <th className="rpt-th rpt-num" style={{ width: 80 }}>IGST</th>
                </tr>
              </thead>
              <tbody>
                {B2B_INVOICES.map((r, i) => <GSTRRow key={i} r={r} />)}
              </tbody>
            </table>
          </div>
        </div>

        {/* Issues side panel */}
        {issuesOpen && (
          <ValidationPanel issues={issues} onClose={() => setIssuesOpen(false)} />
        )}
      </div>

      {/* Bottom action bar */}
      <GSTR1ActionBar />
    </ReportShell>
  );
}

function GSTRRow({ r }) {
  const issue = r.issue;
  const issueBg = issue
    ? (issue === 'pos-mismatch' ? 'rgba(162,103,16,0.06)' : 'rgba(181,49,30,0.05)')
    : 'transparent';
  const gstinStyle = issue === 'missing-gstin' || issue === 'gstin-invalid'
    ? { color: 'var(--danger-text)', textDecoration: 'underline', textDecorationStyle: 'wavy' }
    : { color: 'var(--text-primary)' };
  return (
    <tr className="rpt-row-hover" style={{ background: issueBg }}>
      <td className="rpt-td mono" style={{ fontSize: 11, fontWeight: 600, ...gstinStyle }}>
        {r.gstin === 'PENDING' ? <span style={{ color: 'var(--danger-text)' }}>— missing —</span> : r.gstin}
      </td>
      <td className="rpt-td" style={{ fontSize: 12.5, fontWeight: 500 }}>{r.party}</td>
      <td className="rpt-td mono" style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>{r.inv}</td>
      <td className="rpt-td" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{r.date}</td>
      <td className="rpt-td" style={{ fontSize: 12, color: issue === 'pos-mismatch' ? 'var(--warning-text)' : 'var(--text-secondary)', fontWeight: issue === 'pos-mismatch' ? 600 : 400 }}>
        {r.pos}
        {issue === 'pos-mismatch' && <Icon name="alert" size={11} color="var(--warning-text)" />}
      </td>
      <td className="rpt-td rpt-num" style={{ fontWeight: 600 }}>{inr(r.val, { decimals: 0 })}</td>
      <td className="rpt-td rpt-num" style={{ color: 'var(--text-secondary)' }}>{r.rate}%</td>
      <td className="rpt-td rpt-num">{inr(r.taxable, { decimals: 2 })}</td>
      <td className="rpt-td rpt-num" style={{ color: r.cgst ? 'var(--text-primary)' : 'var(--text-disabled)' }}>{r.cgst ? inr(r.cgst, { decimals: 2 }) : '—'}</td>
      <td className="rpt-td rpt-num" style={{ color: r.sgst ? 'var(--text-primary)' : 'var(--text-disabled)' }}>{r.sgst ? inr(r.sgst, { decimals: 2 }) : '—'}</td>
      <td className="rpt-td rpt-num" style={{ color: r.igst ? 'var(--text-primary)' : 'var(--text-disabled)' }}>{r.igst ? inr(r.igst, { decimals: 2 }) : '—'}</td>
    </tr>
  );
}

const ISSUE_DEFS = {
  'missing-gstin':  { label: 'Missing GSTIN',          severity: 'danger',  desc: 'B2B section requires customer GSTIN. Without it, invoice cannot be filed under B2B and must move to B2C.' },
  'pos-mismatch':   { label: 'Place of supply mismatch', severity: 'warning', desc: 'Customer GSTIN starts with 27 (Maharashtra) but PoS is 24 (Gujarat). One of them is wrong — verify with customer.' },
  'gstin-invalid':  { label: 'GSTIN format invalid',   severity: 'danger',  desc: 'GSTIN structure does not match 15-character pattern. Check for typos in masters.' },
};

function ValidationPanel({ issues, onClose }) {
  const fire = useToast();
  const grouped = {};
  issues.forEach(i => {
    grouped[i.issue] = grouped[i.issue] || [];
    grouped[i.issue].push(i);
  });

  return (
    <aside style={{
      borderLeft: '1px solid var(--border-default)',
      background: 'var(--bg-surface)',
      padding: '20px 20px 24px',
      overflow: 'auto',
      display: 'flex', flexDirection: 'column', gap: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          width: 28, height: 28, borderRadius: 6,
          background: 'var(--warning-subtle)', color: 'var(--warning-text)',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Icon name="alert" size={14} />
        </span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>Validation issues</div>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{issues.length} found · fix before export</div>
        </div>
        <button onClick={onClose} aria-label="Close" style={{
          width: 24, height: 24, border: 'none', background: 'transparent',
          color: 'var(--text-tertiary)', cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}><Icon name="x" size={14} /></button>
      </div>

      {Object.entries(grouped).map(([k, list]) => {
        const def = ISSUE_DEFS[k];
        return (
          <div key={k} style={{
            border: `1px solid ${def.severity === 'danger' ? 'var(--danger)' : 'var(--warning)'}`,
            borderRadius: 8, overflow: 'hidden',
          }}>
            <div style={{
              padding: '10px 12px',
              background: def.severity === 'danger' ? 'var(--danger-subtle)' : 'var(--warning-subtle)',
              borderBottom: `1px solid ${def.severity === 'danger' ? 'var(--danger)' : 'var(--warning)'}`,
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <span style={{
                fontSize: 11, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                background: def.severity === 'danger' ? 'var(--danger)' : 'var(--warning)',
                color: '#FFF', letterSpacing: '0.04em', textTransform: 'uppercase',
              }}>{list.length}</span>
              <span style={{
                fontSize: 12, fontWeight: 700,
                color: def.severity === 'danger' ? 'var(--danger-text)' : 'var(--warning-text)',
              }}>{def.label}</span>
            </div>
            <div style={{ padding: '10px 12px', fontSize: 11.5, color: 'var(--text-secondary)', lineHeight: 1.5, borderBottom: '1px solid var(--border-subtle)' }}>
              {def.desc}
            </div>
            <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {list.map((it, i) => (
                <div key={i} style={{
                  border: '1px solid var(--border-subtle)', borderRadius: 6,
                  padding: 10, background: 'var(--bg-canvas)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 600 }}>{it.party}</div>
                      <div className="mono" style={{ fontSize: 10.5, color: 'var(--accent)', marginTop: 2 }}>{it.inv} · {it.date}</div>
                    </div>
                    <div className="num" style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>₹{inr(it.val, { decimals: 0 })}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                    <button onClick={() => fire('Inline edit opened in masters')} style={fixBtn}>
                      <Icon name="cog" size={11} />
                      {k === 'missing-gstin' ? 'Add GSTIN' : k === 'pos-mismatch' ? 'Pick correct PoS' : 'Fix in masters'}
                    </button>
                    <button onClick={() => fire('Invoice opened')} style={fixBtnGhost}>
                      <Icon name="eye" size={11} />
                      Open invoice
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}

      <div style={{
        marginTop: 'auto', padding: 12, background: 'var(--bg-sunken)',
        borderRadius: 6, fontSize: 11.5, color: 'var(--text-secondary)', lineHeight: 1.5,
      }}>
        <strong style={{ color: 'var(--text-primary)' }}>Tip.</strong> Once all issues are resolved, the export buttons below light up.
        Filing happens on <a href="#" style={{ color: 'var(--accent)' }}>gst.gov.in</a> — Taana prepares the JSON.
      </div>
    </aside>
  );
}

const fixBtn = {
  flex: 1, height: 28, padding: '0 10px', borderRadius: 4,
  background: 'var(--accent)', color: '#FFF', border: 'none',
  fontSize: 11, fontWeight: 600, letterSpacing: '0.02em', cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 5,
};
const fixBtnGhost = {
  height: 28, padding: '0 10px', borderRadius: 4,
  background: 'transparent', color: 'var(--text-secondary)',
  border: '1px solid var(--border-default)',
  fontSize: 11, fontWeight: 500, cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 5,
};

function GSTR1ActionBar() {
  const fire = useToast();
  return (
    <div style={{
      position: 'sticky', bottom: 0, zIndex: 5,
      borderTop: '1px solid var(--border-default)',
      background: 'var(--bg-surface)',
      padding: '14px 24px',
      display: 'flex', alignItems: 'center', gap: 12,
      boxShadow: '0 -4px 12px rgba(20,20,18,0.06)',
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--warning-text)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          ⚠ 9 issues outstanding — exporting now will fail GSTN validation
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 2 }}>
          Once issues are fixed, JSON can be uploaded to gst.gov.in or filed via API.
        </div>
      </div>
      <span title="Enable e-invoice in Settings → GST when you cross ₹5 Cr or onboard a customer above the threshold" style={{ display: 'inline-flex' }}>
        <Button variant="secondary" size="sm" icon="file" state="disabled">Generate IRN payload</Button>
      </span>
      <span onClick={() => fire('Saved to Downloads · GSTR-1_Apr-2026.json', 'success')} style={{ cursor: 'pointer' }}>
        <Button variant="primary" size="sm" icon="download">Export JSON for portal</Button>
      </span>
    </div>
  );
}

function KPI({ label, value, sub, divider, issues }) {
  return (
    <div style={{
      padding: '14px 18px',
      borderLeft: divider ? '1px solid var(--border-default)' : 'none',
      display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
      <div className="num" style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.012em' }}>{value}</div>
      <div style={{ fontSize: 11, color: issues ? 'var(--warning-text)' : 'var(--text-tertiary)', fontWeight: issues ? 600 : 400, display: 'flex', alignItems: 'center', gap: 4 }}>
        {issues && <Icon name="alert" size={11} color="var(--warning-text)" />}
        {sub}
      </div>
    </div>
  );
}

Object.assign(window, { GSTR1Screen });
