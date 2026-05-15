# TASK-TR-B02 retro — Lots backend endpoint + frontend wiring

**Date:** 2026-05-15
**Branch:** task/tr-b02-lots
**Commit:** `<sha>` (pending PR merge)
**Plan:** TASK-TR-B02 brief from team-lead handoff

## Summary

Closed the click-dummy gap left by TR-B01: there is now a real
read-only `GET /lots` + `GET /lots/{lot_id}` pair on the backend,
RLS-scoped to the current org and gated by a new `inventory.lot.read`
permission. Every existing system role (Owner, Accountant, Salesperson,
Warehouse, Production Manager) was granted the new permission so the
existing dogfood + customer-trial seats keep working. The frontend
`useLots()` and `useLot(lotId)` hooks now hit the live endpoints in
live mode while preserving the mock branch for click-dummy demos.
`LotDetail.tsx` renders two shapes: the rich `StagesTimeline` for the
fixture, and a flat field-grid for the BE `LotResponse` (no per-stage
history endpoint exists for v1 — stages stay mock-only).
Lint, typecheck, OpenAPI snapshot regen, full vitest suite (303
tests; 2 new), and the inventory + RBAC + stock backend suites
(53 tests; 11 new) all green. Mypy clean.

## What landed

### Backend

- **`backend/app/service/inventory_lots_service.py`** (new, 155 lines)
  - `list_lots(...)` — paginated list with `item_id` and `search`
    filters (search matches both `lot_number` and
    `supplier_lot_number` ilike). Returns
    `tuple[list[(Lot, Item, Decimal)], total_count]` so the router
    builds the response with the eager-loaded item summary in one
    query — no N+1.
  - `get_lot(...)` — single-lot fetch with the same eager-loaded
    item + qty aggregate. Raises `NotFoundError` (404) on missing
    or wrong-org rows.
  - `_qty_on_hand_subquery()` — correlated scalar subquery that
    sums `stock_position.on_hand_qty` over every (lot_id, location)
    row for the parent Lot. Inlined in both selects, so each row
    carries its live aggregate without a follow-up query.
- **`backend/app/routers/inventory.py`** — added `lots_router`
  exposing `GET /lots` and `GET /lots/{lot_id}` with permission
  `inventory.lot.read` and the standard `firm_id` / `item_id` /
  `search` / `limit` / `offset` query params. Wired into
  `main.py`'s router list.
- **`backend/app/schemas/inventory.py`** — `LotResponse` +
  `LotListResponse` Pydantic models with `Decimal` quantities and
  tight nullability (mfg_date / expiry_date / supplier_lot_number
  optional; lot_number + UoM always present).
- **`backend/app/service/rbac_service.py`** — added
  `("inventory.lot", "read", ...)` to the system permission
  catalog. Granted to Accountant (stock-valuation drilldown),
  Salesperson (lot picker on DC/invoice), Warehouse, and
  Production Manager. Owner already has every permission by
  construction. Seeding is idempotent — existing tenants pick up
  the new permission on their next signup-path call; existing
  customer-trial orgs will need a one-shot reseed if/when they're
  on a long-lived session (flagged below).
- **`backend/tests/test_inventory_lots_routers.py`** (new, 437
  lines) — 11 tests covering:
  - 401 without auth (list + detail).
  - Paginated list happy path (asserts every BE response field).
  - Filter by `item_id`.
  - Search by `supplier_lot_number` substring.
  - Pagination respects `limit` + `offset`.
  - Get-by-id 200.
  - Get-by-id 404 unknown.
  - Get-by-id 404 cross-org (RLS isolation).
  - qty_on_hand math: GRN-style `add_stock(100)` then
    `remove_stock(25)` → expect `75`.
  - 403 for a user whose role lacks `inventory.lot.read` (mints a
    bare custom role).

### Frontend

- **`frontend/src/lib/queries/inventory.ts`** — replaced the
  fakeFetch stubs in `useLots()` and `useLot(lotId)` with real
  `GET /lots` and `GET /lots/{lot_id}` calls in live mode. Kept
  the mock branch so click-dummy builds still demo the rich
  StagesTimeline fixture. Exported `BackendLot = LotResponse`
  type for downstream consumers. `firm_id` is pulled from the
  auth store; the hook accepts overrides for future flows.
