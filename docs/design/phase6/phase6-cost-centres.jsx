// phase6-cost-centres.jsx — Deliverable 4: Cost Centres list + create.
// Simplest of the five: code + name + description.

const CC_COLUMNS = [
  { key: 'code',   label: 'Code',        skelW: 110 },
  { key: 'name',   label: 'Name',        skelW: 180 },
  { key: 'desc',   label: 'Description', skelW: 280 },
  { key: 'ops',    label: 'Ops linked',  align: 'right', skelW: 30, width: 110 },
  { key: 'active', label: 'Status',      skelW: 50, width: 90 },
  { key: 'a',      label: '',            width: 36 },
];

function CostCentresListFull() {
  const rows = COST_CENTRES;
  return (
    <ListShell
      breadcrumb={['Masters', 'Cost centres']}
      sidebarActive="mast"
      title="Cost centres"
      sub={`${rows.length} cost centres · ${rows.filter(r => r.is_active).length} active · used by ${rows.reduce((s, r) => s + r.ops, 0)} operations`}
      secondaryCta={<Button variant="secondary" size="sm" icon="download">Export</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus">New cost centre</Button>}
      searchPlaceholder="Search by code, name…"
      filterChips={<>
        <FilterChip label="All" active count={rows.length} />
        <FilterChip label="Active"   count={rows.filter(r => r.is_active).length} />
        <FilterChip label="Inactive" count={rows.filter(r => !r.is_active).length} />
        <FilterChip label="In-house" count={rows.filter(r => r.code.startsWith('CC-INH') || r.code.startsWith('CC-QC') || r.code.startsWith('CC-PCK')).length} />
        <FilterChip label="Karigar"  count={rows.filter(r => r.code.startsWith('CC-KAR') || r.code.startsWith('CC-DYE') || r.code.startsWith('CC-BLK')).length} />
      </>}
      bottomMeta={<>Sort by <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>Name ↑</span></>}
    >
      <ListTable
        columns={CC_COLUMNS}
        rows={rows}
        renderRow={(r) => (
          <tr key={r.code} style={{ opacity: r.is_active ? 1 : 0.55 }}>
            <td className="mono" style={{...tdL, fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>{r.code}</td>
            <td style={{...tdL, fontWeight: 500 }}>{r.name}</td>
            <td style={{...tdL, color: 'var(--text-secondary)', maxWidth: 340 }}>{r.description}</td>
            <td className="num" style={{...tdL, textAlign: 'right', color: r.ops > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)', fontWeight: r.ops > 0 ? 600 : 400 }}>{r.ops}</td>
            <td style={tdL}>
              {r.is_active
                ? <Pill kind="paid">Active</Pill>
                : <Pill kind="scrap">Inactive</Pill>}
            </td>
            <td style={tdL}><button style={ccIcon} aria-label="More"><Icon name="menu-more" size={14} color="var(--text-tertiary)" /></button></td>
          </tr>
        )}
      />
    </ListShell>
  );
}

const ccIcon = {
  width: 28, height: 28, padding: 0,
  background: 'transparent', border: 'none', borderRadius: 4, cursor: 'pointer',
  color: 'var(--text-tertiary)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
};

function CostCentresListLoading() {
  return (
    <ListShell breadcrumb={['Masters', 'Cost centres']} sidebarActive="mast"
      title="Cost centres" sub="Loading…"
      primaryCta={<Button variant="primary" size="sm" icon="plus" state="disabled">New cost centre</Button>}
      searchPlaceholder="Search by code, name…"
      filterChips={<><FilterChip label="All" /><FilterChip label="Active" /></>}>
      <LoadingSkeletonRows columns={CC_COLUMNS} count={5} />
    </ListShell>
  );
}

function CostCentresListError() {
  return (
    <ListShell breadcrumb={['Masters', 'Cost centres']} sidebarActive="mast"
      title="Cost centres" sub="Couldn't load cost centres"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New cost centre</Button>}>
      <ErrorBanner message="GET /api/v1/manufacturing/cost-centres returned 503 — service unavailable." />
    </ListShell>
  );
}

function CostCentresListEmpty() {
  return (
    <ListShell breadcrumb={['Masters', 'Cost centres']} sidebarActive="mast"
      title="Cost centres" sub="No cost centres yet"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New cost centre</Button>}>
      <EmptyState icon="wallet" title="Track where work happens"
        sub="A cost centre is a bucket like “In-house stitching” or “Karigar — Rashid Tailors”. Operation masters point at them, and MOs roll labour costs up against each one."
        cta={<Button variant="primary" size="md" icon="plus">New cost centre</Button>} />
    </ListShell>
  );
}

function CostCentresListFilteredEmpty() {
  return (
    <ListShell breadcrumb={['Masters', 'Cost centres']} sidebarActive="mast"
      title="Cost centres" sub="7 cost centres · 6 active"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New cost centre</Button>}
      searchPlaceholder="vendor warehouse"
      filterChips={<><FilterChip label="All" count={7} /><FilterChip label="Karigar" count={3} active /></>}>
      <FilteredEmptyState query="vendor warehouse" />
    </ListShell>
  );
}

function CostCentreCreateDialog({ state = 'default' }) {
  const validation = state === 'validation';
  const loading = state === 'loading';
  const showToast = state === 'success';

  const v = {
    default:    { code: 'CC-KAR-IMR', name: 'Karigar embroidery — Imran', desc: 'Hand embroidery, Aari work karigar' },
    validation: { code: '',           name: 'Kar',                         desc: '' },
    loading:    { code: 'CC-KAR-IMR', name: 'Karigar embroidery — Imran', desc: 'Hand embroidery, Aari work karigar' },
    success:    { code: 'CC-KAR-IMR', name: 'Karigar embroidery — Imran', desc: 'Hand embroidery, Aari work karigar' },
  }[state] || { code: 'CC-KAR-IMR', name: 'Karigar embroidery — Imran', desc: 'Hand embroidery, Aari work karigar' };

  return (
    <div style={{ position: 'relative' }}>
      <div style={{ background: 'rgba(20,20,18,0.32)', borderRadius: 8, padding: 32, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Dialog720
          title="New cost centre"
          sub="A bucket for attributing labour cost on MO rollups."
          error={validation ? "Code is required. Name must be at least 3 characters." : null}
          loading={loading}
          footer={ccFoot({ disabled: validation, loading })}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
              <Field label="Code" required state={validation ? 'error' : 'default'} error={validation ? 'Required' : null} hint={!validation ? 'Auto-suggested from name' : null}>
                <Input value={v.code} state={validation ? 'error' : 'default'} />
              </Field>
              <Field label="Name" required state={validation ? 'error' : 'default'} error={validation ? 'Must be at least 3 characters' : null}>
                <Input value={v.name} state={validation ? 'error' : 'default'} />
              </Field>
            </div>
            <Field label="Description" helper="Address, vendor name, internal note (optional)">
              <textarea readOnly value={v.desc} placeholder="e.g. Hand embroidery, Aari work karigar"
                style={{
                  width: '100%', minHeight: 72, padding: '10px 12px',
                  fontSize: 14, fontFamily: 'inherit', resize: 'vertical',
                  border: '1px solid var(--border-default)', borderRadius: 6,
                  color: 'var(--text-primary)', background: 'var(--bg-surface)',
                }} />
            </Field>
          </div>
        </Dialog720>
      </div>
      {showToast && <SuccessToast message='Cost centre "Karigar embroidery — Imran" created · CC-KAR-IMR' />}
    </div>
  );
}

function ccFoot({ disabled, loading }) {
  return <>
    <span style={{ flex: 1 }} />
    <Button variant="ghost" size="sm">Cancel</Button>
    {loading
      ? <Button variant="primary" size="sm" icon={<Icon name="spinner" size={14} />}>Saving…</Button>
      : <Button variant="primary" size="sm" state={disabled ? 'disabled' : 'rest'}>Create cost centre</Button>}
  </>;
}

Object.assign(window, {
  CostCentresListFull, CostCentresListLoading, CostCentresListError, CostCentresListEmpty, CostCentresListFilteredEmpty,
  CostCentreCreateDialog,
});
