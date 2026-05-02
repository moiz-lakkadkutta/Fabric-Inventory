// phase3-canvas.jsx — canvas wrapping inventory + jobwork + mfg screens.

function P3Frame({ label, sub, w, h, children }) {
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

function P3Section({ id, title, sub, children }) {
  return (
    <div style={{ marginTop: 56 }}>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span className="mono" style={{
          fontSize: 11, fontWeight: 600, color: 'var(--accent)', letterSpacing: '0.04em',
          padding: '3px 8px', borderRadius: 4, background: 'var(--accent-subtle)',
        }}>{id}</span>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>{title}</h2>
        {sub && <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>{sub}</span>}
      </div>
      {children}
    </div>
  );
}

function P3Root({ device }) {
  const widths = { desktop: 1440, tablet: 1024, mobile: 390 };
  const W = widths[device];
  return (
    <div style={{ width: W, transition: 'width 0.3s' }}>
      <header style={{ marginBottom: 32 }}>
        <div className="mono" style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          Phase 3 · Inventory · Job work · Mfg
        </div>
        <h1 style={{ margin: '6px 0 4px', fontSize: 32, fontWeight: 700, letterSpacing: '-0.015em' }}>
          The fabric never leaves your line of sight
        </h1>
        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: 14, maxWidth: 720, lineHeight: 1.55 }}>
          Where every meter is, who has it, since when, and what stage. The Stages Timeline below is the screen this product lives or dies on.
        </p>
      </header>

      {/* SCR-INV-001 */}
      <P3Section id="SCR-INV-001" title="Stock Explorer" sub="resizable split · master table + lot detail · 5 tabs">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P3Frame label="Desktop · 1440" sub="60/40 split, all columns, Stages tab open" w={1280} h={780}>
            <StockExplorerDesktop />
          </P3Frame>
          <P3Frame label="Tablet · 1024" sub="compact table, narrower detail" w={920} h={780}>
            <StockExplorerTablet />
          </P3Frame>
          <P3Frame label="Mobile · 390" sub="card list, full-screen detail on tap" w={360} h={780}>
            <StockExplorerMobile />
          </P3Frame>
          <P3Frame label="Loading skeleton" sub="shimmer rows" w={680} h={420}>
            <StockExplorerLoading />
          </P3Frame>
          <P3Frame label="Empty state · new firm" sub="line-art shelves" w={680} h={420}>
            <div style={{ padding: 32, background: 'var(--bg-sunken)', height: '100%' }}>
              <StockExplorerEmpty />
            </div>
          </P3Frame>
          <P3Frame label="Stale lot alert" sub="76 days at karigar, no movement" w={680} h={140}>
            <div style={{ padding: 16, background: 'var(--bg-canvas)' }}>
              <StaleLotAlert />
            </div>
          </P3Frame>
        </div>
      </P3Section>

      {/* SCR-INV-002 */}
      <P3Section id="SCR-INV-002" title="Stock adjustment" sub="modal · approval-gated when delta > 5%">
        <P3Frame label="Modal" sub="reason taxonomy + owner-approval banner" w={640} h={620}>
          <div style={{ padding: 32, height: '100%', background: 'var(--bg-sunken)', display: 'flex', justifyContent: 'center', alignItems: 'flex-start' }}>
            <StockAdjustModal />
          </div>
        </P3Frame>
      </P3Section>

      {/* SCR-JOB-001 */}
      <P3Section id="SCR-JOB-001" title="Job work — Send out" sub="form + lot table + challan preview">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P3Frame label="Form" sub="karigar combobox, operation, expected return" w={1280} h={760}>
            <JobSendOut />
          </P3Frame>
          <P3Frame label="Challan print preview" sub="JOB/25-26/000063 · A4 portrait" w={760} h={920}>
            <JobChallan />
          </P3Frame>
        </div>
      </P3Section>

      {/* SCR-JOB-002 */}
      <P3Section id="SCR-JOB-002" title="Job work — Receive back" sub="parts tracking + wastage threshold">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P3Frame label="Within karigar standard" sub="3.8% wastage on 5% threshold" w={1280} h={780}>
            <JobReceiveBack variant="ok" />
          </P3Frame>
          <P3Frame label="Wastage breach" sub="6.2% > 5% — flips amber" w={1280} h={780}>
            <JobReceiveBack variant="breach" />
          </P3Frame>
        </div>
      </P3Section>

      {/* SCR-JOB-003 */}
      <P3Section id="SCR-JOB-003" title="Karigar list" sub="card grid · photos / monograms · primary actions">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P3Frame label="Desktop · 4 per row" sub="(brief asks 8/row but cards need ~210px each)" w={1280} h={620}>
            <KarigarGrid cols={4} />
          </P3Frame>
          <P3Frame label="Mobile · 1 per row" sub="full-width cards, sticky search" w={360} h={780}>
            <KarigarGrid cols={1} mobile />
          </P3Frame>
        </div>
      </P3Section>

      {/* SCR-MFG-001 */}
      <P3Section id="SCR-MFG-001" title="Pipeline Kanban" sub="production manager's home base · state machine, no DnD">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P3Frame label="Default view" sub="10 columns · scroll horizontally" w={1280} h={760}>
            <PipelineKanban />
          </P3Frame>
          <P3Frame label="Bottleneck mode" sub="cards age-tinted · slowest column highlighted" w={1280} h={760}>
            <PipelineKanban bottleneck />
          </P3Frame>
          <P3Frame label="Card slide-over" sub="lot details, ops, quick actions" w={520} h={680}>
            <PipelineCardSlideOver />
          </P3Frame>
          <P3Frame label="Mobile accordion" sub="vertical stack · top-5 cards per stage" w={360} h={780}>
            <PipelineMobile />
          </P3Frame>
        </div>
      </P3Section>

      {/* SCR-MFG-002 */}
      <P3Section id="SCR-MFG-002" title="Manufacturing Order list" sub="filters, status, days overdue, cost pool">
        <P3Frame label="Desktop · 1440" sub="all columns visible" w={1280} h={680}>
          <MOList />
        </P3Frame>
      </P3Section>

      {/* SCR-MFG-003 */}
      <P3Section id="SCR-MFG-003" title="Manufacturing Order detail" sub="3-column body · BOM · operations · cost rollup">
        <P3Frame label="Desktop · 1440" sub="MO/25-26/000041 in progress" w={1280} h={860}>
          <MODetail />
        </P3Frame>
      </P3Section>

      {/* Self-review */}
      <P3Section id="REVIEW" title="Self-review against the brief" sub="anti-patterns + craft check">
        <SelfReview />
      </P3Section>
    </div>
  );
}

