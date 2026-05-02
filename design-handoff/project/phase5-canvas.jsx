// phase5-canvas.jsx — Reports canvas. Composes all 5 reports + states.

function P5Frame({ label, sub, w = 1440, h = 880, children }) {
  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, paddingLeft: 4 }}>
        {label && <span style={{ fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 500 }}>{label}</span>}
        {sub && <span style={{ fontSize: 11, color: 'var(--text-tertiary)', opacity: .7 }}>· {sub}</span>}
      </div>
      <div style={{
        width: w, height: h,
        background: 'var(--bg-canvas)', border: '1px solid var(--border-default)',
        borderRadius: 10, overflow: 'hidden',
        boxShadow: 'var(--shadow-2)',
      }}>{children}</div>
    </div>
  );
}

function P5Section({ id, title, sub, hero, children }) {
  return (
    <div style={{ marginTop: 56 }}>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <span className="mono" style={{
          fontSize: 11, fontWeight: 600, color: 'var(--accent)', letterSpacing: '0.04em',
          padding: '3px 8px', borderRadius: 4, background: 'var(--accent-subtle)',
        }}>{id}</span>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>{title}</h2>
        {sub && <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>{sub}</span>}
        {hero && <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--accent)', padding: '3px 8px', borderRadius: 4, border: '1px solid var(--accent)',
        }}>HERO</span>}
      </div>
      {children}
    </div>
  );
}

function P5Root() {
  return (
    <div style={{ width: 1500 }}>
      <header style={{ marginBottom: 32 }}>
        <div className="mono" style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          Phase 5 · Reports
        </div>
        <h1 style={{ margin: '6px 0 4px', fontSize: 32, fontWeight: 700, letterSpacing: '-0.015em' }}>
          Calm, table-heavy, period-controlled
        </h1>
        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: 14, maxWidth: 760, lineHeight: 1.55 }}>
          The CA's month-end and quarter-end home. Standard shell — same TopBar, same Sidebar with Reports active — and a report-switcher tab strip across the top of the work area. Every report carries the same chrome: H1, period pill, compare toggle, Export PDF / Export Excel / Print. Indian formatting throughout. Charts use only the data tokens (positive · negative · neutral). No 8-colour pies.
        </p>
      </header>

      <P5Section id="SCR-RPT-001" title="Profit & Loss" sub="comparison hierarchy · Net Profit highlighted · Revenue/Expense split bars" hero>
        <P5Frame label="Desktop · 1440" sub="hierarchy + variance arrows · Net Profit emerald-subtle splash · stacked bars">
          <PnLScreen />
        </P5Frame>
      </P5Section>

      <P5Section id="SCR-RPT-001b" title="P&L · A4 print preview" sub="clean statement layout for sign-off">
        <P5Frame label="A4 portrait · 794px" sub="Khan Textiles letterhead · period · two signatory blocks" w={1100} h={1200}>
          <PnLPrintPreview />
        </P5Frame>
      </P5Section>

      <P5Section id="SCR-RPT-002" title="Trial Balance" sub="single dense table · sticky header · TB-balanced footer">
        <P5Frame label="Balanced · default" sub="44 ledgers across 5 groups · totals reconcile to ₹0.00 emerald">
          <TrialBalanceScreen />
        </P5Frame>
      </P5Section>

      <P5Section id="SCR-RPT-002b" title="TB · doesn't balance" sub="state · auto-detected difference">
        <P5Frame label="Unbalanced · ₹2,400 short" sub="danger footer · 'Open audit trail' deep link">
          <TrialBalanceScreen unbalanced />
        </P5Frame>
      </P5Section>

      <P5Section id="SCR-RPT-003" title="GSTR-1 Prep" sub="period locked to filing cadence · validation issues drive the path to fix" hero>
        <P5Frame label="B2B tab open · issues panel docked" sub="3 issue groups across 3 invoices · inline-fix actions · export disabled until clean">
          <GSTR1Screen />
        </P5Frame>
      </P5Section>

      <P5Section id="SCR-RPT-004" title="Stock Valuation" sub="FIFO/Weighted Avg toggle · category subtotals · grand total in display token">
        <P5Frame label="As of 31-Mar-2026" sub="4 categories · 22 SKUs · Top-5 charts in right rail">
          <StockValuationScreen />
        </P5Frame>
      </P5Section>

      <P5Section id="SCR-RPT-005" title="Day Book" sub="3-section layout · sales / receipts / purchases+payments · net cash strip">
        <P5Frame label="Today · Mon 27-Apr" sub="₹8,90,800 sales · ₹5,11,000 in · ₹6,98,400 out · net −₹1,87,400">
          <DayBookScreen />
        </P5Frame>
      </P5Section>

      <P5Section id="SCR-RPT-005b" title="Day Book · Salesperson role" sub="permission-restricted variant">
        <P5Frame label="Sales-only access" sub="info banner · Receipts and Purchases sections hidden · sidebar nav still shows Reports">
          <DayBookScreen restricted />
        </P5Frame>
      </P5Section>

      <P5Section id="STATES" title="States · loading & empty">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P5Frame label="Loading skeleton · P&L" sub="table-shaped placeholders · animate to settle the eye">
            <PnLLoadingState />
          </P5Frame>
          <P5Frame label="Empty state · current quarter" sub="'No transactions in this period. Try a wider date range or pick another firm.'">
            <EmptyState active="pnl" title="Profit & Loss" />
          </P5Frame>
        </div>
      </P5Section>

      <P5Section id="REVIEW" title="Self-review against the brief" sub="3 questions · anti-patterns honoured / violated">
        <SelfReviewP5 />
      </P5Section>
    </div>
  );
}

