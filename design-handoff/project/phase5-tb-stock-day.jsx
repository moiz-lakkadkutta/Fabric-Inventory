// phase5-tb-stock-day.jsx — SCR-RPT-002 Trial Balance, SCR-RPT-004 Stock Valuation, SCR-RPT-005 Day Book.

/* ─────────────────────────────────────────────────────────────
   SCR-RPT-002 — Trial Balance
───────────────────────────────────────────────────────────── */

const TB_LEDGERS = [
  // ── Assets
  { code: '1100', name: 'Cash in hand',                   group: 'Assets',     dr: 142800,    cr: 0 },
  { code: '1110', name: 'HDFC Current — 5810421',         group: 'Assets',     dr: 8462400,   cr: 0 },
  { code: '1112', name: 'ICICI OD — 0488112',             group: 'Assets',     dr: 0,         cr: 1842600 },
  { code: '1200', name: 'Sundry debtors — control',       group: 'Assets',     dr: 38420600,  cr: 0 },
  { code: '1210', name: 'Sundry debtors — Khan Sarees',   group: 'Assets',     dr: 640000,    cr: 0 },
  { code: '1300', name: 'Stock — finished',               group: 'Assets',     dr: 12480400,  cr: 0 },
  { code: '1305', name: 'Stock — raw',                    group: 'Assets',     dr: 8920200,   cr: 0 },
  { code: '1310', name: 'Stock — WIP',                    group: 'Assets',     dr: 1184000,   cr: 0 },
  { code: '1320', name: 'Stock — at karigar',             group: 'Assets',     dr: 642800,    cr: 0 },
  { code: '1500', name: 'Furniture & fixtures',           group: 'Assets',     dr: 1840000,   cr: 0 },
  { code: '1510', name: 'Plant & machinery',              group: 'Assets',     dr: 3680000,   cr: 0 },
  { code: '1520', name: 'Acc. depreciation',              group: 'Assets',     dr: 0,         cr: 1240000 },
  { code: '1610', name: 'Input CGST',                     group: 'Assets',     dr: 218400,    cr: 0 },
  { code: '1611', name: 'Input SGST',                     group: 'Assets',     dr: 218400,    cr: 0 },
  { code: '1612', name: 'Input IGST',                     group: 'Assets',     dr: 84600,     cr: 0 },

  // ── Liabilities
  { code: '2100', name: 'Sundry creditors — control',     group: 'Liabilities',dr: 0,         cr: 22810400 },
  { code: '2105', name: 'Sundry creditors — Reliance',    group: 'Liabilities',dr: 0,         cr: 482000 },
  { code: '2200', name: 'GST payable — output CGST',      group: 'Liabilities',dr: 0,         cr: 312800 },
  { code: '2201', name: 'GST payable — output SGST',      group: 'Liabilities',dr: 0,         cr: 312800 },
  { code: '2202', name: 'GST payable — output IGST',      group: 'Liabilities',dr: 0,         cr: 184600 },
  { code: '2210', name: 'TDS payable',                    group: 'Liabilities',dr: 0,         cr: 28400 },
  { code: '2300', name: 'Salary payable',                 group: 'Liabilities',dr: 0,         cr: 142000 },
  { code: '2400', name: 'Term loan — HDFC',               group: 'Liabilities',dr: 0,         cr: 14200000 },

  // ── Equity
  { code: '3100', name: 'Share capital',                  group: 'Equity',     dr: 0,         cr: 5000000 },
  { code: '3200', name: 'Retained earnings',              group: 'Equity',     dr: 0,         cr: 28224200 },
  { code: '3300', name: 'Profit for the year',            group: 'Equity',     dr: 0,         cr: 1397600 },

  // ── Income
  { code: '4100', name: 'Sales — tax invoices',           group: 'Income',     dr: 0,         cr: 7892200 },
  { code: '4110', name: 'Sales — bill of supply',         group: 'Income',     dr: 0,         cr: 412800 },
  { code: '4120', name: 'Sales — cash memo',              group: 'Income',     dr: 0,         cr: 248400 },
  { code: '4200', name: 'Sales returns',                  group: 'Income',     dr: 118600,    cr: 0 },
  { code: '4210', name: 'Discount allowed',               group: 'Income',     dr: 42400,     cr: 0 },
  { code: '4500', name: 'Interest received',              group: 'Income',     dr: 0,         cr: 14800 },
  { code: '4510', name: 'Discount earned',                group: 'Income',     dr: 0,         cr: 13600 },

  // ── Expense
  { code: '5100', name: 'Purchases',                      group: 'Expense',    dr: 4920400,   cr: 0 },
  { code: '5200', name: 'Direct labour (karigar)',        group: 'Expense',    dr: 682200,    cr: 0 },
  { code: '5210', name: 'Job-work charges',               group: 'Expense',    dr: 218400,    cr: 0 },
  { code: '5300', name: 'Salaries & wages',               group: 'Expense',    dr: 680000,    cr: 0 },
  { code: '5310', name: 'Rent',                           group: 'Expense',    dr: 360000,    cr: 0 },
  { code: '5320', name: 'Power & fuel',                   group: 'Expense',    dr: 148200,    cr: 0 },
  { code: '5330', name: 'Freight outward',                group: 'Expense',    dr: 212400,    cr: 0 },
  { code: '5340', name: 'Packing materials',              group: 'Expense',    dr: 68400,     cr: 0 },
  { code: '5350', name: 'Marketing & promotion',          group: 'Expense',    dr: 98600,     cr: 0 },
  { code: '5360', name: 'Office & admin',                 group: 'Expense',    dr: 84600,     cr: 0 },
  { code: '5370', name: 'Depreciation',                   group: 'Expense',    dr: 120000,    cr: 0 },
  { code: '5380', name: 'Bank & finance charges',         group: 'Expense',    dr: 70400,     cr: 0 },
];

