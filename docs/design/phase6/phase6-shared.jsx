// phase6-shared.jsx — primitives for the five Manufacturing master surfaces.
// Builds on top of components.jsx / shell-chrome.jsx — does NOT introduce
// new tokens. Provides:
//   • ListShell      — sidebar + topbar + breadcrumb + page header + filters
//   • ListStates     — Empty / Loading / Error / FilteredEmpty / Full table
//   • Dialog720      — modal mirroring NewJournalVoucherDialog (720px sheet)
//   • WizardShell    — 3-tab MO-style wizard chrome (Back / Next / Cancel)
//   • TypeaheadField — design picker / finished-item picker
//   • Toast helpers  — mirrors phase5-shell toast pattern
//   • OP_TYPE_TOK    — per-operation_type pill palette (kanban-harmonious)
//   • Sample data    — designs, items, ops, cost-centres, boms, routings

const { useState: useStateS } = React;

/* ─────────────────────────────────────────────────────────────
   1. Operation-type palette.
   Re-use kanban PHASE_TOKENS where the type maps cleanly; mint
   two harmonious tones for WEAVING + DYEING off the same warm-
   info / accent families already on canvas. No new chromas.
───────────────────────────────────────────────────────────── */
const OP_TYPE_TOK = {
  WEAVING:    { fg: '#3F4C5A', bg: '#E4E7EB', accent: '#3F4C5A', label: 'Weaving'    }, // info slate
  DYEING:     { fg: '#7A4A1F', bg: '#F2DFC9', accent: '#9B5A3D', label: 'Dyeing'     }, // terracotta, sibling of warning
  EMBROIDERY: { fg: '#6B4309', bg: '#F5E8D1', accent: '#A26710', label: 'Embroidery' }, // warning
  STITCHING:  { fg: '#0A4A2B', bg: '#D7E9DF', accent: '#0F7A4E', label: 'Stitching'  }, // accent
  QC:         { fg: '#0A4A2B', bg: '#DDEFE4', accent: '#137A48', label: 'QC'         }, // success
  PACKING:    { fg: '#605D52', bg: '#EAE7DD', accent: '#605D52', label: 'Packing'    }, // packed (neutral warm)
  OTHER:      { fg: '#5C5A52', bg: '#EFEDE6', accent: '#8A8880', label: 'Other'      },
};

function OpTypePill({ type, size = 'sm' }) {
  const t = OP_TYPE_TOK[type] || OP_TYPE_TOK.OTHER;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      height: size === 'sm' ? 22 : 26, padding: size === 'sm' ? '0 8px' : '0 10px',
      borderRadius: 4, background: t.bg, color: t.fg,
      fontSize: size === 'sm' ? 11 : 12, fontWeight: 600,
      letterSpacing: '0.04em', textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: t.accent }} />
      {t.label}
    </span>
  );
}

const EXEC_TOK = {
  IN_HOUSE: { fg: 'var(--info-text)',    bg: 'var(--info-subtle)',    label: 'In-house' },
  KARIGAR:  { fg: 'var(--warning-text)', bg: 'var(--warning-subtle)', label: 'Karigar'  },
  QC:       { fg: 'var(--success-text)', bg: 'var(--success-subtle)', label: 'QC'       },
};
function ExecutorPill({ kind, size = 'sm' }) {
  const t = EXEC_TOK[kind] || EXEC_TOK.IN_HOUSE;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      height: size === 'sm' ? 20 : 24, padding: '0 7px',
      borderRadius: 4, background: t.bg, color: t.fg,
      fontSize: 10.5, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase',
    }}>{t.label}</span>
  );
}

