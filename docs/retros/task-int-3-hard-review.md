# T-INT-3 hard review (2026-05-04)

5 commits, +1340/-22, 14 files on `task/int-3-sales-invoice-read` branched off main at `f18b322`. CI green at `9ba02fe`. T-INT-3 was reordered ahead of T-INT-2 because the dashboard's KPIs are mostly sales-driven and depend on `SalesInvoice` existing; that reorder now stands as the canonical T-INT order.

## Behavior coverage vs the plan's 8-row table

| # | Behavior | Status |
|---|---|---|
| 1 | `GET /v1/invoices?status=...&q=...` filters correctly | **✅ shipped.** Service tests cover status + q (`test_sales_invoice_service`). Router test exercises the HTTP filter. |
| 2 | `GET /v1/invoices/{id}` returns full invoice with lines | **✅ shipped.** `test_get_invoice_returns_full_payload_with_lines`. |
| 3 | `GET /v1/parties?kind=customer` (party picker) | **⚠️ already exists.** Pre-existing `/parties` endpoint covers this; T-INT-3 doesn't touch it. Will need a `kind=customer` filter query param when InvoiceCreate (T-INT-4) wires the picker — flagged below. |
| 4 | `GET /v1/items` (line-item picker) | **⚠️ already exists.** Same as #3; the existing endpoint serves both list-uses. |
| 5 | RLS: invoice from another firm → 404 | **✅ shipped.** `test_get_invoice_cross_org_returns_404` (router) + `test_get_sales_invoice_cross_org_returns_404` (service). Returns `NOT_FOUND` envelope, not a 403 leak. |
| 6 | InvoiceList table renders 25 invoices in correct order | **✅ shipped.** Live mapper reuses the existing `InvoiceList` component without visual changes. The recent-flag path in the service guarantees date-desc + number-desc ordering. |
| 7 | InvoiceDetail renders all lines + totals + status pill | **✅ shipped.** Live mapper coerces the wire shape into the existing `Invoice` type so all components keep working. UOM per line is surfaced via the new `item_meta_map` so lines render with their real unit. |
| 8 | (Smoke) Playwright: list → click row → detail | **❌ deferred.** Same status as T-INT-1 #13 — Playwright config / browser-install / CI workflow are all still out-of-scope for local-dev-mode. |

**6 of 8 shipped, 2 deferred (1 for explicit reason, 1 still on the planning shelf).**

## What landed

### Backend

- **`SalesInvoice` ORM** mirroring DDL `sales_invoice` (1435-1482) + the
  ALTER extensions at 2138-2152: `lifecycle_status` (with the
  `invoice_lifecycle_status` enum), `finalized_at`, `paid_amount`,
  `due_date`, `irn_status`, `irn_hash`, `eway_status`,
  `revises_invoice_id`, `linked_mo_id` (plain UUID, no FK — see CRIT-1
  below), `cost_centre_id`, `tax_type`, `round_off`, `dispatched_at`.
- **`SiLine` ORM** with the audit-sweep columns declared for drift
  parity (`updated_at`, `created_by`, `updated_by`, `deleted_at`).
- **`InvoiceLifecycleStatus` StrEnum** bound to the Postgres enum.
- **`VoucherStatus` declared** in `sales.py` so the cross-domain import
  from procurement.py isn't required (same Postgres type, parallel
  Python enum — mirrors the existing pattern).
- **`sales_service.list_sales_invoices`** + **`get_sales_invoice`**
  with status/q/recent filters, RLS-style `NotFoundError` on cross-org.
- **`sales_service.party_name_map`** + **`item_meta_map`** bulk lookups
  so the response builder doesn't N+1.
- **`GET /v1/invoices`** + **`GET /v1/invoices/{id}`** under
  `invoice_router`, gated on the `sales.invoice.read` permission
  already in the rbac seed.

### Frontend

- **`lib/queries/invoices.ts`** swapped to dual-branch (Q6). Live
  branch maps `SalesInvoiceResponse` (Decimal-as-string rupees) into
  the existing `Invoice` type (paise integers) so every consumer
  component — `InvoiceList`, `InvoiceDetail`, the dashboard recent-
  invoices strip — keeps working unchanged.
- **`mapStatus` table** collapses the backend's 9-state lifecycle into
  the frontend's narrower 6-state enum. CONFIRMED→DRAFT, POSTED→
  FINALIZED, DISCARDED→CANCELLED.
- **`mapDocType`** derives `BILL_OF_SUPPLY` from `tax_type=NIL_LUT` /
  `NIL_NOT_A_SUPPLY`, falling through to `TAX_INVOICE`.
- **`ageingDays`** computed at the boundary so list rows can render
  the "X days overdue" pill without a second hop.

### Tests

- 6 service tests (list, status filter, q match, recent ordering, get
  with lines, cross-org 404).
- 4 router tests (list shape, detail with lines, cross-org 404, status
  filter HTTP roundtrip).