const GROUP_COLORS = {
  'Assets':      { bg: 'var(--info-subtle)',    fg: 'var(--info-text)' },
  'Liabilities': { bg: 'var(--warning-subtle)', fg: 'var(--warning-text)' },
  'Equity':      { bg: '#EAE7DD',                fg: '#605D52' },
  'Income':      { bg: 'var(--success-subtle)', fg: 'var(--success-text)' },
  'Expense':     { bg: 'var(--danger-subtle)',  fg: 'var(--danger-text)' },
};

function TrialBalanceScreen({ unbalanced = false }) {
  const totalDr = TB_LEDGERS.reduce((s, l) => s + l.dr, 0);
  const totalCr = TB_LEDGERS.reduce((s, l) => s + l.cr, 0);
  const diff = unbalanced ? -2400 : (totalDr - totalCr);

  return (
    <ReportShell active="tb">
      <ReportPageHeader
        title="Trial Balance"
        period="As of 31-Mar-2026"
        comparePeriod={null}
        filters={
          <>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Groups</span>
            <FilterChip label="All" active count={TB_LEDGERS.length} />
            <FilterChip label="Assets" count={15} />
            <FilterChip label="Liabilities" count={8} />
            <FilterChip label="Equity" count={3} />
            <FilterChip label="Income" count={7} />
            <FilterChip label="Expense" count={12} />
            <span style={{ width: 1, height: 18, background: 'var(--border-default)', margin: '0 8px' }}></span>
            <FilterChip label="Show zero balances" />
            <span style={{ marginLeft: 'auto' }}>
              <Input placeholder="Search code or ledger…" prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
            </span>
          </>
        }
      />
      <div style={{ padding: 24 }}>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden' }}>
          <div style={{ maxHeight: 540, overflow: 'auto' }}>
            <table className="rpt-table" style={{ position: 'relative' }}>
              <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                <tr>
                  <th className="rpt-th" style={{ width: 80 }}>Code</th>
                  <th className="rpt-th">Ledger</th>
                  <th className="rpt-th" style={{ width: 130 }}>Group</th>
                  <th className="rpt-th rpt-num" style={{ width: 140 }}>Debit ₹</th>
                  <th className="rpt-th rpt-num" style={{ width: 140 }}>Credit ₹</th>
                  <th className="rpt-th rpt-num" style={{ width: 150 }}>Balance ₹</th>
                  <th className="rpt-th" style={{ width: 36 }}></th>
                </tr>
              </thead>
              <tbody>
                {TB_LEDGERS.map((l, i) => <TBRow key={l.code} l={l} i={i} />)}
              </tbody>
            </table>
          </div>
          {/* Totals footer */}
          <TBFooter totalDr={totalDr} totalCr={totalCr} diff={diff} />
        </div>
      </div>
    </ReportShell>
  );
}

