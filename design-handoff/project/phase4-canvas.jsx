// phase4-canvas.jsx — canvas for purchase + party + accounts.

function P4Frame({ label, sub, w, h, children }) {
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

function P4Section({ id, title, sub, hero, children }) {
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
          color: 'var(--accent)', padding: '3px 8px', borderRadius: 4,
          border: '1px solid var(--accent)',
        }}>HERO</span>}
      </div>
      {children}
    </div>
  );
}

function P4Root() {
  return (
    <div style={{ width: 1440 }}>
      <header style={{ marginBottom: 32 }}>
        <div className="mono" style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          Phase 4 · Purchase · Parties · Accounts
        </div>
        <h1 style={{ margin: '6px 0 4px', fontSize: 32, fontWeight: 700, letterSpacing: '-0.015em' }}>
          The accountant's month-end home
        </h1>
        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: 14, maxWidth: 720, lineHeight: 1.55 }}>
          The Party Ledger is the screen the accountant lives on during month-end. Three-way match on GRN is the killer feature for the buyer. Everything else is calm and dense — keyboard-driven where it matters.
        </p>
      </header>

      {/* Purchase */}
      <P4Section id="SCR-PUR-001" title="Purchase order list" sub="Sales-list pattern, parallel layout">
        <P4Frame label="Desktop · 1440" sub="9 POs · filter chips · star + days-open columns" w={1380} h={680}>
          <POList />
        </P4Frame>
      </P4Section>

      <P4Section id="SCR-PUR-002" title="PO create" sub="60/40 split · totals + supplier-balance rail">
        <P4Frame label="Draft · 4 lines" sub="Reliance combobox shows ₹4.82L payable. WhatsApp button shows but is disabled." w={1380} h={760}>
          <POCreate />
        </P4Frame>
      </P4Section>

      <P4Section id="SCR-PUR-003" title="Goods receipt note" sub="three-way match · the killer feature" hero>
        <P4Frame label="GRN with 1 short, 1 excess, 1 reject" sub="3-way match rail shows PO matched, GRN mismatched, PI pending" w={1380} h={760}>
          <GRNScreen />
        </P4Frame>
      </P4Section>

      <P4Section id="SCR-PUR-004" title="Purchase invoice" sub="3-way match completes · FY mismatch warning">
        <P4Frame label="PI/00072 · linked to PO and GRN" sub="supplier honoured short-shipment discount — flagged" w={1380} h={760}>
          <PurchaseInvoice />
        </P4Frame>
      </P4Section>

      {/* Party */}
      <P4Section id="SCR-PARTY-001" title="Party list" sub="4 tabs · monograms · outstanding column">
        <P4Frame label="All parties · 11 rows" sub="Khan Sarees overdue · Lehenga Lounge on hold" w={1380} h={680}>
          <PartyList />
        </P4Frame>
      </P4Section>

      <P4Section id="SCR-PARTY-002" title="Party detail — the khata" sub="ledger tab · aging bar + 25-row inline-expandable ledger" hero>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
          <P4Frame label="Default · Khan Sarees ledger" sub="aging bar tells the story; row 23 is an unallocated receipt, expanded" w={1380} h={1200}>
            <PartyDetail />
          </P4Frame>
          <P4Frame label="Statement tab" sub="A4 PDF preview · period selector · email action" w={1380} h={680}>
            <PartyDetail key="stmt" tinted={false} />
            <script dangerouslySetInnerHTML={{ __html: '' }} />
          </P4Frame>
          <P4Frame label="On-hold variant" sub="amber-tinted page · banner asking for approval" w={1380} h={620}>
            <PartyDetail tinted />
          </P4Frame>
          <P4Frame label="Salesperson role · permission-restricted" sub="only Ledger and Invoices tabs visible — Receipts hidden" w={1380} h={620}>
            <PartyDetail restricted />
          </P4Frame>
        </div>
      </P4Section>

      <P4Section id="SCR-PARTY-003" title="Party edit" sub="modal sheet · GSTIN async-validated">
        <P4Frame label="Modal" sub="addresses, contacts, credit limit, opening balance Dr/Cr" w={760} h={680}>
          <div style={{ padding: 20, height: '100%', background: 'var(--bg-sunken)', display: 'flex', justifyContent: 'center', alignItems: 'flex-start' }}>
            <PartyEdit />
          </div>
        </P4Frame>
      </P4Section>

      {/* Accounts */}
      <P4Section id="SCR-ACCT-001" title="Receipt" sub="FIFO allocation · advance handling">
        <P4Frame label="₹1.84L receipt · FIFO across 6 open invoices" sub="₹1.12L → first invoice closed, balance bleeds into next two" w={1380} h={760}>
          <ReceiptScreen />
        </P4Frame>
      </P4Section>

      <P4Section id="SCR-ACCT-002" title="Payment" sub="supplier-side mirror">
        <P4Frame label="Reliance · ₹4.82L NEFT" sub="bank balance impact in rail" w={1380} h={680}>
          <PaymentScreen />
        </P4Frame>
      </P4Section>

      <P4Section id="SCR-ACCT-003" title="Voucher post" sub="auto-balance indicator">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <P4Frame label="Balanced · ready to post" sub="₹0.00 difference · post button enabled · ledger preview right rail" w={1380} h={760}>
            <VoucherPost />
          </P4Frame>
          <P4Frame label="Unbalanced · post disabled" sub="₹500 short · danger banner" w={1380} h={620}>
            <VoucherPost unbalanced />
          </P4Frame>
        </div>
      </P4Section>

      {/* Self-review */}
      <P4Section id="REVIEW" title="Self-review against the brief" sub="3 questions · anti-patterns honoured / violated">
        <SelfReviewP4 />
      </P4Section>
    </div>
  );
}

