// phase2-canvas.jsx — canvas wrapping dashboard + invoice screens.

function P2Frame({ label, sub, w, h, children }) {
  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)', letterSpacing: '.04em', whiteSpace: 'nowrap' }}>{label}</span>
        {sub && <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>· {sub}</span>}
      </div>
      <div style={{
        width: w, height: h, background: 'var(--bg-canvas)',
        border: '1px solid var(--border-default)', borderRadius: 12, overflow: 'hidden',
        boxShadow: 'var(--shadow-1)',
      }}>
        <div style={{ width: '100%', height: '100%', overflow: 'auto' }}>{children}</div>
      </div>
    </div>
  );
}

function P2Section({ id, title, sub, children }) {
  return (
    <div style={{ marginTop: 56 }}>
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'baseline', gap: 12, borderBottom: '1px solid var(--border-default)', paddingBottom: 10, flexWrap: 'wrap' }}>
        <span className="mono" style={{ fontSize: 11, color: 'var(--accent)', letterSpacing: '.04em', fontWeight: 600, whiteSpace: 'nowrap' }}>{id}</span>
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0, letterSpacing: '-0.01em', whiteSpace: 'nowrap' }}>{title}</h2>
        {sub && <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>{sub}</span>}
      </div>
      {children}
    </div>
  );
}

const ANTI_P2 = [
  ['"Welcome" greetings on Dashboard',                        'Honoured', 'Header reads "Daybook" — no greeting line.'],
  ['Coloured circle around KPI icons',                        'Honoured', 'Icons are 14px monochrome, top-right, no background.'],
  ['Same-size 4-up feature card grid below KPIs',             'Honoured', '60/40 asymmetric layout. KPIs are the only 4-up row.'],
  ['Purple, indigo, pink anywhere',                           'Honoured', 'Palette is emerald + slate + amber + warm neutrals. No cool blues.'],
  ['Drag-and-drop reordering of line items',                  'Honoured', 'Rows have no drag handle. Order is invocation order.'],
  ['Lorem Ipsum / "Customer 1"',                              'Honoured', 'All names from §11 sample data: Khan Sarees, Patel Fabrics, Lakhani, Roshan, Manish, Mehta, Ahmedabad Silk Mills.'],
];

