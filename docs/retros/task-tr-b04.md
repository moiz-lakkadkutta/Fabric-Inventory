# TASK-TR-B04 retro — Ageing / Ledger / Party statement / ITC-04 report tabs

**Date:** 2026-05-15
**Branch:** task/tr-b04-report-tabs
**Commit:** `<sha>` (pending PR merge)
**Plan:** TASK-TR-B04 brief (no plan file)

## Summary

Closed the FE gap that left four already-live `/reports/*` endpoints
without any UI consumer. The Reports page now has nine tabs (was five):
P&L, Trial balance, GSTR-1, Stock, Daybook, **Ageing**, **Ledger
statement**, **Party statement**, **ITC-04**. Each new panel hosts its
own picker state (date / ledger / party / month), renders the response
through paise-converted view-models (mirroring the B03 GSTR-1 pattern),
and shows empty / loading / error states with no silent failures. Lint,
tsc, codegen-drift, and the full vitest suite (290 tests; 20 new) are
all green.

## What landed

- `frontend/src/lib/queries/reports.ts`
  - Added `AgeingVM` / `AgeingRowVM`, `LedgerStatementVM` / `LedgerStatementRowVM`,
    `PartyStatementVM` / `PartyStatementRowVM`, `Itc04VM` / `Itc04SendOutRowVM` /
    `Itc04ReceiveRowVM` view-model types — all money mapped through
    `rupeesToPaise` (signed-aware via `signedRupeesToPaise` for opening /
    closing / balance fields), qty fields parsed as floats.
  - Added `useAgeing(asOf?)`, `useLedgerStatement(ledgerId, fromDate?, toDate?)`,
    `usePartyStatement(partyId, fromDate?, toDate?)`, `useItc04(firmId, period)`.
    Selector-gated hooks use `enabled: Boolean(...)` so the panel can
    render a "pick a ledger / pick a party" empty-state before any
    fetch.
  - `useItc04` is the only one that needs `firm_id` in the query
    string; the panel pulls it from `useMe()` (the other endpoints
    derive firm from the JWT server-side).
  - Re-exported `mapAgeing*` / `mapLedgerStatement*` / `mapPartyStatement*` /
    `mapItc04*` helpers in `_internal` for future unit tests.
- `frontend/src/lib/queries/accounts.ts`
  - New `useLedgers()` + `LedgerPickerItem` projection — fetches up to
    200 active ledgers from `GET /ledgers?limit=200&is_active=true` to
    populate the Ledger statement picker. RLS-scoped per usual.
- `frontend/src/pages/reports/ReportsHub.tsx`
  - Tab union extended to nine: added `'ageing' | 'ledger' |
    'party-statement' | 'itc04'`.
  - Four new panels: `AgeingPanel`, `LedgerStatementPanel`,
    `PartyStatementPanel`, `Itc04Panel`. Each owns its picker UI,
    KPI banner, table(s), and empty-state messaging.
  - `reportExportEndpoint()` returns `null` for the four new tabs, and
    the Export CSV / Export Excel buttons disable themselves with a
    "Export not available for this report" tooltip + alert. No
    invented backend behaviour — the ITC-04 docstring explicitly
    defers PDF/Excel rendering to Wave-5 CUT-403, and the other three
    don't accept a `format=` param today.
  - All picker state hoisted to `ReportsHub` so a future page-level
    header picker is a small refactor.
- `frontend/src/pages/reports/__tests__/`
  - `ReportsHub.ageing.test.tsx` — 5 specs (URL shape, party rows + 5
    buckets, total-outstanding banner, empty state, as-of date
    refetch).
  - `ReportsHub.ledger-statement.test.tsx` — 5 specs (picker
    population from `GET /ledgers`, URL on selection, statement
    rendering + running balance, pick-a-ledger empty state,
    from/to query-param wiring).
  - `ReportsHub.party-statement.test.tsx` — 4 specs (picker, URL,
    rendering, empty state).
  - `ReportsHub.itc04.test.tsx` — 6 specs (firm_id + period URL,
    Send-outs + Receipts headings, send-out row contents, receipt row
    contents incl. wastage, empty state both sections, period
    refetch).

## OpenAPI types used

All four endpoints already had schemas in the codegen output — no
`pnpm gen:types` regen needed. Mapped these straight into the new
view-models:

- `components['schemas']['AgeingResponse']`,
  `components['schemas']['AgeingRow']`
- `components['schemas']['LedgerStatementResponse']`,
  `components['schemas']['LedgerStatementRow']`
- `components['schemas']['PartyStatementResponse']`,
  `components['schemas']['PartyStatementRow']`
- `components['schemas']['ITC04Report']`,
  `components['schemas']['ITC04SendOutRow']`,
  `components['schemas']['ITC04ReceiveRow']`
- Re-used: `components['schemas']['LedgerListResponse']`,
  `components['schemas']['LedgerResponse']` for the picker.

`pnpm check:types` confirms `scripts/openapi-snapshot.json` matches
`src/types/api.ts` — no drift.