function TBRow({ l, i }) {
  const balance = l.dr - l.cr;
  const balKind = balance > 0 ? 'Dr' : balance < 0 ? 'Cr' : '';
  const c = GROUP_COLORS[l.group];
  return (
    <tr className="rpt-row-hover" style={{ borderTop: i === 0 ? 'none' : undefined }}>
      <td className="rpt-td mono" style={{ color: 'var(--text-tertiary)', fontSize: 11.5, fontWeight: 600 }}>{l.code}</td>
      <td className="rpt-td" style={{ fontSize: 13, fontWeight: 500 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          {l.name}
          <Icon name="arrow-right" size={11} color="var(--text-disabled)" />
        </span>
      </td>
      <td className="rpt-td">
        <span style={{
          display: 'inline-block', padding: '2px 8px', borderRadius: 3,
          background: c.bg, color: c.fg, fontSize: 10.5, fontWeight: 600,
          letterSpacing: '0.04em', textTransform: 'uppercase',
        }}>{l.group}</span>
      </td>
      <td className="rpt-td rpt-num" style={{ fontSize: 13, color: l.dr ? 'var(--text-primary)' : 'var(--text-disabled)' }}>
        {l.dr ? inr(l.dr, { decimals: 2 }) : '—'}
      </td>
      <td className="rpt-td rpt-num" style={{ fontSize: 13, color: l.cr ? 'var(--text-primary)' : 'var(--text-disabled)' }}>
        {l.cr ? inr(l.cr, { decimals: 2 }) : '—'}
      </td>
      <td className="rpt-td rpt-num" style={{ fontSize: 13, fontWeight: 600 }}>
        <span style={{ color: balance === 0 ? 'var(--text-disabled)' : 'var(--text-primary)' }}>
          {balance === 0 ? '—' : inr(Math.abs(balance), { decimals: 2 })}
        </span>
        {balKind && <span style={{
          marginLeft: 6, fontSize: 10, fontWeight: 700,
          color: balKind === 'Dr' ? 'var(--info-text)' : 'var(--warning-text)',
        }}>{balKind}</span>}
      </td>
      <td className="rpt-td">
        <button style={{
          width: 22, height: 22, borderRadius: 4, border: 'none', background: 'transparent',
          color: 'var(--text-tertiary)', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }} aria-label="Drill"><Icon name="chevron-right" size={14} /></button>
      </td>
    </tr>
  );
}

function TBFooter({ totalDr, totalCr, diff }) {
  const balanced = diff === 0;
  return (
    <div style={{
      borderTop: '2px solid var(--text-primary)',
      background: balanced ? 'var(--success-subtle)' : 'var(--danger-subtle)',
    }}>
      <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr 130px 140px 140px 150px 36px', alignItems: 'center' }}>
        <div></div>
        <div style={{ padding: '14px 14px', fontSize: 12.5, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', color: balanced ? 'var(--success-text)' : 'var(--danger-text)' }}>
          Total
        </div>
        <div></div>
        <div className="rpt-num" style={{ padding: '14px 14px', fontSize: 14, fontWeight: 700, color: balanced ? 'var(--success-text)' : 'var(--danger-text)' }}>
          {inr(totalDr, { decimals: 2 })}
        </div>
        <div className="rpt-num" style={{ padding: '14px 14px', fontSize: 14, fontWeight: 700, color: balanced ? 'var(--success-text)' : 'var(--danger-text)' }}>
          {inr(totalCr, { decimals: 2 })}
        </div>
        <div className="rpt-num" style={{ padding: '14px 14px', fontSize: 14, fontWeight: 700, color: balanced ? 'var(--success-text)' : 'var(--danger-text)' }}>
          Diff: {balanced ? '₹0.00' : inr(Math.abs(diff), { decimals: 2 })}
        </div>
        <div></div>
      </div>
      {!balanced && (
        <div style={{ padding: '10px 14px', borderTop: '1px solid rgba(181,49,30,0.2)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="alert" size={14} color="var(--danger-text)" />
          <span style={{ fontSize: 12, color: 'var(--danger-text)', fontWeight: 500 }}>
            TB doesn't balance — investigate.
          </span>
          <button style={{
            border: 'none', background: 'transparent', color: 'var(--danger-text)',
            fontSize: 12, fontWeight: 600, textDecoration: 'underline', cursor: 'pointer', padding: 0,
          }}>Open audit trail →</button>
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-RPT-004 — Stock Valuation
───────────────────────────────────────────────────────────── */

const STOCK_CATEGORIES = [
  {
    name: 'Raw — Fabric',
    items: [
      { sku: 'RAW-FAB-0042', name: 'Silk Georgette 60GSM White',   qty: 1840,  uom: 'm',  unit: 184,  aging: '0-30' },
      { sku: 'RAW-FAB-0058', name: 'Banarasi Silk 90GSM Maroon',   qty: 642,   uom: 'm',  unit: 618,  aging: '31-60' },
      { sku: 'RAW-FAB-0061', name: 'Crepe Double 42 Blush',        qty: 1240,  uom: 'm',  unit: 138,  aging: '0-30' },
      { sku: 'RAW-FAB-0033', name: 'Cotton Slub Indigo',           qty: 480,   uom: 'm',  unit: 92,   aging: '60-90' },
      { sku: 'RAW-FAB-0019', name: 'Tussar Silk Natural',          qty: 320,   uom: 'm',  unit: 460,  aging: '90-180' },
      { sku: 'RAW-FAB-0008', name: 'Khadi Voile Off-white',        qty: 180,   uom: 'm',  unit: 124,  aging: '180+' },
    ],
  },
  {
    name: 'Raw — Trim',
    items: [
      { sku: 'RAW-TRM-0008', name: 'Zari Trim Gold 2 cm',          qty: 184,   uom: 'rl', unit: 1240, aging: '0-30' },
      { sku: 'RAW-TRM-0024', name: 'Sequin Border Silver',         qty: 96,    uom: 'rl', unit: 380,  aging: '31-60' },
      { sku: 'RAW-TRM-0011', name: 'Lace Trim Cream 4 cm',         qty: 240,   uom: 'rl', unit: 168,  aging: '60-90' },
    ],
  },
  {
    name: 'WIP',
    items: [
      { sku: 'WIP-MO-0041',  name: 'A-402 Bridal Suit · cut',      qty: 84,    uom: 'pc', unit: 4820, aging: '0-30' },
      { sku: 'WIP-MO-0040',  name: 'B-218 Anarkali · stitched',    qty: 162,   uom: 'pc', unit: 2840, aging: '0-30' },
      { sku: 'WIP-MO-0038',  name: 'C-104 Lehenga · embroidery',   qty: 24,    uom: 'pc', unit: 8640, aging: '31-60' },
    ],
  },
  {
    name: 'Finished',
    items: [
      { sku: 'FG-SAR-1842',  name: 'Banarasi Saree · Maroon Zari', qty: 48,    uom: 'pc', unit: 6480, aging: '0-30' },
      { sku: 'FG-SUI-2104',  name: 'Anarkali Suit · Blush 3pc',    qty: 124,   uom: 'pc', unit: 4280, aging: '0-30' },
      { sku: 'FG-LEH-1108',  name: 'Lehenga Set · Gold Embroidery',qty: 18,    uom: 'pc', unit: 18400,aging: '31-60' },
      { sku: 'FG-SAR-1820',  name: 'Tussar Saree · Natural',       qty: 32,    uom: 'pc', unit: 3640, aging: '60-90' },
      { sku: 'FG-DUP-0840',  name: 'Dupatta · Silver Sequin',      qty: 84,    uom: 'pc', unit: 1280, aging: '90-180' },
      { sku: 'FG-KUR-2014',  name: 'Kurta · Khadi Off-white',      qty: 26,    uom: 'pc', unit: 1840, aging: '180+' },
    ],
  },
];

const AGING_COLOR = {
  '0-30':   'var(--success-subtle)',
  '31-60':  'var(--info-subtle)',
  '60-90':  'var(--warning-subtle)',
  '90-180': '#F0DCC2',
  '180+':   'var(--danger-subtle)',
};
const AGING_FG = {
  '0-30':   'var(--success-text)',
  '31-60':  'var(--info-text)',
  '60-90':  'var(--warning-text)',
  '90-180': '#7A4C0F',
  '180+':   'var(--danger-text)',
};

function StockValuationScreen() {
  // Gather all items for top-5 charts.
  const all = STOCK_CATEGORIES.flatMap(c => c.items.map(i => ({ ...i, cat: c.name, value: i.qty * i.unit })));
  const top5Value = [...all].sort((a, b) => b.value - a.value).slice(0, 5);
  const top5Aging = [...all]
    .filter(i => i.aging === '180+' || i.aging === '90-180')
    .sort((a, b) => agingRank(b.aging) - agingRank(a.aging) || b.value - a.value)
    .slice(0, 5);
  const grandTotal = all.reduce((s, i) => s + i.value, 0);

  return (
    <ReportShell active="stock">
      <ReportPageHeader
        title="Stock Valuation"
        period="As of 31-Mar-2026"
        comparePeriod="vs 31-Mar-2025"
        filters={
          <>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Method</span>
            <SegToggle options={['FIFO', 'Weighted Avg']} active="FIFO" />
            <span style={{ width: 1, height: 18, background: 'var(--border-default)', margin: '0 8px' }}></span>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Location</span>
            <FilterChip label="All locations" active />
            <FilterChip label="Surat warehouse" />
            <FilterChip label="Showroom" />
            <FilterChip label="At karigar" />
            <span style={{ width: 1, height: 18, background: 'var(--border-default)', margin: '0 8px' }}></span>
            <FilterChip label="Raw" active />
            <FilterChip label="WIP" active />
            <FilterChip label="Finished" active />
          </>
        }
      />
      <div style={{ padding: 24, display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20 }}>
        {/* Main table */}
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden' }}>
          <table className="rpt-table">
            <thead>
              <tr>
                <th className="rpt-th" style={{ width: 130 }}>SKU</th>
                <th className="rpt-th">Item</th>
                <th className="rpt-th rpt-num" style={{ width: 80 }}>Qty</th>
                <th className="rpt-th" style={{ width: 60 }}>UOM</th>
                <th className="rpt-th rpt-num" style={{ width: 100 }}>Unit cost ₹</th>
                <th className="rpt-th rpt-num" style={{ width: 130 }}>Value ₹</th>
                <th className="rpt-th" style={{ width: 90 }}>Aging</th>
              </tr>
            </thead>
            <tbody>
              {STOCK_CATEGORIES.map(cat => {
                const catTotal = cat.items.reduce((s, i) => s + i.qty * i.unit, 0);
                return (
                  <React.Fragment key={cat.name}>
                    <tr>
                      <td colSpan={7} style={{
                        padding: '10px 14px', background: 'var(--bg-sunken)',
                        fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                        color: 'var(--text-secondary)',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      }}>
                        <span>{cat.name} <span style={{ color: 'var(--text-tertiary)', fontWeight: 500, marginLeft: 6 }}>({cat.items.length})</span></span>
                        <span className="num" style={{ color: 'var(--text-primary)', fontSize: 12.5 }}>₹{inr(catTotal, { decimals: 0 })}</span>
                      </td>
                    </tr>
                    {cat.items.map(i => (
                      <tr key={i.sku} className="rpt-row-hover">
                        <td className="rpt-td mono" style={{ color: 'var(--accent)', fontSize: 11, fontWeight: 600 }}>{i.sku}</td>
                        <td className="rpt-td" style={{ fontSize: 12.5 }}>{i.name}</td>
                        <td className="rpt-td rpt-num" style={{ fontWeight: 500 }}>{i.qty.toLocaleString('en-IN')}</td>
                        <td className="rpt-td" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{i.uom}</td>
                        <td className="rpt-td rpt-num" style={{ color: 'var(--text-secondary)' }}>{inr(i.unit, { decimals: 0 })}</td>
                        <td className="rpt-td rpt-num" style={{ fontWeight: 600 }}>{inr(i.qty * i.unit, { decimals: 0 })}</td>
                        <td className="rpt-td">
                          <span style={{
                            display: 'inline-flex', alignItems: 'center', height: 20, padding: '0 8px', borderRadius: 3,
                            background: AGING_COLOR[i.aging], color: AGING_FG[i.aging],
                            fontSize: 10.5, fontWeight: 600, letterSpacing: '0.04em',
                          }}>{i.aging} d</span>
                        </td>
                      </tr>
                    ))}
                  </React.Fragment>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={5} style={{
                  padding: '14px 14px', background: 'var(--accent-subtle)', borderTop: '2px solid var(--accent)',
                  fontWeight: 700, fontSize: 13, color: 'var(--accent)',
                  letterSpacing: '0.04em', textTransform: 'uppercase',
                }}>Grand total</td>
                <td className="rpt-num" style={{
                  padding: '14px 14px', background: 'var(--accent-subtle)', borderTop: '2px solid var(--accent)',
                  fontWeight: 700, fontSize: 16, color: 'var(--accent)',
                }}>₹{inr(grandTotal, { decimals: 0 })}</td>
                <td style={{ background: 'var(--accent-subtle)', borderTop: '2px solid var(--accent)' }}></td>
              </tr>
            </tfoot>
          </table>
        </div>

        {/* Right rail */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <RailChart title="Top 5 by value" sub="this period" items={top5Value.map(i => ({ label: i.name, sub: i.sku, value: i.value }))} valueColor="var(--data-positive)" />
          <RailChart title="Top 5 by aging" sub="oldest first" items={top5Aging.map(i => ({ label: i.name, sub: `${i.aging} days · ${i.sku}`, value: i.value }))} valueColor="var(--data-negative)" agingFlavour />
        </div>
      </div>
    </ReportShell>
  );
}

function agingRank(a) { return ['0-30','31-60','60-90','90-180','180+'].indexOf(a); }

function RailChart({ title, sub, items, valueColor, agingFlavour }) {
  const max = Math.max(...items.map(i => i.value), 1);
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{sub}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {items.map((i, idx) => (
          <div key={idx}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 12, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{i.label}</div>
                <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 1 }}>{i.sub}</div>
              </div>
              <div className="num" style={{ fontSize: 12, fontWeight: 600, color: valueColor }}>₹{inrShort(i.value).replace('₹','')}</div>
            </div>
            <div style={{ height: 6, background: 'var(--bg-sunken)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${(i.value / max) * 100}%`, height: '100%', background: valueColor, opacity: agingFlavour ? 0.55 + 0.1 * (items.length - idx) : 1 }}></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SegToggle({ options, active }) {
  return (
    <div style={{ display: 'inline-flex', borderRadius: 6, border: '1px solid var(--border-default)', overflow: 'hidden', background: 'var(--bg-surface)' }}>
      {options.map(o => (
        <span key={o} style={{
          padding: '5px 12px', fontSize: 12, fontWeight: o === active ? 600 : 500,
          background: o === active ? 'var(--accent-subtle)' : 'transparent',
          color: o === active ? 'var(--accent)' : 'var(--text-secondary)',
        }}>{o}</span>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-RPT-005 — Day Book
───────────────────────────────────────────────────────────── */

const TODAY_SALES = [
  { time: '09:14', no: 'TI/00821', party: 'Lehenga Lounge', mode: 'Credit', amt: 184200 },
  { time: '10:42', no: 'TI/00822', party: 'Khan Sarees',    mode: 'Credit', amt: 64800 },
  { time: '11:18', no: 'CM/02411', party: 'Walk-in (Surat)',mode: 'Cash',   amt: 12400 },
  { time: '13:02', no: 'TI/00823', party: 'Anand Boutique', mode: 'Credit', amt: 240800 },
  { time: '14:38', no: 'BoS/00184',party: 'Walk-in (Composition)', mode: 'Cash', amt: 8400 },
  { time: '16:04', no: 'TI/00824', party: 'Sangam Wholesale', mode: 'Credit', amt: 380400 },
];
const TODAY_RECEIPTS = [
  { time: '11:42', no: 'RCT/00214', party: 'Lehenga Lounge', mode: 'NEFT', amt: 184200, alloc: 'TI/00821' },
  { time: '12:22', no: 'RCT/00215', party: 'Khan Sarores',   mode: 'UPI',  amt: 184000, alloc: 'unallocated' },
  { time: '15:18', no: 'RCT/00216', party: 'Bridal Couture', mode: 'Cheque',amt: 142800, alloc: 'TI/00794, TI/00802' },
];
const TODAY_PURCHASES = [
  { time: '10:24', no: 'PI/00072',  party: 'Reliance Industries', mode: 'Credit', amt: 199900, dir: 'in' },
  { time: '11:50', no: 'PMT/00184', party: 'Sangam Mills',        mode: 'NEFT',   amt: 216400, dir: 'out' },
  { time: '14:12', no: 'PI/00073',  party: 'Anand Trims',         mode: 'Credit', amt: 38200,  dir: 'in' },
  { time: '15:48', no: 'PMT/00185', party: 'Reliance Industries', mode: 'NEFT',   amt: 482000, dir: 'out' },
];

function DayBookScreen({ restricted = false }) {
  const salesTotal = TODAY_SALES.reduce((s, i) => s + i.amt, 0);
  const receiptsTotal = TODAY_RECEIPTS.reduce((s, i) => s + i.amt, 0);
  const purchaseIn = TODAY_PURCHASES.filter(p => p.dir === 'in').reduce((s, i) => s + i.amt, 0);
  const paymentsOut = TODAY_PURCHASES.filter(p => p.dir === 'out').reduce((s, i) => s + i.amt, 0);
  const netCash = receiptsTotal - paymentsOut;

  return (
    <ReportShell active="day">
      <ReportPageHeader
        title={restricted ? 'Day Book' : 'Day Book'}
        period="Today · 27-Apr-2026 · Mon"
        comparePeriod={null}
        filters={
          <>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Quick jump</span>
            <FilterChip label="Today" active />
            <FilterChip label="Yesterday" />
            <FilterChip label="This week" />
            <FilterChip label="Pick date" />
            <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--text-secondary)' }}>
              <span style={{ color: 'var(--text-tertiary)' }}>Net cash movement today:</span>{' '}
              <strong className="num" style={{ color: netCash >= 0 ? 'var(--success-text)' : 'var(--danger-text)' }}>
                {netCash >= 0 ? '+' : '−'}₹{inr(Math.abs(netCash), { decimals: 0 })}
              </strong>
            </span>
          </>
        }
      />
      {restricted && (
        <div style={{
          padding: '10px 32px', background: 'var(--info-subtle)', borderBottom: '1px solid var(--border-default)',
          fontSize: 12, color: 'var(--info-text)', display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <Icon name="lock" size={14} color="var(--info-text)" />
          <span><strong>Salesperson role.</strong> You see Day Book and Sales registers. Full Reports require accountant or owner.</span>
        </div>
      )}

      <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>
        <DayBookSection
          title="Sales today"
          icon="shopping-bag"
          count={TODAY_SALES.length}
          total={salesTotal}
          totalLabel="Sales total"
          totalKind="positive"
          rows={TODAY_SALES}
          cols={[
            { k: 'time', label: 'Time', w: 70 },
            { k: 'no',   label: 'Doc #', w: 110, mono: true, accent: true },
            { k: 'party',label: 'Party' },
            { k: 'mode', label: 'Mode', w: 80, pill: true },
            { k: 'amt',  label: 'Amount ₹', w: 130, num: true, weight: 600 },
          ]}
        />
        {!restricted && (
          <DayBookSection
            title="Receipts today"
            icon="wallet"
            count={TODAY_RECEIPTS.length}
            total={receiptsTotal}
            totalLabel="Cash in"
            totalKind="positive"
            rows={TODAY_RECEIPTS}
            cols={[
              { k: 'time', label: 'Time', w: 70 },
              { k: 'no',   label: 'Doc #', w: 110, mono: true, accent: true },
              { k: 'party',label: 'Party' },
              { k: 'mode', label: 'Mode', w: 80, pill: true },
              { k: 'alloc',label: 'Allocated to', w: 200, soft: true },
              { k: 'amt',  label: 'Amount ₹', w: 130, num: true, weight: 600 },
            ]}
          />
        )}
        {!restricted && (
          <DayBookSection
            title="Purchases & Payments today"
            icon="truck"
            count={TODAY_PURCHASES.length}
            totals={[
              { label: 'Purchases booked', value: purchaseIn, kind: 'neutral' },
              { label: 'Payments made',    value: paymentsOut, kind: 'negative' },
            ]}
            rows={TODAY_PURCHASES}
            cols={[
              { k: 'time', label: 'Time', w: 70 },
              { k: 'no',   label: 'Doc #', w: 120, mono: true, accent: true },
              { k: 'party',label: 'Party' },
              { k: 'mode', label: 'Mode', w: 80, pill: true },
              { k: 'amt',  label: 'Amount ₹', w: 130, num: true, weight: 600, signed: 'dir' },
            ]}
          />
        )}

        {!restricted && (
          <div style={{
            background: netCash >= 0 ? 'var(--success-subtle)' : 'var(--danger-subtle)',
            border: `1px solid ${netCash >= 0 ? 'var(--success)' : 'var(--danger)'}`,
            borderRadius: 8, padding: 18,
            display: 'flex', alignItems: 'center', gap: 16,
          }}>
            <div style={{
              width: 44, height: 44, borderRadius: 8,
              background: netCash >= 0 ? 'var(--success)' : 'var(--danger)',
              color: '#FFF', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Icon name={netCash >= 0 ? 'arrow-up' : 'arrow-down'} size={22} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: netCash >= 0 ? 'var(--success-text)' : 'var(--danger-text)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Net cash movement</div>
              <div className="num" style={{ fontSize: 26, fontWeight: 700, color: netCash >= 0 ? 'var(--success-text)' : 'var(--danger-text)', marginTop: 2 }}>
                {netCash >= 0 ? '+' : '−'}₹{inr(Math.abs(netCash), { decimals: 0 })}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 28 }}>
              <Stat k="Cash in"  v={`₹${inr(receiptsTotal, { decimals: 0 })}`} good />
              <Stat k="Cash out" v={`−₹${inr(paymentsOut, { decimals: 0 })}`} bad />
            </div>
          </div>
        )}
      </div>
    </ReportShell>
  );
}

function Stat({ k, v, good, bad }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{k}</div>
      <div className="num" style={{ fontSize: 16, fontWeight: 700, color: good ? 'var(--success-text)' : bad ? 'var(--danger-text)' : 'var(--text-primary)', marginTop: 2 }}>{v}</div>
    </div>
  );
}

function DayBookSection({ title, icon, count, total, totals, totalLabel, totalKind, rows, cols }) {
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{
        padding: '14px 18px', borderBottom: '1px solid var(--border-default)',
        background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <span style={{
          width: 32, height: 32, borderRadius: 6, background: 'var(--bg-sunken)',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)',
        }}>
          <Icon name={icon} size={16} />
        </span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>{title}</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>{count} entries</div>
        </div>
        {total != null && (
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{totalLabel}</div>
            <div className="num" style={{ fontSize: 18, fontWeight: 700, color: totalKind === 'positive' ? 'var(--success-text)' : 'var(--text-primary)' }}>
              ₹{inr(total, { decimals: 0 })}
            </div>
          </div>
        )}
        {totals && totals.map((t, i) => (
          <div key={i} style={{ textAlign: 'right', paddingLeft: 16, borderLeft: '1px solid var(--border-default)', marginLeft: 4 }}>
            <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t.label}</div>
            <div className="num" style={{ fontSize: 15, fontWeight: 700,
              color: t.kind === 'positive' ? 'var(--success-text)' :
                     t.kind === 'negative' ? 'var(--danger-text)' : 'var(--text-primary)' }}>
              ₹{inr(t.value, { decimals: 0 })}
            </div>
          </div>
        ))}
      </div>
      <table className="rpt-table">
        <thead>
          <tr>
            {cols.map(c => (
              <th key={c.k} className="rpt-th" style={{ width: c.w, textAlign: c.num ? 'right' : 'left' }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="rpt-row-hover">
              {cols.map(c => {
                const v = r[c.k];
                if (c.num) {
                  let display = inr(v, { decimals: 0 });
                  let color = 'var(--text-primary)';
                  if (c.signed === 'dir') {
                    const isOut = r.dir === 'out';
                    display = (isOut ? '−' : '+') + '₹' + display;
                    color = isOut ? 'var(--danger-text)' : 'var(--success-text)';
                  } else {
                    display = '₹' + display;
                  }
                  return <td key={c.k} className="rpt-td rpt-num" style={{ fontWeight: c.weight || 500, color }}>{display}</td>;
                }
                if (c.pill) {
                  return <td key={c.k} className="rpt-td">
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 3,
                      background: 'var(--bg-sunken)', color: 'var(--text-secondary)',
                      fontSize: 10.5, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase',
                    }}>{v}</span>
                  </td>;
                }
                if (c.mono) {
                  return <td key={c.k} className="rpt-td mono" style={{ fontSize: 11.5, fontWeight: 600, color: c.accent ? 'var(--accent)' : 'var(--text-primary)' }}>{v}</td>;
                }
                if (c.soft) {
                  const isUnalloc = String(v).includes('unalloc');
                  return <td key={c.k} className="rpt-td" style={{
                    fontSize: 12, fontStyle: isUnalloc ? 'italic' : 'normal',
                    color: isUnalloc ? 'var(--warning-text)' : 'var(--text-secondary)',
                  }}>{isUnalloc ? <><Icon name="alert" size={11} color="var(--warning-text)" /> unallocated</> : v}</td>;
                }
                return <td key={c.k} className="rpt-td" style={{ fontSize: c.k === 'time' ? 11.5 : 13, color: c.k === 'time' ? 'var(--text-tertiary)' : 'var(--text-primary)', fontFamily: c.k === 'time' ? 'var(--font-num)' : 'inherit' }}>{v}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

Object.assign(window, { TrialBalanceScreen, StockValuationScreen, DayBookScreen });
