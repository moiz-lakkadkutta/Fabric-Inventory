// phase4-accounts.jsx — Receipt, Payment, Voucher post.

const { useState: useStateA } = React;

/* ─────────────────────────────────────────────────────────────
   SCR-ACCT-001 — Receipt
───────────────────────────────────────────────────────────── */

const OPEN_INVOICES = [
  { doc: 'INV/25-26/000338', date: '02-Dec-25', amt: 312000, alloc: 0,      out: 112000, days: 145, fifoFirst: true },
  { doc: 'INV/25-26/000412', date: '04-Jan-26', amt: 188000, alloc: 0,      out: 188000, days: 112 },
  { doc: 'INV/25-26/000489', date: '02-Feb-26', amt: 96000,  alloc: 0,      out: 96000,  days: 84 },
  { doc: 'INV/25-26/000581', date: '12-Mar-26', amt: 248000, alloc: 0,      out: 248000, days: 46 },
  { doc: 'INV/25-26/000642', date: '02-Apr-26', amt: 124000, alloc: 0,      out: 84000,  days: 25 },
  { doc: 'INV/25-26/000718', date: '24-Apr-26', amt: 76000,  alloc: 0,      out: 76000,  days: 3 },
];

function ReceiptScreen({ amount = 184000, fifo = true }) {
  // Apply FIFO allocation
  let remaining = amount;
  const allocated = OPEN_INVOICES.map(i => {
    if (!fifo) return { ...i, allocated: 0 };
    const take = Math.min(remaining, i.out);
    remaining -= take;
    return { ...i, allocated: take };
  });
  const totalAllocated = amount - remaining;
  const advance = remaining;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '16px 24px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Accounts › Receipts</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>RCT/25-26/000409</h1>
            <Pill kind="draft">Draft</Pill>
          </div>
        </div>
        <Button variant="secondary" size="sm">Save draft</Button>
        <Button variant="primary" size="sm" icon="check">Post receipt</Button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, padding: 24 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* form */}
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
              <Field label="Party" required>
                <div style={{ border: '1px solid var(--border-default)', borderRadius: 6, padding: '8px 10px', display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg-surface)' }}>
                  <Monogram initials="KS" size={28} tone="indigo" />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>Khan Sarees Pvt Ltd</div>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Outstanding ₹6,40,000 · 5 open invoices</div>
                  </div>
                  <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
                </div>
              </Field>
              <Field label="Date" required><Input value="27-Apr-2026" suffix={<Icon name="calendar" size={14} />} /></Field>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 12 }}>
              <Field label="Mode" required>
                <SegmentedControl options={['Cash', 'Cheque', 'NEFT', 'UPI']} active="NEFT" />
              </Field>
              <Field label="Amount" required>
                <Input value="1,84,000.00" prefix={<span>₹</span>} />
              </Field>
              <Field label="Reference" helper="Txn ID / cheque #"><Input value="HDFC0042189123" /></Field>
            </div>
            <div style={{ marginTop: 12 }}>
              <Field label="Notes"><Input value="Part payment against Dec & Jan billing" /></Field>
            </div>
          </div>

          {/* allocation */}
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
            <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>Allocate against open invoices</h3>
              <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>· {OPEN_INVOICES.length} open</span>
              <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Auto-allocate FIFO</span>
                <Toggle on={fifo} />
              </span>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ background: 'var(--bg-sunken)' }}>
                  <th style={thA}>Doc #</th>
                  <th style={thA}>Date</th>
                  <th style={{...thA, textAlign: 'right'}}>Amount</th>
                  <th style={{...thA, textAlign: 'right'}}>Outstanding</th>
                  <th style={{...thA, textAlign: 'right'}}>Days</th>
                  <th style={{...thA, textAlign: 'right'}}>Allocate ₹</th>
                </tr>
              </thead>
              <tbody>
                {allocated.map((r, i) => (
                  <tr key={r.doc} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)', background: r.allocated > 0 ? 'rgba(73,128,82,0.04)' : 'transparent' }}>
                    <td className="mono" style={{...tdA, color: 'var(--accent)', fontWeight: 600}}>{r.doc}</td>
                    <td style={{...tdA, color: 'var(--text-secondary)'}}>{r.date}</td>
                    <td className="num" style={{...tdA, textAlign: 'right'}}>₹{r.amt.toLocaleString('en-IN')}</td>
                    <td className="num" style={{...tdA, textAlign: 'right', color: 'var(--text-secondary)'}}>₹{r.out.toLocaleString('en-IN')}</td>
                    <td className="num" style={{...tdA, textAlign: 'right', color: r.days > 90 ? 'var(--danger-text)' : 'var(--text-tertiary)', fontWeight: r.days > 90 ? 600 : 400}}>{r.days}d</td>
                    <td style={{...tdA, textAlign: 'right'}}>
                      <input
                        readOnly
                        value={r.allocated > 0 ? r.allocated.toLocaleString('en-IN') : ''}
                        placeholder="—"
                        className="num"
                        style={{
                          width: 100, textAlign: 'right',
                          padding: '6px 8px', fontSize: 12.5, fontFamily: 'inherit', fontWeight: r.allocated > 0 ? 600 : 400,
                          border: '1px solid ' + (r.allocated > 0 ? 'var(--accent)' : 'var(--border-default)'),
                          borderRadius: 4, color: r.allocated > 0 ? 'var(--accent)' : 'var(--text-primary)',
                          background: r.allocated > 0 ? 'var(--accent-subtle)' : 'var(--bg-surface)',
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* summary rail */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Summary</div>
            <Row k="Receipt amount" v={<span className="num" style={{ fontWeight: 600 }}>₹{amount.toLocaleString('en-IN')}</span>} />
            <Row k="Allocated" v={<span className="num" style={{ color: 'var(--accent)', fontWeight: 600 }}>₹{totalAllocated.toLocaleString('en-IN')}</span>} />
            <Row k="Unallocated (advance)" v={<span className="num" style={{ color: advance > 0 ? 'var(--warning-text)' : 'var(--text-tertiary)', fontWeight: 600 }}>₹{advance.toLocaleString('en-IN')}</span>} />
            <div style={{ height: 8, marginTop: 8, marginBottom: 4, borderRadius: 4, background: 'var(--bg-sunken)', overflow: 'hidden', display: 'flex' }}>
              <div style={{ width: (totalAllocated / amount * 100) + '%', background: 'var(--accent)' }} />
              <div style={{ width: (advance / amount * 100) + '%', background: 'var(--warning)' }} />
            </div>
          </div>

          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Khan Sarees — after this</div>
            <Row k="Current outstanding" v="₹6,40,000" />
            <Row k="Less: this receipt" v={<span style={{ color: 'var(--success-text)' }}>− ₹1,84,000</span>} />
            <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 8, marginTop: 6 }}>
              <Row k="New outstanding" v={<span className="num" style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)' }}>₹4,56,000</span>} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

const thA = { fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '8px 12px', textAlign: 'left', whiteSpace: 'nowrap' };
const tdA = { padding: '10px 12px', verticalAlign: 'middle' };

function Toggle({ on }) {
  return (
    <span style={{
      width: 32, height: 18, borderRadius: 9,
      background: on ? 'var(--accent)' : 'var(--bg-sunken)',
      border: on ? 'none' : '1px solid var(--border-default)',
      position: 'relative', display: 'inline-block', cursor: 'pointer',
    }}>
      <span style={{
        position: 'absolute', top: 2, left: on ? 16 : 2,
        width: 14, height: 14, borderRadius: '50%', background: '#FFF', boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
        transition: 'left 0.15s',
      }} />
    </span>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-ACCT-002 — Payment (supplier-side)
───────────────────────────────────────────────────────────── */

function PaymentScreen() {
  const open = [
    { doc: 'PI/25-26/00064', date: '02-Apr-26', amt: 482000, out: 482000, days: 25 },
    { doc: 'PI/25-26/00071', date: '18-Apr-26', amt: 312000, out: 312000, days: 9 },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '16px 24px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Accounts › Payments</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>PMT/25-26/000182</h1>
            <Pill kind="draft">Draft</Pill>
          </div>
        </div>
        <Button variant="secondary" size="sm">Save draft</Button>
        <Button variant="primary" size="sm" icon="check">Post payment</Button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, padding: 24 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
              <Field label="Supplier" required>
                <div style={{ border: '1px solid var(--border-default)', borderRadius: 6, padding: '8px 10px', display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg-surface)' }}>
                  <Monogram initials="RI" size={28} tone="indigo" />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>Reliance Industries Ltd</div>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Payable ₹4,82,000 · 1 invoice</div>
                  </div>
                  <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />
                </div>
              </Field>
              <Field label="Date" required><Input value="27-Apr-2026" suffix={<Icon name="calendar" size={14} />} /></Field>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 12 }}>
              <Field label="Mode"><SegmentedControl options={['Cash','Cheque','NEFT','UPI']} active="NEFT" /></Field>
              <Field label="Amount" required><Input value="4,82,000.00" prefix={<span>₹</span>} /></Field>
              <Field label="Bank" hint="Paying from"><Input value="HDFC ****8921" /></Field>
            </div>
          </div>

          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
            <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>Allocate against invoices</h3>
              <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Auto-allocate FIFO</span>
                <Toggle on={true} />
              </span>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ background: 'var(--bg-sunken)' }}>
                  <th style={thA}>Doc #</th>
                  <th style={thA}>Date</th>
                  <th style={{...thA, textAlign: 'right'}}>Outstanding</th>
                  <th style={{...thA, textAlign: 'right'}}>Days</th>
                  <th style={{...thA, textAlign: 'right'}}>Allocate ₹</th>
                </tr>
              </thead>
              <tbody>
                {open.map((r, i) => (
                  <tr key={r.doc} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)', background: i === 0 ? 'rgba(73,128,82,0.04)' : 'transparent' }}>
                    <td className="mono" style={{...tdA, color: 'var(--accent)', fontWeight: 600}}>{r.doc}</td>
                    <td style={{...tdA, color: 'var(--text-secondary)'}}>{r.date}</td>
                    <td className="num" style={{...tdA, textAlign: 'right'}}>₹{r.out.toLocaleString('en-IN')}</td>
                    <td className="num" style={{...tdA, textAlign: 'right', color: 'var(--text-tertiary)'}}>{r.days}d</td>
                    <td style={{...tdA, textAlign: 'right'}}>
                      <input
                        readOnly
                        value={i === 0 ? '4,82,000' : ''}
                        placeholder="—"
                        className="num"
                        style={{
                          width: 100, textAlign: 'right', padding: '6px 8px', fontSize: 12.5, fontFamily: 'inherit',
                          fontWeight: i === 0 ? 600 : 400,
                          border: '1px solid ' + (i === 0 ? 'var(--accent)' : 'var(--border-default)'),
                          borderRadius: 4, color: i === 0 ? 'var(--accent)' : 'var(--text-primary)',
                          background: i === 0 ? 'var(--accent-subtle)' : 'var(--bg-surface)',
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Summary</div>
            <Row k="Payment amount" v="₹4,82,000.00" />
            <Row k="Allocated" v={<span style={{ color: 'var(--accent)', fontWeight: 600 }}>₹4,82,000.00</span>} />
            <Row k="Advance to supplier" v="₹0.00" />
          </div>
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Bank balance — HDFC ****8921</div>
            <Row k="Current" v="₹18,42,318" />
            <Row k="Less: this payment" v={<span style={{ color: 'var(--danger-text)' }}>− ₹4,82,000</span>} />
            <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 8, marginTop: 6 }}>
              <Row k="After posting" v={<span className="num" style={{ fontWeight: 700, fontSize: 14 }}>₹13,60,318</span>} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   SCR-ACCT-003 — Voucher Post
───────────────────────────────────────────────────────────── */

function VoucherPost({ unbalanced = false }) {
  const lines = unbalanced ? [
    { sno: 1, ledger: 'Travel — Mumbai trip Apr',           dr: 24500, cr: 0, note: 'Hotel + flights for buyers' },
    { sno: 2, ledger: 'Conveyance — Local',                  dr: 1200,  cr: 0, note: 'Cabs' },
    { sno: 3, ledger: 'Cash on hand',                        dr: 0,     cr: 25200, note: 'Petty cash withdrawal' },
  ] : [
    { sno: 1, ledger: 'Travel — Mumbai trip Apr',           dr: 24500, cr: 0,     note: 'Hotel + flights for buyers' },
    { sno: 2, ledger: 'Conveyance — Local',                  dr: 1200,  cr: 0,     note: 'Cabs to suppliers' },
    { sno: 3, ledger: 'Hospitality — Customer entertainment',dr: 4800,  cr: 0,     note: '' },
    { sno: 4, ledger: 'Cash on hand',                        dr: 0,     cr: 30500, note: 'Petty cash withdrawal' },
  ];
  const totalDr = lines.reduce((s, l) => s + l.dr, 0);
  const totalCr = lines.reduce((s, l) => s + l.cr, 0);
  const diff = totalDr - totalCr;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <div style={{ padding: '16px 24px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Accounts › Vouchers</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>JV/25-26/000019</h1>
            <Pill kind="draft">Draft</Pill>
          </div>
        </div>
        <Button variant="secondary" size="sm">Save draft</Button>
        <Button variant="primary" size="sm" icon="check" state={diff !== 0 ? 'disabled' : 'rest'}>Post voucher</Button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'grid', gridTemplateColumns: '1fr 340px', gap: 20, padding: 24 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 16, display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
            <Field label="Voucher type">
              <SegmentedControl options={['Journal','Contra','Receipt','Payment']} active="Journal" />
            </Field>
            <Field label="Date" required><Input value="27-Apr-2026" suffix={<Icon name="calendar" size={14} />} /></Field>
            <Field label="Reference"><Input value="EXP-APR-NK-04" /></Field>
            <div style={{ gridColumn: '1 / span 3' }}>
              <Field label="Narration"><Input value="Petty cash expenditure — Mumbai supplier visits, week of 22-Apr" /></Field>
            </div>
          </div>

          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ background: 'var(--bg-sunken)' }}>
                  <th style={thA}>#</th>
                  <th style={thA}>Ledger</th>
                  <th style={thA}>Notes</th>
                  <th style={{...thA, textAlign: 'right'}}>Debit ₹</th>
                  <th style={{...thA, textAlign: 'right'}}>Credit ₹</th>
                  <th style={{...thA, width: 28}}></th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={l.sno} style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)' }}>
                    <td style={{...tdA, color: 'var(--text-tertiary)'}}>{l.sno}</td>
                    <td style={{...tdA, fontWeight: 500}}>
                      {l.ledger}
                      <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>
                        {l.ledger.startsWith('Travel') ? 'Group: Indirect Expenses' : l.ledger.startsWith('Cash') ? 'Group: Cash & bank' : 'Group: Indirect Expenses'}
                      </div>
                    </td>
                    <td style={{...tdA, color: 'var(--text-secondary)', fontSize: 11.5}}>{l.note || '—'}</td>
                    <td className="num" style={{...tdA, textAlign: 'right', color: l.dr ? 'var(--text-primary)' : 'var(--text-tertiary)', fontWeight: l.dr ? 600 : 400}}>{l.dr ? l.dr.toLocaleString('en-IN') : '—'}</td>
                    <td className="num" style={{...tdA, textAlign: 'right', color: l.cr ? 'var(--success-text)' : 'var(--text-tertiary)', fontWeight: l.cr ? 600 : 400}}>{l.cr ? l.cr.toLocaleString('en-IN') : '—'}</td>
                    <td style={tdA}><Icon name="x" size={12} color="var(--text-tertiary)" /></td>
                  </tr>
                ))}
                <tr style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td colSpan="6" style={{ padding: '10px 12px', fontSize: 12, fontStyle: 'italic', color: 'var(--text-tertiary)' }}>+ Add line</td>
                </tr>
                <tr style={{ borderTop: '2px solid var(--border-strong)', background: 'var(--bg-sunken)' }}>
                  <td colSpan="3" style={{...tdA, fontWeight: 700, textAlign: 'right'}}>Totals</td>
                  <td className="num" style={{...tdA, textAlign: 'right', fontWeight: 700, fontSize: 13.5}}>{totalDr.toLocaleString('en-IN')}</td>
                  <td className="num" style={{...tdA, textAlign: 'right', fontWeight: 700, fontSize: 13.5}}>{totalCr.toLocaleString('en-IN')}</td>
                  <td></td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* balance indicator */}
          <div style={{
            padding: '12px 16px', borderRadius: 8,
            background: diff === 0 ? 'var(--success-subtle)' : 'var(--danger-subtle)',
            border: '1px solid ' + (diff === 0 ? '#A7C8AB' : '#E0A498'),
            display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <Icon name={diff === 0 ? 'check' : 'alert'} size={20} color={diff === 0 ? 'var(--success-text)' : 'var(--danger-text)'} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: diff === 0 ? 'var(--success-text)' : 'var(--danger-text)' }}>
                {diff === 0 ? 'Difference ₹0.00 — voucher balanced' : `Difference ₹${Math.abs(diff).toLocaleString('en-IN')}.00 — voucher unbalanced`}
              </div>
              <div style={{ fontSize: 11.5, color: diff === 0 ? 'var(--success-text)' : 'var(--danger-text)', marginTop: 2 }}>
                {diff === 0 ? 'Debits equal credits. Ready to post.' : `${diff > 0 ? 'Debit' : 'Credit'} side is ₹${Math.abs(diff).toLocaleString('en-IN')} short. Post is disabled until matched.`}
              </div>
            </div>
          </div>
        </div>

        {/* ledger preview */}
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, padding: 16, height: 'fit-content', position: 'sticky', top: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>Ledger preview — Cash on hand</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {[
              ['24-Apr', 'Cash sale', 14000, 0, 38400],
              ['25-Apr', 'Driver — Aza delivery', 0, 800, 37600],
              ['26-Apr', 'Petty cash refill', 20000, 0, 57600],
              ['27-Apr', '★ This voucher', 0, totalCr, 57600 - totalCr, true],
            ].map(([d, p, dr, cr, bal, hi], i) => (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '60px 1fr 70px 70px',
                gap: 6, padding: '8px 6px',
                borderBottom: '1px solid var(--border-subtle)',
                background: hi ? 'var(--accent-subtle)' : 'transparent',
                fontWeight: hi ? 600 : 400,
              }}>
                <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>{d}</span>
                <span style={{ fontSize: 11.5 }}>{p}</span>
                <span className="num" style={{ fontSize: 11.5, textAlign: 'right', color: cr ? 'var(--danger-text)' : 'var(--text-tertiary)' }}>{cr ? `−${cr.toLocaleString('en-IN')}` : ''}</span>
                <span className="num" style={{ fontSize: 11.5, textAlign: 'right', fontWeight: 700 }}>{bal.toLocaleString('en-IN')}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10, padding: 10, background: 'var(--bg-sunken)', borderRadius: 6 }}>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Closing balance after posting</div>
            <div className="num" style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>₹{(57600 - totalCr).toLocaleString('en-IN')}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ReceiptScreen, PaymentScreen, VoucherPost });
