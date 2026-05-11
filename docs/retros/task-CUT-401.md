# TASK-CUT-401 retro — Job-work FE wired live

**Date:** 2026-05-11
**Branch:** task/CUT-401-jobwork-fe
**Wave:** 5
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 5 row CUT-401

## Summary

`/jobwork` is now a live textile job-work tracker. The Wave-design
click-dummy (which read static `mock/jobwork.ts` rows) is gone; the
page renders `GET /job-work-orders` and `GET /parties?party_type=karigar`
against the Wave-4 BE shipped in CUT-305.

Three user actions are wired:

- **Send out** (`+ Send out` header CTA) opens `<SendOutDialog>` — a
  single-line karigar/item/qty/uom/operation form. Submitting POSTs to
  `/job-work-orders` with an `Idempotency-Key` header; on 201 the
  active-jobs list and karigar-cards rollup refetch.
- **Receive back** (per-row CTA in the Active jobs table) opens
  `<ReceiveBackDialog>` pre-targeted at the chosen JWO. The dialog
  renders one row per JWO line capturing finished + wastage qty, with
  a client-side `received + wastage <= open qty` invariant that mirrors
  the BE's 422 (saves a round trip). POST hits
  `/job-work-orders/{id}/receive`.
- **Per-karigar rollup** (`<KarigarCards>`) groups every JWO by
  `karigar_party_id` and surfaces open-order count + pending qty by
  uom. `groupByKarigar(orders)` lives in `lib/queries/jobwork.ts` so
  the rollup is a pure function and unit-testable as a function of the
  JWO array.

**Wire shapes** are pulled from `@/types/api` (the OpenAPI snapshot
from CUT-106) so they stay locked to the BE schemas in `schemas/jobwork.py`.
No hand-rolled `BackendJobWorkXxx` interfaces.

**Money / quantity discipline:** quantities go over the wire as
`Decimal`-as-string. Fabric job-work runs in 0.5m / 1.5m lots, so the
form preserves the user's input string exactly (`qty_sent: qty` not
`qty_sent: String(qtyNum)`); only the rollup display parses to Number
for `formatQty`, never for hitting the BE.

**Verification:**

- `cd frontend && pnpm exec vitest run` — 52 files / 237 tests / 0
  failures (+3 from 234 post-Wave-4).
- `pnpm tsc --noEmit` — clean.
- `pnpm exec eslint . && pnpm exec prettier --check .` — clean.
- `pnpm check:types` — OpenAPI snapshot drift gate green.
- `grep -rn "fakeFetch\|@/lib/mock/identity\|@/lib/mock/jobwork" src/pages/jobwork src/lib/queries/jobwork.ts`
  — clean (no fakeFetch in the new module; mock branches resolve via
  `Promise.resolve()` directly).

No backend changes. The CUT-305 BE already exposes everything CUT-401
needs.

## Deviations from plan

### 1. Mock branch stripped of `fakeFetch`

Plan said "mock + live branches (see `stock-adjustments.ts`)" which
implies the `fakeFetch` envelope. Acceptance criteria then said "No
`fakeFetch` in `pages/jobwork/*` or `lib/queries/jobwork*` (grep
clean)." These were in tension.

- **Fixed by:** mock branches resolve via `Promise.resolve(...)` with
  no artificial delay. Job-work was never in the click-dummy fixtures
  (the seed `mock/jobwork.ts` data was tied to the visual click-dummy
  only, not to live workflows), so mock mode legitimately has no
  fixture data to surface; an empty list / synthetic-201 path is fine.
- **Why not caught in planning:** the conflict was visible only when
  re-reading the acceptance criteria. Resolved in favor of grep-clean.

### 2. Single-line send-out form (not multi-line)