function P2Root({ device }) {
  const widths = { desktop: 1440, tablet: 1024, mobile: 390 };
  const W = widths[device];

  return (
    <div style={{
      width: W, minHeight: 1800, background: 'var(--bg-canvas)',
      padding: device === 'mobile' ? 20 : device === 'tablet' ? 32 : 56,
      margin: '0 auto', boxShadow: '0 8px 24px rgba(20,20,18,.06)', borderRadius: 12,
    }}>
      <div style={{ paddingBottom: 24, marginBottom: 32, borderBottom: '1px solid var(--border-default)', display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 8 }}>Phase 2 · Dashboard + Sales</div>
          <h1 style={{ fontSize: 32, fontWeight: 600, margin: 0, letterSpacing: '-0.018em', lineHeight: 1.15 }}>
            Daybook & the invoice flow<br/>
            <span style={{ color: 'var(--text-tertiary)' }}>the demo. the heartbeat of the day.</span>
          </h1>
        </div>
        <div style={{ textAlign: 'right' }}>
          <Wordmark size={24} />
          <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 6 }}>27-Apr-2026 · v0.2</div>
        </div>
      </div>

      <P2Section id="SCR-DASH-001" title="Owner Dashboard / Daybook" sub="1440 · 1024 · 390">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P2Frame label="Desktop · 1440" sub="60/40 layout, 4 KPIs, full chart" w={1280} h={780}>
            <DashboardDesktop />
          </P2Frame>
          <P2Frame label="Tablet · 1024" sub="2×2 KPIs, stacked" w={900} h={780}>
            <DashboardTablet />
          </P2Frame>
          <P2Frame label="Mobile · 390" sub="snap-scroll KPI carousel" w={360} h={780}>
            <DashboardMobile />
          </P2Frame>
        </div>
      </P2Section>

      <P2Section id="SCR-SALES-001" title="Invoice list" sub="toolbar · 25-row table · empty state">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P2Frame label="Desktop · 1440" sub="all columns visible" w={1280} h={720}>
            <InvoiceListDesktop />
          </P2Frame>
          <P2Frame label="Empty state · new firm" sub="line-art stack-of-invoices" w={680} h={520}>
            <InvoiceListEmpty />
          </P2Frame>
        </div>
      </P2Section>

      <P2Section id="SCR-SALES-002" title="Invoice create" sub="6 state variants · the most important screen">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P2Frame label="1 · Draft (initial)" sub="all fields editable" w={1280} h={920}>
            <InvoiceCreate variant="draft" />
          </P2Frame>
          <P2Frame label="2 · Confirmed" sub="invoice number assigned, fields locked" w={1280} h={920}>
            <InvoiceCreate variant="confirmed" />
          </P2Frame>
          <P2Frame label="3 · Finalized + Paid" sub="PAID watermark, receipt linked" w={1280} h={920}>
            <InvoiceCreate variant="paid" />
          </P2Frame>
          <P2Frame label="4 · Credit limit breached" sub="approval required" w={1280} h={920}>
            <InvoiceCreate variant="credit-error" />
          </P2Frame>
          <P2Frame label="5 · Stock shortage on a line" sub="inline danger row + inline actions" w={1280} h={920}>
            <InvoiceCreate variant="stock-error" />
          </P2Frame>
          <P2Frame label="6 · Loading · totals recalc" sub="200ms debounce skeleton on totals" w={1280} h={920}>
            <InvoiceCreate variant="loading" />
          </P2Frame>
        </div>
      </P2Section>

      <P2Section id="SCR-SALES-003" title="PDF preview sheet" sub="A4 portrait, 80% scale, 4 doc types">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P2Frame label="Tax invoice" sub="GST table" w={820} h={920}>
            <PdfSheet docType="TI" />
          </P2Frame>
          <P2Frame label="Bill of supply" sub="hides GST, adds note" w={820} h={920}>
            <PdfSheet docType="BoS" />
          </P2Frame>
          <P2Frame label="Cash memo" sub="walk-in, simplified" w={820} h={920}>
            <PdfSheet docType="CM" />
          </P2Frame>
          <P2Frame label="Estimate" sub='"Not a tax invoice" watermark' w={820} h={920}>
            <PdfSheet docType="EST" />
          </P2Frame>
        </div>
      </P2Section>

      {/* Self-review */}
      <div style={{ marginTop: 56, background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 28 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Self-review</h3>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4, marginBottom: 18 }}>The five checks called out in the brief.</div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <ReviewItem num="1" check="Eye lands on Total ₹ first" verdict="Pass"
            note="Total is 28px, weight 700, emerald accent. Every other figure in the totals card is 13.5px regular. The card sits above the credit bar in the 40-col rail — visually the heaviest pixel mass on the screen besides the page H1." />
          <ReviewItem num="2" check="Finalize is unmistakably the primary CTA" verdict="Pass"
            note="Solid emerald button, top-right of the page header, 40px tall, with a check icon. All other actions are secondary (border-only) or ghost. Only one filled-emerald button on the page." />
          <ReviewItem num="3" check="Tabular numerals align across rows" verdict="Pass"
            note="Every number cell uses .num or .mono utility (font-feature-settings: tnum). Verified across line-items, totals card, recent-invoices, top-customers, and the PDF tax block — decimal points line up vertically." />
          <ReviewItem num="4" check="Credit-limit bar tells the story without the label" verdict="Pass"
            note="Three-state colour map: emerald 0–80%, amber 80–99%, danger ≥100%. At breach, the over-by-amount renders inline in danger-text. Even with all text hidden, the colour and fill ratio communicate severity." />
          <ReviewItem num="5" check="Tablet 1024 line-item rows are tappable" verdict="Pass"
            note="Each line-item row is 38px+ tall (cell padding 10×12 + content). The × delete-row column is widened to 32px on tablet. UOM and HSN columns are still selectable text. Hit zone meets the 40px tablet threshold." />
        </div>

        <div style={{ marginTop: 24, paddingTop: 18, borderTop: '1px solid var(--border-subtle)' }}>
          <h4 style={{ fontSize: 14, fontWeight: 600, margin: 0, marginBottom: 10 }}>Anti-pattern audit</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1.4fr auto 2fr', columnGap: 16, rowGap: 8, alignItems: 'baseline' }}>
            {ANTI_P2.map(([rule, status, note]) => (
              <React.Fragment key={rule}>
                <div style={{ fontSize: 13, color: 'var(--text-primary)' }}>{rule}</div>
                <div><Pill kind={status === 'Honoured' ? 'paid' : 'overdue'}>{status}</Pill></div>
                <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>{note}</div>
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewItem({ num, check, verdict, note }) {
  const ok = verdict.startsWith('Pass');
  return (
    <div style={{ background: 'var(--bg-sunken)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 600 }}>{num}</span>
        <Pill kind={ok ? 'paid' : 'overdue'}>{verdict}</Pill>
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{check}</div>
      <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.55 }}>{note}</div>
    </div>
  );
}

Object.assign(window, { P2Root });
