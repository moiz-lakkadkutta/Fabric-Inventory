// phase6-boms.jsx — Deliverable 5: BOM list + 3-tab create wizard.
// Wizard tabs: (a) Design & version, (b) Lines, (c) Review & activate.
// Lines tab has TWO variations: 'dense' (spreadsheet-feel) and 'editorial' (wizard-feel).

const { useState: useStateB } = React;

/* ─────────────────────────────────────────────────────────────
   BOM list — groups rows by design, shows version chip + Active pill.
───────────────────────────────────────────────────────────── */
const BOM_COLUMNS = [
  { key: 'design',  label: 'Design',     skelW: 200 },
  { key: 'ver',     label: 'Version',    align: 'right', skelW: 30, width: 100 },
  { key: 'lines',   label: 'Lines',      align: 'right', skelW: 30, width: 80 },
  { key: 'cost',    label: 'Cost / unit', align: 'right', skelW: 80, width: 140 },
  { key: 'active',  label: 'Active',     skelW: 60, width: 100 },
  { key: 'updated', label: 'Updated',    skelW: 90 },
  { key: 'by',      label: 'By',         skelW: 70 },
  { key: 'a',       label: '',           width: 36 },
];

function VersionChip({ ver, active }) {
  return (
    <span className="mono" style={{
      display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 8px',
      background: active ? 'var(--accent-subtle)' : 'var(--bg-sunken)',
      color: active ? 'var(--accent)' : 'var(--text-secondary)',
      borderRadius: 4, fontSize: 11.5, fontWeight: 700,
      border: '1px solid ' + (active ? 'transparent' : 'var(--border-subtle)'),
    }}>v{ver}</span>
  );
}

