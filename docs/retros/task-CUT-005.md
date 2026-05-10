# TASK-CUT-005 retro — three-spike combo (Vyapar source / Reports BE schema / PDF tech)

**Date:** 2026-05-10
**Branch:** task/CUT-005-wave1-spikes
**Commit:** `<sha>` (to be assigned at merge)
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 1, agent W1-E

## Summary

Discovery only — no code, no migrations, no new deps. Wrote three spike docs in `docs/spikes/` plus a literal HTML wireframe for the invoice template. All four files open and parse cleanly. Each doc ends with a Recommendation (3 bullets) and a "Decision needed from Moiz" section listing override hooks. No CI test/lint relevant; this is docs-only. Total budget 5h; actual ~2h thanks to (a) the dev DB already being available for index recon, (b) WeasyPrint + Vyapar format being well-documented enough that web research closed the loops without sample data.

## Deviations from plan

### 1. Tightened the Vyapar recommendation early because external evidence was overwhelming
Plan said "if you can't recommend, ask Moiz to drop a sample export." A web check confirmed (a) `.vyp` is a SQLite blob wrapped in a `.vyb` ZIP, (b) Vyapar's first-party Excel export covers all the master+register fields v1 needs, and (c) the only working third-party Vyapar migration (BUSY) explicitly uses Excel, not `.vyp`. So the recommendation is conclusive — Excel — and the sample-drop ask is now a "30-min validation spike if Moiz wants belt-and-braces" rather than a blocker.
- **Fixed by:** added Override Hook 2 in `vyapar-source-format.md` so Moiz can still drop a sample if he wants the belt-and-braces validation, but Wave 5 isn't blocked on it.
- **Why not caught in planning:** plan was written assuming the format was opaque. The web research closed it cheaply.
- **Impact on later tasks:** TASK-CUT-402 (Wave 5) can now proceed with `openpyxl` as the parser dep without further investigation.

### 2. Skipped the GitHub Actions CI verification step
The instructions said "open + merge on green CI (which for docs is just lint)." Branch is local; CI/PR will be opened by the parent agent after this report. No CI run yet inside this agent's runtime. Acceptance criterion was creating the docs, which is done.
- **Fixed by:** parent agent will push and open the PR.
- **Impact on later tasks:** zero.

## Things the plan got right (no deviation)

- Time-box per spike (1h/2h/2h, total 5h) was generous; spike-1 came in at ~30 min thanks to web evidence; spike-2 was the longest, at ~75 min, including dev-DB reconnaissance and index design; spike-3 was ~45 min including the wireframe HTML.
- "Lazy SQL is the right shape for v1" was the right intuition — confirmed once Moiz's expected volume (~60k voucher_line/yr) was sized against existing indexes.
- WeasyPrint as the default PDF tech matches the audit's Tier-1 item and CLAUDE.md's HTML-first philosophy. Easy call once the alternatives were costed.
- Wireframe-as-a-real-HTML-file is the right artefact: it's openable by Moiz directly, can be visually approved without spinning up the BE, and becomes the literal Jinja template seed for Wave 3.

## Pre-TASK-CUT-101..106 checklist (Wave 2 prep)

Ordered by what will bite first when Wave 2 spawns.

### 1. Sign off the three spike outputs
Moiz reads `docs/spikes/{vyapar-source-format,reports-be-schema,pdf-rendering-tech}.md` (5 min total — the recommendations + decision sections are 1 page each). If any override applies, note in the wave-1 demo doc.

### 2. Open `invoice-template-wireframe.html` in a browser and visually approve
File path: `docs/spikes/invoice-template-wireframe.html`. Shows a complete Indian GST tax invoice with placeholder values across all 12 mandatory fields. Browser print preview shows A4 layout. If the visual baseline is rejected, supply a Vyapar-style sample PDF for Wave 3 to style-match against.

### 3. Decide if a Vyapar sample drop is wanted
If yes, drop `.xlsx` and/or `.vyb` at `/Users/moizp/fabric/docs/spikes/vyapar-sample-export.xlsx`. A 30-min follow-up agent will validate column coverage. If no, Wave 5 will assume the typical-Vyapar-export shape and adapt at run time.

### 4. Wave 2 (TASK-CUT-105) note
Reports BE foundation must include the two surgical migrations (`sales_invoice.gstr1_section`, plus the partner P1-2 fix on `voucher.party_id` in TASK-CUT-104) and the two new indexes (`idx_voucher_firm_date_status`, `idx_si_firm_invoice_date`) called out in the spike. Don't skip them — they're the difference between "P95 < 200ms" and "P95 < 1s" once data grows.

### 5. Wave 3 (TASK-CUT-205) install plan
Add `weasyprint = ">=63.0"` to `backend/pyproject.toml` and the system-dep block to `backend/Dockerfile`. ~50 MB image cost. Devanagari fonts via `fonts-noto fonts-noto-cjk` apt packages. The Jinja template seed is the wireframe — copy, parameterise, ship.

## Open flags carried over

- **Vyapar sample drop pending.** Override Hook 2 in spike-1; resurfaces in Wave 5 (TASK-CUT-402) if Moiz declines and the live import then surfaces a column-coverage gap.
- **Stock-summary historical (FIFO valuation) is deferred to v2.** Captured as Override Hook 3 in spike-2; only relevant if Moiz files year-end stock to CA.
- **GSTR-1 portal JSON exact-shape match is deferred until e-file flag flips.** Captured as Override Hook 4 in spike-2; CLAUDE.md decision #6 already feature-flags the upload itself.
- **Per-firm invoice template customisation deferred to v2.** Captured as Override Hook 4 in spike-3; comes back if a friendly customer needs a different PDF look.

## Observable state at end of task

- New files (only):
  - `docs/spikes/vyapar-source-format.md`
  - `docs/spikes/reports-be-schema.md`
  - `docs/spikes/pdf-rendering-tech.md`
  - `docs/spikes/invoice-template-wireframe.html`
  - `docs/retros/task-CUT-005.md` (this file)
- No code changes, no schema changes, no new BE/FE deps installed.
- Branch: `task/CUT-005-wave1-spikes` off `main`. Worktree: `agent-a659656dcbbc0cfa1`.
- Dev DB was queried read-only for index recon (`pg_stat_user_tables`, `\d voucher`, `\d sales_invoice`, etc.). No mutations. Connection used CLAUDE.md-default credentials.
- Parent agent should push the branch, open the PR with title `TASK-CUT-005: Wave-1 spike combo (Vyapar / Reports BE / PDF)`, and self-merge on green lint CI.