- **`frontend/src/pages/inventory/LotDetail.tsx`** — refactored
  into two siblings: `LiveLotDetail` (renders the BE
  `LotResponse` as a 2-col field grid with the on-hand
  prominent in the header) and `MockLotDetail` (the existing
  `StagesTimeline` view, preserved verbatim for the click-dummy).
  A type guard on `lot_number` routes between them.
- **`frontend/src/pages/inventory/__tests__/LotDetail.live.test.tsx`**
  (new) — two integration tests that pin live mode with
  `vi.mock('@/lib/api/mode')` and a fetch mock:
  - Renders the BE LotResponse fields (lot number, item summary,
    supplier lot, qty_on_hand with UoM).
  - Renders "Lot not found" on a 404 from the API.
- **`frontend/scripts/openapi-snapshot.json` +
  `frontend/src/types/api.ts`** — regenerated via
  `make openapi-snapshot` so CI's drift check sees the new paths
  and schemas.

## qty_on_hand aggregation — approach picked

The BE service computes `qty_on_hand` as a correlated scalar
subquery over `stock_position`, inlined into both the list and
detail selects:

```python
select(func.coalesce(func.sum(StockPosition.on_hand_qty), 0))
    .where(StockPosition.lot_id == Lot.lot_id)
    .correlate(Lot)
    .scalar_subquery()
```

This matches the pattern that `inventory_service.add_stock` /
`remove_stock` already keep in lock-step with the `stock_ledger`
(every movement that bumps the ledger also updates the position
row). The alternative — walking `stock_ledger` and summing
qty deltas — would correctly reproduce the history but at higher
cost per row and would also double-count if any future migration
ever shipped a backfill row.

`stock_position` is already the canonical "current state" view
used by `/reports/stock-summary` (CUT-302), so reusing it keeps
the lot endpoint consistent with the inventory-list endpoint
the FE already trusts. Historical / as-of-date reads (if a
future report needs them) walk the ledger; current state always
trusts the position.

The test
`test_qty_on_hand_reflects_inbound_and_outbound` pins this
contract: mint 100 via `add_stock`, drain 25 via `remove_stock`,
expect the endpoint to surface `75`. If a future refactor breaks
the aggregation (e.g. a new movement type that bypasses
`stock_position`), this test fails loud.

## Deviations from plan

### 1. LotDetail dual-shape rendering

The plan said "do the adapter in the queries file, not in
components." I kept the queries file lean (it returns the live BE
shape verbatim) but had to put a type-guard branch in
`LotDetail.tsx` because the click-dummy mock shape carries
`stages`, `bin`, `opening_qty`, `current_qty` — none of which the
BE produces for v1, and dropping the stages timeline would break
the design demo path the click-dummy depends on.

- **Fixed by:** `isBackendLot()` guard in `LotDetail.tsx`. Live
  mode renders a flat 2-col field grid; mock mode renders the
  existing `StagesTimeline`. Both render paths share the page
  header chrome and the back-link.
- **Why not caught in planning:** the spec called for "adapter
  in queries" assuming the live + mock shapes were
  superficially-different views of the same data. They aren't —
  the mock fixture is a richer envelope that depends on a
  per-stage history endpoint that doesn't exist on the BE.
- **Impact on later tasks:** zero. When a future task adds a
  stages endpoint (likely as part of TR-A04 or job-work history),
  the live branch can grow a `stages` field and the type-guard
  collapses. Until then, the dual-render keeps the click-dummy
  demo intact.

### 2. RBAC denied test uses a custom role, not a seed role

The plan asked for "RBAC denied for users without
`inventory.lot.read`". All five seeded system roles (Owner,
Accountant, Salesperson, Warehouse, Production Manager) were
granted `inventory.lot.read` because each one has a real
business need for it (stock valuation, lot picker, GRN intake,
MO consumption). To get a permission-denied test I mint a custom
role with zero permissions via `rbac_service.create_custom_role`.

- **Fixed by:** `test_list_lots_denied_without_lot_read_permission`
  in `test_inventory_lots_routers.py`.
- **Why not caught in planning:** the brief implied at least one
  seed role would lack lot.read. None do — and intentionally so,
  because gating lot visibility behind a separate role is
  user-hostile for a single-firm dogfood deployment.

### 3. Pre-existing journal-voucher test failures left untouched