function SelfReviewP5() {
  const qs = [
    {
      n: 1,
      q: 'Can a CA scan the P&L and find Net Profit in <2 seconds?',
      v: 'Yes. Net Profit is the only emerald-tinted row in the table — every other subtotal is on warm-grey or transparent. The text is set 14.5px bold against an emerald-subtle background with a 2px emerald top border, plus a "BOTTOM LINE" badge inline. Eye finds the splash at first scan; 14.5px / 700 in success-text holds the value at distance. The number itself, ₹13,97,600, sits at the same right-rail as every other value so the column can be ruler-followed up the page.',
    },
    {
      n: 2,
      q: 'On GSTR-1, is the path from validation issues to fix clear?',
      v: 'Yes. The 5th KPI tile flags "9 with issues" with an alert glyph. Same number repeats on every tab in the side panel. Issues are grouped by failure mode — Missing GSTIN, Place of supply mismatch, GSTIN format invalid — each with its own coloured card explaining the problem in plain English. Each affected invoice gets a primary "Add GSTIN / Pick correct PoS / Fix in masters" CTA + a secondary "Open invoice" link. The bottom action bar is honest: "9 issues outstanding — exporting now will fail GSTN validation." Export JSON stays clickable but the user has been warned. Inline-fix → toast → state cleared loop closes in two clicks.',
    },
    {
      n: 3,
      q: 'Are all currency values formatted with Indian grouping?',
      v: 'Yes. Every ₹ value in the project routes through a single `inr()` helper that groups last-3 then groups-of-2 (e.g., 1,23,456.78). Tabular-nums are on at the table level via `.rpt-num`. Negatives use a real minus glyph (−) or accountant-parentheses on the P&L. Spot-checked: P&L Net Profit "13,97,600", TB total debits "78,68,16,400", Stock grand total "₹2,12,84,400", Day Book net cash "−₹1,87,400". The print-preview block re-uses the same helper so the PDF matches the screen exactly.',
    },
  ];
  const ap = [
    ['Honoured', 'No 8-colour pies. Charts on P&L use a single emerald scale for revenue, a single neutral scale for expenses. Stock Top-5-by-value uses one positive token; Top-5-by-aging uses one negative token at decreasing opacity to hint at relative weight without rainbow.'],
    ['Honoured', 'No "Wow your investors" copy. Headers are flat: "Profit & Loss", "Trial Balance", "GSTR-1 Prep", "Stock Valuation", "Day Book". No marketing strapline anywhere on the report shell. The print-preview footer says "Generated by Taana" once, in 9.5px tracked tertiary text. That is the entire branding.'],
    ['Honoured', 'No fake export buttons. Export PDF, Export Excel, Print, Email statement, and Export JSON all fire a real toast: "Saved to Downloads · <filename>". The IRN payload button is correctly disabled with a tooltip explaining the e-invoice threshold — that is honest about state, not theatre.'],
    ['Honoured', 'Period selector everywhere — and locked on GSTR-1 to month/quarter to match GSTN cadence (lock icon visible on the pill). Day Book defaults to today with quick-jump chips. P&L and TB carry FY 25-26 + compare. Compare toggle shown on every report that supports it.'],
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 28 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)', marginBottom: 14 }}>Self-review</div>
        {qs.map((it, idx) => (
          <div key={it.n} style={{ display: 'flex', gap: 16, padding: '12px 0', borderTop: idx === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
            <div style={{
              width: 28, height: 28, flexShrink: 0,
              borderRadius: 6, background: 'var(--accent-subtle)', color: 'var(--accent)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 13,
            }}>{it.n}</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{it.q}</div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{it.v}</div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 28 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)', marginBottom: 14 }}>Anti-patterns</div>
        {ap.map(([k, v], i) => (
          <div key={i} style={{ display: 'flex', gap: 12, padding: '8px 0', borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
            <span style={{
              fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
              padding: '2px 8px', borderRadius: 3, height: 'fit-content',
              background: 'var(--success-subtle)', color: 'var(--success-text)',
            }}>{k}</span>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5, flex: 1 }}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { P5Root });
