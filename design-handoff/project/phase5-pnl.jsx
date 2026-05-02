// phase5-pnl.jsx — SCR-RPT-001 Profit & Loss + A4 print preview.

/* ─────────────────────────────────────────────────────────────
   P&L data — period vs prior period.
   Hierarchy: heading → group → leaf. Subtotals roll up.
───────────────────────────────────────────────────────────── */

const PNL_ROWS = [
  // ── Revenue ──────────────────────────
  { kind: 'heading', label: 'Revenue',                    this: 8642400, prior: 7180600, ind: 0 },
  { kind: 'leaf',    label: 'Sales — Tax invoices',       this: 7892200, prior: 6510400, ind: 1 },
  { kind: 'leaf',    label: 'Sales — Bill of supply',     this: 412800,  prior: 384200,  ind: 1 },
  { kind: 'leaf',    label: 'Sales — Cash memo',          this: 248400,  prior: 218000,  ind: 1 },
  { kind: 'leaf',    label: 'Sales returns',              this: -118600, prior: -82400,  ind: 1, expense: false, neg: true },
  { kind: 'leaf',    label: 'Discount allowed',           this: -42400,  prior: -36200,  ind: 1, neg: true },
  { kind: 'subtotal',label: 'Net revenue',                this: 8392400, prior: 6994000, ind: 0 },

  // ── Cost of goods ────────────────────
  { kind: 'heading', label: 'Cost of goods sold',         this: -5180600, prior: -4216200, ind: 0, expense: true },
  { kind: 'leaf',    label: 'Opening stock',              this: -2840000, prior: -2516000, ind: 1, expense: true },
  { kind: 'leaf',    label: 'Purchases',                  this: -4920400, prior: -4180600, ind: 1, expense: true },
  { kind: 'leaf',    label: 'Direct labour (karigar)',    this: -682200,  prior: -548400,  ind: 1, expense: true },
  { kind: 'leaf',    label: 'Job-work charges',           this: -218400,  prior: -166000,  ind: 1, expense: true },
  { kind: 'leaf',    label: 'Closing stock',              this: 3480400,  prior: 3194800,  ind: 1, expense: true, isCredit: true },
  { kind: 'subtotal',label: 'COGS',                       this: -5180600, prior: -4216200, ind: 0, expense: true },

  // ── Gross profit ─────────────────────
  { kind: 'gross',   label: 'Gross profit',               this: 3211800, prior: 2777800, ind: 0 },

  // ── Operating expenses ───────────────
  { kind: 'heading', label: 'Operating expenses',         this: -1842600, prior: -1568400, ind: 0, expense: true },
  { kind: 'leaf',    label: 'Salaries & wages',           this: -680000, prior: -612000, ind: 1, expense: true },
  { kind: 'leaf',    label: 'Rent (showroom + godown)',   this: -360000, prior: -340000, ind: 1, expense: true },
  { kind: 'leaf',    label: 'Power & fuel',               this: -148200, prior: -132600, ind: 1, expense: true },
  { kind: 'leaf',    label: 'Freight outward',            this: -212400, prior: -184600, ind: 1, expense: true },
  { kind: 'leaf',    label: 'Packing materials',          this: -68400,  prior: -54800,  ind: 1, expense: true },
  { kind: 'leaf',    label: 'Marketing & promotion',      this: -98600,  prior: -42200,  ind: 1, expense: true },
  { kind: 'leaf',    label: 'Office & admin',             this: -84600,  prior: -78200,  ind: 1, expense: true },
  { kind: 'leaf',    label: 'Depreciation',               this: -120000, prior: -110000, ind: 1, expense: true },
  { kind: 'leaf',    label: 'Bank & finance charges',     this: -70400,  prior: -14000,  ind: 1, expense: true },
  { kind: 'subtotal',label: 'Total opex',                 this: -1842600, prior: -1568400, ind: 0, expense: true },

  // ── Operating profit ─────────────────
  { kind: 'op',      label: 'Operating profit (EBIT)',    this: 1369200, prior: 1209400, ind: 0 },

  // ── Other income ─────────────────────
  { kind: 'heading', label: 'Other income',               this: 28400,   prior: 18200,   ind: 0 },
  { kind: 'leaf',    label: 'Interest received',          this: 14800,   prior: 8400,    ind: 1 },
  { kind: 'leaf',    label: 'Discount earned',            this: 13600,   prior: 9800,    ind: 1 },

  // ── Net profit ───────────────────────
  { kind: 'net',     label: 'Net profit',                 this: 1397600, prior: 1227600, ind: 0 },
];