function SelfReviewP4() {
  const qs = [
    {
      n: 1,
      q: 'On the Party Ledger, can an accountant find an unallocated receipt in <5 seconds?',
      v: 'Yes. The unallocated row is tinted info-blue across the full width, carries an UNALLOCATED pill in two places (status column and inline next to particulars), and is expanded by default revealing a red "0 / ₹1,84,000 allocated" line with an Allocate now CTA. Even at a 1-second glance it is the only non-grey row in the table.',
    },
    {
      n: 2,
      q: "Is the aging bar's story readable at a glance — without reading the labels?",
      v: 'Yes. The 5-segment bar runs slate→amber→rust→ochre→danger from left to right. The rightmost (120+) segment is danger red and visibly skewed — Khan Sarees has 22% of receivable in 120+, which reads as "trouble on the right". The legend below mirrors widths, so weights stay legible. Total ₹6,40,000 sits big and red above it for instant context.',
    },
    {
      n: 3,
      q: 'Does the 3-way match panel on GRN make a mismatch obvious?',
      v: 'Yes. Each doc row gets a 36-px circle: emerald check on match, amber alert on mismatch, dashed grey badge on pending. Connector between rows turns dashed where the chain breaks. A coloured warning banner directly under the panel explains the mismatch in one sentence with a deep link to the discrepancy report. PO ↔ GRN ↔ PI are explicitly stacked top-to-bottom so the eye reads the chain in order.',
    },
  ];
  const ap = [
    ['Honoured', 'Monogram chips from a 12-colour rotation. No avatar photos for parties.'],
    ['Honoured', 'No "Send via WhatsApp" actions on the Party screen — that is Phase 4 of the broader platform. The button on PO create is shown but disabled with a tooltip.'],
    ['Honoured', 'Emerald is reserved for primary actions ("Record receipt", "Post receipt", "Accept & post") and bold balance / total numbers. Aging bar uses the slate→amber→red ramp, not green-on-everything.'],
    ['Honoured', 'Tabular nums + right-aligned numerics throughout the ledger. Negative balances render in danger-text. Running balance is bolded.'],
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 12, padding: 28 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-tertiary)', marginBottom: 14 }}>Self-review</div>
        {qs.map(it => (
          <div key={it.n} style={{ display: 'flex', gap: 16, padding: '12px 0', borderTop: it.n === 1 ? 'none' : '1px solid var(--border-subtle)' }}>
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

Object.assign(window, { P4Root });
