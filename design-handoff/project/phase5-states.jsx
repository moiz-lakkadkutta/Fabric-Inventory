// phase5-states.jsx — loading skeletons + empty states.

function PnLLoadingState() {
  return (
    <ReportShell active="pnl">
      <ReportPageHeader
        title="Profit & Loss"
        period="FY 2025–26 · Apr 2025 – Mar 2026"
        comparePeriod="FY 2024–25"
      />
      <div style={{ padding: 24 }}>
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden' }}>
          <table className="rpt-table">
            <thead>
              <tr>
                <th className="rpt-th" style={{ width: '40%' }}>Particulars</th>
                <th className="rpt-th rpt-num">FY 25–26 ₹</th>
                <th className="rpt-th rpt-num">FY 24–25 ₹</th>
                <th className="rpt-th rpt-num">Variance ₹</th>
                <th className="rpt-th rpt-num" style={{ width: 96 }}>Var %</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 12 }).map((_, i) => {
                const isHead = i === 0 || i === 4 || i === 8;
                const indent = isHead ? 0 : 24;
                return (
                  <tr key={i}>
                    <td className="rpt-td" style={{ paddingLeft: 14 + indent }}>
                      <SkeletonBar w={isHead ? 120 : 200 - i * 8} h={isHead ? 14 : 12} dark={isHead} />
                    </td>
                    <td className="rpt-td rpt-num"><SkeletonBar w={80} h={12} dark={isHead} /></td>
                    <td className="rpt-td rpt-num"><SkeletonBar w={80} h={12} /></td>
                    <td className="rpt-td rpt-num"><SkeletonBar w={70} h={12} /></td>
                    <td className="rpt-td rpt-num"><SkeletonBar w={40} h={12} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </ReportShell>
  );
}

function EmptyState({ active = 'pnl', title = 'Profit & Loss' }) {
  return (
    <ReportShell active={active}>
      <ReportPageHeader
        title={title}
        period="Aug 2026 — current quarter"
        comparePeriod="vs last year"
      />
      <div style={{ padding: 64, display: 'flex', justifyContent: 'center' }}>
        <div style={{
          maxWidth: 460, textAlign: 'center', padding: 40,
          background: 'var(--bg-surface)', border: '1px dashed var(--border-strong)', borderRadius: 12,
        }}>
          <div style={{
            width: 64, height: 64, margin: '0 auto 16px',
            borderRadius: 12, background: 'var(--bg-sunken)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--text-tertiary)',
          }}>
            <Icon name="inbox" size={28} />
          </div>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>No transactions in this period.</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 18 }}>
            Try a wider date range or pick another firm.
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
            <Button variant="secondary" size="sm" icon="calendar">Change period</Button>
            <Button variant="primary" size="sm" icon="building">Switch firm</Button>
          </div>
        </div>
      </div>
    </ReportShell>
  );
}

Object.assign(window, { PnLLoadingState, EmptyState });
