// phase6-operations.jsx — Deliverable 3: Operation Masters list + create.
// Adds operation_type color-coded pill column re-using kanban palette
// plus harmonious tones for WEAVING + DYEING.

const { useState: useStateOp } = React;

const OP_COLUMNS = [
  { key: 'code',   label: 'Code',    skelW: 110 },
  { key: 'name',   label: 'Name',    skelW: 220 },
  { key: 'type',   label: 'Type',    skelW: 100, width: 150 },
  { key: 'dur',    label: 'Default duration', align: 'right', skelW: 50, width: 140 },
  { key: 'cc',     label: 'Cost centre', skelW: 160 },
  { key: 'active', label: 'Status',  skelW: 50, width: 90 },
  { key: 'a',      label: '',        width: 36 },
];

function durFmt(mins) {
  if (mins == null) return '—';
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60); const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function OperationsListFull() {
  const rows = OPERATION_MASTERS;
  const typeCounts = rows.reduce((acc, r) => { acc[r.type] = (acc[r.type] || 0) + 1; return acc; }, {});
  return (
    <ListShell
      breadcrumb={['Masters', 'Operation masters']}
      sidebarActive="mast"
      title="Operation masters"
      sub={`${rows.length} operations · ${Object.keys(typeCounts).length} types · ${rows.filter(r => r.is_active).length} active`}
      secondaryCta={<Button variant="secondary" size="sm" icon="download">Export</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus">New operation</Button>}
      searchPlaceholder="Search by code, name, cost centre…"
      filterChips={<>
        <FilterChip label="All" active count={rows.length} />
        <FilterChip label="Weaving"    count={typeCounts.WEAVING    || 0} />
        <FilterChip label="Dyeing"     count={typeCounts.DYEING     || 0} />
        <FilterChip label="Embroidery" count={typeCounts.EMBROIDERY || 0} />
        <FilterChip label="Stitching"  count={typeCounts.STITCHING  || 0} />
        <FilterChip label="QC"         count={typeCounts.QC         || 0} />
        <FilterChip label="Packing"    count={typeCounts.PACKING    || 0} />
      </>}
      bottomMeta={<>Sort by <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>Type ↑ · Name ↑</span></>}
    >
      <ListTable
        columns={OP_COLUMNS}
        rows={rows}
        renderRow={(r, i) => {
          const cc = COST_CENTRES.find(c => c.code === r.cc);
          return (
            <tr key={r.code} style={{ opacity: r.is_active ? 1 : 0.55 }}>
              <td className="mono" style={{...tdL, fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>{r.code}</td>
              <td style={{...tdL, fontWeight: 500 }}>{r.name}</td>
              <td style={tdL}><OpTypePill type={r.type} /></td>
              <td className="num" style={{...tdL, textAlign: 'right', color: 'var(--text-secondary)' }}>{durFmt(r.dur)}</td>
              <td style={{...tdL, color: 'var(--text-secondary)' }}>
                {cc?.name || '—'}
                {cc && <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 1 }}>{cc.code}</div>}
              </td>
              <td style={tdL}>
                {r.is_active
                  ? <Pill kind="paid">Active</Pill>
                  : <Pill kind="scrap">Inactive</Pill>}
              </td>
              <td style={tdL}><button style={{...iconBtnSmallOp}} aria-label="More"><Icon name="menu-more" size={14} color="var(--text-tertiary)" /></button></td>
            </tr>
          );
        }}
      />
    </ListShell>
  );
}

const iconBtnSmallOp = {
  width: 28, height: 28, padding: 0,
  background: 'transparent', border: 'none', borderRadius: 4, cursor: 'pointer',
  color: 'var(--text-tertiary)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
};

function OperationsListLoading() {
  return (
    <ListShell breadcrumb={['Masters', 'Operation masters']} sidebarActive="mast"
      title="Operation masters" sub="Loading…"
      primaryCta={<Button variant="primary" size="sm" icon="plus" state="disabled">New operation</Button>}
      searchPlaceholder="Search by code, name, cost centre…"
      filterChips={<><FilterChip label="All" /><FilterChip label="Stitching" /><FilterChip label="QC" /></>}>
      <LoadingSkeletonRows columns={OP_COLUMNS} count={7} />
    </ListShell>
  );
}

function OperationsListError() {
  return (
    <ListShell breadcrumb={['Masters', 'Operation masters']} sidebarActive="mast"
      title="Operation masters" sub="Couldn't load operations"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New operation</Button>}>
      <ErrorBanner message="GET /api/v1/manufacturing/operations returned 503 — service unavailable." />
    </ListShell>
  );
}

function OperationsListEmpty() {
  return (
    <ListShell breadcrumb={['Masters', 'Operation masters']} sidebarActive="mast"
      title="Operation masters" sub="No operations yet"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New operation</Button>}>
      <EmptyState icon="cog" title="Define your manufacturing steps"
        sub="Operations are reusable steps like “Cut”, “Aari embroidery”, “Quality check”. You'll wire them into a routing for each design — they decide the kanban columns lots move through."
        cta={<Button variant="primary" size="md" icon="plus">New operation</Button>} />
    </ListShell>
  );
}

function OperationsListFilteredEmpty() {
  return (
    <ListShell breadcrumb={['Masters', 'Operation masters']} sidebarActive="mast"
      title="Operation masters" sub="13 operations · 12 active"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New operation</Button>}
      searchPlaceholder="screen printing"
      filterChips={<><FilterChip label="All" count={13} /><FilterChip label="Embroidery" count={3} active /></>}>
      <FilteredEmptyState query="screen printing" />
    </ListShell>
  );
}

