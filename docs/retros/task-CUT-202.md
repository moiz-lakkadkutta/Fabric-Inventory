# TASK-CUT-202 retro — GRN + Purchase Invoice FE wired live

**Date:** 2026-05-10
**Branch:** task/CUT-202-grn-pi-fe-live
**Wave:** 3 (Procurement + Sales lifecycle + PDF + Stock)
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 3 row W3-B

## Summary

GRN and Purchase Invoice screens now run against the live backend.
`/purchase/grns` lists real GRNs; `/purchase/grns/new` picks a confirmed
PO via `GET /purchase-orders` (filtered locally to `CONFIRMED |
APPROVED | PARTIAL_GRN`), pulls the PO detail to default each line's
received qty to ordered qty, and POSTs to `/grns` with an
`Idempotency-Key` header — landing on the new detail page that shows
the GRN number plus a link to the source PO. `/purchase/invoices`
mirrors the shape: list → create-from-GRN → detail with `Post` and
`Void` lifecycle buttons that wire to `/purchase-invoices/{id}/post`
and `/purchase-invoices/{id}/void`.

`pnpm exec vitest run` (39 files / 165 tests / 0 failed),
`pnpm exec tsc --noEmit`, `pnpm exec eslint .`, `pnpm exec prettier
--check .` all clean. `make lint` clean (ruff + ruff format + mypy on
backend, eslint + prettier + tsc on frontend). `uv run pytest -q` on
backend: 121 passed, 541 skipped — same baseline as the merged Wave-2
PRs.

## Deviations from plan

### 1. Added a small live PO reader (`liveListPos` + `liveGetPo`) in CUT-202's lane

The plan said "Files (likely)" only listed the GRN/PI hooks and pages.
Reality: the GRN form has to pick a confirmed PO and read its lines
(to default qty_received = qty_ordered), so the GRN lane needs a
read-only PO API client. CUT-201 (PO list/create FE wiring) is a
sibling task that will land its own composing hook on top of
`liveListPos`. To stay strictly inside CUT-202's lane I:

- shipped `frontend/src/lib/api/purchase-orders.ts` (read-only, types-
  derived from the codegen output);
- shipped `useConfirmedPosForGrnForm()` and `useLivePo()` hooks in
  `lib/queries/grn.ts` (rather than touching the existing
  `lib/queries/purchase.ts` mock-only module so CUT-201 can wire its
  own `usePurchaseOrders()` live branch without conflict).

Zero overlap with CUT-201's expected files; trivial follow-up to
extract the live PO hooks into `lib/queries/purchase.ts` once that
task lands.

### 2. GRN/PI list mock branch is intentionally empty

The pattern from CUT-101 (parties) and CUT-102 (items) preserves a
click-dummy mock store so navigation works pre-live. The procurement
domain wasn't deeply click-dummy'd at the GRN/PI level — only POs
were. Rather than fabricate fixtures, the mock branch returns `[]`
for list reads and rejects mutations with a clear error message. This
matches the wave-3 expectation that procurement will be wired-live-
or-empty in the click-dummy session — the live branch is the canonical
path.

### 3. Money is rendered as the BE Decimal-as-string (not paise)

Sales invoices map `rupeesToPaise` at the boundary so the existing
`formatINR(paise)` helpers work. For GRN and PI we leave the BE's
`Decimal`-as-string values (`"50000.00"`) as-is in the UI. Reasoning:
the Wave-3 demo doc only asks the user to *verify* the numbers, not
exercise paise-aware arithmetic; mapping into paise just to format
back into rupees costs LOC and doesn't change correctness for these
read-only stats. When the Reports BE (CUT-105) cross-references PI
amounts, the BE handles the math — the FE only displays what the BE
returns. Money is never in float on either side of the wire.

### 4. PI lines default `gst_rate = 5%`, not from the GRN

The BE's GRN response doesn't carry GST rate (GST lives at the item
master level). The PI create form pre-fills `gst_rate = 5` per line as
a sensible default; the user edits before posting. A future
CUT-follow-up could fetch the item's GST rate via `GET /items/{id}`
when the GRN's lines reference it — out of scope for this PR.

## Things the plan got right (no deviation)