/* ─────────────────────────────────────────────────────────────
   The screen
───────────────────────────────────────────────────────────── */

function PnLScreen({ printPreview = false }) {
  if (printPreview) return <PnLPrintPreview />;
  return (
    <ReportShell active="pnl">
      <ReportPageHeader
        title="Profit & Loss"
        period="FY 2025–26 · Apr 2025 – Mar 2026"
        comparePeriod="FY 2024–25"
        filters={
          <>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Show</span>
            <FilterChip label="Whole firm" active />
            <FilterChip label="By location" />
            <FilterChip label="By segment" />
            <span style={{ width: 1, height: 18, background: 'var(--border-default)', margin: '0 8px' }}></span>
            <FilterChip label="Round to ₹" active />
            <FilterChip label="Round to ₹'000" />
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-tertiary)' }}>Last refreshed 14:22 · 27-Apr-2026</span>
          </>
        }
      />
      <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>
        <PnLTable />
        <PnLCharts />
      </div>
    </ReportShell>
  );
}

function PnLTable() {
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden' }}>
      <table className="rpt-table">
        <thead>
          <tr>
            <th className="rpt-th" style={{ width: '38%' }}>Particulars</th>
            <th className="rpt-th rpt-num">FY 25–26 ₹</th>
            <th className="rpt-th rpt-num">FY 24–25 ₹</th>
            <th className="rpt-th rpt-num">Variance ₹</th>
            <th className="rpt-th rpt-num" style={{ width: 96 }}>Var %</th>
          </tr>
        </thead>
        <tbody>
          {PNL_ROWS.map((r, i) => <PnLRow key={i} r={r} />)}
        </tbody>
      </table>
    </div>
  );
}

function PnLRow({ r }) {
  const variance = r.this - r.prior;
  const pct = r.prior !== 0 ? (variance / Math.abs(r.prior)) * 100 : 0;
  const kind = r.expense ? 'expense' : 'revenue';

  // Style per row kind
  const baseTd = { padding: '9px 14px', borderBottom: '1px solid var(--border-subtle)', verticalAlign: 'middle' };

  const isHeading = r.kind === 'heading';
  const isSubtotal = r.kind === 'subtotal';
  const isGross = r.kind === 'gross';
  const isOp = r.kind === 'op';
  const isNet = r.kind === 'net';
  const isLeaf = r.kind === 'leaf';

  const rowStyle = isNet
    ? { background: 'var(--success-subtle)', borderTop: '2px solid var(--success)' }
    : isGross || isOp
    ? { background: 'var(--bg-sunken)' }
    : isSubtotal
    ? { background: '#FAF8F1' }
    : isHeading
    ? {}
    : {};

  const labelStyle = isNet
    ? { fontWeight: 700, fontSize: 14.5, color: 'var(--success-text)' }
    : isGross || isOp
    ? { fontWeight: 700, fontSize: 13.5 }
    : isSubtotal
    ? { fontWeight: 600, fontSize: 13 }
    : isHeading
    ? { fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }
    : { fontWeight: 400, fontSize: 12.5, color: 'var(--text-secondary)' };

  const numStyle = isNet
    ? { fontWeight: 700, fontSize: 15, color: 'var(--success-text)' }
    : isGross || isOp
    ? { fontWeight: 700, fontSize: 13.5 }
    : isSubtotal
    ? { fontWeight: 600, fontSize: 13 }
    : isHeading
    ? { fontWeight: 600, fontSize: 13 }
    : { fontWeight: 400, fontSize: 12.5, color: 'var(--text-secondary)' };

  // Indentation and prefix
  const indent = (r.ind || 0) * 20 + (isLeaf ? 12 : 0);
  const prefix = isLeaf ? <span style={{ color: 'var(--text-tertiary)', marginRight: 6 }}>·</span> : null;

  // Headings show no own value (they are pre-aggregate). Subtotals do.
  const showValues = !isHeading;

  return (
    <tr style={rowStyle} className="rpt-row-hover">
      <td className="rpt-td" style={{ ...baseTd, paddingLeft: 14 + indent, ...labelStyle }}>
        {prefix}{r.label}
        {isNet && <span style={{
          marginLeft: 10, fontSize: 9.5, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--success-text)', padding: '2px 6px', border: '1px solid var(--success)', borderRadius: 3, opacity: 0.9,
        }}>BOTTOM LINE</span>}
      </td>
      {showValues ? (
        <>
          <td className="rpt-td rpt-num" style={{ ...baseTd, ...numStyle }}>{fmtPnL(r.this)}</td>
          <td className="rpt-td rpt-num" style={{ ...baseTd, ...numStyle, color: numStyle.color || 'var(--text-tertiary)' }}>
            <span style={{ color: 'var(--text-tertiary)', fontWeight: numStyle.fontWeight || 400 }}>{fmtPnL(r.prior)}</span>
          </td>
          <td className="rpt-td rpt-num" style={{ ...baseTd, ...numStyle }}>{fmtPnL(variance, { signed: true })}</td>
          <td className="rpt-td rpt-num" style={{ ...baseTd }}>
            <VarianceArrow delta={variance} pct={pct} kind={kind} />
          </td>
        </>
      ) : (
        <>
          <td className="rpt-td rpt-num" style={baseTd}><span style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>—</span></td>
          <td className="rpt-td rpt-num" style={baseTd}><span style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>—</span></td>
          <td className="rpt-td rpt-num" style={baseTd}></td>
          <td className="rpt-td rpt-num" style={baseTd}></td>
        </>
      )}
    </tr>
  );
}

