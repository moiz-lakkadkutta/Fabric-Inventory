// phase6-canvas.jsx — composes all five manufacturing-masters deliverables
// onto a single DesignCanvas, with per-section states and variations.

/* ─────────────────────────────────────────────────────────────
   Common artboard sizes
───────────────────────────────────────────────────────────── */
const FULL_W = 1440, FULL_H = 880;   // standard list / wizard
const DLG_W  = 820,  DLG_H  = 640;    // dialog state (with backdrop padding)
const DLG_TALL_H = 720;

function P6Root() {
  return (
    <DesignCanvas>
      {/* ──────────────────────────────────────────────────────
          INTRO
      ────────────────────────────────────────────────────── */}
      <DCSection id="intro" title="Phase 6 · Manufacturing masters" subtitle="Designs → BOM → Routing → MO — five missing master surfaces, end-to-end">
        <DCArtboard id="brief" label="Brief & rationale" width={1080} height={460}>
          <P6Intro />
        </DCArtboard>
        <DCArtboard id="op-palette" label="Operation type palette" width={620} height={460}>
          <OpTypePaletteShowcase />
        </DCArtboard>
      </DCSection>

      {/* ──────────────────────────────────────────────────────
          1 — DESIGNS
      ────────────────────────────────────────────────────── */}
      <DCSection id="designs" title="1 · Designs" subtitle="/manufacturing/designs — list + 720px create dialog. Mirrors PartyList for spacing, filters, breadcrumb.">
        <DCArtboard id="d-full"  label="List · Full (8 rows incl. inactive)" width={FULL_W} height={FULL_H}><DesignsListFull /></DCArtboard>
        <DCArtboard id="d-load"  label="List · Loading"                       width={FULL_W} height={FULL_H}><DesignsListLoading /></DCArtboard>
        <DCArtboard id="d-err"   label="List · Error + retry"                 width={FULL_W} height={FULL_H}><DesignsListError /></DCArtboard>
        <DCArtboard id="d-empt"  label="List · Empty (fresh signup)"          width={FULL_W} height={FULL_H}><DesignsListEmpty /></DCArtboard>
        <DCArtboard id="d-fe"    label="List · Filtered-empty"                width={FULL_W} height={FULL_H}><DesignsListFilteredEmpty /></DCArtboard>
        <DCArtboard id="d-dlg"   label="Dialog · Default"                     width={DLG_W} height={DLG_TALL_H}><DesignCreateDialog state="default" /></DCArtboard>
        <DCArtboard id="d-dlg-t" label="Dialog · Typeahead open"              width={DLG_W} height={DLG_TALL_H}><DesignCreateDialog state="typeahead" /></DCArtboard>
        <DCArtboard id="d-dlg-v" label="Dialog · Validation errors"           width={DLG_W} height={DLG_TALL_H}><DesignCreateDialog state="validation" /></DCArtboard>
        <DCArtboard id="d-dlg-l" label="Dialog · Saving"                      width={DLG_W} height={DLG_TALL_H}><DesignCreateDialog state="loading" /></DCArtboard>
        <DCArtboard id="d-dlg-s" label="Dialog · Success toast"               width={DLG_W} height={DLG_TALL_H}><DesignCreateDialog state="success" /></DCArtboard>
      </DCSection>

      {/* ──────────────────────────────────────────────────────
          2 — OPERATION MASTERS
      ────────────────────────────────────────────────────── */}
      <DCSection id="operations" title="3 · Operation masters" subtitle="/manufacturing/operations — colour-coded type pills harmonised with the kanban palette (WEAVING + DYEING new but sibling-tone).">
        <DCArtboard id="o-full"  label="List · Full (13 rows, all 7 type pills)" width={FULL_W} height={FULL_H}><OperationsListFull /></DCArtboard>
        <DCArtboard id="o-load"  label="List · Loading"                           width={FULL_W} height={FULL_H}><OperationsListLoading /></DCArtboard>
        <DCArtboard id="o-err"   label="List · Error"                             width={FULL_W} height={FULL_H}><OperationsListError /></DCArtboard>
        <DCArtboard id="o-empt"  label="List · Empty"                             width={FULL_W} height={FULL_H}><OperationsListEmpty /></DCArtboard>
        <DCArtboard id="o-fe"    label="List · Filtered-empty"                    width={FULL_W} height={FULL_H}><OperationsListFilteredEmpty /></DCArtboard>
        <DCArtboard id="o-dlg"   label="Dialog · Default + type radio + preview"  width={DLG_W} height={DLG_TALL_H}><OperationCreateDialog state="default" /></DCArtboard>
        <DCArtboard id="o-dlg-v" label="Dialog · Validation"                      width={DLG_W} height={DLG_TALL_H}><OperationCreateDialog state="validation" /></DCArtboard>
        <DCArtboard id="o-dlg-l" label="Dialog · Saving"                          width={DLG_W} height={DLG_TALL_H}><OperationCreateDialog state="loading" /></DCArtboard>
        <DCArtboard id="o-dlg-s" label="Dialog · Success toast"                   width={DLG_W} height={DLG_TALL_H}><OperationCreateDialog state="success" /></DCArtboard>
      </DCSection>

      {/* ──────────────────────────────────────────────────────
          3 — COST CENTRES
      ────────────────────────────────────────────────────── */}
      <DCSection id="cost-centres" title="4 · Cost centres" subtitle="/manufacturing/cost-centres — the simplest of the five (code · name · description).">
        <DCArtboard id="cc-full"  label="List · Full (7 rows incl. inactive)" width={FULL_W} height={FULL_H}><CostCentresListFull /></DCArtboard>
        <DCArtboard id="cc-load"  label="List · Loading"                      width={FULL_W} height={FULL_H}><CostCentresListLoading /></DCArtboard>
        <DCArtboard id="cc-err"   label="List · Error"                        width={FULL_W} height={FULL_H}><CostCentresListError /></DCArtboard>
        <DCArtboard id="cc-empt"  label="List · Empty"                        width={FULL_W} height={FULL_H}><CostCentresListEmpty /></DCArtboard>
        <DCArtboard id="cc-fe"    label="List · Filtered-empty"               width={FULL_W} height={FULL_H}><CostCentresListFilteredEmpty /></DCArtboard>
        <DCArtboard id="cc-dlg"   label="Dialog · Default"                    width={DLG_W} height={DLG_H}><CostCentreCreateDialog state="default" /></DCArtboard>
        <DCArtboard id="cc-dlg-v" label="Dialog · Validation"                 width={DLG_W} height={DLG_H}><CostCentreCreateDialog state="validation" /></DCArtboard>
        <DCArtboard id="cc-dlg-l" label="Dialog · Saving"                     width={DLG_W} height={DLG_H}><CostCentreCreateDialog state="loading" /></DCArtboard>
        <DCArtboard id="cc-dlg-s" label="Dialog · Success toast"              width={DLG_W} height={DLG_H}><CostCentreCreateDialog state="success" /></DCArtboard>
      </DCSection>

      {/* ──────────────────────────────────────────────────────
          4 — BOMs
      ────────────────────────────────────────────────────── */}
      <DCSection id="boms" title="5 · Bills of materials" subtitle="/manufacturing/boms — grouped list by design + 3-tab wizard. Lines tab in TWO variations.">
        <DCArtboard id="b-full"  label="List · Full (10 BOMs / 6 designs, grouped)" width={FULL_W} height={FULL_H}><BomsListFull /></DCArtboard>
        <DCArtboard id="b-load"  label="List · Loading"                              width={FULL_W} height={FULL_H}><BomsListLoading /></DCArtboard>
        <DCArtboard id="b-err"   label="List · Error"                                width={FULL_W} height={FULL_H}><BomsListError /></DCArtboard>
        <DCArtboard id="b-empt"  label="List · Empty"                                width={FULL_W} height={FULL_H}><BomsListEmpty /></DCArtboard>
        <DCArtboard id="b-fe"    label="List · Filtered-empty"                       width={FULL_W} height={FULL_H}><BomsListFilteredEmpty /></DCArtboard>
        <DCArtboard id="b-wz-a"  label="Wizard · Tab A · Design & version"           width={FULL_W} height={FULL_H}><BomWizard activeStep="design" /></DCArtboard>
        <DCArtboard id="b-wz-b-dense"  label="Wizard · Tab B · Lines — VARIATION 1 (dense / spreadsheet)"     width={FULL_W} height={FULL_H}><BomWizard activeStep="lines" linesVariant="dense" /></DCArtboard>
        <DCArtboard id="b-wz-b-edit"   label="Wizard · Tab B · Lines — VARIATION 2 (editorial / wizard)"      width={FULL_W} height={FULL_H}><BomWizard activeStep="lines" linesVariant="editorial" /></DCArtboard>
        <DCArtboard id="b-wz-c"  label="Wizard · Tab C · Review & activate · diff"   width={FULL_W} height={FULL_H}><BomWizard activeStep="review" /></DCArtboard>
        <DCArtboard id="b-wz-v"  label="Wizard · Validation banner (lines tab)"      width={FULL_W} height={FULL_H}><BomWizard activeStep="lines" linesVariant="dense" wizardState="validation" /></DCArtboard>
        <DCArtboard id="b-wz-l"  label="Wizard · Submitting (footer spinner)"        width={FULL_W} height={FULL_H}><BomWizard activeStep="review" wizardState="loading" /></DCArtboard>
        <DCArtboard id="b-wz-s"  label="Wizard · Success toast on activate"          width={FULL_W} height={FULL_H}><BomWizard activeStep="review" wizardState="success" /></DCArtboard>
      </DCSection>

      {/* ──────────────────────────────────────────────────────
          5 — ROUTINGS
      ────────────────────────────────────────────────────── */}
      <DCSection id="routings" title="6 · Routings" subtitle="/manufacturing/routings — DAG editor with cycle detection. Operations tab in TWO variations.">
        <DCArtboard id="r-full"  label="List · Full (grouped, 7 routings)"           width={FULL_W} height={FULL_H}><RoutingsListFull /></DCArtboard>
        <DCArtboard id="r-load"  label="List · Loading"                              width={FULL_W} height={FULL_H}><RoutingsListLoading /></DCArtboard>
        <DCArtboard id="r-err"   label="List · Error"                                width={FULL_W} height={FULL_H}><RoutingsListError /></DCArtboard>
        <DCArtboard id="r-empt"  label="List · Empty"                                width={FULL_W} height={FULL_H}><RoutingsListEmpty /></DCArtboard>
        <DCArtboard id="r-fe"    label="List · Filtered-empty"                       width={FULL_W} height={FULL_H}><RoutingsListFilteredEmpty /></DCArtboard>
        <DCArtboard id="r-wz-a"  label="Wizard · Tab A · Design & version"           width={FULL_W} height={FULL_H}><RoutingWizard activeStep="design" /></DCArtboard>
        <DCArtboard id="r-wz-b-edit"  label="Wizard · Tab B · Operations — VARIATION 1 (editorial / DAG canvas)" width={FULL_W} height={FULL_H}><RoutingWizard activeStep="ops" opsVariant="editorial" /></DCArtboard>
        <DCArtboard id="r-wz-b-dense" label="Wizard · Tab B · Operations — VARIATION 2 (dense / sequence rows)"  width={FULL_W} height={FULL_H}><RoutingWizard activeStep="ops" opsVariant="dense" /></DCArtboard>
        <DCArtboard id="r-wz-b-cyc"   label="Wizard · Tab B · Cycle detected (DAG canvas)" width={FULL_W} height={FULL_H}><RoutingWizard activeStep="ops" opsVariant="editorial" wizardState="validation" /></DCArtboard>
        <DCArtboard id="r-wz-b-cyc-d" label="Wizard · Tab B · Cycle detected (dense rows)" width={FULL_W} height={FULL_H}><RoutingWizard activeStep="ops" opsVariant="dense" wizardState="validation" /></DCArtboard>
        <DCArtboard id="r-wz-c"  label="Wizard · Tab C · Review & activate · snapshot" width={FULL_W} height={FULL_H}><RoutingWizard activeStep="review" /></DCArtboard>
        <DCArtboard id="r-wz-l"  label="Wizard · Submitting (footer spinner)"        width={FULL_W} height={FULL_H}><RoutingWizard activeStep="review" wizardState="loading" /></DCArtboard>
        <DCArtboard id="r-wz-s"  label="Wizard · Success toast on activate"          width={FULL_W} height={FULL_H}><RoutingWizard activeStep="review" wizardState="success" /></DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

/* ─────────────────────────────────────────────────────────────
   Intro card — reasoning + decisions
───────────────────────────────────────────────────────────── */
function P6Intro() {
  return (
    <div style={{ height: '100%', background: 'var(--bg-canvas)', padding: 32, overflow: 'auto' }}>
      <div className="mono" style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        Phase 6 · Manufacturing master entities
      </div>
      <h1 style={{ margin: '6px 0 4px', fontSize: 28, fontWeight: 700, letterSpacing: '-0.015em' }}>
        Wire the upstream so the MO wizard can find its dependencies
      </h1>
      <p style={{ margin: '0 0 18px', color: 'var(--text-secondary)', fontSize: 14, maxWidth: 720, lineHeight: 1.55 }}>
        A fresh Taana trial signup hits a dead end the moment they open the MO Create wizard: the Designs picker is empty,
        because no UI exists to author Designs, Operation Masters, Cost Centres, BOMs, or Routings. This phase ships those
        five list + create surfaces so the chain <strong>Design → BOM → Routing → MO</strong> is reachable end-to-end.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        <Decision title="Breadcrumb pattern, globally"
          body="Three master registries live under Masters › … (Designs, Operations, Cost Centres). Two versioned-per-design entities stay under Manufacturing › … (BOMs, Routings) because they are operationally linked to the kanban, not the Items master. Fixed across the whole app per the brief." />
        <Decision title="Reuse, don't reinvent"
          body="Every list page is the same shell as PartyList; every dialog is sized + footer-positioned like NewJournalVoucherDialog; the BOM + Routing wizards inherit the MO-wizard tab strip and Back / Cancel / Next footer placement. New visual logic only where the brief asks." />
        <Decision title="Two of the five tabs get variations"
          body="BOM Lines and Routing Operations are the only steps with non-trivial UX. Each ships in a dense (spreadsheet, owner-mode) and editorial (per-item card, trial-user mode) variation so we can A/B the density before locking. The other three deliverables get one direction." />
      </div>
    </div>
  );
}

function Decision({ title, body }) {
  return (
    <div style={{
      padding: 16, borderRadius: 8,
      background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
    }}>
      <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{body}</div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Operation type palette showcase — proves WEAVING/DYEING tones
   are sibling tones of the kanban palette, not a new chroma.
───────────────────────────────────────────────────────────── */
function OpTypePaletteShowcase() {
  const types = [
    { t: 'WEAVING',    src: 'Sibling of info-text (warm slate)' },
    { t: 'DYEING',     src: 'Sibling of warning-text (terracotta)' },
    { t: 'EMBROIDERY', src: 'warning-subtle / warning-text' },
    { t: 'STITCHING',  src: 'accent-subtle / accent-text' },
    { t: 'QC',         src: 'success-subtle / success-text' },
    { t: 'PACKING',    src: 'neutral warm (existing PACKED tone)' },
    { t: 'OTHER',      src: 'neutral cool (fallback)' },
  ];
  return (
    <div style={{ height: '100%', background: 'var(--bg-canvas)', padding: 28, overflow: 'auto' }}>
      <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 600 }}>OperationType pill</div>
      <h3 style={{ margin: '4px 0 14px', fontSize: 18, fontWeight: 700 }}>Harmonious with the kanban palette</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {types.map(({ t, src }) => {
          const tok = OP_TYPE_TOK[t];
          return (
            <div key={t} style={{
              display: 'grid', gridTemplateColumns: '160px 1fr', alignItems: 'center', gap: 14,
              padding: '12px 14px', borderRadius: 8,
              background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
            }}>
              <OpTypePill type={t} size="md" />
              <div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{src}</div>
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <span style={{ width: 16, height: 16, borderRadius: 3, background: tok.bg, border: '1px solid var(--border-subtle)' }} title="bg" />
                  <span style={{ width: 16, height: 16, borderRadius: 3, background: tok.accent }} title="accent" />
                  <span style={{ width: 16, height: 16, borderRadius: 3, background: tok.fg }} title="fg" />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, { P6Root });
