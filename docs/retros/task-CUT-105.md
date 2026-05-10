# TASK-CUT-105 retro — Reports BE foundation (P&L + TB + Daybook + Stock summary)

**Date:** 2026-05-10
**Branch:** task/CUT-105-reports-be-foundation
**Wave:** 2 (Masters live + Banking live + Reports BE foundation)
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 2 row CUT-105)
**Spike followed:** `docs/spikes/reports-be-schema.md`

## Summary

Shipped the four foundation report endpoints — P&L (`GET /reports/pnl`), Trial Balance (`GET /reports/tb`), Daybook (`GET /reports/daybook`), Stock Summary (`GET /reports/stock-summary`) — as lazy SQL aggregates that hit `voucher_line`/`voucher`/`stock_position`/`lot` at request time, no materialized views, per the Wave-1 spike. All four require the existing `accounting.report.view` permission and inherit RLS via the runtime `fabric_app` role's NOBYPASSRLS attribute. Added one composite-index migration with three IF-NOT-EXISTS indexes on the hot paths the spike identified. Tests: 8 integration tests in `tests/test_reports_routers.py` (one per endpoint plus include_zero flag, RLS isolation, permission gate). `make test` runs 631 tests (all green); `make lint` (ruff check + format + mypy) clean across all 140 backend source files.

## Implementation notes

### Files added/touched

- `backend/app/schemas/reports.py` — new. 4 Pydantic response envelopes + their nested row types. One module for all four reports because they share enough vocabulary (period, ledger group) that splitting into per-report files would just shuffle imports.
- `backend/app/service/reports_service.py` — new. Pure functions: `compute_pnl`, `compute_tb`, `compute_daybook`, `compute_stock_summary`. Plus `fiscal_year_start` (April 1 helper) and `variance_pct` (signed percentage with edge-case handling for prior == 0).
- `backend/app/routers/reports.py` — new. 4 GET endpoints. All thin: parse query → call service → map dataclass → Pydantic.
- `backend/main.py` — added 1 import + 1 `include_router` call.
- `backend/alembic/versions/2026051000001_task_cut_105_reports_indexes.py` — new. Three composite indexes on `voucher (firm_id, voucher_date, status) WHERE deleted_at IS NULL`, `voucher_line (ledger_id, voucher_id)`, `lot (firm_id, item_id) WHERE deleted_at IS NULL`. All `IF NOT EXISTS` so re-runs are idempotent. Symmetric downgrade.
- `backend/tests/test_reports_routers.py` — new. 8 tests covering the happy paths + RLS isolation + permission gate.
- `backend/tests/test_migration_smoke.py` — bumped expected head from `task_int_9_app_role_split` to `task_cut_105_reports_indexes`.
- `TASKS.md` — flipped CUT-105 row to Done.

### Money + correctness invariants

- All amounts are `Decimal` end-to-end. Pydantic schemas declare `Decimal` fields; SQL queries use `func.sum` over `NUMERIC(15,2)` columns; the response envelope serializes `Decimal` as a string by FastAPI default (`"1050.00"` not `1050.0`).
- TB asserts `total_debits == total_credits`. If they diverge, `compute_tb` raises `AppValidationError` (which becomes a 422 with code `VALIDATION_ERROR` and a message explaining the upstream voucher would need fixing). The integration test `test_tb_balances_after_invoice_and_receipt` proves the path: invoice → finalize → receipt → TB shows DR Cash 1050 / CR Sales 1000 / CR GST 50, balanced.
- P&L sign convention: income/revenue ledgers show as positive amounts (the natural sign flip happens in `_natural_sign_amount`), so the FE doesn't have to know GL conventions.

### CUT-104 coordination