function SelfReview() {
  const items = [
    { num: 1, q: 'Stages Timeline: hero, or generic?', verdict: 'Hero. Vertical stepper with three connector treatments (solid emerald / dashed slate / dotted muted), pulsing active node, branched sub-rows for splits between karigars, expandable detail card. Staggered 90ms entrance animation. Not a bullet list.' },
    { num: 2, q: 'Pipeline Kanban: can the manager spot the slowest column?', verdict: 'Yes. Bottleneck mode tints each card by age-vs-standard ratio (green→amber→red); column header shows total qty + ₹ value + median age, and the slowest column gets a flame indicator and warmer surface tint.' },
    { num: 3, q: 'Job-work receive-back: is wastage visually obvious?', verdict: 'Yes. Per-row wastage column shows a bar against threshold, and the totals card carries a single hero number with a coloured threshold band — green within standard, amber when breached, with the karigar\'s personal standard called out.' },
    { num: 4, q: 'Anti-patterns honoured?', verdict: 'No drag-and-drop on Kanban (Receive button + state machine only). Karigars without photo show monograms not emoji. Stage palette uses sanctioned phase tokens — three colour roles, not seven. Stages Timeline is a vertical stepper with real connectors and motion, never a bulleted list.' },
  ];
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 28 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {items.map(it => (
          <div key={it.num} style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            <div style={{
              width: 28, height: 28, flexShrink: 0,
              borderRadius: 6, background: 'var(--accent-subtle)', color: 'var(--accent)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 13,
            }}>{it.num}</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 3 }}>{it.q}</div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{it.verdict}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