## Backend response-shape surprises

### 1. Ledger / party statement query params are `from` / `to`, NOT `from_date` / `to_date`

The task brief used `from_date` / `to_date` for the query params, but
the OpenAPI operations show `?from=YYYY-MM-DD&to=YYYY-MM-DD`. The
response envelope still has `from_date` and `to_date` (window
boundaries). The hooks send the bare-name params and read back the
`_date`-suffixed fields. Easy to miss if you only skim the schema.

### 2. ITC-04 `total_send_outs` / `total_receipts` are row counts, not money

These fields look financial but are integer counts of rows in the
respective arrays. Don't paise-convert them. The schema marks them
as `number` (default 0) and `send_outs` / `receipts` as optional
arrays — `?? []` defaults applied in the mapper to keep the panel
tolerant of an envelope that omits them entirely.

### 3. Ageing buckets are `current` / `bucket_1_30` / `31_60` / `61_90` / `bucket_over_90`

Per the schema docstring, the five buckets sum exactly to
`outstanding` per row. The panel renders Current / 1-30 / 31-60 /
61-90 / >90 in that order, with the per-party total in a bolded
column on the right.

### 4. ITC-04 needs `firm_id` in the query string

The other three new endpoints (ageing, ledger, party-statement)
derive firm from the JWT. ITC-04 is the odd one out — its operation
schema marks `firm_id: string` as REQUIRED. The panel pulls the
current firm from `useMe()`; if `me.firm_id` is null the panel shows
a "no firm selected" error state instead of issuing a 422.

## Deviations from plan

### 1. Export buttons disable rather than offering a JSON-only fallback

The brief said "If only JSON, surface 'Export not available for this
report' rather than guessing a CSV shape." Implemented as a disabled
button with the message in a `title` tooltip + an alert if clicked.
Cleaner than the alternative of a separate per-panel export UI, and it
matches the existing CUT-403 disabled-export pattern used elsewhere.

### 2. Empty state copy distinguishes from the picker's placeholder

The "pick a ledger / pick a party" empty-state was initially worded
identically to the `<option value="">— Choose a ledger —</option>`
picker placeholder, which broke `getByText()`. Empty-state copy
disambiguated: "Pick a ledger to view its statement."

### 3. Date inputs use HTML `<input type="date">`

The click-dummy uses a custom DatePicker elsewhere, but `<input
type="date">` is the lightest path here and renders identically to
the existing GSTR-1 `<input type="month">` picker (B03 precedent).
A future shared DateRangePicker is a separate refactor.

## Pre-next-task checklist

### 1. Picker state is panel-local — hoist target

`ageingAsOf`, `ledgerId/ledgerFrom/ledgerTo`,
`partyId/partyFrom/partyTo`, `itc04Period` all live in `ReportsHub`
state today. If TASK-TR-B05 or beyond consolidates pickers into a
single page-level header, this is the migration point.

### 2. Ledger picker pulls all active ledgers (no typeahead)

`useLedgers()` returns up to 200 rows; the picker is a plain
`<select>`. Typical CoAs have ~30–60 ledgers so this scales for now.
If a firm crosses ~200 ledgers, switch the picker to a typeahead
backed by a server-side search query.

### 3. Party picker re-uses `useParties()` — order is whatever BE returns

Parties aren't pre-sorted in the picker today. If users want
alphabetical, sort client-side here or push a server-side sort
parameter.

### 4. Export-not-available is a placeholder

When CUT-403 lands the Wave-5 CSV/XLSX renderers for these four
reports, extend `reportExportEndpoint()` (the switch already has the
named cases for the new tabs) and the disabled-state path goes away
automatically.

### 5. ITC-04 quarterly periods (YYYY-QN) not surfaced in the picker

The BE accepts both monthly (`YYYY-MM`) and quarterly (`YYYY-QN`)
period strings per the schema, but the UI uses a plain
`<input type="month">` so only monthly is reachable. A radio
toggle for quarterly would unlock the quarterly filing window;
out of scope here.

### 6. Signed balance formatting uses "Cr" suffix

`formatSignedINR()` renders negative paise as `"... Cr"` for credit
balances, the Indian-accounting convention. Used by both the ledger
and party statement balance columns + KPI banners. If a future
design wants brackets `(...)` instead, this is the one place to
change.

## Open flags

- **No E2E Playwright spec.** The 20 vitest integration specs cover
  the live-mode wiring at the fetch boundary; the existing reports
  folder has no Playwright precedent to copy.
- **No print / PDF path** for these four reports — the existing
  Print button still triggers the global `useComingSoon` dialog.
  PDF rendering for Reports is TASK-046, not TR-B04.

## Observable state at end of task

- New env requirements: none.
- Running services: none new.
- Untracked files: none.
- 20 new tests across 4 files in `frontend/src/pages/reports/__tests__/`.
- No existing tests modified.
- No backend changes.
- No OpenAPI codegen regen.