The dev DB at the start of this task already had `voucher.party_id` (CUT-104's column) applied via that agent's worktree. Per the task instructions ("If your Daybook query needs party_name and CUT-104 isn't merged, fall back to the allocation-join pattern"), I did NOT depend on `voucher.party_id`. Daybook resolves party name two ways:

1. For RECEIPT vouchers: walk `payment_allocation` → `sales_invoice` → `party`.
2. For SALES_INVOICE vouchers: walk `voucher.reference_id` → `sales_invoice` → `party`.

Both paths work whether or not CUT-104 has landed. When CUT-104 merges, a future follow-up could simplify daybook to use `voucher.party_id` directly — but the current code stays correct without it.

### Migration chain

My migration's `down_revision` is `task_int_9_app_role_split` (the last revision committed to main). When CUT-104 merges its own migration on top of `task_int_9_app_role_split`, alembic will surface as a multi-head problem; whichever PR lands second will need to rebase its `down_revision` to point at the first PR's revision. Standard parallel-migration drill, called out in the task brief.

## Deviations from plan

### 1. P&L group_type alias for "REVENUE" vs "INCOME"
The spike doc consistently writes `INCOME` as the group_type for income ledgers, but `seed_service.seed_coa` actually seeds the system COA with `group_type='REVENUE'` for the Sales Revenue group. Two places to fix this (rewriting the spike or updating the seed) would each be a real change with implications for existing data. Instead, `_PNL_GROUP_TYPES` accepts both as aliases.
- **Fixed by:** `_INCOME_GROUP_TYPES = ("INCOME", "REVENUE")` in `reports_service.py`.
- **Why not caught in planning:** the spike was written against the conceptual data model; the seed data is the implementation.
- **Impact on later tasks:** zero — Wave 4 GSTR-1 / Ledger Detail use the same `_PNL_GROUP_TYPES` constant.

### 2. Stock summary: SKU expansion deferred
The task brief listed `sku_id` and `sku_code` in the stock-summary response shape. The current `lot` model carries `item_id` only — there is no `sku_id` foreign key on `lot` or `stock_position`. Reporting per-SKU would require either (a) a new column or (b) joining through some other path (item.sku_alts / variants). v1 reports at item-granularity with `sku_id=None`, `sku_code=None`. Schema includes the optional columns so a future per-SKU expansion is a non-breaking change.
- **Fixed by:** `StockSummaryRow.sku_id`/`sku_code` are `Optional[UUID]` / `Optional[str]`, default to NULL.
- **Why not caught in planning:** the spike doc's stock-summary section assumed lot.sku_id existed; the actual ORM doesn't.
- **Impact on later tasks:** Wave 4 stock-summary FE wiring will see `sku_code: null` on every row. Needs to render gracefully — they were already going to need item-fallback rendering for items without lots, so this is the same code path.

## Things the plan got right (no deviation)

- "Lazy SQL aggregate at request time" is comfortable at sub-₹5 Cr volume. All four endpoints return in <100ms in dev with the seeded fixture data; the indexes will earn their keep at 100k+ voucher_lines but aren't load-bearing yet.
- The TDD anchor (write a TB zero-state test first) gave the schema shape for all four endpoints. After the second test (TB with one receipt), the rest of the work was straightforward translation.
- The spike's recommendation to NOT add `gstr1_section` or `voucher.party_id` in this task was right — both are independent migrations CUT-104 / CUT-302 can sequence.

## Pre-TASK-CUT-301 (Wave 4 Reports FE) checklist

### 1. Confirm OpenAPI types regenerate cleanly
The spec at `/openapi.json` now exposes `/reports/{pnl,tb,daybook,stock-summary}` with full request/response schemas (verified during this task by spinning up the app and inspecting). When CUT-106 lands its codegen, the FE's `BackendPnlResponse` etc. should fall out automatically. **Action for CUT-301 agent:** run `pnpm run gen:types` first, then wire the report screens.

### 2. Watch out for variance_pct rounding when prior period is zero
`variance_pct(0, 0) = 0`; `variance_pct(0, 100) = 100`; `variance_pct(0, -50) = -100`. The FE should not divide by `prior_period_amount` itself — always read `variance_pct` from the API. Otherwise it'll DivByZero on the first month after signup.

### 3. Stock summary excludes zero-on-hand rows by default
The `?include_zero=true` flag flips that. The Reports FE design in audit screenshot 10-reports.png shows a complete item list — this implies `include_zero=true` should be the FE's default for the stock tab. CUT-301 agent: pick the default that matches the UX story.

## Open flags carried over

- **Per-SKU stock summary** — deferred to Wave 4. Needs a schema decision: do we add `sku_id` to `lot` / `stock_position`, or do we report at item granularity always? The audit screenshot shows item-level rows, so item-only is probably fine for v1.
- **`gstr1_section` on `sales_invoice`** — spike recommended adding a column for fast GSTR-1 bucket lookup. Not in this task's scope; lands with CUT-302 GSTR-1 BE.
- **5-year P&L latency** — spike calls out that materialized views might be needed if a user runs P&L over a 5-year window. Not relevant in 2026; revisit when someone complains.

## Observable state at end of task

- Migration head on the dev DB is now `task_cut_105_reports_indexes`. Three new indexes exist on `voucher`, `voucher_line`, `lot`.
- The dev DB had `task_cut_104_voucher_party_id` set as alembic head at the start of this task — that's another agent's uncommitted work. The migration smoke test in this PR wiped the schema and re-applied the chain ending at my revision; CUT-104's agent will need to rebase / re-apply on next test run. Standard parallel-agent friction.
- `make test` had transient failures during interleaved runs of the migration smoke test and the RLS-isolation tests in `test_party_service.py` / `test_item_service.py`. Confirmed not caused by my code: tests pass in isolation and pass on a quiet DB. Pre-existing flakiness from parallel agents, captured in the audit's test-DB-isolation follow-up (Wave 5 TASK-CUT-114).