// Format ₹ for the P&L. Negative numbers wrapped in parentheses (accountants love this).
function fmtPnL(n, { signed = false } = {}) {
  if (n === 0) return <span style={{ color: 'var(--text-tertiary)' }}>—</span>;
  const abs = Math.abs(n);
  const grouped = inr(abs, { decimals: 0 });
  if (signed) {
    return n >= 0 ? `+${grouped}` : `−${grouped}`;
  }
  return n < 0 ? `(${grouped})` : grouped;
}

/* ─────────────────────────────────────────────────────────────
   Charts panel — revenue split + expense split
───────────────────────────────────────────────────────────── */
function PnLCharts() {
  const revenueSplit = [
    { label: 'Tax invoices',     value: 7892200, color: 'var(--data-positive)' },
    { label: 'Bill of supply',   value: 412800,  color: '#3D8E62' },
    { label: 'Cash memo',        value: 248400,  color: '#7AB29A' },
  ];
  const expenseSplit = [
    { label: 'Direct labour',    value: 682200,  color: 'var(--data-neutral)' },
    { label: 'Salaries',         value: 680000,  color: '#7C7A72' },
    { label: 'Rent',             value: 360000,  color: '#9C998F' },
    { label: 'Freight',          value: 212400,  color: '#B5B3AB' },
    { label: 'Other opex',       value: 588000,  color: '#C8C5B8' },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <ChartCard
        title="Revenue mix"
        sub="By document type · this period"
        total="₹86,42,400"
        bar={<StackedBar data={revenueSplit} />}
      />
      <ChartCard
        title="Operating expense mix"
        sub="By category · this period"
        total="₹25,22,800"
        bar={<StackedBar data={expenseSplit} />}
      />
    </div>
  );
}

function ChartCard({ title, sub, total, bar }) {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: 18,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 1 }}>{sub}</div>
        </div>
        <div className="num" style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>{total}</div>
      </div>
      {bar}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   A4 Print Preview — clean statement layout for sign-off
───────────────────────────────────────────────────────────── */

