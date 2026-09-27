# TASK-195 retro — GSTR-1 rate-wise rows + equal-halves CGST/SGST

**Date:** 2026-09-03
**Branch:** fix/issue-195
**Commit:** (on `fix/issue-195`, NOT merged — see gate)
**Plan:** GitHub issue #195 comment (implementation plan)

## Summary

Fixed the two GSTR-1 blockers: (a) CGST != SGST from halving a full-rate line
total and dumping the odd paisa on CGST, and (b) a blended per-invoice
`gst_rate` (e.g. 10.34%) in B2B rows instead of one row per statutory slab.
End-to-end: new `gst_service.compute_line_gst` computes each half as
`round(taxable × rate/200)` (explicit `ROUND_HALF_EVEN`), the sales write path
uses it in a second pass (subsuming #193 NIL zeroing), `split_tax` now returns
equal halves, `compute_gstr1` was rewritten to query at line level grouped by
`(invoice, gst_rate)` so B2B/B2CL/EXPORT emit one row per slab, B2CS groups by
`(state, slab)` with a distinct-invoice count, and the HSN summary is rate-wise
with a new `gst_rate` field. Schemas, OpenAPI spec, XLSX HSN sheet, FE types +
ReportsHub tables, and a dry-run-first repair script all moved with it. Backend
`ruff`/`mypy` clean; 350 related backend tests pass; FE typecheck + 37 reports
vitest + eslint/prettier clean; no API-type drift. **NOT merged** — tax logic
is Ask-vs-Decide gated on Moiz + CA.

## Deviations from plan

### 1. No Alembic migration (as planned) and `_NIL_TAX_TYPES` removed from sales_service
Plan predicted no DDL migration — held. Additionally, the #193 explicit NIL
zeroing block in `create_draft_invoice` became dead once `compute_line_gst`
returns an all-zero split for the NIL family, so I removed the now-unused
`_NIL_TAX_TYPES` constant in `sales_service.py` (the `accounting_service.py`
guard set is untouched).
- **Fixed by:** second-pass loop calls the helper for every line; NIL tests stay green.
- **Why not caught in planning:** plan said "subsumes #193's zeroing block" but
  didn't note the constant would go unused.
- **Impact on later tasks:** none — zero behaviour change for NIL invoices.

### 2. FE never rendered the EXPORT bucket
`ReportsHub` renders B2B / B2CL / B2CS / HSN only (no Export section) —
pre-existing. Left as-is (out of scope); export rows are still returned by the
API and appear in the XLSX export.

### 3. HSN grouping keeps tax_type in the SQL key
Plan said group `(hsn, uom, gst_rate)`. To keep IGST vs CGST/SGST honest when
the same HSN+rate is sold both intra- and inter-state, the SQL still groups by
`(hsn, uom, gst_rate, tax_type)` and folds into one output row per
`(hsn, uom, gst_rate)`. Same output shape the plan wanted; correct split.

## Things the plan got right (no deviation)

- Two-pass ordering (provisional full-rate GST for the B2CL ₹2.5L bucket, final
  tax after PoS) works exactly as described; 1-paisa drift can't flip `> 250000`.
- Existing single-rate GSTR-1 tests stayed green (one rate → one row).
- `split_tax` legacy odd-input behaviour (equal halves, ≤1 paisa GL divergence)
  is the right call; documented in the docstring.
- Canonical vector 233.31 @ 5% → 5.83/5.83, line 11.66 verified across unit,
  service, PDF, and GSTR-1 layers.

## Ask-vs-Decide gate (BLOCKING merge)

**PENDING MOIZ + CA SIGN-OFF.** Tax logic + BREAKING `/reports/gstr1` API shape.
CA must confirm: (1) half-rate method `CGST = SGST = round(taxable × rate/200)`;
(2) rounding mode — kept `ROUND_HALF_EVEN`, now explicit, one-line switch to
`ROUND_HALF_UP` if CA prefers; (3) legacy policy — DRAFT repaired in place,
FINALIZED report-only (forward-only, or wipe/repost QA orgs); (4) B2B one row
per rate with `invoice_value` repeated. Do NOT merge until recorded on the PR.

## Data repair

`backend/scripts/repair_gst_line_amounts.py` — dry-run default. DRAFT invoices
recomputed + headers resummed; FINALIZED reported only (GL already posted).
Composes with #193 (NIL zero → clean), #194 (non-GST firm zero-rate → clean),
#199 (cancelled invoices excluded from GSTR-1 by lifecycle, untouched here).
Run against the real DB before any GSTR-1 filing prep.

## Migration & composition notes

- **Migration:** none needed — the split is computed at read time; rate-wise
  rows come from existing `si_line.gst_rate` / `gst_amount`. No `down_revision`
  change; worktree head stays `199_invoice_cancel`.
- **#193/#194:** `compute_line_gst` returns zeros for the NIL family and the
  helper never re-introduces GST on NIL invoices; non-GST firms are still
  refused (422) by `compute_gstr1` before any rate logic runs.
- **#199:** cancelled invoices remain excluded from GSTR-1 via `_GSTR1_LIFECYCLE`.

## Observable state at end of task

- `frontend/node_modules` was missing on this worktree; ran `pnpm install`
  (fast, lockfile present) to run `gen:types` / typecheck / vitest.
- `pnpm gen:types` was re-run so `src/types/api.ts` matches the updated
  `scripts/openapi-snapshot.json` (`pnpm check:types` clean).
- Backend test env needs `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.

## CA-review correction (2026-09-26) — B2CL threshold is date-dependent

**What changed.** `B2C_INTER_STATE_THRESHOLD = ₹2,50,000` is replaced by
`gst_service.b2cl_threshold(invoice_date)` (+ `is_b2cl_value`): ₹2,50,000 for invoices dated
before 2024-08-01, ₹1,00,000 on/after. B2CL = invoice value (incl. tax) **strictly greater than**
the threshold. Used by the PoS engine's `gstr1_section` hint (now given `invoice_date` by
`sales_service.create_draft_invoice`) and by the authoritative GSTR-1 classifier
`reports_service._bucket_for_invoice` (per-invoice `invoice_date`). Reporting bucket only — tax
type and amounts are unaffected.

**Why / legal basis.** Notification 12/2024-Central Tax (10-Jul-2024) lowered the GSTR-1 Table 5
(B2CL) threshold for inter-state B2C invoices from ₹2.5 lakh to ₹1 lakh w.e.f. 01-Aug-2024.
The code still used ₹2.5L, so inter-state B2C invoices between ₹1L and ₹2.5L were being
consolidated in B2CS instead of reported invoice-wise in B2CL.

**Tests.** Boundaries: 2024-08-01 ₹1,00,001 → B2CL, ₹1,00,000 → B2CS; 2024-07-31 ₹1,50,000 →
B2CS; tax-inclusive value (taxable ₹95,239 @5% = ₹1,00,000.95) → B2CL. Three existing tests that
pinned the ₹2.5L boundary without a date were given a 2024-07-31 invoice date (their scenario is
the pre-cutover law); expectations unchanged.

**Note.** `determine_place_of_supply(invoice_date=None)` uses the current (₹1L) threshold; its
`gstr1_section` is not persisted — the filed bucket always comes from `reports_service`.

PENDING MOIZ + CA SIGN-OFF.