- The `vi.mock('@/lib/api/mode')` + `globalThis.fetch = vi.fn()`
  pattern from `Parties.live.test.tsx` ports verbatim — three live
  tests run against fully-mocked fetch, no MSW.
- `useIdempotencyKey()` mints one UUID per form mount and resets after
  success. POST/POST/POST mutations all carry the header — verified
  by regex match in the live tests.
- Splitting the API layer (`lib/api/grn.ts`,
  `lib/api/purchase-invoices.ts`) from the React-Query layer
  (`lib/queries/`) lets future pages (e.g. a GRN export, a PI ledger
  cross-link) import shapes without depending on the React-Query
  module.
- Each page is < 350 LOC and has a single aggregate concern. The
  Field/Input/Pill/Skeleton kit handled all form ergonomics with no
  new deps.

## Pre-CUT-203 (Sales Order + Delivery Challan) checklist

### 1. Apply the same dual-branch pattern

CUT-203 should `cp` the structure of `lib/api/grn.ts` +
`lib/queries/grn.ts` for sales-order and delivery-challan. The
mock-branch returns `[]` if the existing click-dummy doesn't model the
flow; live-branch hits the real BE endpoints.

### 2. PO live wiring (CUT-201) supersedes my temporary live PO reader

When CUT-201 lands `usePurchaseOrders()` with a live branch in
`lib/queries/purchase.ts`, my `useConfirmedPosForGrnForm()` /
`useLivePo()` hooks should be folded into CUT-201's code. Trivial
PR; no behavior change.

### 3. After CUT-202 + CUT-201 + CUT-203 land, exercise the full lifecycle on a live tenant

Sign up Audit Co → create supplier party → create item → build PO
(CUT-201) → approve → confirm → build GRN against PO (CUT-202) →
build PI from GRN (CUT-202) → post PI → check Vouchers tab on
`/accounting` for the input-GST + payable journal entries.

### 4. Item GST default in PI form

The PI create form hard-codes `gst_rate = 5%` per line. If the wave-3
demo finds it blocking, file a follow-up to fetch the per-line item's
GST rate from `GET /items/{id}` on PO/GRN line load. ~30 LOC.

## Open flags carried over

- **Item code/name not displayed in GRN/PI line tables.** Both BE
  responses carry `item_id` only — no `item_code` or `item_name`
  projection on the GRN/PI line. Showing the truncated UUID is ugly
  but functional. Either add a name projection on the BE
  `GRNLineResponse`/`PILineResponse` or fetch items in a side-car
  query and zip on the FE. Defer until a real user complains.
- **No `useVoidGrn` shipped.** GRN soft-delete exists (`DELETE
  /grns/{id}`) but the spec only flagged it as optional. Add when
  needed; ~20 LOC.
- **Mock-branch failures emit a clear "not implemented in click-dummy"
  rejection.** OK because the PR is meant to be run in `IS_LIVE=true`
  mode against a real backend. If the wave-3 click-dummy demo wants to
  exercise procurement without a backend, file a follow-up to
  scaffold mock fixtures.
- **`partyId`/`firmId` come from the PO/GRN payload, not from the
  authStore's `me.firm_id`.** The signed-in user's active firm is
  hopefully the same as the source PO's firm — in a multi-firm org
  these can drift. The BE will reject the create with a 422 if they
  don't match; surface to the user via the existing inline error
  panel. Acceptable for MVP.

## Observable state at end of task

- Worktree at `/Users/moizp/fabric/.claude/worktrees/agent-a9276f54c3b06b1dd`,
  branch `task/CUT-202-grn-pi-fe-live` off `main`.
- 11 new files (3 api wrappers + 2 query modules + 6 pages + 2 tests +
  this retro), 1 modified (`App.tsx` adds 6 routes).
- Frontend vitest: 39 files / 165 tests / 0 failed. Lint + tsc clean.
- Backend untouched. No Alembic migration. No OpenAPI delta — all
  endpoints existed already.
- New routes: `/purchase/grns`, `/purchase/grns/new`,
  `/purchase/grns/:id`, `/purchase/invoices`, `/purchase/invoices/new`,
  `/purchase/invoices/:id`.