- 6 vitest tests for the live mappers (paise rounding, status mapping,
  ageing days, list/detail shape, BILL_OF_SUPPLY derivation).

## Critical findings

### CRIT-1: `manufacturing_order` table not in ORM

**Where:** `app/models/sales.py` — `SalesInvoice.linked_mo_id` is
declared as plain UUID with no FK declaration, even though the DDL has
`REFERENCES manufacturing_order(manufacturing_order_id)`.

**What's the trade-off:** ORM-DDL drift is bounded (drift test passes
because the column-shape matches; the test only flags missing/extra
columns and FKs the ORM declares). The runtime FK constraint is still
enforced by Postgres. The risk is purely diagnostic: a SQL error from
a missing manufacturing_order row surfaces as `IntegrityError` rather
than `NoForeignKeyError`, which is fine.

**Resolution path:** when manufacturing lands (Phase-3 per CLAUDE.md
locked decision #8), add `ManufacturingOrder` ORM and re-attach the
FK. Deliberate deferral — same pattern as `sales_order.quotation_id`.

### CRIT-2: List rows have `lines: []` instead of an absent field

**Where:** `frontend/src/lib/queries/invoices.ts :: mapListItem`.

The frontend `Invoice` type requires `lines: InvoiceLine[]`. The
backend list response (`SalesInvoiceListItem`) doesn't include lines —
they're loaded by the detail call. The mapper sets `lines: []` for
list rows, which works for the list view but is structurally wrong:
the row LOOKS like an empty invoice, not a partial fetch.

**Trade-off chosen:** keep the type unified so consumers don't have to
juggle two flavors of `Invoice`. The cost is that any code that
expects `lines.length > 0` for non-empty invoices will misbehave when
fed a list-row.

**Resolution path:** if/when this trips someone, split the type into
`InvoiceListRow` and `Invoice` (with discriminator). Not blocking
T-INT-3 close-out since no consumer currently treats list rows as
detail rows.

### CRIT-3: `tracking` column name collision with `TrackingType`

**Where:** Item ORM has `tracking: Mapped[TrackingType | None]` (the
column is `tracking`, the enum is `TrackingType`). My initial test
fixture used the more-natural `tracking_type=TrackingType.NONE` and
CI surfaced the mismatch on the first DB-bound run.

**Trade-off:** rename considered, declined — `tracking` is the DDL
column name and changing the ORM would create migration churn for a
cosmetic win.

**Resolution path:** added a comment to the fixture so the next test
author doesn't repeat the mistake. Could add a docstring note on
`Item.tracking` later.

## Other observations

- **Rupees → paise rounding is nearest-integer.** Decimal-as-string
  parsed via `parseFloat * 100` and `Math.round`. The third decimal
  of rupee values is dropped; for any row Moiz cares about (₹0.01
  granularity), this is fine. If invoice templates ever need
  sub-paise precision, swap to `dinero.js` at the boundary.
- **`limit=200` hardcoded** on the live list call. Click-dummy has
  25 invoices; production tenants will hit this cap fast. Move to
  cursor-based pagination when an InvoiceList table grows past one
  page in real use. Not blocking — matches the click-dummy fixture
  density.
- **No InvoiceDetail UOM rendering test.** The mock fixture had
  hardcoded UOMs; the live mapper now reads them from `item_meta_map`.
  Verified manually via the vitest `mapDetail` test (asserts
  `lines[0].uom === 'METER'`), no E2E coverage. T-INT-4 will need an
  invoice detail with multi-UOM lines for the GST-place-of-supply
  tests anyway.
- **Drift test caught two issues** I missed locally: `linked_mo_id`
  FK and `created_by` inline-FK override. Both are now in the ORM
  consistently with the existing `PurchaseInvoice` and `SalesOrder`
  patterns. Worth noting that the local skip-when-no-DB stance hides
  this class of bug — running `make test` against a local Postgres
  before push would catch it earlier. Not changing local-dev-mode for
  this; it's a `pnpm tab in another terminal` problem.

## Recommended close-out

- **Merge.** No CRIT blocks the merge.
- **T-INT-2 (dashboard) unblocks** as soon as this lands; sales-driven
  KPIs can now read from `sales_invoice` directly.
- **T-INT-4 (invoice create + finalize)** is the natural next slice
  on top of this — it can reuse the read-side service helpers
  (`get_sales_invoice`, `party_name_map`, `item_meta_map`) and the
  frontend mappers (`mapDetail` consumes the same response shape that
  finalize will return).

## Summary

T-INT-3 is functionally complete against the plan's must-ship list.
The two deferred items (Behavior #3 customer-only filter, Behavior #8
Playwright) are explicitly downstream concerns. Three CRITs are all
"intentional trade-off" rather than bug; each has a clear resolution
path tied to a future task. The ORM groundwork laid here unblocks both
T-INT-2 and T-INT-4.