Running the full backend suite surfaces 9 failures in
`tests/test_journal_voucher_service.py` (NOT NULL constraint
on `organization.encrypted_dek` when the test constructs an
Organization directly). The failing test was untouched on this
branch (`git diff main` is empty for that file) and the root
cause is in TR-SEC1 (#112), which added field-level encryption.
Flagged below for a future TR-SEC follow-up; not in scope here.

## Things the plan got right (no deviation)

- `stock_position` is indeed the right source of truth for
  `qty_on_hand` — the subquery pattern is consistent with how
  `compute_stock_summary` reads aggregates.
- Reusing `NotFoundError` (which surfaces as a clean 404 via the
  global handler) was straightforward — no new exception class
  needed.
- The `inventory.adjustment.create` permission pattern (one slug
  per concrete action) extended cleanly to `inventory.lot.read`.
- The `vi.mock('@/lib/api/mode')` pin-the-mode pattern from
  TR-B01 was directly reusable for the new LotDetail live test.

## Pre-TASK-(NNN+1) checklist

### 1. Existing tenants need a one-shot RBAC reseed

`rbac_service.seed_system_permissions` is called from
`/auth/signup`, so new tenants automatically pick up the new
`inventory.lot.read` permission. Existing tenants (Moiz's
dogfood org, the customer-trial org) won't — their existing
seeded roles continue to lack the grant. A one-shot reseed
helper or a manual SQL patch should run before the next FE
deploy that surfaces the LotDetail screen to those tenants;
otherwise the existing OWNER user will get a 403 from `/lots`.

For Moiz's local dogfood DB, the simplest fix is a manual
`uv run python -m app.cli.seed --org-id <UUID>` (if that CLI
exists — TASKS.md `make seed` text suggests it does). Otherwise
file a TR-Q follow-up for a `seed_system_permissions` re-run
command.

### 2. Per-SKU lot counts on InventoryList

The `lots` column still shows 0 in live mode (TR-B01 left it
that way pending a sibling endpoint). With `/lots` now live,
the simplest fix is a second `useQuery(['inventory', 'lots'])`
on InventoryList that buckets the response by `item_id` and
joins into the existing SKU rows. Scope as a TR-B02b follow-up
or roll into a future TR-Bx that adds the status-mix bar in
one go.

### 3. Stages timeline backed by real history

The mock LotDetail's stages timeline is the most polished view
of a lot in the codebase. A future task should crawl
`stock_ledger` + job-work history (`job_work_order_line` +
`job_work_receipt_line`) into a per-stage timeline endpoint.
Probably belongs to TR-A04 (MO routing) or a sibling
manufacturing-history task — it'll need the manufacturing
schema in place first.

### 4. Fix the journal-voucher test failures (TR-SEC1 follow-up)

`tests/test_journal_voucher_service.py` constructs `Organization`
without an `encrypted_dek` and now fails on the NOT NULL
constraint. Quick fix: route the test fixture through
`identity_service.register_user` (which calls
`crypto.generate_org_dek()` internally). Belongs in a TR-SEC
hotfix, not blocking this PR.

## Open flags carried over

- New `inventory.lot.read` permission is not auto-granted to
  existing tenants. Resurfaces as soon as an existing-tenant
  user hits the LotDetail or lot-list endpoint.
- Per-SKU lot count + status-mix bar still mock-only on
  InventoryList. Resurfaces in TR-B02b or a future TR-Bx.
- LotDetail stages timeline is mock-only in live mode.
  Resurfaces in a future manufacturing-history task.
- `tests/test_journal_voucher_service.py` is red on main due to
  TR-SEC1 schema change. Pre-existing; not caused or fixed by
  this task.

## Observable state at end of task

- New dev-env requirement: the `inventory.lot.read` permission
  row + role grants land via `seed_system_permissions` on signup.
  Fresh tenants get them automatically; existing tenants need
  a manual reseed (see checklist item 1).
- The `frontend/scripts/openapi-snapshot.json` grew by 2 paths
  (`/lots` and `/lots/{lot_id}`) and 2 schemas (`LotResponse`,
  `LotListResponse`). CI's `openapi-drift` job will check this.
- No new migrations, env vars, or runtime services. Pure
  service + router + schema + FE wiring on top of an existing
  `lot` table that's been in the schema since TASK-004.
- Worktree's `backend/.env` points DATABASE_URL +
  MIGRATION_DATABASE_URL at the dedicated test DB
  `fabric_erp_trb02_test`. `.env.example` is unchanged — the
  team-lead's main worktree is unaffected.