/* ─────────────────────────────────────────────────────────────
   Create dialog — operation_type radio group, default duration,
   optional cost-centre picker.
───────────────────────────────────────────────────────────── */
function OpTypeRadioGroup({ value, error }) {
  const types = ['WEAVING', 'DYEING', 'EMBROIDERY', 'STITCHING', 'QC', 'PACKING', 'OTHER'];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
      {types.map(t => {
        const tok = OP_TYPE_TOK[t];
        const selected = t === value;
        return (
          <div key={t} style={{
            border: '1px solid ' + (selected ? tok.accent : error ? 'var(--danger)' : 'var(--border-default)'),
            background: selected ? tok.bg : 'var(--bg-surface)',
            borderRadius: 6, padding: '10px 12px', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 8,
            boxShadow: selected ? `0 0 0 3px ${tok.bg}` : 'none',
          }}>
            <span style={{
              width: 16, height: 16, borderRadius: '50%',
              border: '1.5px solid ' + (selected ? tok.accent : 'var(--border-strong)'),
              background: 'var(--bg-surface)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              {selected && <span style={{ width: 8, height: 8, borderRadius: '50%', background: tok.accent }} />}
            </span>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: tok.accent }} />
            <span style={{ fontSize: 12.5, fontWeight: selected ? 600 : 500, color: selected ? tok.fg : 'var(--text-primary)' }}>{tok.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function OperationCreateDialog({ state = 'default' }) {
  const validation = state === 'validation';
  const loading = state === 'loading';
  const showToast = state === 'success';

  const v = {
    default:    { code: 'OP-EMB-MKS', name: 'Hand Embroidery — Mukaish', type: 'EMBROIDERY', dur: '480', cc: 'CC-KAR-RSD', ccName: 'Karigar embroidery — Rashid Tailors' },
    validation: { code: '',           name: 'Hand Em',                   type: null,         dur: '480', cc: '', ccName: '' },
    loading:    { code: 'OP-EMB-MKS', name: 'Hand Embroidery — Mukaish', type: 'EMBROIDERY', dur: '480', cc: 'CC-KAR-RSD', ccName: 'Karigar embroidery — Rashid Tailors' },
    success:    { code: 'OP-EMB-MKS', name: 'Hand Embroidery — Mukaish', type: 'EMBROIDERY', dur: '480', cc: 'CC-KAR-RSD', ccName: 'Karigar embroidery — Rashid Tailors' },
  }[state] || { code: 'OP-EMB-MKS', name: 'Hand Embroidery — Mukaish', type: 'EMBROIDERY', dur: '480', cc: 'CC-KAR-RSD', ccName: 'Karigar embroidery — Rashid Tailors' };

  return (
    <div style={{ position: 'relative' }}>
      <div style={{ background: 'rgba(20,20,18,0.32)', borderRadius: 8, padding: 32, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Dialog720
          title="New operation master"
          sub="A reusable manufacturing step. Use it in routings across designs."
          error={validation ? "Code is required. Name must be at least 3 characters. Pick an operation type." : null}
          loading={loading}
          footer={dialogFooter({ disabled: validation, loading, submitLabel: 'Create operation' })}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
              <Field label="Code" required state={validation ? 'error' : 'default'} error={validation ? 'Required' : null} hint={!validation ? 'e.g. OP-EMB-MKS' : null}>
                <Input value={v.code} state={validation ? 'error' : 'default'} />
              </Field>
              <Field label="Name" required state={validation ? 'error' : 'default'} error={validation ? 'Must be at least 3 characters' : null}>
                <Input value={v.name} state={validation ? 'error' : 'default'} />
              </Field>
            </div>

            <Field label="Operation type" required
              state={validation ? 'error' : 'default'}
              error={validation ? 'Choose one — drives the kanban column + pill colour' : null}
              hint={!validation ? 'Drives kanban column + pill colour for lots at this step' : null}>
              <OpTypeRadioGroup value={v.type} error={validation && !v.type} />
            </Field>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
              <Field label="Default duration"
                hint="Used to forecast cycle time. Editable per MO.">
                <Input value={v.dur} suffix="minutes" />
              </Field>
              <Field label="Cost centre"
                hint="Optional. Used to attribute labour cost in MO rollup.">
                <TypeaheadField value={v.ccName} placeholder="Search cost centres…" />
              </Field>
            </div>

            <div style={{
              padding: 12, background: 'var(--bg-sunken)', borderRadius: 6,
              border: '1px solid var(--border-subtle)',
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', flexShrink: 0 }}>Preview</span>
              {v.type ? <OpTypePill type={v.type} size="md" /> : <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Pick a type to preview the kanban pill</span>}
              <span style={{ flex: 1 }} />
              {v.type && <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
                Appears as <strong style={{ color: 'var(--text-primary)' }}>{OP_TYPE_TOK[v.type]?.label}</strong> in the pipeline kanban
              </span>}
            </div>
          </div>
        </Dialog720>
      </div>
      {showToast && <SuccessToast message='Operation "Hand Embroidery — Mukaish" created · OP-EMB-MKS' />}
    </div>
  );
}

/* Reuse dialogFooter from phase6-designs scope */
function dialogFooter({ disabled, loading, submitLabel = 'Create', onCancel, onSubmit }) {
  return <>
    <span style={{ flex: 1 }} />
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

Object.assign(window, {
  OperationsListFull, OperationsListLoading, OperationsListError, OperationsListEmpty, OperationsListFilteredEmpty,
  OperationCreateDialog,
});