function BomsListFull() {
  // Group by design
  const designs = [...new Set(BOMS.map(b => b.design))];
  const grouped = designs.map(d => ({ d, name: BOMS.find(b => b.design === d).dname, versions: BOMS.filter(b => b.design === d) }));

  return (
    <ListShell
      breadcrumb={['Manufacturing', 'Bills of materials']}
      sidebarActive="mfg"
      title="Bills of materials"
      sub={`${BOMS.length} BOMs across ${designs.length} designs · ${BOMS.filter(b => b.active).length} active`}
      secondaryCta={<Button variant="secondary" size="sm" icon="download">Export</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus">New BOM</Button>}
      searchPlaceholder="Search by design code, name, item…"
      filterChips={<>
        <FilterChip label="All" active count={BOMS.length} />
        <FilterChip label="Active versions" count={BOMS.filter(b => b.active).length} />
        <FilterChip label="Has older versions" count={designs.filter(d => BOMS.filter(b => b.design === d).length > 1).length} />
        <FilterChip label="Single-version designs" count={designs.filter(d => BOMS.filter(b => b.design === d).length === 1).length} />
      </>}
      bottomMeta={<>Grouped by <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>Design</span></>}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            {BOM_COLUMNS.map(c => <th key={c.key} style={{...thL, ...(c.align === 'right' ? { textAlign: 'right' } : null), ...(c.width ? { width: c.width } : null)}}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {grouped.map((g, gi) => (
            <React.Fragment key={g.d}>
              <tr style={{ background: 'var(--bg-sunken)' }}>
                <td colSpan={BOM_COLUMNS.length} style={{
                  padding: '8px 14px', borderBottom: '1px solid var(--border-default)',
                  borderTop: gi === 0 ? 'none' : '1px solid var(--border-default)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="mono" style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700 }}>{g.d}</span>
                    <span style={{ fontSize: 12.5, fontWeight: 600 }}>{g.name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>· {g.versions.length} version{g.versions.length > 1 ? 's' : ''}</span>
                  </div>
                </td>
              </tr>
              {g.versions.map((r, i) => (
                <tr key={`${r.design}-v${r.ver}`} style={{ opacity: r.active ? 1 : 0.62 }}>
                  <td style={{...tdL, paddingLeft: 28, color: 'var(--text-secondary)' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      <Icon name="corner-down" size={12} color="var(--text-tertiary)" />
                      <span style={{ fontWeight: r.active ? 500 : 400 }}>{r.dname}</span>
                    </span>
                  </td>
                  <td style={{...tdL, textAlign: 'right' }}><VersionChip ver={r.ver} active={r.active} /></td>
                  <td className="num" style={{...tdL, textAlign: 'right', color: 'var(--text-secondary)' }}>{r.lines}</td>
                  <td className="num" style={{...tdL, textAlign: 'right', fontWeight: 500 }}>{inrRs(r.cost)}</td>
                  <td style={tdL}>{r.active ? <Pill kind="paid">Active</Pill> : <Pill kind="scrap">Superseded</Pill>}</td>
                  <td style={{...tdL, color: 'var(--text-secondary)', fontSize: 12.5 }}>{r.updated}</td>
                  <td style={{...tdL, color: 'var(--text-secondary)', fontSize: 12.5 }}>{r.by}</td>
                  <td style={tdL}><button style={bomIcon} aria-label="More"><Icon name="menu-more" size={14} color="var(--text-tertiary)" /></button></td>
                </tr>
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </ListShell>
  );
}

const bomIcon = {
  width: 28, height: 28, padding: 0, background: 'transparent', border: 'none',
  borderRadius: 4, cursor: 'pointer', color: 'var(--text-tertiary)',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
};

function BomsListLoading() {
  return (
    <ListShell breadcrumb={['Manufacturing', 'Bills of materials']} sidebarActive="mfg"
      title="Bills of materials" sub="Loading…"
      primaryCta={<Button variant="primary" size="sm" icon="plus" state="disabled">New BOM</Button>}
      searchPlaceholder="Search by design code, name, item…"
      filterChips={<><FilterChip label="All" /><FilterChip label="Active versions" /></>}>
      <LoadingSkeletonRows columns={BOM_COLUMNS} count={6} />
    </ListShell>
  );
}

function BomsListError() {
  return (
    <ListShell breadcrumb={['Manufacturing', 'Bills of materials']} sidebarActive="mfg"
      title="Bills of materials" sub="Couldn't load BOMs"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New BOM</Button>}>
      <ErrorBanner message="GET /api/v1/manufacturing/boms returned 503 — service unavailable." />
    </ListShell>
  );
}

function BomsListEmpty() {
  return (
    <ListShell breadcrumb={['Manufacturing', 'Bills of materials']} sidebarActive="mfg"
      title="Bills of materials" sub="No BOMs yet"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New BOM</Button>}>
      <EmptyState icon="list-checks" title="Build your first bill of materials"
        sub="A BOM is the recipe of raw materials per finished unit, versioned per design. Only the active version is consumed by Manufacturing Orders."
        cta={<Button variant="primary" size="md" icon="plus">New BOM</Button>} />
    </ListShell>
  );
}

function BomsListFilteredEmpty() {
  return (
    <ListShell breadcrumb={['Manufacturing', 'Bills of materials']} sidebarActive="mfg"
      title="Bills of materials" sub="10 BOMs across 6 designs · 6 active"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New BOM</Button>}
      searchPlaceholder="palazzo"
      filterChips={<><FilterChip label="All" count={10} /><FilterChip label="Active versions" count={6} active /></>}>
      <FilteredEmptyState query="palazzo" />
    </ListShell>
  );
}

/* ─────────────────────────────────────────────────────────────
   BOM Create wizard — tab A: Design & version
───────────────────────────────────────────────────────────── */
function BomWizardTabA() {
  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '28px 32px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Design & version</h2>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          Pick which design this BOM belongs to. Version auto-bumps from the existing active version.
        </div>
      </div>

      <Field label="Design" required hint="The finished product this BOM produces">
        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ flex: 1 }}>
            <TypeaheadField value="Anarkali Pink Embroidered" placeholder="Search designs…" />
          </div>
        </div>
        <div style={{
          marginTop: 8, padding: '10px 12px', background: 'var(--accent-subtle)',
          border: '1px solid var(--accent)', borderRadius: 6,
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <Icon name="package" size={14} color="var(--accent)" />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--accent)' }}>DSN-ANK-PNK · Anarkali Pink Embroidered</div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 1 }}>Finished item · FIN-ANK-PNK · Active routing v2 attached</div>
          </div>
        </div>
      </Field>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <Field label="Version" hint="Auto-incremented">
          <Input value="4" suffix={<span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>previous v3 active</span>} />
        </Field>
        <Field label="Effective from" hint="Used by MO scheduler">
          <Input value="27 Apr 2026" suffix={<Icon name="calendar" size={14} color="var(--text-tertiary)" />} />
        </Field>
      </div>

      <div style={{
        padding: '14px 16px', borderRadius: 8,
        background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <input type="checkbox" defaultChecked style={{ marginTop: 3, accentColor: 'var(--accent)' }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>Clone lines from previous active version (v3)</div>
            <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
              Pre-fills the Lines tab with the 7 lines from v3. You can edit, add, or remove rows before activating.
            </div>
          </div>
        </div>
      </div>

      <div style={{ padding: 12, borderRadius: 6, background: 'var(--bg-sunken)', display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <Icon name="info" size={14} color="var(--text-secondary)" />
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          When you activate v4 in the final step, <strong>v3 will be marked superseded</strong>. In-flight MOs continue to consume v3 lines until they finish; new MOs pick up v4.
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   BOM Create wizard — tab B: LINES (dense variation)
   Spreadsheet-feel: tight rows, inline editing, sticky totals.
───────────────────────────────────────────────────────────── */
function BomLinesDense() {
  const lines = BOM_LINES_ANARKALI;
  const totalCost = lines.reduce((s, l) => {
    const effQty = l.qty * (1 + l.scrap / 100);
    return s + effQty * l.cost;
  }, 0);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '20px 32px 12px', display: 'flex', alignItems: 'center', gap: 14, borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Lines — raw inputs per finished unit</h2>
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 2 }}>
            {lines.length} lines · 1 set of Anarkali Pink Embroidered · cost per finished unit updates live
          </div>
        </div>
        <Button variant="secondary" size="sm" icon="upload">Paste from sheet</Button>
        <Button variant="secondary" size="sm" icon="plus">Add line</Button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '0 32px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              <th style={{...thLDense, width: 36 }}>#</th>
              <th style={{...thLDense}}>Item</th>
              <th style={{...thLDense, textAlign: 'right', width: 110 }}>Qty / unit</th>
              <th style={{...thLDense, width: 70 }}>UoM</th>
              <th style={{...thLDense, textAlign: 'right', width: 100 }}>Scrap %</th>
              <th style={{...thLDense, textAlign: 'right', width: 120 }}>Std cost ₹/UoM</th>
              <th style={{...thLDense, textAlign: 'right', width: 130 }}>Line cost ₹</th>
              <th style={{...thLDense, width: 36 }}></th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => {
              const effQty = l.qty * (1 + l.scrap / 100);
              const lineCost = effQty * l.cost;
              return (
                <tr key={l.item} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{...tdDense, color: 'var(--text-tertiary)', fontSize: 11 }}>{i + 1}</td>
                  <td style={tdDense}>
                    <div style={{
                      height: 30, padding: '0 10px', borderRadius: 4,
                      border: '1px solid var(--border-subtle)',
                      background: 'var(--bg-surface)',
                      display: 'flex', alignItems: 'center', gap: 8,
                    }}>
                      <span style={{ fontWeight: 500 }}>{l.name}</span>
                      <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>{l.item}</span>
                    </div>
                  </td>
                  <td style={{...tdDense, textAlign: 'right' }}>
                    <DenseCell value={l.qty} align="right" mono />
                  </td>
                  <td style={tdDense}><DenseCell value={l.uom} muted /></td>
                  <td style={{...tdDense, textAlign: 'right' }}>
                    <DenseCell value={l.scrap + '%'} align="right" mono />
                  </td>
                  <td className="num" style={{...tdDense, textAlign: 'right', color: 'var(--text-secondary)' }}>{l.cost.toLocaleString('en-IN')}</td>
                  <td className="num" style={{...tdDense, textAlign: 'right', fontWeight: 600 }}>{lineCost.toFixed(2).replace(/\B(?=(\d{2})+(?!\d))/g, ',')}</td>
                  <td style={{...tdDense, textAlign: 'center' }}>
                    <button style={denseDel} aria-label="Remove"><Icon name="x" size={12} /></button>
                  </td>
                </tr>
              );
            })}
            {/* Add-row affordance */}
            <tr>
              <td colSpan={8} style={{ padding: '8px 0' }}>
                <button style={{
                  width: '100%', padding: '8px 12px', textAlign: 'left',
                  background: 'transparent', border: '1px dashed var(--border-default)', borderRadius: 4,
                  fontSize: 12, color: 'var(--text-tertiary)', cursor: 'pointer',
                }}>+ Add line · ⌘N</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Sticky totals strip */}
      <div style={{
        padding: '12px 32px', borderTop: '1px solid var(--border-default)',
        background: 'var(--bg-sunken)',
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16,
      }}>
        <RollupStat label="Lines" value={lines.length} />
        <RollupStat label="Material before scrap" value={inrRs(lines.reduce((s, l) => s + l.qty * l.cost, 0))} sub="per finished unit" />
        <RollupStat label="Scrap allowance" value={inrRs(lines.reduce((s, l) => s + (l.qty * l.scrap / 100) * l.cost, 0))} sub="weighted average 4.6%" />
        <RollupStat label="Total raw cost / unit" value={inrRs(totalCost)} hero />
      </div>
    </div>
  );
}

const thLDense = { fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '8px 10px', textAlign: 'left', whiteSpace: 'nowrap', background: 'var(--bg-sunken)', borderBottom: '1px solid var(--border-default)', position: 'sticky', top: 0 };
const tdDense = { padding: '6px 8px', verticalAlign: 'middle' };
const denseDel = {
  width: 24, height: 24, padding: 0,
  background: 'transparent', border: 'none', borderRadius: 4, cursor: 'pointer',
  color: 'var(--text-tertiary)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
};

function DenseCell({ value, align, mono, muted }) {
  return (
    <div style={{
      height: 30, padding: '0 10px', borderRadius: 4,
      border: '1px solid var(--border-subtle)',
      background: 'var(--bg-surface)',
      display: 'flex', alignItems: 'center',
      justifyContent: align === 'right' ? 'flex-end' : 'flex-start',
      color: muted ? 'var(--text-tertiary)' : 'var(--text-primary)',
      fontFamily: mono ? 'var(--font-num)' : 'inherit',
      fontVariantNumeric: 'tabular-nums', fontSize: 12.5,
    }}>{value}</div>
  );
}

function RollupStat({ label, value, sub, hero }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
      <div className="num" style={{
        fontSize: hero ? 22 : 15, fontWeight: hero ? 700 : 600,
        marginTop: hero ? 2 : 4, letterSpacing: hero ? '-0.012em' : 0,
        color: hero ? 'var(--accent)' : 'var(--text-primary)',
      }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   BOM Lines tab — EDITORIAL variation
   Each line is a card with full breathing room, qty + scrap stepper,
   and a per-line cost preview. Right rail shows the live rollup.
───────────────────────────────────────────────────────────── */
function BomLinesEditorial() {
  const lines = BOM_LINES_ANARKALI;
  const totalCost = lines.reduce((s, l) => s + l.qty * (1 + l.scrap / 100) * l.cost, 0);
  return (
    <div style={{ height: '100%', display: 'grid', gridTemplateColumns: '1fr 320px', minHeight: 0 }}>
      {/* Left — line cards */}
      <div style={{ overflow: 'auto', padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Lines — raw inputs per finished unit</h2>
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
            Build the recipe for one set of Anarkali Pink Embroidered. Add a line per material, set quantity per finished unit, and account for scrap.
          </div>
        </div>

        {lines.map((l, i) => {
          const effQty = l.qty * (1 + l.scrap / 100);
          const lineCost = effQty * l.cost;
          return (
            <div key={l.item} style={{
              background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
              borderRadius: 8, padding: 14,
              display: 'grid', gridTemplateColumns: '24px 1fr 160px 160px 130px 28px', gap: 14, alignItems: 'center',
            }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-tertiary)' }}>{String(i + 1).padStart(2, '0')}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>{l.name}</div>
                <div style={{ display: 'flex', gap: 10, marginTop: 3 }}>
                  <span className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{l.item}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>· std cost {inrRs(l.cost)}/{l.uom}</span>
                </div>
              </div>
              <Field label="Qty / unit">
                <Input value={`${l.qty} ${l.uom}`} />
              </Field>
              <Field label="Scrap allowance">
                <Input value={`${l.scrap}%`} suffix={<span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>= {effQty.toFixed(2)} {l.uom}</span>} />
              </Field>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Line cost</div>
                <div className="num" style={{ fontSize: 16, fontWeight: 700, marginTop: 2 }}>{inrRs(lineCost, { forceDecimal: true })}</div>
              </div>
              <button style={{
                width: 28, height: 28, background: 'transparent', border: 'none', borderRadius: 4,
                cursor: 'pointer', color: 'var(--text-tertiary)',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              }} aria-label="Remove"><Icon name="x" size={14} /></button>
            </div>
          );
        })}

        <button style={{
          padding: '14px 16px', textAlign: 'center', cursor: 'pointer',
          background: 'transparent', border: '1.5px dashed var(--border-default)', borderRadius: 8,
          fontSize: 13, color: 'var(--text-secondary)', fontWeight: 500,
        }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Icon name="plus" size={14} color="var(--text-secondary)" /> Add a material line
          </span>
        </button>
      </div>

      {/* Right rail — live rollup */}
      <div style={{ borderLeft: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', padding: 24, overflow: 'auto' }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Total raw cost per finished unit</div>
        <div className="num" style={{ fontSize: 32, fontWeight: 700, marginTop: 8, letterSpacing: '-0.015em', color: 'var(--accent)' }}>{inrRs(totalCost, { forceDecimal: true })}</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 4 }}>versus v3 active · {inrRs(1740)} (+{((totalCost - 1740) / 1740 * 100).toFixed(1)}%)</div>

        <div style={{ height: 1, background: 'var(--border-subtle)', margin: '20px 0' }} />

        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 12 }}>Composition</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {lines.slice(0, 6).map((l, i) => {
            const lc = l.qty * (1 + l.scrap / 100) * l.cost;
            const pct = lc / totalCost;
            return (
              <div key={i}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                  <span style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 170 }}>{l.name}</span>
                  <span className="num" style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{(pct * 100).toFixed(0)}%</span>
                </div>
                <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-sunken)', overflow: 'hidden' }}>
                  <div style={{ width: `${pct * 100}%`, height: '100%', background: i === 0 ? 'var(--accent)' : i === 1 ? 'var(--warning)' : 'var(--info)' }} />
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ height: 1, background: 'var(--border-subtle)', margin: '20px 0' }} />

        <div style={{ padding: 12, borderRadius: 6, background: 'var(--bg-sunken)' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>Implied MO cost</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            For a typical MO of <strong>20 sets</strong>, this BOM books <strong className="num">{inrRs(totalCost * 20)}</strong> in raw material consumption before labour.
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   BOM Create wizard — tab C: Review & activate (diff vs current active)
───────────────────────────────────────────────────────────── */
function BomWizardTabC() {
  // v3 → v4 diff
  const diff = [
    { kind: 'unchanged', name: 'Silk Georgette 60GSM',  old: '3.2 m · 4% scrap', new: '3.2 m · 4% scrap' },
    { kind: 'unchanged', name: 'Cotton Voile 60s',       old: '2.4 m · 3% scrap', new: '2.4 m · 3% scrap' },
    { kind: 'changed',   name: 'Zari Thread Gold',       old: '0.25 spl · 5%',    new: '0.30 spl · 6%' },
    { kind: 'changed',   name: 'Stone Work Pkt',         old: '0.30 pkt · 6%',    new: '0.40 pkt · 8%' },
    { kind: 'added',     name: 'Sequins Silver',         old: null,               new: '0.20 pkt · 5%' },
    { kind: 'unchanged', name: 'Cotton Lace 1cm Ivory',  old: '1.8 rl · 2%',      new: '1.8 rl · 2%' },
    { kind: 'unchanged', name: 'Fall hooks metallic',    old: '4 pc · 5%',        new: '4 pc · 5%' },
    { kind: 'removed',   name: 'Wooden buttons natural', old: '2 pc · 5%',        new: null },
  ];
  const added = diff.filter(d => d.kind === 'added').length;
  const removed = diff.filter(d => d.kind === 'removed').length;
  const changed = diff.filter(d => d.kind === 'changed').length;

  return (
    <div style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Review & activate</h2>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          Compare v4 against the current active v3. Activating supersedes v3 for new MOs.
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <Stat label="Lines" value="7" sub="was 7 in v3 (one added, one removed)" />
        <Stat label="Added" value={added} sub="new materials" tone="accent" />
        <Stat label="Changed" value={changed} sub="qty or scrap edited" tone="warning" />
        <Stat label="Removed" value={removed} sub="dropped from recipe" tone="danger" />
      </div>

      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-sunken)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Line diff</span>
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>v3 active · {`→`} · v4 proposed</span>
        </div>
        {diff.map((d, i) => (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '90px 1fr 1fr 1fr', gap: 12,
            padding: '10px 14px', alignItems: 'center',
            borderBottom: i === diff.length - 1 ? 'none' : '1px solid var(--border-subtle)',
            background: d.kind === 'added' ? '#F2F8F4' : d.kind === 'removed' ? '#FBEDE6' : d.kind === 'changed' ? '#FBF6E9' : 'transparent',
          }}>
            <DiffBadge kind={d.kind} />
            <span style={{ fontSize: 13, fontWeight: 500 }}>{d.name}</span>
            <span style={{ fontSize: 12, color: 'var(--text-tertiary)', fontFamily: d.old ? 'var(--font-num)' : 'inherit', textDecoration: d.kind === 'removed' ? 'line-through' : 'none' }}>{d.old || '—'}</span>
            <span style={{ fontSize: 12, color: d.kind === 'removed' ? 'var(--text-tertiary)' : 'var(--text-primary)', fontFamily: d.new ? 'var(--font-num)' : 'inherit', fontWeight: d.kind === 'changed' || d.kind === 'added' ? 600 : 400 }}>{d.new || '—'}</span>
          </div>
        ))}
      </div>

      <div style={{
        padding: '14px 16px', borderRadius: 8,
        background: 'var(--accent-subtle)', border: '1px solid var(--accent)',
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <input type="checkbox" defaultChecked style={{ marginTop: 3, accentColor: 'var(--accent)' }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--accent)' }}>Set v4 as the active BOM for DSN-ANK-PNK</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
              v3 is automatically marked superseded. In-flight MOs continue to consume v3; new MOs pick up v4.
            </div>
          </div>
          <span className="num" style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent)', whiteSpace: 'nowrap' }}>
            New unit cost {inrRs(1885)} <span style={{ color: 'var(--text-tertiary)', fontWeight: 400 }}>was {inrRs(1740)}</span>
          </span>
        </div>
      </div>
    </div>
  );
}

function DiffBadge({ kind }) {
  const m = {
    added:     { fg: 'var(--success-text)', bg: 'var(--success-subtle)', label: '+ Added' },
    removed:   { fg: 'var(--danger-text)',  bg: 'var(--danger-subtle)',  label: '− Removed' },
    changed:   { fg: 'var(--warning-text)', bg: 'var(--warning-subtle)', label: '↻ Changed' },
    unchanged: { fg: 'var(--text-tertiary)', bg: 'transparent', label: 'Unchanged' },
  }[kind];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 20, padding: '0 7px',
      borderRadius: 3, background: m.bg, color: m.fg,
      fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
      border: kind === 'unchanged' ? '1px dashed var(--border-subtle)' : 'none',
    }}>{m.label}</span>
  );
}

function Stat({ label, value, sub, tone }) {
  const c = tone === 'accent' ? 'var(--accent)' : tone === 'warning' ? 'var(--warning-text)' : tone === 'danger' ? 'var(--danger-text)' : 'var(--text-primary)';
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, padding: 14 }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
      <div className="num" style={{ fontSize: 24, fontWeight: 700, marginTop: 4, color: c, letterSpacing: '-0.012em' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   BOM Wizard — composes the WizardShell with the three tabs.
   `linesVariant` toggles 'dense' vs 'editorial' for tab B.
   `wizardState`: 'default' | 'validation' | 'loading' | 'success'
───────────────────────────────────────────────────────────── */
function BomWizard({ activeStep = 'design', linesVariant = 'dense', wizardState = 'default' }) {
  const steps = [
    { key: 'design', label: 'Design & version', body: <BomWizardTabA /> },
    { key: 'lines',  label: 'Lines',            body: linesVariant === 'editorial' ? <BomLinesEditorial /> : <BomLinesDense /> },
    { key: 'review', label: 'Review & activate', body: <BomWizardTabC /> },
  ];
  const nextLabel = activeStep === 'review' ? 'Activate v4' : 'Next';
  return (
    <div style={{ position: 'relative', height: '100%' }}>
      <WizardShell
        breadcrumb={['Manufacturing', 'Bills of materials', 'New BOM']}
        sidebarActive="mfg"
        title="New BOM"
        subtitle="DSN-ANK-PNK · Anarkali Pink Embroidered · v4 (will supersede v3 on activate)"
        steps={steps}
        activeStep={activeStep}
        nextLabel={nextLabel}
        loading={wizardState === 'loading'}
        validationBanner={wizardState === 'validation' ? 'Line 3 (Zari Thread Gold) needs a qty greater than 0. Line 8 has an unknown UoM.' : null}
      />
      {wizardState === 'success' && <SuccessToast message='BOM v4 activated for Anarkali Pink Embroidered · 7 lines, ₹1,885/unit' />}
    </div>
  );
}

Object.assign(window, {
  BomsListFull, BomsListLoading, BomsListError, BomsListEmpty, BomsListFilteredEmpty,
  BomWizard, BomWizardTabA, BomLinesDense, BomLinesEditorial, BomWizardTabC,
});
