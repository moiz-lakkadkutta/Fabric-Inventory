# TASK-TR-B03 retro — GSTR-1 report tab wired to live backend

**Date:** 2026-05-15
**Branch:** task/tr-b03-gstr1-ui
**Commit:** `<sha>` (pending PR merge)
**Plan:** TASK-TR-B03 brief (no plan file)

## Summary

Closed the FE gap that left the Reports → GSTR-1 tab on a "coming soon"
stub even though `GET /reports/gstr1?period=YYYY-MM` had been live
since CUT-302. `useGstr1` now hits the real endpoint, the panel
renders the four required buckets (B2B / B2CL / B2CS / HSN) with empty
states, the CSV + Excel export buttons are enabled, and a panel-local
period picker drives both the query and the export endpoint. Existing
mock-mode tests pass via a click-dummy view-model built from the
existing `gstrRows` fixture. Lint, tsc, and the full vitest suite
(270 tests; 6 new) are green.

## What landed

- `frontend/src/lib/queries/reports.ts`
  - Removed `mockResolve([])` GSTR-1 live stub.
  - Added `Gstr1VM` / `Gstr1InvoiceVM` / `Gstr1B2csVM` / `Gstr1HsnVM`
    view-model types (rupees → integer paise mapping).
  - `useGstr1(period)` now takes a period parameter, has a real
    `api('/reports/gstr1?period=...')` live branch, and a mock branch
    that synthesizes a click-dummy view-model from `gstrRows`.
  - Re-exported `mapGstr1*` helpers in `_internal` for any future unit
    tests.
- `frontend/src/pages/reports/ReportsHub.tsx`
  - Replaced `Gstr1ComingSoon` + the single-table panel with a 4-section
    panel: `Gstr1B2BSection`, `Gstr1B2CLSection`, `Gstr1B2CSSection`,
    `Gstr1HsnSection`. Each has an empty-state copy ("No B2B invoices
    in this period.", etc.).
  - Added a `<input type="month">` period picker tied to a
    `gstr1Period` `useState` in `ReportsHub`. The query and the export
    endpoint both read from it; non-GSTR-1 tabs ignore it.
  - Removed the `xlsxOnly` flag and the CSV-disabled state on the GSTR-1
    tab — the BE supports both formats (CSV flattens B2B, XLSX is the
    5-sheet canonical filing).
  - Kept Print button as the existing `useComingSoon` dialog (PDF
    print is a separate task, TASK-046).
- `frontend/src/pages/reports/__tests__/ReportsHub.gstr1.test.tsx` —
  six new live-mode tests (URL shape, all four section headings, empty
  state per bucket, no coming-soon stub, export buttons enabled,
  paise-converted compact-INR rendering).
- `frontend/src/pages/reports/__tests__/ReportsHub.test.tsx` —
  updated mock-mode "switches to GSTR-1" test to assert the new
  four-bucket panel + period picker (replaced the obsolete validation
  pill assertion).

## OpenAPI types

The codegen already shipped these as part of CUT-302:
`components['schemas']['Gstr1Response']`,
`components['schemas']['Gstr1InvoiceRow']`,
`components['schemas']['Gstr1B2csRow']`,
`components['schemas']['Gstr1HsnRow']`. `pnpm check:types` confirms
the snapshot at `scripts/openapi-snapshot.json` matches the in-tree
`src/types/api.ts` — no regen required. Mapped them straight into the
new view-models in `reports.ts`.

## Deviations from plan

### 1. Export framework — slotted in cleanly

The brief asked whether the existing exporter "framework slotted in
cleanly or needed extension." It slotted in cleanly: `reportExportEndpoint(tab,
gstr1Period)` returns the path with `?period=...`, `downloadExport()`
appends `?format=csv|xlsx`, and the BE already returns
Content-Disposition + an XLSX or CSV body for GSTR-1. The only edits
were (a) removing the `xlsxOnly: true` flag that blocked the CSV
button, and (b) threading `gstr1Period` into the endpoint resolver.

### 2. Period selector — panel-local, not page-level

The brief said "The Reports page already has a month picker (since
other tabs use it). Make sure `useGstr1` reads from the same selector
so the panel re-fetches when the user changes month."

There is no shared month picker — the page-level period string is a
hard-coded `"Apr 2026 · FY 2025-26"` label, and the other tabs (P&L,
TB, daybook, stock) each pass period/`as_of` defaults to the BE which
resolves them server-side. To stay scope-disciplined ("Don't touch any
other report tab"), I put the picker inside `Gstr1Panel`. If a
page-level picker lands later, `gstr1Period` already lives in
`ReportsHub` state so hoisting is a five-line refactor.

### 3. No e2e Playwright spec

The brief offered E2E as "Optionally add a Playwright E2E test… only
if there's an existing similar E2E to model on." The repo has
`frontend/__tests__/e2e/` but no Reports E2E to model on — and the
six vitest integration specs already cover the live-mode wiring at the
fetch boundary. Skipped.

### 4. Mock branch retained (not removed)

The brief said "the mock branch can stay returning `[]` since the
click-dummy doesn't need to fake the panel — or remove the mock
branch entirely if no other consumer needs it; check first." Removing
it would break the existing `ReportsHub.test.tsx` mock-mode test
(under `VITE_API_MODE=mock`) and any future click-dummy demos. I kept
the mock branch and synthesized a view-model from `gstrRows`, so the
click-dummy renders the new four-bucket panel with the B2B fixture
data visible and the other buckets empty.

## Pre-next-task checklist

### 1. The period picker is panel-local
If TASK-TR-B04 (or a future tab) needs the period picker hoisted to a
page-level header, `gstr1Period` already lives in `ReportsHub` state
— move the `<input type="month">` from `Gstr1Header` into the
top-level header and pass via context or prop drilling.

### 2. CSV export flattens to B2B only
The BE's `?format=csv` branch only writes the B2B sheet (other buckets
are XLSX-only). The UI doesn't currently surface this to the user.
If users get confused, add a tooltip on the CSV button when the GSTR-1
tab is active.

### 3. HSN "missing" rows highlighted but not surfaced as a stat
When `hsn_code === ''`, the row gets a yellow background and shows
"(missing)" in the code cell. We don't currently roll this up as a
data-quality stat in the header. A small follow-up could add an
"X items missing HSN" tile.

### 4. Place-of-supply state codes are raw two-digit codes
The BE returns "27", "24", etc. The panel renders them verbatim. A
state-code-to-name map (e.g., "27 → Maharashtra") would be nicer but
needs a small lookup table — out of scope for this task.

## Open flags

- **E-invoice / IRN JSON export:** Still post-trial, flagged off per
  CLAUDE.md `gst.einvoice.enabled = FALSE`. Not touched.
- **GSTR-1 filing XML payload:** Not in this task. The XLSX export is
  the canonical filing format for now; the JSON payload for direct
  NIC/GSP filing is Wave-5 work.
- **GSTIN masking:** BE comment notes "masked-but-printable" — the
  panel currently renders whatever the BE returns. Future filing-XML
  generation will need decrypted GSTINs; that's a backend concern.

## Observable state at end of task

- New env requirements: none.
- Running services: none new.
- Untracked files: none.
- 6 new tests in `frontend/src/pages/reports/__tests__/ReportsHub.gstr1.test.tsx`.
- 1 existing test updated in `frontend/src/pages/reports/__tests__/ReportsHub.test.tsx`.
- No backend changes.