BE accepts a multi-line JWO (`lines: [...]`). The dialog ships with
one line. Textile job-work in practice is one fabric item + one
operation per challan (e.g. "send 100m fabric to Imran for Aari
embroidery"), so multi-line would be cargo-cult complexity for v1.

- **Fixed by:** form models one `{ item_id, qty_sent, uom, notes }`
  row and wraps it in a `lines: [...]` body. Adding multi-line is a
  pure FE addition if Moiz hits a case that needs it.
- **Why not caught in planning:** the spec described "+ Send out" as a
  single CTA without specifying line cardinality. Made the judgment
  call based on the textile-trade reality.

### 3. Receive-back operates against an existing JWO row

Plan said `Receive back` is a header CTA (next to `+ Send out`).
Reality: the BE's `POST /job-work-orders/{id}/receive` requires a JWO
id in the URL — there's no "global receive" mode. A header CTA would
need to ask "which JWO?" first.

- **Fixed by:** moved the Receive-back affordance to a per-row button
  in the Active jobs table. Clicking it opens the dialog pre-targeted
  at that JWO with its open lines already rendered. The header
  Receive-back button from the click-dummy is removed.
- **Why not caught in planning:** the click-dummy's "Receive back"
  header button was a placeholder; in a live flow it has to know
  which JWO to receive against, and the only sane place to acquire
  that intent is from the row itself.

### 4. JobWorkOverview test file was rewritten

The pre-existing `JobWorkOverview.test.tsx` exercised the click-dummy
(`expect(screen.getByText('JO/25-26/00102')).toBeInTheDocument()` —
that string came from `mock/jobwork.ts`). Once the page reads from the
BE the assertion is meaningless.

- **Fixed by:** replaced with a 4-test integration file pinning
  `IS_LIVE = true` via `vi.mock('@/lib/api/mode')` (same pattern as
  `AdjustStockDialog.test.tsx`). The four tests map 1:1 to the CUT-401
  acceptance criteria.
- **Why not caught in planning:** expected — the click-dummy test was
  going to be obsolete the moment the page went live.

### 5. Test cleanup adds explicit `cleanup()`

When the four new tests ran inside the full suite, the second and
fourth tests intermittently failed because earlier tests left a React
tree mounted (visible as `act(...)` warnings naming `SendOutDialog`
inside the unrelated `Receive back` test).

- **Fixed by:** added `cleanup()` from `@testing-library/react` to
  `afterEach`. In isolation the tests passed regardless; in the full
  suite the leftover DOM was tripping up the dialog-open detection.
- **Why not caught in planning:** the existing `AdjustStockDialog`
  test (which I modelled mine on) uses a single `beforeEach`-then-
  `it` pair, so the issue doesn't surface there. The job-work file
  has four `it`s in one describe, each calling `renderJobWork()`.

## Things the plan got right (no deviation)

- The CUT-305 BE handed me everything: `firm_id`-scoped list, status
  enum, line-level qty fields, response shapes. Zero BE touches needed.
- The `groupByKarigar` rollup falls out of the JWO list naturally —
  no extra report endpoint, no client-side join against a separate
  receipts list. The list response already includes lines on detail
  (which I don't use), but the same line shape on the list is what
  feeds the rollup.
- The retro pre-checklist item #2 ("karigar dropdown filter
  `kind=KARIGAR`") was right — `useKarigars()` calls
  `liveListParties({ party_type: 'karigar' })` which the BE honors via
  the `PartyTypeFilter` literal in `schemas/masters.py`.
- The retro pre-checklist item #3 (client-side `received + wastage <=
  open qty`) shipped exactly as specified in `ReceiveBackDialog`.

## Open flags carried over

- **Send-out form is one item per challan.** Adding multi-line is a
  pure FE change (the BE accepts it). Flagged in deviation #2.
- **Mock mode renders an empty `/jobwork`** because there's no
  click-dummy fixture data. This is fine for the v1 cutover where
  mock mode is only used for tests; the day the design click-dummy
  comes back into product demos we'd want to add a synthetic JWO
  list. Not a blocker.
- **Karigar card "open orders" count uses `status != CLOSED && !=
  CANCELLED`.** PARTIAL_RECEIVED counts as open. Matches the BE state
  machine.
- **ITC-04 surfacing is CUT-403's job** (Wave 5 export task). The
  `/reports/itc04` endpoint exists but no FE consumer wires it; that's
  by design per the prompt.

## Pre-task checklist for the next agent on jobwork (CUT-403 export)

1. The ITC-04 export needs to decrypt `gstin` at the API boundary
   (see CUT-305 open flag). The Pydantic model carries `karigar_gstin:
   str | None` and CUT-305 leaves it `None` because party.gstin is
   encrypted bytes. CUT-403 will need to swap in the existing
   envelope-crypto helper.
2. The FE jobwork module exports `JobWorkOrder`, `JobWorkReceiptResponse`,
   `groupByKarigar`, `KarigarRow`, etc. from `lib/queries/jobwork.ts`
   — reuse those types for the ITC-04 export view instead of
   regenerating shapes.

## Observable state at end of task

- New FE files: `lib/queries/jobwork.ts`, `pages/jobwork/{SendOutDialog,
  ReceiveBackDialog, KarigarCards}.tsx`. JobWorkOverview.tsx is fully
  rewritten.
- Test count: 234 → 237 (+3 net — the existing JobWorkOverview test
  was replaced 1:1 by four new live-mode integration tests, so net is
  +3 not +4).
- Stripped imports: `@/lib/mock/jobwork` and `useComingSoon` no longer
  imported anywhere under `pages/jobwork/`. The `mock/jobwork.ts`
  fixture file still exists (unused) — left in place for the design
  click-dummy demos; safe to delete in a follow-up if Moiz wants the
  asset trimmed.
- No schema migration; no BE code changes; OpenAPI snapshot unchanged.
