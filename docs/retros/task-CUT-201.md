# TASK-CUT-201 retro — Purchase Order FE wired live

**Date:** 2026-05-10
**Branch:** task/CUT-201-purchase-order-fe-live
**Wave:** 3 (Procurement + Sales lifecycle + PDF + Stock)
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 3 row W3-A

## Summary

`/purchase`, `/purchase/new`, and `/purchase/:id` now read/write through the live BE (`GET /purchase-orders`, `POST /purchase-orders`, `POST /purchase-orders/{id}/{approve,confirm,cancel}`) when `IS_LIVE` is true; the click-dummy mock branch is preserved for tests / dev-no-backend per Q6. The `New PO` button on the list opens a real form with a supplier dropdown sourced from the new `useSuppliers()` hook (parties with `is_supplier=true`), an item dropdown wired to `useItems()`, and a line-item builder. Submit posts a `POCreateRequest` with an `Idempotency-Key` and lands on the new detail page. The detail page exposes Approve / Confirm / Cancel buttons whose enabled state respects the BE state-machine guards (`canApprove` / `canConfirm` / `canCancel`); each button hits its lifecycle endpoint with a fresh idempotency key, refetches via React-Query cache mutation, and the lifecycle pill updates in place.

`pnpm exec vitest run` (40 files / 187 tests / 0 failures), `pnpm exec tsc --noEmit`, `pnpm exec eslint .`, and `pnpm exec prettier --check .` all green. Backend unit pytest (`uv run pytest -m "not integration"`, 121 passed) untouched and still green; no backend code was modified.

## Deviations from plan

### 1. The brief said `useSuppliers()` already shipped via CUT-101, but it didn't

The task spec stated: "The dropdown of suppliers comes from `useSuppliers()` (parties with `is_supplier=true`) — that's already shipped via CUT-101's parties query module." Reality: CUT-101 shipped `useCustomers()` and `useParties()` but not `useSuppliers()`. The CUT-101 retro confirms only customers + all-parties were wired.
- **Fixed by:** added `useSuppliers()` next to `useCustomers()` in `frontend/src/lib/queries/parties.ts`. Live branch hits `/parties?party_type=supplier`; mock branch filters `kind === 'supplier'`. Mirrors `useCustomers()` exactly. ~10 LOC.
- **Why not caught in planning:** the brief's writer misremembered the CUT-101 surface area.
- **Impact on later tasks:** zero — `useSuppliers()` is reusable for CUT-202 (GRN), CUT-303 (PI), and CUT-401 (Job-work karigar dropdown). One-line API.

### 2. `taxes_applicable` / per-line GST-on-PO not wired