/* ─────────────────────────────────────────────────────────────
   2. ListShell — sidebar + topbar + page header + filter bar.
   `sidebarActive` chooses which sidebar item gets highlighted.
   `breadcrumb` is a full path array (Masters › Designs etc).
───────────────────────────────────────────────────────────── */
function ListShell({
  breadcrumb, sidebarActive = 'mfg',
  title, sub, primaryCta, secondaryCta,
  tabs, activeTab, onTab,
  searchPlaceholder, filterChips,
  bottomMeta,
  children,
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <TopBar device="desktop" breadcrumb={breadcrumb} />
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <Sidebar active={sidebarActive} activeSub={null} />
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          {/* Page header — mirrors PartyList exactly */}
          <div style={{
            padding: '14px 24px', borderBottom: '1px solid var(--border-subtle)',
            background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <div style={{ flex: 1 }}>
              <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>{title}</h1>
              {sub && <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>}
            </div>
            {secondaryCta}
            {primaryCta}
          </div>

          {/* Optional tab strip (parties uses one for All/Customers/Suppliers) */}
          {tabs && (
            <div style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', padding: '0 24px', display: 'flex', gap: 4 }}>
              {tabs.map(t => (
                <div key={t.key} onClick={() => onTab && onTab(t.key)} style={{
                  padding: '12px 14px', cursor: 'default',
                  fontSize: 13, fontWeight: 500,
                  color: t.key === activeTab ? 'var(--text-primary)' : 'var(--text-tertiary)',
                  borderBottom: t.key === activeTab ? '2px solid var(--accent)' : '2px solid transparent',
                  marginBottom: -1,
                }}>
                  {t.label}{t.count != null && <span style={{ color: 'var(--text-tertiary)', fontWeight: 400, marginLeft: 4 }}>{t.count}</span>}
                </div>
              ))}
            </div>
          )}

          {/* Filter bar — search left, chips right */}
          {(searchPlaceholder || filterChips) && (
            <div style={{ padding: '10px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 8, alignItems: 'center', background: 'var(--bg-canvas)', flexWrap: 'wrap' }}>
              {searchPlaceholder && (
                <div style={{ width: 280 }}>
                  <Input placeholder={searchPlaceholder} prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />} />
                </div>
              )}
              {filterChips}
              {bottomMeta && <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--text-tertiary)' }}>{bottomMeta}</span>}
            </div>
          )}

          <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg-surface)' }}>{children}</div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   3. List state renderers — every list page draws all of these.
───────────────────────────────────────────────────────────── */
const thL = { fontSize: 10.5, fontWeight: 600, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '10px 14px', textAlign: 'left', whiteSpace: 'nowrap', background: 'var(--bg-sunken)', borderBottom: '1px solid var(--border-default)' };
const tdL = { padding: '12px 14px', verticalAlign: 'middle', borderBottom: '1px solid var(--border-subtle)' };

function ListTable({ columns, rows, renderRow }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead>
        <tr>
          {columns.map(c => <th key={c.key} style={{...thL, ...(c.align === 'right' ? { textAlign: 'right' } : null), ...(c.width ? { width: c.width } : null)}}>{c.label}</th>)}
        </tr>
      </thead>
      <tbody>{rows.map(renderRow)}</tbody>
    </table>
  );
}

function EmptyState({ icon = 'inbox', title, sub, cta }) {
  return (
    <div style={{ padding: '64px 32px', textAlign: 'center', maxWidth: 460, margin: '0 auto' }}>
      <div style={{
        width: 64, height: 64, borderRadius: 16,
        background: 'var(--bg-sunken)', border: '1px solid var(--border-default)',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 20,
      }}>
        <Icon name={icon} size={24} color="var(--text-tertiary)" />
      </div>
      <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, letterSpacing: '-0.005em' }}>{title}</h3>
      <p style={{ margin: '6px 0 18px', fontSize: 13, color: 'var(--text-tertiary)', lineHeight: 1.5 }}>{sub}</p>
      {cta}
    </div>
  );
}

function FilteredEmptyState({ query, onClear }) {
  return (
    <div style={{ padding: '56px 32px', textAlign: 'center' }}>
      <div style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
        No results matching <span className="mono" style={{
          color: 'var(--text-primary)', padding: '2px 6px', background: 'var(--bg-sunken)',
          border: '1px solid var(--border-subtle)', borderRadius: 4, fontSize: 12,
        }}>{query}</span>
      </div>
      <div style={{ marginTop: 12 }}>
        <span onClick={onClear} style={{ cursor: 'pointer' }}>
          <Button variant="ghost" size="sm">Clear search</Button>
        </span>
      </div>
    </div>
  );
}

function LoadingSkeletonRows({ columns, count = 6 }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead>
        <tr>
          {columns.map(c => <th key={c.key} style={{...thL, ...(c.align === 'right' ? { textAlign: 'right' } : null)}}>{c.label}</th>)}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: count }).map((_, i) => (
          <tr key={i}>
            {columns.map((c, j) => (
              <td key={c.key} style={tdL}>
                <SkeletonBar w={c.skelW || (j === 0 ? 120 : j === 1 ? 200 : 80)} h={12} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ErrorBanner({ message = "Couldn't load. The server returned a 5xx.", onRetry }) {
  return (
    <div style={{ padding: 24 }}>
      <div style={{
        background: 'var(--danger-subtle)', border: '1px solid #E5B3A8',
        borderRadius: 8, padding: '14px 16px',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <Icon name="alert" size={18} color="var(--danger-text)" />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--danger-text)' }}>Couldn't load list</div>
          <div style={{ fontSize: 12, color: 'var(--danger-text)', opacity: 0.85, marginTop: 2 }}>{message}</div>
        </div>
        <span onClick={onRetry} style={{ cursor: 'pointer' }}>
          <Button variant="secondary" size="sm" icon="rotate">Retry</Button>
        </span>
      </div>
    </div>
  );
}

/* Re-use the shimmer keyframe defined in phase5-shell */
function SkeletonBar({ w = '100%', h = 12 }) {
  return (
    <span style={{
      display: 'inline-block', width: w, height: h,
      borderRadius: 3, background: '#E8E5DA',
      animation: 'rpt-shimmer 1.4s ease-in-out infinite',
      verticalAlign: 'middle',
    }} />
  );
}

/* ─────────────────────────────────────────────────────────────
   4. Dialog720 — mirrors NewJournalVoucherDialog: 720px modal,
   header w/ title + close, scrollable body, footer with
   ghost Cancel + primary Submit, validation banner slot.
───────────────────────────────────────────────────────────── */
function Dialog720({ title, sub, onClose, children, footer, error, loading, width = 720 }) {
  return (
    <div style={{
      width, maxWidth: '95vw', maxHeight: '88vh',
      background: 'var(--bg-surface)', borderRadius: 12,
      boxShadow: 'var(--shadow-4)', overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
      border: '1px solid var(--border-default)',
    }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, letterSpacing: '-0.005em' }}>{title}</h2>
          {sub && <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>}
        </div>
        <button onClick={onClose} aria-label="Close" style={{
          width: 30, height: 30, padding: 0, background: 'transparent',
          border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4,
        }}><Icon name="x" size={16} /></button>
      </div>
      {error && (
        <div style={{
          padding: '10px 18px', background: 'var(--danger-subtle)',
          borderBottom: '1px solid #E5B3A8', display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <Icon name="alert" size={14} color="var(--danger-text)" />
          <div style={{ fontSize: 12.5, color: 'var(--danger-text)', fontWeight: 500 }}>{error}</div>
        </div>
      )}
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>{children}</div>
      <div style={{
        padding: '12px 18px', borderTop: '1px solid var(--border-subtle)',
        background: 'var(--bg-sunken)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>{footer}</div>
    </div>
  );
}

/* Typeahead — used by Designs (finished item), BOMs (design), Routings (design) */
function TypeaheadField({ value, placeholder, results, hint, state = 'default' }) {
  return (
    <div style={{ position: 'relative' }}>
      <Input value={value} placeholder={placeholder} state={state}
        prefix={<Icon name="search" size={14} color="var(--text-tertiary)" />}
        suffix={<Icon name="chevron-down" size={14} color="var(--text-tertiary)" />}
      />
      {results && results.length > 0 && (
        <div style={{
          position: 'absolute', top: 44, left: 0, right: 0, zIndex: 5,
          background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
          borderRadius: 6, boxShadow: 'var(--shadow-3)', overflow: 'hidden', maxHeight: 240,
        }}>
          {results.map((r, i) => (
            <div key={i} style={{
              padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 10,
              borderBottom: i === results.length - 1 ? 'none' : '1px solid var(--border-subtle)',
              background: i === 0 ? 'var(--bg-sunken)' : 'transparent',
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 500 }}>{r.name}</div>
                {r.meta && <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>{r.meta}</div>}
              </div>
              {r.code && <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>{r.code}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   5. WizardShell — 3-tab MO-style wizard with Back / Next / Cancel.
   Renders a full app shell (TopBar + Sidebar + breadcrumb) and a
   wizard panel inside the work area. `steps` = [{ key, label, body }]
───────────────────────────────────────────────────────────── */
function WizardShell({
  breadcrumb, sidebarActive = 'mfg',
  title, subtitle,
  steps, activeStep, onStep,
  backLabel = 'Back', nextLabel = 'Next', cancelLabel = 'Cancel',
  onBack, onNext, onCancel,
  loading, validationBanner,
  primaryDisabled,
}) {
  const idx = steps.findIndex(s => s.key === activeStep);
  const active = steps[idx];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-canvas)' }}>
      <TopBar device="desktop" breadcrumb={breadcrumb} />
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <Sidebar active={sidebarActive} activeSub={null} />
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{
            padding: '14px 32px', borderBottom: '1px solid var(--border-subtle)',
            background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 14,
          }}>
            <div style={{ flex: 1 }}>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>{title}</h1>
              {subtitle && <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>{subtitle}</div>}
            </div>
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Step {idx + 1} of {steps.length}</span>
          </div>

          {/* tab strip */}
          <div style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', padding: '0 32px', display: 'flex', gap: 0 }}>
            {steps.map((s, i) => {
              const a = s.key === activeStep;
              const past = i < idx;
              return (
                <div key={s.key} onClick={() => onStep && onStep(s.key)} style={{
                  padding: '14px 4px 12px', cursor: 'default',
                  display: 'flex', alignItems: 'center', gap: 10,
                  marginRight: 28, position: 'relative',
                }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: '50%',
                    background: a ? 'var(--accent)' : past ? 'var(--accent-subtle)' : 'var(--bg-sunken)',
                    color: a ? 'var(--accent-text)' : past ? 'var(--accent)' : 'var(--text-tertiary)',
                    fontSize: 11, fontWeight: 700,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    border: '1px solid ' + (a ? 'var(--accent)' : past ? 'var(--accent-subtle)' : 'var(--border-default)'),
                  }}>{past ? <Icon name="check" size={11} color="var(--accent)" /> : i + 1}</span>
                  <span style={{
                    fontSize: 13, fontWeight: a ? 600 : 500,
                    color: a ? 'var(--text-primary)' : 'var(--text-secondary)',
                  }}>{s.label}</span>
                  {a && <span style={{
                    position: 'absolute', left: 0, right: 0, bottom: -1, height: 2,
                    background: 'var(--accent)', borderRadius: '2px 2px 0 0',
                  }} />}
                </div>
              );
            })}
          </div>

          {validationBanner && (
            <div style={{
              padding: '10px 32px', background: 'var(--danger-subtle)',
              borderBottom: '1px solid #E5B3A8', display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <Icon name="alert" size={16} color="var(--danger-text)" />
              <div style={{ fontSize: 12.5, color: 'var(--danger-text)', fontWeight: 500 }}>{validationBanner}</div>
            </div>
          )}

          <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>{active?.body}</div>

          {/* Footer — Back / Cancel / Next, MO wizard position */}
          <div style={{
            padding: '12px 32px', borderTop: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <span onClick={onBack} style={{ cursor: idx === 0 ? 'not-allowed' : 'pointer', opacity: idx === 0 ? 0.5 : 1 }}>
              <Button variant="ghost" size="md" icon="corner-down">{backLabel}</Button>
            </span>
            <span style={{ flex: 1 }} />
            <span onClick={onCancel} style={{ cursor: 'pointer' }}>
              <Button variant="ghost" size="md">{cancelLabel}</Button>
            </span>
            {loading
              ? <Button variant="primary" size="md" icon={<Icon name="spinner" size={14} />}>Submitting…</Button>
              : (
                <span onClick={onNext} style={{ cursor: primaryDisabled ? 'not-allowed' : 'pointer' }}>
                  <Button variant="primary" size="md" iconRight="arrow-right" state={primaryDisabled ? 'disabled' : 'rest'}>{nextLabel}</Button>
                </span>
              )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   6. Toast — minimal, matches phase5-shell semantics.
───────────────────────────────────────────────────────────── */
function SuccessToast({ message }) {
  return (
    <div style={{
      position: 'absolute', right: 24, bottom: 24, zIndex: 60,
      background: 'var(--text-primary)', color: 'var(--text-inverse)',
      padding: '10px 14px', borderRadius: 6, fontSize: 12.5,
      boxShadow: 'var(--shadow-3)', minWidth: 220,
      display: 'inline-flex', alignItems: 'center', gap: 10,
    }}>
      <Icon name="check-circle" size={14} color="var(--accent-subtle)" />
      <span>{message}</span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   7. Sample data — real Indian textile vocabulary, never lorem.
───────────────────────────────────────────────────────────── */
const ITEMS = [
  { code: 'FIN-ANK-PNK',  name: 'Anarkali Pink Embroidered',     uom: 'set', cost: 4250, kind: 'finished' },
  { code: 'FIN-SHR-GLD',  name: 'Sharara Set Gold',              uom: 'set', cost: 6800, kind: 'finished' },
  { code: 'FIN-SLW-BLU',  name: 'Salwar Kameez Blue Cotton',     uom: 'set', cost: 2150, kind: 'finished' },
  { code: 'FIN-LHG-MRN',  name: 'Lehenga Maroon Banarasi',       uom: 'set', cost: 8400, kind: 'finished' },
  { code: 'FIN-KRT-IND',  name: 'Kurta Indigo Block Print',      uom: 'pc',  cost: 1180, kind: 'finished' },
  { code: 'FIN-DPT-CHM',  name: 'Dupatta Champagne Mukaish',     uom: 'pc',  cost: 1420, kind: 'finished' },
  { code: 'RAW-CTV-60',   name: 'Cotton Voile 60s',              uom: 'm',   cost: 78,   kind: 'raw' },
  { code: 'RAW-SGE-60',   name: 'Silk Georgette 60GSM',          uom: 'm',   cost: 185,  kind: 'raw' },
  { code: 'RAW-BNS-MRN',  name: 'Banarasi Silk Maroon',          uom: 'm',   cost: 620,  kind: 'raw' },
  { code: 'RAW-CHN-OFW',  name: 'Chanderi Cotton Off-white',     uom: 'm',   cost: 95,   kind: 'raw' },
  { code: 'CON-ZRI-GLD',  name: 'Zari Thread Gold',              uom: 'spl', cost: 240,  kind: 'consumable' },
  { code: 'CON-STN-PKT',  name: 'Stone Work Pkt',                uom: 'pkt', cost: 180,  kind: 'consumable' },
  { code: 'CON-SQN-SLV',  name: 'Sequins Silver',                uom: 'pkt', cost: 120,  kind: 'consumable' },
  { code: 'CON-LCE-IVR',  name: 'Cotton Lace 1cm Ivory',         uom: 'rl',  cost: 480,  kind: 'consumable' },
  { code: 'CON-HOK-MTL',  name: 'Fall hooks metallic',           uom: 'pc',  cost: 12,   kind: 'consumable' },
  { code: 'CON-BTN-WOD',  name: 'Wooden buttons natural',        uom: 'pc',  cost: 24,   kind: 'consumable' },
];

const COST_CENTRES = [
  { code: 'CC-INH-STC', name: 'In-house stitching',                 description: 'Internal stitching floor — Surat unit 1',           is_active: true,  ops: 4 },
  { code: 'CC-KAR-RSD', name: 'Karigar embroidery — Rashid Tailors', description: 'Aari & zardosi specialist, Pahargunj cluster',     is_active: true,  ops: 6 },
  { code: 'CC-KAR-IMR', name: 'Karigar embroidery — Imran',          description: 'Hand embroidery, Aari work karigar',                is_active: true,  ops: 3 },
  { code: 'CC-PCK-MGD', name: 'Packing — main godown',               description: 'Final QC + packing area, Surat HQ',                 is_active: true,  ops: 2 },
  { code: 'CC-DYE-SLM', name: 'Dyeing — Salim',                      description: 'Batch dyeing vendor, Bhuvaldi industrial estate',   is_active: true,  ops: 2 },
  { code: 'CC-QC-INH',  name: 'In-house QC',                         description: 'Final inspection & sample audit',                   is_active: true,  ops: 1 },
  { code: 'CC-BLK-PRT', name: 'Block printing — Sanganer',           description: 'Traditional block printing artisans (Jaipur)',      is_active: false, ops: 1 },
];

const OPERATION_MASTERS = [
  { code: 'OP-WEV-CTN', name: 'Cotton Voile weaving',          type: 'WEAVING',     dur: 240, cc: 'CC-INH-STC', is_active: true },
  { code: 'OP-DYE-BAT', name: 'Batch dyeing — reactive',       type: 'DYEING',      dur: 720, cc: 'CC-DYE-SLM', is_active: true },
  { code: 'OP-DYE-VAT', name: 'Vat dyeing — indigo',           type: 'DYEING',      dur: 540, cc: 'CC-DYE-SLM', is_active: true },
  { code: 'OP-EMB-AAR', name: 'Hand Embroidery — Aari Work',   type: 'EMBROIDERY',  dur: 480, cc: 'CC-KAR-IMR', is_active: true },
  { code: 'OP-EMB-ZRD', name: 'Hand Embroidery — Zardosi',     type: 'EMBROIDERY',  dur: 600, cc: 'CC-KAR-RSD', is_active: true },
  { code: 'OP-PRT-BLK', name: 'Block Printing',                type: 'EMBROIDERY',  dur: 180, cc: 'CC-BLK-PRT', is_active: false },
  { code: 'OP-CUT-STD', name: 'Cut to pattern',                type: 'STITCHING',   dur: 45,  cc: 'CC-INH-STC', is_active: true },
  { code: 'OP-STC-MNL', name: 'Stitch — straight assembly',    type: 'STITCHING',   dur: 90,  cc: 'CC-INH-STC', is_active: true },
  { code: 'OP-STC-FNS', name: 'Stitch — finishing & trim',     type: 'STITCHING',   dur: 60,  cc: 'CC-INH-STC', is_active: true },
  { code: 'OP-QC-VIS',  name: 'Quality Check — visual',        type: 'QC',          dur: 15,  cc: 'CC-QC-INH',  is_active: true },
  { code: 'OP-QC-MSR',  name: 'Quality Check — measurement',   type: 'QC',          dur: 25,  cc: 'CC-QC-INH',  is_active: true },
  { code: 'OP-PCK-FLD', name: 'Fold & poly-pack',              type: 'PACKING',     dur: 8,   cc: 'CC-PCK-MGD', is_active: true },
  { code: 'OP-PCK-BX',  name: 'Box & label',                   type: 'PACKING',     dur: 10,  cc: 'CC-PCK-MGD', is_active: true },
];

const DESIGNS = [
  { code: 'DSN-ANK-PNK', name: 'Anarkali Pink Embroidered',  fin: 'FIN-ANK-PNK', bom: 3, rtg: 2, is_active: true,  updated: '14 Apr 2026' },
  { code: 'DSN-SHR-GLD', name: 'Sharara Set Gold',           fin: 'FIN-SHR-GLD', bom: 2, rtg: 2, is_active: true,  updated: '12 Apr 2026' },
  { code: 'DSN-SLW-BLU', name: 'Salwar Kameez Blue Cotton',  fin: 'FIN-SLW-BLU', bom: 1, rtg: 1, is_active: true,  updated: '08 Apr 2026' },
  { code: 'DSN-LHG-MRN', name: 'Lehenga Maroon Banarasi',    fin: 'FIN-LHG-MRN', bom: 4, rtg: 3, is_active: true,  updated: '02 Apr 2026' },
  { code: 'DSN-KRT-IND', name: 'Kurta Indigo Block Print',   fin: 'FIN-KRT-IND', bom: 1, rtg: 1, is_active: true,  updated: '28 Mar 2026' },
  { code: 'DSN-DPT-CHM', name: 'Dupatta Champagne Mukaish',  fin: 'FIN-DPT-CHM', bom: 2, rtg: 1, is_active: true,  updated: '24 Mar 2026' },
  { code: 'DSN-KRT-OFW', name: 'Kurta Off-white Chikankari', fin: 'FIN-KRT-IND', bom: 1, rtg: 0, is_active: true,  updated: '18 Mar 2026' },
  { code: 'DSN-LHG-PCH', name: 'Lehenga Peach Mirror Work',  fin: 'FIN-LHG-MRN', bom: 1, rtg: 1, is_active: false, updated: '02 Feb 2026' },
];

/* BOM samples — Anarkali Pink active version */
const BOM_LINES_ANARKALI = [
  { item: 'RAW-SGE-60',  name: 'Silk Georgette 60GSM',     qty: 3.2,  uom: 'm',   scrap: 4, cost: 185  },
  { item: 'RAW-CTV-60',  name: 'Cotton Voile 60s',          qty: 2.4,  uom: 'm',   scrap: 3, cost: 78   },
  { item: 'CON-ZRI-GLD', name: 'Zari Thread Gold',          qty: 0.3,  uom: 'spl', scrap: 6, cost: 240  },
  { item: 'CON-STN-PKT', name: 'Stone Work Pkt',            qty: 0.4,  uom: 'pkt', scrap: 8, cost: 180  },
  { item: 'CON-SQN-SLV', name: 'Sequins Silver',            qty: 0.2,  uom: 'pkt', scrap: 5, cost: 120  },
  { item: 'CON-LCE-IVR', name: 'Cotton Lace 1cm Ivory',     qty: 1.8,  uom: 'rl',  scrap: 2, cost: 480  },
  { item: 'CON-HOK-MTL', name: 'Fall hooks metallic',       qty: 4,    uom: 'pc',  scrap: 5, cost: 12   },
];

const BOMS = [
  { design: 'DSN-ANK-PNK', dname: 'Anarkali Pink Embroidered',  ver: 3, lines: 7, cost: 1885,  active: true,  updated: '14 Apr 2026', by: 'Asha P.' },
  { design: 'DSN-ANK-PNK', dname: 'Anarkali Pink Embroidered',  ver: 2, lines: 6, cost: 1740,  active: false, updated: '02 Feb 2026', by: 'Asha P.' },
  { design: 'DSN-ANK-PNK', dname: 'Anarkali Pink Embroidered',  ver: 1, lines: 5, cost: 1620,  active: false, updated: '04 Jan 2026', by: 'Asha P.' },
  { design: 'DSN-SHR-GLD', dname: 'Sharara Set Gold',           ver: 2, lines: 9, cost: 3120,  active: true,  updated: '10 Apr 2026', by: 'Naseem'   },
  { design: 'DSN-SHR-GLD', dname: 'Sharara Set Gold',           ver: 1, lines: 8, cost: 2850,  active: false, updated: '12 Feb 2026', by: 'Naseem'   },
  { design: 'DSN-LHG-MRN', dname: 'Lehenga Maroon Banarasi',    ver: 4, lines: 11,cost: 4280,  active: true,  updated: '02 Apr 2026', by: 'Asha P.' },
  { design: 'DSN-LHG-MRN', dname: 'Lehenga Maroon Banarasi',    ver: 3, lines: 10,cost: 4120,  active: false, updated: '28 Feb 2026', by: 'Asha P.' },
  { design: 'DSN-SLW-BLU', dname: 'Salwar Kameez Blue Cotton',  ver: 1, lines: 4, cost: 540,   active: true,  updated: '08 Apr 2026', by: 'Owner'    },
  { design: 'DSN-KRT-IND', dname: 'Kurta Indigo Block Print',   ver: 1, lines: 3, cost: 420,   active: true,  updated: '28 Mar 2026', by: 'Owner'    },
  { design: 'DSN-DPT-CHM', dname: 'Dupatta Champagne Mukaish',  ver: 2, lines: 4, cost: 680,   active: true,  updated: '24 Mar 2026', by: 'Naseem'   },
];

const ROUTINGS = [
  { design: 'DSN-ANK-PNK', dname: 'Anarkali Pink Embroidered',  ver: 2, nodes: 6, ops: ['Cut', 'Embroidery — Aari', 'Stitch', 'Finishing', 'QC', 'Pack'],     active: true,  updated: '12 Apr 2026', by: 'Asha P.' },
  { design: 'DSN-ANK-PNK', dname: 'Anarkali Pink Embroidered',  ver: 1, nodes: 5, ops: ['Cut', 'Embroidery', 'Stitch', 'QC', 'Pack'],                          active: false, updated: '04 Jan 2026', by: 'Asha P.' },
  { design: 'DSN-SHR-GLD', dname: 'Sharara Set Gold',           ver: 2, nodes: 7, ops: ['Cut', 'Embroidery — Zardosi', 'Stitch', 'Finishing', 'QC', 'Pack'],  active: true,  updated: '10 Apr 2026', by: 'Naseem'   },
  { design: 'DSN-LHG-MRN', dname: 'Lehenga Maroon Banarasi',    ver: 3, nodes: 8, ops: ['Dye', 'Cut', 'Embroidery — Zardosi', 'Embroidery — Stone', 'Stitch', 'Finishing', 'QC', 'Pack'], active: true, updated: '02 Apr 2026', by: 'Asha P.' },
  { design: 'DSN-SLW-BLU', dname: 'Salwar Kameez Blue Cotton',  ver: 1, nodes: 4, ops: ['Cut', 'Stitch', 'QC', 'Pack'],                                        active: true,  updated: '08 Apr 2026', by: 'Owner'    },
  { design: 'DSN-KRT-IND', dname: 'Kurta Indigo Block Print',   ver: 1, nodes: 5, ops: ['Block Print', 'Cut', 'Stitch', 'QC', 'Pack'],                         active: true,  updated: '28 Mar 2026', by: 'Owner'    },
  { design: 'DSN-DPT-CHM', dname: 'Dupatta Champagne Mukaish',  ver: 1, nodes: 4, ops: ['Embroidery — Mukaish', 'Finishing', 'QC', 'Pack'],                    active: true,  updated: '24 Mar 2026', by: 'Naseem'   },
];

/* ─────────────────────────────────────────────────────────────
   8. Indian rupee formatter (lakhs / crores). Integer omits .00
───────────────────────────────────────────────────────────── */
function inrRs(n, opts = {}) {
  const { forceDecimal = false } = opts;
  if (n == null || isNaN(n)) return '—';
  const isInt = Number.isInteger(n);
  const abs = Math.abs(n);
  const fixed = (forceDecimal || !isInt) ? abs.toFixed(2) : abs.toString();
  const [intPart, decPart] = fixed.split('.');
  const lastThree = intPart.slice(-3);
  const rest = intPart.slice(0, -3);
  const groupedRest = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  const grouped = rest ? `${groupedRest},${lastThree}` : lastThree;
  const sign = n < 0 ? '−' : '';
  return `${sign}₹${grouped}${decPart ? '.' + decPart : ''}`;
}

Object.assign(window, {
  OP_TYPE_TOK, OpTypePill, EXEC_TOK, ExecutorPill,
  ListShell, ListTable, thL, tdL,
  EmptyState, FilteredEmptyState, LoadingSkeletonRows, ErrorBanner, SkeletonBar,
  Dialog720, TypeaheadField, WizardShell, SuccessToast,
  ITEMS, COST_CENTRES, OPERATION_MASTERS, DESIGNS, BOM_LINES_ANARKALI, BOMS, ROUTINGS,
  inrRs,
});
