# TASK-CUT-403 retro — CSV/Excel export per list

**Date:** 2026-05-11
**Branch:** task/CUT-403-exports
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 5, W5-C)

## Summary

Shipped CSV + XLSX export for every list view and report tab in the
Wave 5 scope, as a `?format=csv|xlsx` branch on the existing list
endpoints — no new "export-only" routes. One PR, FE wired end-to-end.

**Backend:**

- `backend/app/service/export_service.py` (new) — two pure helpers:
  - `to_csv(rows, columns) -> bytes` — UTF-8 BOM + CRLF line endings,
    comma + double-quote escaping via the stdlib `csv` module.
  - `to_xlsx(sheets) -> bytes` — multi-sheet workbook via `openpyxl`,
    Decimal money → numeric cell with `#,##0.00`, date → date cell
    with `yyyy-mm-dd`, header row bold + frozen pane at A2.
  - Both reject `float`-as-money at write time (CLAUDE.md rule). No
    pandas.
- `backend/app/service/export_builders.py` (new) — per-domain column
  schemas + row mappers (invoices, parties, items, receipts, vouchers,
  P&L, TB, Daybook, Stock summary, GSTR-1). One module so routers stay
  thin and the CSV / XLSX headers never drift from each other.
- 10 list / report endpoints learnt a `format` query param:
  `/invoices`, `/parties`, `/items`, `/receipts`, `/vouchers`,
  `/reports/pnl`, `/reports/tb`, `/reports/daybook`,
  `/reports/stock-summary`, `/reports/gstr1`. GSTR-1 xlsx is the
  multi-sheet variant (B2B / B2CL / B2CS / Export / HSN).
- New dep: `openpyxl>=3.1` in `pyproject.toml`.
- 17 end-to-end pytest tests in `tests/test_exports.py` plus 10 service
  unit tests in `tests/test_export_service.py`. RLS-isolation test
  verifies org A's CSV can't leak org B's parties.

**Frontend:**

- `frontend/src/lib/api/download.ts` (new) — `downloadExport({ path,
  format, fallbackFilename })` does fetch → blob → `<a download>`,
  parses the server-suggested filename out of Content-Disposition,
  falls back to a stamped default. Reuses the auth Bearer token from
  `authStore`.
- Buttons wired live on: InvoiceList, PartyList, ItemList,
  AccountingHub (Receipts / Vouchers tabs), ReportsHub. The old
  `useComingSoon` dialog is gone from each.
- 4 vitest unit tests on the download helper, 2 component tests on
  InvoiceList's button. NavigationAudit's "Export CSV opens
  ComingSoonDialog" test rewritten to assert the new live wiring.

**Verification:**
- `cd backend && uv run pytest -q` — 642 passed, 144 skipped (DB-bound
  tests pass on the local Postgres; the rest skip without DATABASE_URL).
- `uv run ruff check . && uv run ruff format --check .` — both clean.
- `cd frontend && pnpm exec vitest run` — 240 passed across 54 files.
- `pnpm tsc --noEmit && pnpm exec eslint . && pnpm exec prettier --check .` — all clean.

## Deviations from plan

### 1. PartyList didn't actually have an Export button to replace
The task prompt said "find existing `Export` buttons that are currently
`useComingSoon('TASK-NNN')` and replace". For PartyList, the existing
button was **Import** (still coming-soon, pointing at Wave 5
migration). I added two fresh buttons (Export CSV + Export Excel)
alongside the Import button, instead of replacing nothing.

- **Fixed by:** Added the Export buttons; left Import as-is (it points
  to TASK-CUT-502 now, the cutover runbook).
- **Why not caught in planning:** I read the prompt too narrowly. The
  spec ("every list view has Export CSV / Export Excel") is the source
  of truth; the "replace useComingSoon" sentence was a hint about
  where the seams were, not an inventory.
- **Impact on later tasks:** None — PartyList is now consistent with
  the other list pages.

### 2. ItemList also had no Export buttons
Same situation. Added them.

### 3. ReportsHub had a single "Export" button that became two
The original `useComingSoon` had a single Export button. To honour the
acceptance criterion ("Export CSV and Export Excel"), I split it into
two buttons. The CSV button is disabled on the GSTR-1 tab because
GSTR-1 is multi-sheet by definition — the BE returns the B2B sheet
flattened to CSV if forced, but the canonical filing is the workbook.
The disabled state is paired with a clear FE message when an XLSX-only
endpoint is asked for CSV.

- **Fixed by:** Two buttons; XLSX-only tabs disable the CSV button and
  surface a tooltip-grade message on click. The BE still serves the
  flattened-B2B CSV if a power user forces it.
- **Why not caught in planning:** Plan said "Export CSV and Export
  Excel"; I had to make a call on per-tab multi-sheet semantics.
  Decided in the retro flag below.
- **Impact on later tasks:** The GST-portal upload flow (future) will
  consume the XLSX directly; the FE doesn't need to round-trip through
  the CSV for that.