function PnLPrintPreview() {
  // Only the line items that print on a clean statement. Same data, no styling fluff.
  const printRows = PNL_ROWS;

  return (
    <div style={{
      width: '100%', height: '100%', background: 'var(--bg-sunken)',
      padding: 28, overflow: 'auto', display: 'flex', justifyContent: 'center',
    }}>
      <div style={{
        width: 794, // A4 at ~96 DPI
        minHeight: 1123,
        background: '#FFFFFF',
        boxShadow: 'var(--shadow-3)',
        padding: '56px 56px 48px',
        position: 'relative',
        fontFamily: 'var(--font-ui)',
      }}>
        {/* Letterhead */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, paddingBottom: 18, borderBottom: '2px solid var(--text-primary)' }}>
          <TaanaMark size={44} color="var(--accent)" />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.01em' }}>Khan Textiles Pvt Ltd</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2 }}>
              42 Ring Road, Surat, Gujarat 395002 · GSTIN 24AAACK4521P1Z5 · CIN U17110GJ2008PTC053421
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
              Tel +91 261 240 1100 · accounts@khantextiles.in
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Statement</div>
            <div style={{ fontSize: 10.5, color: 'var(--text-secondary)', marginTop: 2 }}>Page 1 of 1</div>
          </div>
        </div>

        {/* Statement title */}
        <div style={{ textAlign: 'center', padding: '24px 0 18px' }}>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.01em' }}>Statement of Profit &amp; Loss</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
            For the year ended <strong>31 March 2026</strong> · all amounts in ₹
          </div>
        </div>

        {/* Statement table */}
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
          <thead>
            <tr>
              <th style={printTh}>Particulars</th>
              <th style={{ ...printTh, textAlign: 'right' }}>FY 2025–26</th>
              <th style={{ ...printTh, textAlign: 'right' }}>FY 2024–25</th>
            </tr>
          </thead>
          <tbody>
            {printRows.map((r, i) => {
              const isNet = r.kind === 'net';
              const isGrossOrOp = r.kind === 'gross' || r.kind === 'op';
              const isSub = r.kind === 'subtotal';
              const isHead = r.kind === 'heading';
              const indent = (r.ind || 0) * 14 + (r.kind === 'leaf' ? 12 : 0);
              const fontWeight = isNet ? 700 : (isGrossOrOp ? 700 : (isSub || isHead ? 600 : 400));
              const fontSize = isNet ? 12 : (isGrossOrOp ? 11.5 : 11);
              const showVal = !isHead;
              const borderTop = (isNet || isGrossOrOp) ? '1px solid var(--text-primary)' : 'none';
              const borderBottom = isNet ? '2px solid var(--text-primary)' : (isSub ? '0.5px solid var(--border-default)' : '0');
              return (
                <tr key={i}>
                  <td style={{ padding: '5px 0', paddingLeft: indent, borderTop, borderBottom, fontWeight, fontSize }}>
                    {r.label}
                  </td>
                  <td style={{ padding: '5px 0', textAlign: 'right', borderTop, borderBottom, fontWeight, fontSize }}>
                    {showVal ? fmtPnLPrint(r.this) : ''}
                  </td>
                  <td style={{ padding: '5px 0', textAlign: 'right', borderTop, borderBottom, fontWeight, fontSize, color: isNet ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                    {showVal ? fmtPnLPrint(r.prior) : ''}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {/* Notes */}
        <div style={{ marginTop: 20, fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.55 }}>
          <strong>Note:</strong> Amounts in parentheses denote credits / negatives. Closing stock valued at lower of cost (FIFO) or NRV.
          Refer accompanying notes 1–18 for accounting policies and detail.
        </div>

        {/* Signatories */}
        <div style={{ marginTop: 64, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
          <Signatory title="For Khan Textiles Pvt Ltd" line1="Director" line2="DIN 02841029" />
          <Signatory title="As per our report of even date" line1="Naseem & Co · Chartered Accountants" line2="FRN 108942W · M.No. 058241" right />
        </div>

        <div style={{ marginTop: 36, textAlign: 'center', fontSize: 9.5, color: 'var(--text-tertiary)', letterSpacing: '0.06em' }}>
          Place: Surat · Date: 27 April 2026 · Generated by Taana
        </div>
      </div>
    </div>
  );
}

const printTh = {
  fontSize: 9.5, fontWeight: 700, color: 'var(--text-primary)',
  letterSpacing: '0.08em', textTransform: 'uppercase',
  padding: '8px 0', textAlign: 'left',
  borderBottom: '1.5px solid var(--text-primary)',
};

function fmtPnLPrint(n) {
  if (n === 0) return '—';
  const abs = Math.abs(n);
  const g = inr(abs, { decimals: 0 });
  return n < 0 ? `(${g})` : g;
}

function Signatory({ title, line1, line2, right }) {
  return (
    <div style={{ textAlign: right ? 'right' : 'left' }}>
      <div style={{ fontSize: 10.5, color: 'var(--text-secondary)', marginBottom: 28 }}>{title}</div>
      <div style={{ borderTop: '1px solid var(--text-primary)', paddingTop: 6 }}>
        <div style={{ fontSize: 11, fontWeight: 600 }}>{line1}</div>
        <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 1 }}>{line2}</div>
      </div>
    </div>
  );
}

Object.assign(window, { PnLScreen, PnLPrintPreview });
