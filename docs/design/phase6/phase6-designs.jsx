// phase6-designs.jsx — Deliverable 1: Designs list + create dialog.
// Mirrors PartyList (spacing, filter chips, search, "+ New design" CTA, breadcrumb).

const { useState: useStateD } = React;

/* ─────────────────────────────────────────────────────────────
   Designs list — full state, 8 rows incl. one inactive (muted).
───────────────────────────────────────────────────────────── */
const DESIGN_COLUMNS = [
  { key: 'code',    label: 'Code',     skelW: 110 },
  { key: 'name',    label: 'Name',     skelW: 220 },
  { key: 'fin',     label: 'Finished item', skelW: 180 },
  { key: 'bom',     label: 'BOM v',    align: 'right', skelW: 30, width: 80 },
  { key: 'rtg',     label: 'Routing v', align: 'right', skelW: 30, width: 90 },
  { key: 'active',  label: 'Active',   skelW: 50, width: 90 },
  { key: 'updated', label: 'Updated',  skelW: 80 },
  { key: 'a',       label: '',         width: 36 },
];

function DesignsListFull({ variant = 'full' }) {
  const rows = DESIGNS;
  return (
    <ListShell
      breadcrumb={['Masters', 'Designs']}
      sidebarActive="mast"
      title="Designs"
      sub={`${rows.length} designs · ${rows.filter(r => r.is_active).length} active · linked to ${new Set(rows.map(r => r.fin)).size} finished items`}
      secondaryCta={<Button variant="secondary" size="sm" icon="upload">Import</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus">New design</Button>}
      searchPlaceholder="Search by code, name, finished item…"
      filterChips={<>
        <FilterChip label="All" active count={rows.length} />
        <FilterChip label="Active" count={rows.filter(r => r.is_active).length} />
        <FilterChip label="Inactive" count={rows.filter(r => !r.is_active).length} />
        <FilterChip label="Has active BOM" count={rows.filter(r => r.bom > 0).length} />
        <FilterChip label="No routing" count={rows.filter(r => r.rtg === 0).length} />
      </>}
      bottomMeta={<>Sort by <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>Updated ↓</span></>}
    >
      <ListTable
        columns={DESIGN_COLUMNS}
        rows={rows}
        renderRow={(r, i) => (
          <tr key={r.code} style={{ opacity: r.is_active ? 1 : 0.55 }}>
            <td style={{...tdL, fontFamily: 'var(--font-num)', fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>{r.code}</td>
            <td style={{...tdL, fontWeight: 500 }}>{r.name}</td>
            <td style={tdL}>
              <span style={{ color: 'var(--text-secondary)' }}>{ITEMS.find(it => it.code === r.fin)?.name || '—'}</span>
              <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 1 }}>{r.fin}</div>
            </td>
            <td className="num" style={{...tdL, textAlign: 'right', color: r.bom > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)', fontWeight: r.bom > 0 ? 600 : 400 }}>{r.bom}</td>
            <td className="num" style={{...tdL, textAlign: 'right', color: r.rtg > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)', fontWeight: r.rtg > 0 ? 600 : 400 }}>
              {r.rtg > 0 ? r.rtg : <span style={{ color: 'var(--warning-text)', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 700 }}>none</span>}
            </td>
            <td style={tdL}>
              {r.is_active
                ? <Pill kind="paid">Active</Pill>
                : <Pill kind="scrap">Inactive</Pill>}
            </td>
            <td style={{...tdL, color: 'var(--text-secondary)', fontSize: 12.5 }}>{r.updated}</td>
            <td style={tdL}><button style={iconBtnSmall} aria-label="More"><Icon name="menu-more" size={14} color="var(--text-tertiary)" /></button></td>
          </tr>
        )}
      />
    </ListShell>
  );
}

const iconBtnSmall = {
  width: 28, height: 28, padding: 0,
  background: 'transparent', border: 'none', borderRadius: 4, cursor: 'pointer',
  color: 'var(--text-tertiary)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
};

/* ─────────────────────────────────────────────────────────────
   Designs list — Loading / Error / Empty / Filtered-empty
───────────────────────────────────────────────────────────── */
function DesignsListLoading() {
  return (
    <ListShell
      breadcrumb={['Masters', 'Designs']} sidebarActive="mast"
      title="Designs" sub="Loading…"
      secondaryCta={<Button variant="secondary" size="sm" icon="upload" state="disabled">Import</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus" state="disabled">New design</Button>}
      searchPlaceholder="Search by code, name, finished item…"
      filterChips={<><FilterChip label="All" /><FilterChip label="Active" /><FilterChip label="Inactive" /></>}
    >
      <LoadingSkeletonRows columns={DESIGN_COLUMNS} count={6} />
    </ListShell>
  );
}

function DesignsListError() {
  return (
    <ListShell
      breadcrumb={['Masters', 'Designs']} sidebarActive="mast"
      title="Designs" sub="Couldn't load designs"
      secondaryCta={<Button variant="secondary" size="sm" icon="upload">Import</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus">New design</Button>}
    >
      <ErrorBanner message="GET /api/v1/manufacturing/designs returned 503 — service unavailable. Last successful sync 2 min ago." />
    </ListShell>
  );
}

function DesignsListEmpty() {
  return (
    <ListShell
      breadcrumb={['Masters', 'Designs']} sidebarActive="mast"
      title="Designs" sub="No designs yet"
      secondaryCta={<Button variant="secondary" size="sm" icon="upload">Import</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus">New design</Button>}
    >
      <EmptyState
        icon="package"
        title="Add your first design"
        sub="A design is a finished product like Anarkali Pink or Sharara Gold. You'll attach a BOM and a Routing to each — the Manufacturing Order wizard pulls from this list."
        cta={<div style={{ display: 'inline-flex', gap: 8 }}>
          <Button variant="primary" size="md" icon="plus">New design</Button>
          <Button variant="secondary" size="md" icon="upload">Import from CSV</Button>
        </div>}
      />
    </ListShell>
  );
}

function DesignsListFilteredEmpty() {
  return (
    <ListShell
      breadcrumb={['Masters', 'Designs']} sidebarActive="mast"
      title="Designs" sub="8 designs · 7 active"
      secondaryCta={<Button variant="secondary" size="sm" icon="upload">Import</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus">New design</Button>}
      searchPlaceholder="kanjeevaram"
      filterChips={<><FilterChip label="All" count={8} /><FilterChip label="Active" count={7} active /></>}
    >
      <FilteredEmptyState query="kanjeevaram" />
    </ListShell>
  );
}

/* ─────────────────────────────────────────────────────────────
   Designs create dialog — 720px modal, mirrors NewJournalVoucherDialog.
   States: default, validation error, loading, success-toast-after.
───────────────────────────────────────────────────────────── */
function dialogFooter({ disabled, loading, onCancel, onSubmit, submitLabel = 'Create design' }) {
  return <>
    <span style={{ flex: 1, fontSize: 11.5, color: 'var(--text-tertiary)' }}>
      Required: code, name, finished item
    </span>
    <span onClick={onCancel} style={{ cursor: 'pointer' }}>
      <Button variant="ghost" size="sm">Cancel</Button>
    </span>
    {loading
      ? <Button variant="primary" size="sm" icon={<Icon name="spinner" size={14} />}>Saving…</Button>
      : <span onClick={onSubmit} style={{ cursor: disabled ? 'not-allowed' : 'pointer' }}>
          <Button variant="primary" size="sm" state={disabled ? 'disabled' : 'rest'}>{submitLabel}</Button>
        </span>}
  </>;
}

function DesignCreateDialog({ state = 'default' }) {
  const validation = state === 'validation';
  const loading = state === 'loading';
  const showToast = state === 'success';

  // Field values per state
  const v = {
    default: { code: 'DSN-KRT-OFW', name: 'Kurta Off-white Chikankari', desc: '', fin: 'Kurta Indigo Block Print', finResults: null },
    validation: { code: '', name: 'Kurta Off-', desc: '', fin: '', finResults: null },
    loading:   { code: 'DSN-KRT-OFW', name: 'Kurta Off-white Chikankari', desc: 'Lucknow chikankari panel, Ramadan collection', fin: 'Kurta Indigo Block Print', finResults: null },
    success:   { code: 'DSN-KRT-OFW', name: 'Kurta Off-white Chikankari', desc: 'Lucknow chikankari panel, Ramadan collection', fin: 'Kurta Indigo Block Print', finResults: null },
    typeahead: { code: 'DSN-KRT-OFW', name: 'Kurta Off-white Chikankari', desc: '', fin: 'kurta',
      finResults: ITEMS.filter(i => i.kind === 'finished' && i.name.toLowerCase().includes('kurta')).map(i => ({ name: i.name, code: i.code, meta: `Finished · cost ${inrRs(i.cost)}/${i.uom}` })) },
  }[state] || { code: 'DSN-KRT-OFW', name: 'Kurta Off-white Chikankari', desc: '', fin: 'Kurta Indigo Block Print', finResults: null };

  const submitDisabled = !v.code || !v.name || !v.fin || v.fin === 'kurta';

  return (
    <div style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center' }}>
      {/* dim backdrop for dialog presentation */}
      <div style={{
        background: 'rgba(20,20,18,0.32)', borderRadius: 8,
        padding: 32, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Dialog720
          title="New design"
          sub="Adds a finished-product master row. You'll attach a BOM and routing next."
          error={validation ? "Code is required. Name must be at least 3 characters. Finished item must be selected." : null}
          loading={loading}
          footer={dialogFooter({
            disabled: validation || submitDisabled,
            loading,
          })}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
              <Field label="Code" required
                state={validation ? 'error' : 'default'}
                error={validation ? 'Required' : null}
                hint={!validation ? 'Auto-suggested from name' : null}>
                <Input value={v.code} state={validation ? 'error' : 'default'} />
              </Field>
              <Field label="Name" required
                state={validation ? 'error' : 'default'}
                error={validation ? 'Must be at least 3 characters' : null}>
                <Input value={v.name} state={validation ? 'error' : 'default'} />
              </Field>
            </div>

            <Field label="Description" helper="Internal notes, season tag, fabric story (optional)">
              <textarea readOnly value={v.desc} placeholder="e.g. Lucknow chikankari panel, Ramadan collection"
                style={{
                  width: '100%', minHeight: 64, padding: '10px 12px',
                  fontSize: 14, fontFamily: 'inherit', resize: 'vertical',
                  border: '1px solid var(--border-default)', borderRadius: 6,
                  color: 'var(--text-primary)', background: 'var(--bg-surface)',
                }} />
            </Field>

            <Field label="Finished item" required
              hint="Type 3+ characters to search the Items master"
              state={validation ? 'error' : 'default'}
              error={validation ? 'Pick a finished item from the Items master' : null}>
              <TypeaheadField value={v.fin} placeholder="Search items…"
                results={v.finResults}
                state={validation ? 'error' : 'default'}
              />
            </Field>

            <div style={{
              padding: 12, background: 'var(--bg-sunken)', borderRadius: 6,
              border: '1px solid var(--border-subtle)',
              display: 'flex', alignItems: 'flex-start', gap: 10,
            }}>
              <Icon name="info" size={14} color="var(--text-secondary)" />
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                After this dialog, you can attach a <strong>Bill of Materials</strong> and a <strong>Routing</strong> from the Design detail page.
                A design without an active BOM and routing won't appear in the MO Create wizard.
              </div>
            </div>
          </div>
        </Dialog720>
      </div>
      {showToast && <SuccessToast message='Design "Kurta Off-white Chikankari" created · DSN-KRT-OFW' />}
    </div>
  );
}

Object.assign(window, {
  DesignsListFull, DesignsListLoading, DesignsListError, DesignsListEmpty, DesignsListFilteredEmpty,
  DesignCreateDialog,
});
