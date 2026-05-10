# TASK-CUT-102 retro — Items + SKUs FE wired live

**Date:** 2026-05-10
**Branch:** task/CUT-102-items-skus-fe-live
**Wave:** 2
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 2 row CUT-102

## Summary

Items master is now a real page. `frontend/src/lib/queries/items.ts` was rewritten to dual-branch on `IS_LIVE`: live mode hits `GET /items`, `GET /uoms`, `GET /hsn`, and the per-item SKU endpoints; mock mode keeps the click-dummy click-through working. New pages `ItemList.tsx` (with `+ New item` modal) and `ItemDetail.tsx` (with inline `+ Add SKU` form) live under `/masters/items`. Sidebar Masters now exposes a sub-nav with Parties + Items. The InvoiceCreate item dropdown was repointed to read `primary_uom` and `gst_rate` from the new `ItemDetail` shape so the moment CUT-101 lands its parties wiring, the invoice form will send real party + item UUIDs to `POST /invoices` and end the 422 cascade audited in P0/P1-related issues.

`pnpm test` green (32 files, 123 tests), `pnpm typecheck` green, `pnpm lint` green. `make test` is green for the frontend portion; the backend portion is also green (121 passed, 529 skipped — same baseline as the merged Wave-1 PRs). `make lint` for the backend reformats `tests/test_receipt_after_finalize_allocates.py`, an untracked file authored by the concurrent CUT-104 worktree (not in this PR's diff).

## Deviations from plan

### 1. ItemDetail backend shape exposes `tracking` (not `tracking_type`)

Plan said the BE accepts `tracking_type`. Reality: the BE schema field is `tracking` (the column rename happened pre-Wave-2 in commit cba9051 "fix(tests): Item ORM column is `tracking`, not `tracking_type`").
- **Fixed by:** `lib/api/items.ts` named the type `BackendTrackingType` and the field `tracking`. The mapper coerces `null` → `'NONE'` to match the BE's enum default.
- **Why not caught in planning:** the audit cited `ItemCreateRequest` from `app/schemas/masters.py` which already had `tracking`, but the prompt template still listed it under "Optional = … tracking". Confirmed by reading the live schema before writing the FE type.
- **Impact on later tasks:** zero — Wave-3 stock adjustments will use the same shape.

### 2. SKU `attributes` field renamed (BE `variant_attributes` → FE `attributes`)

Plan said the FE consumes `attributes`. The BE actually returns `variant_attributes`. The mapper does the rename so consumers see a stable shape.
- **Fixed by:** `mapSku()` aliases `variant_attributes ?? {}` to `attributes`.
- **Why not caught in planning:** classic naming-drift; would have surfaced as a test failure if the test had hit a live BE.
- **Impact on later tasks:** zero — only `ItemDetail.tsx`'s SKU child UI consumes this field today.

### 3. InventoryList live SOH stubbed at 0

Plan said `useSkus()` should aggregate stock-on-hand from a BE endpoint. There is no aggregated SOH endpoint yet (the audit confirmed Wave 3+ TASK-CUT-204 is where stock adjustments land, and reports/stock-summary is Wave 4 TASK-CUT-302).
- **Fixed by:** `lib/queries/inventory.ts` `useSkus()` queries `GET /items` in live mode and stubs `on_hand: 0` per item, with a TODO comment pointing at CUT-204 / CUT-302.
- **Why not caught in planning:** the prompt did anticipate this — "let the FE compute SOH=0 for now". This is the implementation of that note.
- **Impact on later tasks:** `make-CUT-204` (stock adjustments) or `CUT-302` (reports) replaces the stub.

### 4. InvoiceCreate item rate prefill removed

Plan said the dropdown should pick a default rate. Reality: the live BE doesn't store a default sell price on items (only `default_cost` on SKUs), so the FE can't prefill rate.
- **Fixed by:** `InvoiceCreate.tsx` now prefills `gst_pct` from the item's `gst_rate` but leaves rate at the user's input (line still defaults to 0).
- **Why not caught in planning:** the click-dummy mock items have a `rate` field; ItemList/InvoiceCreate were originally written assuming this field would land in the BE.
- **Impact on later tasks:** zero — Wave 3 invoice flows will continue to ask the user for the rate per line.

## Things the plan got right (no deviation)

- The dual-branch `IS_LIVE` pattern from `dashboard.ts` and `invoices.ts` ports cleanly to items/skus.
- The `useIdempotencyKey()` hook + `api()` wrapper handle both the `Idempotency-Key` header and 401-refresh-retry without any per-mutation glue.
- Pragmatic vertical-slice TDD worked: one failing mapper test → minimum impl → green; one failing UI integration test → minimum dialog → green; SKU child UI test added last as the third increment.
- `lib/api/items.ts` as a separate module of types (not a fetch wrapper) lets future masters pages (CUT-201 PO, CUT-204 Stock adjustments) import shapes without depending on the React-Query hook.

## Pre-CUT-103 (Banking) checklist

### 1. Coordinate `lib/api/*` shape with CUT-101 (Parties)

CUT-101 is in flight in another worktree. When it lands, verify `lib/api/parties.ts` mirrors the shape of `lib/api/items.ts` (split between `BackendXxx` types, `XxxDetail` view types, and `XxxCreateBody` mutation bodies). If it diverges, file a small follow-up to align.

### 2. Don't trust `make lint` until backend untracked files are committed

`backend/tests/test_receipt_after_finalize_allocates.py` (CUT-104) is on disk in this worktree but not formatted. CI on the CUT-102 PR will not see it (only the diff is checked); but `make lint` locally will fail until CUT-104 lands.

### 3. After CUT-101 + CUT-102 both merge

Re-run the audit's P1 reproducer:
1. Sign up a fresh org via the Onboarding wizard.
2. Visit `/masters/items`, click `+ New item`, create "Cotton Suit / COTSUIT / FINISHED / PIECE / 5208 / 5%".
3. Visit `/masters/parties`, click `+ New party` (CUT-101 wiring), create an ACME customer.
4. Visit `/sales/invoices/new`. Customer dropdown shows ACME (not Anjali). Item dropdown shows Cotton Suit (not Georgette Cotton 44…). Save draft → Finalize → no 422.

If 422 still appears, the bug is downstream of items/parties — most likely in the `place_of_supply_state` derivation or in the GST tax-type inference (see audit P1-2 / P1-3 follow-ups).

## Open flags carried over

- **SOH on `/inventory`** stays at 0 until Wave 3+ ships (TASK-CUT-204 stock adjustments). UI displays 0 transparently.
- **Item edit / delete** not in this PR. The `+ New item` form covers create only. Edit/delete UI lands in a follow-up if Wave-2 demo finds it blocking.
- **HSN typeahead** vs simple `<select>`: shipped a select-from-list because the BE only seeds ~10 HSN rows. If real customers need 5-digit search across the 8000-row HSN catalog, swap to a typeahead in a follow-up.
- **OpenAPI codegen (CUT-106)** will regenerate `lib/api/items.ts` types automatically. Mark this file as "hand-rolled until CUT-106" in the file's docstring (already done).

## Observable state at end of task

- Five new files, six modified.
- `pnpm test` 32 files / 123 tests, all green.
- `pnpm lint` clean. `pnpm typecheck` clean.
- The dev box has uncommitted CUT-104 + concurrent-agent files on disk that this branch deliberately does NOT include. They're owned by other Wave-2 agents.
- New routes: `/masters/items` and `/masters/items/:id` accessible from the Masters sidebar group.