The BE `POLineRequest` has a `taxes_applicable: dict[str, Any]` field that's currently free-form, not a structured GST rate. `POResponse` lines also lack a `gst_rate`/`gst_amount` projection. The form collects `gst_pct` per line for UI consistency with the invoice flow, but it's NOT sent to the BE today (the BE doesn't compute PO GST anyway — that lives on the PI side).
- **Fixed by:** the FE-side `gst_pct` is captured and rendered, but the live `buildCreateBody` simply omits it from the wire body. Live mapper sets `gst_pct: 0` on returned lines. The PI flow (CUT-202) is the right place for line-level GST.
- **Why not caught in planning:** the click-dummy `PoLine` shape didn't exist (mock POs had only a header `total`); the FE form invented `gst_pct` to match the InvoiceCreate UX. Acceptable on review — totals are still BE-authoritative, GST flows downstream on the PI.
- **Impact on later tasks:** CUT-202 (PI FE) is the one that should send GST per line. PO line GST stays a UI affordance until BE gains the projection.

### 3. Supplier name not on the wire — relied on a parties-list lookup

The BE `POResponse` has `party_id` but no `party_name` projection. The list page calls `useParties()` alongside `usePurchaseOrders()` and builds an in-memory id→name map. The detail page calls `useParty(po.supplier_id)` to fetch a single party row.
- **Fixed by:** `PurchaseOrderList.tsx` does the lookup; falls back to `'—'` if the parties list hasn't loaded yet. Detail uses the single-row endpoint.
- **Why not caught in planning:** the click-dummy stored `supplier_name` denormalized on the PO row.
- **Impact on later tasks:** consistent with how Wave 2 handled invoices (party_name comes from `SalesInvoiceListItem.party_name` on the BE — different decision there). If the BE later projects `party_name` onto `POResponse`, drop the lookup. Either way zero behavior change.

### 4. First Edit/Write calls landed in the main checkout, not the worktree

Same trap CUT-101 retro flagged: when in `/Users/moizp/fabric/.claude/worktrees/agent-ad1cd24c0f4d62c55`, absolute paths starting with `/Users/moizp/fabric/...` resolve to the main checkout, not the worktree. Caught when `git status` in the worktree showed clean while edits were "applied" elsewhere.
- **Fixed by:** copied files into the worktree explicitly via `cp`, then restored the main checkout via `git checkout HEAD -- <files>`. No content lost.
- **Why not caught in planning:** the CUT-101 retro flagged exactly this and I read it; still tripped because the bash tool's `cd` doesn't persist between calls so I was implicitly working from `/Users/moizp/fabric` (the cwd printed by the env).
- **Impact on later tasks:** spent ~5 minutes recovering. Lesson re-iterated: when in a worktree, sanity-check the first Edit by `ls`-ing the target dir before assuming the absolute path resolved correctly. Better still — always pass absolute paths that include `/.claude/worktrees/<id>/` for files in the agent's worktree.

## Things the plan got right (no deviation)

- The `lib/queries/invoices.ts` template is the right grain: dual-branch on `IS_LIVE`, `_internal` test exports for mappers, `__live` test exports for fetch-mocked integration tests.
- Pragmatic vertical-slice TDD: one failing mapper test → minimum impl → green; one failing fetch-integration test → minimum impl → green; component flow tests added last.
- The lifecycle hooks (`useApprovePo` / `useConfirmPo` / `useCancelPo`) collapse cleanly into one `buildLifecycleHook(action)` factory — no copy-paste.
- `canApprove` / `canConfirm` / `canCancel` exposed as plain functions (not just embedded in the component) so future GRN/PI flows can read them without depending on React.
- Mock seed `purchase.ts` already had `po_9008` as the only DRAFT row, which made detail-page lifecycle tests trivial.

## Pre-CUT-202 (GRN FE + Purchase Invoice FE) checklist

### 1. GRN FE wires almost identically to this PR

CUT-202 should `cp` the structure of `lib/queries/purchase-orders.ts` for `lib/queries/grns.ts`: thin live wrappers + mock-branched query hooks + `_internal` exports for unit tests + `__live` for fetch-mocked integration tests. The PI `lifecycle` is `post` / `void`, not `approve` / `confirm` / `cancel` — the lifecycle factory in this PR is the template.

### 2. PO `lines[].gst_pct` is a UI-only field today

If CUT-202 (PI) needs PO line GST, it should join PO line → item → item.gst_rate at the BE side or fetch the item via `useItem(item_id)` on the FE. Don't trust the `gst_pct: 0` on `mapLine` output.

### 3. Supplier-name fallback pattern

The list page uses an in-memory `Map<party_id, name>` from `useParties()`. CUT-202's GRN list and PI list will have the same need. Either:
- Lift the lookup into a `useSupplierLookup()` hook in `parties.ts`, or
- Defer until the BE projects `party_name` on the procurement responses.

Current preference: defer — the lookup is 5 lines and the BE projection is the right long-term answer.

### 4. The "amount" pill values for live POs

The BE `total_amount` may be null for a draft PO (BE computes on save / approve). The mapper coerces null → 0 paise; UI shows ₹0 cleanly. Verify in the demo that DRAFT POs created via the live form show their lines × rate as the total — which they should, because the BE's `create_po` service sums `line_amount` on insert.

### 5. The DEFAULT_SERIES = 'PO/25-26' is hard-coded

Change in `lib/queries/purchase-orders.ts` if Moiz wants a per-firm series prefix (sales already does this — see InvoiceCreate's `series: 'RT/2526'` passed inline). Wave-5 series-management UX is the right place for this; ship as-is for the dogfood.

## Open flags carried over

- **PO line GST not on the wire.** UI captures `gst_pct` per line but live `buildCreateBody` strips it. Re-surface in CUT-202 if PI expects it; otherwise leave for the BE to project on POResponse.
- **Supplier name not on `POResponse`.** Mitigated via `useParties()` lookup + `useParty(supplier_id)`. Drop when BE projects.
- **Edit / delete on detail page.** Out of scope for CUT-201; the BE has `PATCH` / `DELETE` for POs but the form-driven flow stops at create + lifecycle. File a follow-up if the dogfood demo finds it blocking.
- **`expected_date` is BE `delivery_date`.** Renamed at the FE boundary in mapPo / buildCreateBody. The click-dummy still calls it `expected_date`.
- **The receive-GRN button on the list still renders a coming-soon dialog.** Pointed at CUT-202.

## Observable state at end of task

- Worktree at `/Users/moizp/fabric/.claude/worktrees/agent-ad1cd24c0f4d62c55`, branch `task/CUT-201-purchase-order-fe-live` off `origin/main`.
- 8 files touched (vs main): 4 modified (App.tsx, parties.ts, mock/purchase.ts, PurchaseOrderList.tsx), 4 new (purchase-orders.ts, PurchaseOrderCreate.tsx, PurchaseOrderDetail.tsx, retro), 1 deleted (queries/purchase.ts → superseded). Plus 2 new test files.
- Diff is `~900 LOC` net-add, with the bulk in `purchase-orders.ts` (live wrappers + lifecycle factory) and the two new pages.
- Backend untouched. No Alembic migration. No OpenAPI delta — all endpoints existed.
- Frontend vitest: 40 files / 187 tests / 0 failed. Lint + tsc + prettier clean.
- New routes: `/purchase/new` and `/purchase/:id`.
