// phase6-routings.jsx — Deliverable 6: Routing list + 3-tab create wizard.
// Operations tab has TWO variations:
//   • 'editorial' = visual DAG canvas (rail + nodes + edges + cycle-error chip)
//   • 'dense'     = spreadsheet-feel sequence editor (rows + predecessor col)

const { useState: useStateR } = React;

/* ─────────────────────────────────────────────────────────────
   Routing list — grouped by design, mirrors BomsListFull
───────────────────────────────────────────────────────────── */
const RTG_COLUMNS = [
  { key: 'design',  label: 'Design',     skelW: 200 },
  { key: 'ver',     label: 'Version',    align: 'right', skelW: 30, width: 100 },
  { key: 'nodes',   label: 'Nodes',      align: 'right', skelW: 30, width: 80 },
  { key: 'ops',     label: 'Operations sequence', skelW: 280 },
  { key: 'active',  label: 'Active',     skelW: 60, width: 100 },
  { key: 'updated', label: 'Updated',    skelW: 90 },
  { key: 'by',      label: 'By',         skelW: 70 },
  { key: 'a',       label: '',           width: 36 },
];

function VersionChipR({ ver, active }) {
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

function RoutingsListFull() {
  const designs = [...new Set(ROUTINGS.map(r => r.design))];
  const grouped = designs.map(d => ({
    d, name: ROUTINGS.find(b => b.design === d).dname,
    versions: ROUTINGS.filter(b => b.design === d),
  }));

  return (
    <ListShell
      breadcrumb={['Manufacturing', 'Routings']} sidebarActive="mfg"
      title="Routings"
      sub={`${ROUTINGS.length} routings across ${designs.length} designs · ${ROUTINGS.filter(r => r.active).length} active · ${ROUTINGS.reduce((s, r) => s + r.nodes, 0)} operation nodes wired`}
      secondaryCta={<Button variant="secondary" size="sm" icon="download">Export</Button>}
      primaryCta={<Button variant="primary" size="sm" icon="plus">New routing</Button>}
      searchPlaceholder="Search by design, operation…"
      filterChips={<>
        <FilterChip label="All" active count={ROUTINGS.length} />
        <FilterChip label="Active versions" count={ROUTINGS.filter(r => r.active).length} />
        <FilterChip label="Uses Karigar"    count={ROUTINGS.filter(r => r.ops.join(' ').toLowerCase().includes('embroidery')).length} />
        <FilterChip label="Single-step"     count={ROUTINGS.filter(r => r.nodes <= 4).length} />
      </>}
      bottomMeta={<>Grouped by <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>Design</span></>}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            {RTG_COLUMNS.map(c => <th key={c.key} style={{...thL, ...(c.align === 'right' ? { textAlign: 'right' } : null), ...(c.width ? { width: c.width } : null)}}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {grouped.map((g, gi) => (
            <React.Fragment key={g.d}>
              <tr style={{ background: 'var(--bg-sunken)' }}>
                <td colSpan={RTG_COLUMNS.length} style={{
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
              {g.versions.map((r) => (
                <tr key={`${r.design}-v${r.ver}`} style={{ opacity: r.active ? 1 : 0.62 }}>
                  <td style={{...tdL, paddingLeft: 28, color: 'var(--text-secondary)' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      <Icon name="corner-down" size={12} color="var(--text-tertiary)" />
                      <span style={{ fontWeight: r.active ? 500 : 400 }}>{r.dname}</span>
                    </span>
                  </td>
                  <td style={{...tdL, textAlign: 'right' }}><VersionChipR ver={r.ver} active={r.active} /></td>
                  <td className="num" style={{...tdL, textAlign: 'right', color: 'var(--text-secondary)' }}>{r.nodes}</td>
                  <td style={tdL}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                      {r.ops.map((o, j) => (
                        <React.Fragment key={j}>
                          <span style={{
                            fontSize: 11, padding: '2px 7px', borderRadius: 3,
                            background: 'var(--bg-sunken)', color: 'var(--text-secondary)',
                            border: '1px solid var(--border-subtle)',
                            whiteSpace: 'nowrap',
                          }}>{o}</span>
                          {j < r.ops.length - 1 && <Icon name="chevron-right" size={10} color="var(--text-tertiary)" />}
                        </React.Fragment>
                      ))}
                    </div>
                  </td>
                  <td style={tdL}>{r.active ? <Pill kind="paid">Active</Pill> : <Pill kind="scrap">Superseded</Pill>}</td>
                  <td style={{...tdL, color: 'var(--text-secondary)', fontSize: 12.5 }}>{r.updated}</td>
                  <td style={{...tdL, color: 'var(--text-secondary)', fontSize: 12.5 }}>{r.by}</td>
                  <td style={tdL}>
                    <button style={rtgIcon} aria-label="More"><Icon name="menu-more" size={14} color="var(--text-tertiary)" /></button>
                  </td>
                </tr>
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </ListShell>
  );
}

const rtgIcon = {
  width: 28, height: 28, padding: 0, background: 'transparent', border: 'none',
  borderRadius: 4, cursor: 'pointer', color: 'var(--text-tertiary)',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
};

function RoutingsListLoading() {
  return (
    <ListShell breadcrumb={['Manufacturing', 'Routings']} sidebarActive="mfg"
      title="Routings" sub="Loading…"
      primaryCta={<Button variant="primary" size="sm" icon="plus" state="disabled">New routing</Button>}
      searchPlaceholder="Search by design, operation…"
      filterChips={<><FilterChip label="All" /><FilterChip label="Active" /></>}>
      <LoadingSkeletonRows columns={RTG_COLUMNS} count={6} />
    </ListShell>
  );
}

function RoutingsListError() {
  return (
    <ListShell breadcrumb={['Manufacturing', 'Routings']} sidebarActive="mfg"
      title="Routings" sub="Couldn't load routings"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New routing</Button>}>
      <ErrorBanner message="GET /api/v1/manufacturing/routings returned 503 — service unavailable." />
    </ListShell>
  );
}

function RoutingsListEmpty() {
  return (
    <ListShell breadcrumb={['Manufacturing', 'Routings']} sidebarActive="mfg"
      title="Routings" sub="No routings yet"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New routing</Button>}>
      <EmptyState icon="cog" title="Wire your first routing"
        sub="A routing is the DAG of operations that produces a design — Cut → Embroidery → Stitch → QC → Pack. MOs walk this graph to assign work in the pipeline kanban."
        cta={<Button variant="primary" size="md" icon="plus">New routing</Button>} />
    </ListShell>
  );
}

function RoutingsListFilteredEmpty() {
  return (
    <ListShell breadcrumb={['Manufacturing', 'Routings']} sidebarActive="mfg"
      title="Routings" sub="7 routings across 6 designs · 6 active"
      primaryCta={<Button variant="primary" size="sm" icon="plus">New routing</Button>}
      searchPlaceholder="laser cut"
      filterChips={<><FilterChip label="All" count={7} /><FilterChip label="Active" count={6} active /></>}>
      <FilteredEmptyState query="laser cut" />
    </ListShell>
  );
}

/* ─────────────────────────────────────────────────────────────
   Wizard tab A — Design & version (same shape as BOM tab A)
───────────────────────────────────────────────────────────── */
function RtgWizardTabA() {
  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '28px 32px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Design & version</h2>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          Pick the design this routing produces. Version auto-bumps from the existing active version.
        </div>
      </div>
      <Field label="Design" required hint="The finished product this routing produces">
        <TypeaheadField value="Lehenga Maroon Banarasi" placeholder="Search designs…" />
        <div style={{
          marginTop: 8, padding: '10px 12px', background: 'var(--accent-subtle)',
          border: '1px solid var(--accent)', borderRadius: 6,
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <Icon name="package" size={14} color="var(--accent)" />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--accent)' }}>DSN-LHG-MRN · Lehenga Maroon Banarasi</div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 1 }}>Active BOM v4 attached · 11 lines · ₹4,280/unit</div>
          </div>
        </div>
      </Field>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
        <Field label="Routing name">
          <Input value="Lehenga Maroon — Festive '26" />
        </Field>
        <Field label="Version" hint="Auto-incremented">
          <Input value="4" suffix={<span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>prev v3</span>} />
        </Field>
      </div>
      <div style={{
        padding: '14px 16px', borderRadius: 8,
        background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <input type="checkbox" defaultChecked style={{ marginTop: 3, accentColor: 'var(--accent)' }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>Clone graph from previous active version (v3)</div>
            <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
              Pre-fills the Operations canvas with the 8 nodes and 8 edges from v3. You can edit before activating.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   DAG sample for Lehenga Maroon
───────────────────────────────────────────────────────────── */
const DAG_NODES = [
  { id: 'n1', op: 'OP-DYE-VAT', name: 'Vat dyeing — indigo',     type: 'DYEING',     exec: 'KARIGAR',  col: 0, row: 1 },
  { id: 'n2', op: 'OP-CUT-STD', name: 'Cut to pattern',          type: 'STITCHING',  exec: 'IN_HOUSE', col: 1, row: 1 },
  { id: 'n3', op: 'OP-EMB-ZRD', name: 'Embroidery — Zardosi',    type: 'EMBROIDERY', exec: 'KARIGAR',  col: 2, row: 0 },
  { id: 'n4', op: 'OP-EMB-STN', name: 'Embroidery — Stone',      type: 'EMBROIDERY', exec: 'KARIGAR',  col: 2, row: 2 },
  { id: 'n5', op: 'OP-STC-MNL', name: 'Stitch — assembly',       type: 'STITCHING',  exec: 'IN_HOUSE', col: 3, row: 1 },
  { id: 'n6', op: 'OP-STC-FNS', name: 'Stitch — finishing',      type: 'STITCHING',  exec: 'IN_HOUSE', col: 4, row: 1 },
  { id: 'n7', op: 'OP-QC-VIS',  name: 'QC — visual',             type: 'QC',         exec: 'QC',       col: 5, row: 1 },
  { id: 'n8', op: 'OP-PCK-BX',  name: 'Box & label',             type: 'PACKING',    exec: 'IN_HOUSE', col: 6, row: 1 },
];
const DAG_EDGES = [
  { from: 'n1', to: 'n2', type: 'FS' },
  { from: 'n2', to: 'n3', type: 'FS' },
  { from: 'n2', to: 'n4', type: 'SS' },
  { from: 'n3', to: 'n5', type: 'FS' },
  { from: 'n4', to: 'n5', type: 'FS' },
  { from: 'n5', to: 'n6', type: 'FS' },
  { from: 'n6', to: 'n7', type: 'FS' },
  { from: 'n7', to: 'n8', type: 'FS' },
];
const CYCLE_EDGE = { from: 'n7', to: 'n3', type: 'FS', cycle: true };

function dagAccent(type) { return OP_TYPE_TOK[type]?.accent || '#9aa'; }
function dagBg(type)     { return OP_TYPE_TOK[type]?.bg     || '#eee'; }

/* ─────────────────────────────────────────────────────────────
   Wizard tab B — EDITORIAL: visual DAG editor
───────────────────────────────────────────────────────────── */
function RoutingOpsEditorial({ showCycle = false }) {
  const COL_W = 184, ROW_H = 116, PAD_X = 30, PAD_Y = 36;
  const NODE_W = 156, NODE_H = 80;
  const nodeX = (col) => PAD_X + col * COL_W;
  const nodeY = (row) => PAD_Y + row * ROW_H;
  const cx = (col) => nodeX(col) + NODE_W / 2;
  const cyForNode = (row) => nodeY(row) + NODE_H / 2;

  const nodeById = Object.fromEntries(DAG_NODES.map(n => [n.id, n]));
  const edges = showCycle ? [...DAG_EDGES, CYCLE_EDGE] : DAG_EDGES;

  const canvasW = nodeX(6) + NODE_W + PAD_X;
  const canvasH = nodeY(2) + NODE_H + PAD_Y;

  return (
    <div style={{ height: '100%', display: 'grid', gridTemplateColumns: '260px 1fr', minHeight: 0 }}>
      {/* LEFT RAIL — available operations */}
      <aside style={{ borderRight: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Drag onto canvas</div>
          <div style={{ marginTop: 8 }}>
            <Input placeholder="Search operations…" prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
          </div>
        </div>
        {OPERATION_MASTERS.filter(o => o.is_active).slice(0, 9).map(o => (
          <div key={o.code} draggable style={{
            padding: '10px 12px', borderRadius: 6,
            background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
            display: 'flex', alignItems: 'center', gap: 10, cursor: 'grab',
            boxShadow: 'var(--shadow-1)',
          }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: dagAccent(o.type), flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{o.name}</div>
              <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginTop: 1 }}>{o.code}</div>
            </div>
          </div>
        ))}
        <button style={{
          padding: '10px 12px', textAlign: 'center', cursor: 'pointer',
          background: 'transparent', border: '1.5px dashed var(--border-default)', borderRadius: 6,
          fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500,
        }}>+ New operation master</button>
      </aside>

      {/* CANVAS */}
      <div style={{ position: 'relative', overflow: 'auto', background: 'var(--bg-canvas)' }}>
        {/* Toolbar over canvas */}
        <div style={{
          position: 'sticky', top: 0, zIndex: 4,
          padding: '12px 24px', borderBottom: '1px solid var(--border-subtle)',
          background: 'rgba(252,250,245,0.94)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Operations</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>{DAG_NODES.length} nodes · {edges.length} edges · drag to move, click an edge to set FS/SS, hold ⇧ to draw an edge between nodes</div>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            <span style={pillLegend('IN_HOUSE')}><span style={pillDot('IN_HOUSE')} />In-house</span>
            <span style={pillLegend('KARIGAR')}><span style={pillDot('KARIGAR')} />Karigar</span>
            <span style={pillLegend('QC')}><span style={pillDot('QC')} />QC</span>
          </div>
          <Button variant="secondary" size="sm" icon="check-square">Validate DAG</Button>
        </div>

        {/* DAG canvas — pattern grid */}
        <div style={{
          position: 'relative', width: canvasW, height: canvasH,
          backgroundImage: 'radial-gradient(circle, #E0DCCF 1px, transparent 1px)',
          backgroundSize: '18px 18px', backgroundPosition: '8px 8px',
          margin: '20px 24px',
        }}>
          {/* Edges */}
          <svg width={canvasW} height={canvasH} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            <defs>
              <marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" fill="#7A766B" />
              </marker>
              <marker id="arrErr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" fill="var(--danger-text)" />
              </marker>
            </defs>
            {edges.map((e, i) => {
              const A = nodeById[e.from], B = nodeById[e.to];
              const x1 = nodeX(A.col) + NODE_W, y1 = cyForNode(A.row);
              const x2 = nodeX(B.col),          y2 = cyForNode(B.row);
              const mx = (x1 + x2) / 2;
              const d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2 - 4} ${y2}`;
              const isCycle = e.cycle;
              const isSS = e.type === 'SS';
              return (
                <g key={i}>
                  <path d={d} fill="none"
                    stroke={isCycle ? 'var(--danger-text)' : '#7A766B'}
                    strokeWidth={isCycle ? 2 : 1.5}
                    strokeDasharray={isSS ? '5 4' : isCycle ? '6 3' : 'none'}
                    markerEnd={`url(#${isCycle ? 'arrErr' : 'arr'})`} />
                  {(isSS || isCycle) && (
                    <g transform={`translate(${mx - 18}, ${(y1 + y2) / 2 - 10})`}>
                      <rect width={isCycle ? 76 : 38} height={20} rx={3}
                        fill={isCycle ? 'var(--danger-subtle)' : 'var(--bg-surface)'}
                        stroke={isCycle ? 'var(--danger-text)' : '#C8C3B2'} strokeWidth="1" />
                      <text x={isCycle ? 38 : 19} y={14} textAnchor="middle"
                        fontSize="10" fontWeight="700" letterSpacing="0.04em"
                        fill={isCycle ? 'var(--danger-text)' : 'var(--text-secondary)'}>
                        {isCycle ? 'CYCLE — REMOVE' : 'SS'}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>

          {/* Nodes */}
          {DAG_NODES.map(n => {
            const isProblem = showCycle && (n.id === 'n3' || n.id === 'n7');
            return (
              <div key={n.id} style={{
                position: 'absolute', left: nodeX(n.col), top: nodeY(n.row),
                width: NODE_W, height: NODE_H,
                background: 'var(--bg-surface)',
                border: '1.5px solid ' + (isProblem ? 'var(--danger-text)' : dagAccent(n.type)),
                borderRadius: 8, padding: 10,
                boxShadow: isProblem ? '0 0 0 3px var(--danger-subtle)' : 'var(--shadow-2)',
                display: 'flex', flexDirection: 'column', gap: 6, cursor: 'grab',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 6, height: 6, borderRadius: 2, background: dagAccent(n.type), flexShrink: 0 }} />
                  <span style={{ fontSize: 9.5, fontWeight: 700, color: dagAccent(n.type), letterSpacing: '0.05em', textTransform: 'uppercase' }}>{OP_TYPE_TOK[n.type]?.label}</span>
                  <span style={{ flex: 1 }} />
                  <span className="mono" style={{ fontSize: 9.5, color: 'var(--text-tertiary)' }}>{n.id}</span>
                </div>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.name}</div>
                <div style={{ marginTop: 'auto' }}>
                  <ExecutorPill kind={n.exec} />
                </div>

                {/* connection handles */}
                <span style={{
                  position: 'absolute', left: -5, top: NODE_H / 2 - 5,
                  width: 10, height: 10, borderRadius: '50%',
                  background: 'var(--bg-surface)', border: '1.5px solid ' + dagAccent(n.type),
                }} />
                <span style={{
                  position: 'absolute', right: -5, top: NODE_H / 2 - 5,
                  width: 10, height: 10, borderRadius: '50%',
                  background: dagAccent(n.type), border: '1.5px solid var(--bg-surface)',
                  boxShadow: '0 0 0 1px ' + dagAccent(n.type),
                }} />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function pillLegend(kind) {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
    background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
    borderRadius: 999, fontSize: 11.5, color: 'var(--text-secondary)',
  };
}
function pillDot(kind) {
  const c = kind === 'IN_HOUSE' ? 'var(--info-text)' : kind === 'KARIGAR' ? 'var(--warning-text)' : 'var(--success-text)';
  return { width: 8, height: 8, borderRadius: '50%', background: c, display: 'inline-block' };
}

/* ─────────────────────────────────────────────────────────────
   Wizard tab B — DENSE: spreadsheet sequence editor.
   Each operation is a row; predecessors set explicitly.
───────────────────────────────────────────────────────────── */
function RoutingOpsDense({ showCycle = false }) {
  const rows = DAG_NODES.map((n, i) => {
    const preds = DAG_EDGES.filter(e => e.to === n.id).map(e => ({ id: e.from, type: e.type }));
    if (showCycle && n.id === 'n3') preds.push({ id: 'n7', type: 'FS', cycle: true });
    return { ...n, seq: i + 1, preds };
  });

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '20px 32px 12px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Operations — sequence editor</h2>
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 2 }}>{rows.length} steps · use Predecessors col to wire dependencies · FS = finish-to-start, SS = start-to-start</div>
        </div>
        <Button variant="secondary" size="sm" icon="check-square">Validate DAG</Button>
        <Button variant="secondary" size="sm" icon="plus">Add step</Button>
      </div>

      {showCycle && (
        <div style={{
          margin: '12px 32px 0', padding: '10px 14px',
          background: 'var(--danger-subtle)', border: '1px solid #E5B3A8', borderRadius: 6,
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <Icon name="alert" size={14} color="var(--danger-text)" />
          <div style={{ fontSize: 12.5, color: 'var(--danger-text)', fontWeight: 500 }}>
            Cycle detected: step #3 lists step #7 as a predecessor, but step #7 also depends on step #3 (via #5 → #6). Remove one edge to break the cycle.
          </div>
        </div>
      )}

      <div style={{ flex: 1, overflow: 'auto', padding: '8px 32px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              <th style={{...thLDense2, width: 44 }}>Seq</th>
              <th style={{...thLDense2 }}>Operation</th>
              <th style={{...thLDense2, width: 130 }}>Type</th>
              <th style={{...thLDense2, width: 120 }}>Executor</th>
              <th style={{...thLDense2 }}>Predecessors</th>
              <th style={{...thLDense2, textAlign: 'right', width: 110 }}>Duration</th>
              <th style={{...thLDense2, width: 36 }}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const op = OPERATION_MASTERS.find(o => o.code === r.op);
              const hasCycle = r.preds.some(p => p.cycle);
              return (
                <tr key={r.id} style={{
                  borderBottom: '1px solid var(--border-subtle)',
                  background: hasCycle ? 'var(--danger-subtle)' : 'transparent',
                }}>
                  <td style={{...tdDense2, fontFamily: 'var(--font-num)', fontWeight: 700, color: 'var(--text-tertiary)' }}>{r.seq}</td>
                  <td style={tdDense2}>
                    <div style={{
                      height: 30, padding: '0 10px', borderRadius: 4,
                      border: '1px solid var(--border-subtle)', background: 'var(--bg-surface)',
                      display: 'flex', alignItems: 'center', gap: 8,
                    }}>
                      <span style={{ fontWeight: 500 }}>{r.name}</span>
                      <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>{r.op}</span>
                    </div>
                  </td>
                  <td style={tdDense2}><OpTypePill type={r.type} /></td>
                  <td style={tdDense2}><ExecutorPill kind={r.exec} /></td>
                  <td style={tdDense2}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                      {r.preds.length === 0
                        ? <span style={{ fontSize: 11, color: 'var(--text-tertiary)', fontStyle: 'italic' }}>start node</span>
                        : r.preds.map((p, i) => {
                            const predRow = rows.find(x => x.id === p.id);
                            return (
                              <span key={i} style={{
                                display: 'inline-flex', alignItems: 'center', gap: 4,
                                padding: '2px 7px', borderRadius: 3,
                                background: p.cycle ? 'var(--danger-subtle)' : 'var(--bg-sunken)',
                                color: p.cycle ? 'var(--danger-text)' : 'var(--text-secondary)',
                                border: '1px solid ' + (p.cycle ? 'var(--danger-text)' : 'var(--border-subtle)'),
                                fontSize: 11, fontWeight: 500,
                              }}>
                                <span className="mono" style={{ fontWeight: 700 }}>#{predRow?.seq}</span>
                                {p.type === 'SS' && <span style={{ fontSize: 9, fontWeight: 700, opacity: 0.6 }}>SS</span>}
                                {p.cycle && <Icon name="alert" size={10} color="var(--danger-text)" />}
                              </span>
                            );
                          })}
                      <button style={{
                        height: 22, padding: '0 6px', fontSize: 11,
                        border: '1px dashed var(--border-default)', background: 'transparent',
                        borderRadius: 3, color: 'var(--text-tertiary)', cursor: 'pointer',
                      }}>+ pred</button>
                    </div>
                  </td>
                  <td className="num" style={{...tdDense2, textAlign: 'right', color: 'var(--text-secondary)' }}>{op?.dur ? (op.dur < 60 ? `${op.dur} min` : `${Math.floor(op.dur / 60)}h ${op.dur % 60 || ''}`.trim()) : '—'}</td>
                  <td style={{...tdDense2, textAlign: 'center' }}>
                    <button style={denseDel2} aria-label="Remove"><Icon name="x" size={12} /></button>
                  </td>
                </tr>
              );
            })}
            <tr>
              <td colSpan={7} style={{ padding: '8px 0' }}>
                <button style={{
                  width: '100%', padding: '8px 12px', textAlign: 'left',
                  background: 'transparent', border: '1px dashed var(--border-default)', borderRadius: 4,
                  fontSize: 12, color: 'var(--text-tertiary)', cursor: 'pointer',
                }}>+ Add step · ⌘N</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div style={{
        padding: '12px 32px', borderTop: '1px solid var(--border-default)',
        background: 'var(--bg-sunken)',
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16,
      }}>
        <RollupStat2 label="Nodes" value={DAG_NODES.length} />
        <RollupStat2 label="Edges" value={DAG_EDGES.length + (showCycle ? 1 : 0)} />
        <RollupStat2 label="Total cycle time" value="29h 30m" sub="critical path" />
        <RollupStat2 label="Validation" value={showCycle ? '1 error' : 'Clean'} tone={showCycle ? 'danger' : 'success'} />
      </div>
    </div>
  );
}

const thLDense2 = { fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '8px 10px', textAlign: 'left', whiteSpace: 'nowrap', background: 'var(--bg-sunken)', borderBottom: '1px solid var(--border-default)' };
const tdDense2 = { padding: '6px 8px', verticalAlign: 'middle' };
const denseDel2 = { width: 24, height: 24, padding: 0, background: 'transparent', border: 'none', borderRadius: 4, cursor: 'pointer', color: 'var(--text-tertiary)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' };

function RollupStat2({ label, value, sub, tone }) {
  const c = tone === 'danger' ? 'var(--danger-text)' : tone === 'success' ? 'var(--success-text)' : 'var(--text-primary)';
  return (
    <div>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
      <div className="num" style={{ fontSize: 18, fontWeight: 700, marginTop: 2, color: c }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Wizard tab C — Review & activate (read-only snapshot)
───────────────────────────────────────────────────────────── */
function RtgWizardTabC() {
  return (
    <div style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Review & activate</h2>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          Read-only snapshot of v4 vs v3 active. Activating supersedes v3 for new MOs.
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <Stat2 label="Nodes" value={8} sub="was 7 in v3 (+1)" />
        <Stat2 label="Edges" value={8} sub="1 parallel start (SS)" />
        <Stat2 label="Critical path" value="29h 30m" sub="from Dye → Pack" tone="accent" />
        <Stat2 label="Karigar steps" value={3} sub="2 embroidery + 1 dye" tone="warning" />
      </div>

      {/* Read-only canvas thumbnail */}
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-sunken)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Graph snapshot</span>
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>read-only · v4</span>
        </div>
        <div style={{ height: 280, overflow: 'auto' }}>
          {/* mini DAG */}
          <RoutingMiniDag />
        </div>
      </div>

      <div style={{
        padding: '14px 16px', borderRadius: 8,
        background: 'var(--accent-subtle)', border: '1px solid var(--accent)',
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <input type="checkbox" defaultChecked style={{ marginTop: 3, accentColor: 'var(--accent)' }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--accent)' }}>Set v4 as the active routing for DSN-LHG-MRN</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
              v3 is automatically marked superseded. In-flight MOs continue to consume v3; new MOs pick up v4.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat2({ label, value, sub, tone }) {
  const c = tone === 'accent' ? 'var(--accent)' : tone === 'warning' ? 'var(--warning-text)' : tone === 'danger' ? 'var(--danger-text)' : 'var(--text-primary)';
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, padding: 14 }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
      <div className="num" style={{ fontSize: 22, fontWeight: 700, marginTop: 4, color: c, letterSpacing: '-0.012em' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/* Mini read-only DAG */
function RoutingMiniDag() {
  const COL_W = 130, ROW_H = 80, PAD_X = 18, PAD_Y = 20;
  const NW = 108, NH = 50;
  const x = c => PAD_X + c * COL_W, y = r => PAD_Y + r * ROW_H;
  const cy = r => y(r) + NH / 2;
  const nodeById = Object.fromEntries(DAG_NODES.map(n => [n.id, n]));
  const W = x(6) + NW + PAD_X, H = y(2) + NH + PAD_Y;
  return (
    <div style={{ position: 'relative', width: W, height: H, padding: 4 }}>
      <svg width={W} height={H} style={{ position: 'absolute', inset: 0 }}>
        <defs>
          <marker id="arrMini" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 z" fill="#7A766B" />
          </marker>
        </defs>
        {DAG_EDGES.map((e, i) => {
          const A = nodeById[e.from], B = nodeById[e.to];
          const x1 = x(A.col) + NW, y1 = cy(A.row), x2 = x(B.col), y2 = cy(B.row);
          const mx = (x1 + x2) / 2;
          return <path key={i} d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2 - 4} ${y2}`} fill="none" stroke="#7A766B" strokeWidth="1.2" strokeDasharray={e.type === 'SS' ? '4 3' : 'none'} markerEnd="url(#arrMini)" />;
        })}
      </svg>
      {DAG_NODES.map(n => (
        <div key={n.id} style={{
          position: 'absolute', left: x(n.col), top: y(n.row),
          width: NW, height: NH,
          background: 'var(--bg-surface)',
          border: '1.5px solid ' + dagAccent(n.type), borderRadius: 6,
          padding: '6px 8px', boxShadow: 'var(--shadow-1)',
        }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: dagAccent(n.type), letterSpacing: '0.04em', textTransform: 'uppercase' }}>{OP_TYPE_TOK[n.type]?.label}</div>
          <div style={{ fontSize: 11, fontWeight: 600, lineHeight: 1.2, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.name}</div>
        </div>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Routing wizard composer
───────────────────────────────────────────────────────────── */
function RoutingWizard({ activeStep = 'design', opsVariant = 'editorial', wizardState = 'default' }) {
  const showCycle = wizardState === 'validation' && activeStep === 'ops';
  const steps = [
    { key: 'design', label: 'Design & version', body: <RtgWizardTabA /> },
    { key: 'ops',    label: 'Operations',       body: opsVariant === 'dense' ? <RoutingOpsDense showCycle={showCycle} /> : <RoutingOpsEditorial showCycle={showCycle} /> },
    { key: 'review', label: 'Review & activate', body: <RtgWizardTabC /> },
  ];
  const nextLabel = activeStep === 'review' ? 'Activate v4' : 'Next';
  return (
    <div style={{ position: 'relative', height: '100%' }}>
      <WizardShell
        breadcrumb={['Manufacturing', 'Routings', 'New routing']}
        sidebarActive="mfg"
        title="New routing"
        subtitle="DSN-LHG-MRN · Lehenga Maroon Banarasi · v4 (will supersede v3 on activate)"
        steps={steps}
        activeStep={activeStep}
        nextLabel={nextLabel}
        loading={wizardState === 'loading'}
        validationBanner={wizardState === 'validation' ? 'Operations graph has 1 cycle. Remove the offending edge before activating.' : null}
      />
      {wizardState === 'success' && <SuccessToast message='Routing v4 activated for Lehenga Maroon Banarasi · 8 nodes' />}
    </div>
  );
}

Object.assign(window, {
  RoutingsListFull, RoutingsListLoading, RoutingsListError, RoutingsListEmpty, RoutingsListFilteredEmpty,
  RoutingWizard, RtgWizardTabA, RoutingOpsEditorial, RoutingOpsDense, RtgWizardTabC,
});