### 4. AccountingHub bank-accounts + cheques tabs don't export
The task prompt called out Receipts + Vouchers as the in-scope tabs
for AccountingHub. The hub has four tabs total; bank-accounts and
cheques don't have export-ready BE list endpoints today (cheques is
filtered-per-bank-account so the export semantic is unclear, and bank
accounts don't have a meaningful columnar view yet).

- **Fixed by:** Export buttons render only on receipts / vouchers
  tabs; the other two tabs hide the button.
- **Why not caught in planning:** Plan said "Receipts, Vouchers" —
  exactly what I shipped. Documenting it here so future me doesn't
  expand scope to the other tabs without thinking.

## Things the plan got right (no deviation)

- The `?format=` query param is exactly the lower-friction choice the
  prompt called out. Adding it to the existing list endpoints (vs new
  `/exports/...` routes) means permission gates and RLS scoping are
  reused without extra plumbing. The single change per router was
  about 30 lines.
- `openpyxl` works perfectly for the multi-sheet GSTR-1 case. Direct
  cell-level API means we control `cell.number_format` per type
  without pandas converting `Decimal` to `float` behind our backs.
- UTF-8 BOM + CRLF is the right invariant — the tests assert both and
  the service unit test (`test_csv_renders_rupee_glyph_in_utf8`) proves
  the ₹ glyph round-trips.
- Holding rows at <10k means a single in-memory `Response` is fine; the
  streaming branch is correctly deferred (flagged below).

## Pre-TASK-CUT-502 (Wave 5 — Cutover runbook) checklist

### 1. Document the Export workflow in the runbook
The cutover runbook should mention that Moiz can hit
`/parties?format=xlsx` to get a baseline export before the migration
upload, and again after, to diff in Excel. Same pattern for the TB
(`/reports/tb?as_of=…&format=xlsx`) as the cross-check against Vyapar.

### 2. Filename includes the report period for time-anchored reports
P&L → `pnl-<from>_to_<to>.xlsx`; TB → `tb-<as_of>.xlsx`; GSTR-1 →
`gstr1-<period>.xlsx`. Lists default to today's UTC date. If Moiz's
demo screenshots want a deterministic name, override via the FE
`fallbackFilename` argument before calling `downloadExport`.

### 3. Bank accounts / cheques exports — filed follow-up
Both tabs are reachable in AccountingHub but don't export. Suggested
follow-up: add `?format=` to `GET /bank-accounts` + `GET /cheques`
behind a small column schema. Easy lift; deferred because the v1
demo doesn't need it.

## Open flags carried over

- **Streaming for lists >10k rows.** The prompt called this out as a
  forbidden premature optimisation. The export bumps `limit` to 10k
  for the export branch, which matches what `compute_*` reports do
  anyway. If a tenant ever hits >10k receipts in a single firm-day
  view we'll see slow exports first, then file a streaming branch.
- **GSTR-1 CSV is B2B-only.** A power user who forces `?format=csv`
  on `/reports/gstr1` gets the B2B bucket flattened. The full filing
  is multi-sheet, so the FE disables the CSV button on that tab. If a
  future user needs the other buckets as separate CSVs, easy follow-up
  is one CSV per bucket downloaded as a zip.
- **Mock mode shows a friendly "set VITE_API_MODE=live" notice
  instead of fetching nothing.** The decision was: keep mock mode
  exactly what it says (no real backend), but don't gate the wired
  button behind a `useComingSoon`. The notice points users to the
  right knob without lying about the feature being incomplete.
- **OpenAPI spec lists `format` on the canonical endpoint shapes**
  (`/invoices`, `/parties`, `/items`, `/vouchers`, plus the four
  reports with matching paths). The spec uses legacy report paths
  (`/reports/day-book`, `/reports/profit-loss`) that don't match the
  actual implementation paths (`/reports/daybook`, `/reports/pnl`).
  This is a pre-existing spec/code drift; the export-format addition
  is on the spec's canonical paths so it documents the contract Moiz
  will publish to early-access users. Bringing the spec in line with
  the impl is filed as a separate cleanup.
- **Permissions are inherited from the JSON list.** A user with
  `sales.invoice.read` can export invoices; a user without can't. No
  new permission codes were added.

## Observable state at end of task

- No DB schema changes. Migration head unchanged.
- New deps: `openpyxl>=3.1` in `backend/pyproject.toml`. `uv sync`
  pulled it on the dev box; CI's `uv sync` will too.
- 27 new tests (10 service unit, 17 router integration). Frontend
  added 6 tests. Total deltas: backend +27, frontend +6, plus 1
  rewritten NavigationAudit assertion.
- The `useComingSoon('TASK-046'…)` and `useComingSoon('TASK-CUT-403'…)`
  affordances on InvoiceList + PartyList + ReportsHub are gone. Other
  pages (manufacturing pipeline, inventory list, admin hub, etc.) still
  use `useComingSoon` for unrelated coming-soon features — those are
  out of scope.

## Schema migration summary (per Ask-vs-Decide)

None. This task is BE/FE wiring + a new service module + tests; no
schema touches.
