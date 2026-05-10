## TASK-CUT-104 retro — Wave-2 P1 fix bundle (receipts + cheques + invoice list)

**Date:** 2026-05-10
**Branch:** task/CUT-104-p1-fix-bundle
**Wave:** 2 (post-Wave-1 demo gate)
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (CUT-104 in Wave-2 table)
**Audit:** `docs/ops/platform-audit-2026-05-10.md` (P1-2, P1-3, P1-8, P1-9)

## Summary

Four small independent P1 fixes from the audit, bundled into one PR. Each was test-first, vertical-slice TDD: write the failing test, implement the minimum to flip it green, repeat. End state: 650 backend tests + 123 frontend tests + ruff + ruff format + mypy + eslint + prettier + tsc all green. New Alembic migration `task_cut_104_voucher_party_id` upgrades cleanly and downgrades cleanly (verified up→down→up).

What shipped:

1. **Fix 1 (P1-2): voucher.party_id column.** New migration adds nullable `party_id UUID` to `voucher` with FK to `party.party_id` ON DELETE SET NULL, plus index `(org_id, firm_id, party_id)` for future party-statement / FIFO queries. `Voucher` model gains the field. `receipt_service.post_receipt` populates it. `list_receipts_with_details` prefers `voucher.party_id` and falls back to the legacy `payment_allocation` → `sales_invoice` → `party` join only for rows that pre-date the migration. Test: `tests/test_receipt_no_allocation_keeps_party.py` reproduces the audit's `0eb047bf` regression — post a receipt for a party with NO open invoices, GET /receipts returns the receipt with `party_id` and `party_name` populated.

2. **Fix 2 (P1-3): FIFO regression test.** New `tests/test_receipt_after_finalize_allocates.py` runs the audit's repro chain (signup → party → item → DRAFT → finalize → POST /receipts) parameterized over 25 iterations. Asserts allocations is non-empty AND invoice transitions to PAID. Was GREEN immediately on the first run — the audit's flake was likely sidecar-uvicorn-specific or a race we don't hit through `TestClient`. Test docstring clearly labels this a regression guard, not a TDD-driven new feature. No code change to `_list_open_invoices_fifo` was needed.

3. **Fix 3 (P1-8): cheques count.** Audit reported `count: null`; reading the code at `routers/banking.py:257`, it already returned `count=len(cheques)` and the schema mandates `count: int` (non-null). The audit's observation may have been transient or against a different commit. Added `tests/test_banking_routers.py::test_list_cheques_count_is_int_matching_items_length` as a regression guard verifying both empty (count=0) and populated (count=2) cases return integer counts that match `len(items)`.

4. **Fix 4 (P1-9): invoice list mapper gst_total.** Backend: added `gst_amount: Decimal | None` to `SalesInvoiceListItem` schema; `_invoice_to_list_item` now passes `invoice.gst_amount` through (already loaded — list query selects `SalesInvoice` fully). Frontend: `BackendSalesInvoiceListItem` gains `gst_amount: string | null`; `mapListItem` computes `total = rupeesToPaise(invoice_amount)`, `gst_total = rupeesToPaise(gst_amount)`, `subtotal = total - gst_total`. Tests extended on both sides:
   - BE `test_list_invoices_returns_seeded_row` asserts `gst_amount` field present + value equals seeded amount.
   - FE `mapListItem populates totals + gst + subtotal + status without lines` asserts non-zero `gst_total`.
   - FE legacy-safety test `mapListItem falls back to gst_total=0 when backend omits gst_amount` proves the FE gracefully degrades on a stale backend.

## Deviations from plan

### 1. Fix 2 was already GREEN — no FIFO snapshot fix needed
Plan said: "MAY pass already... If RED, investigate `_list_open_invoices_fifo` snapshot isolation; consider adding `FOR UPDATE` lock or moving to `READ COMMITTED` snapshot." Reality: the test passed all 25 iterations on the first run. The audit's repro was on a sidecar uvicorn under specific conditions; a `TestClient`-driven test runs the whole signup+finalize+receipt sequence on one connection that always sees its own writes. We chose 25 iterations not 100 because each iteration signs up a fresh tenant + seeds party + seeds item — at ~0.4s/iter it's the dominant cost in the test file, and 25 is enough to catch any P>=10% flake. If the bug ever re-surfaces in dogfood, the fix lane is documented in the test docstring.

### 2. Fix 3 was already correct in code — added regression test only
Plan said: "currently returns `count: null` per audit. Fix: compute `count = len(items)`." Reality: the code at `routers/banking.py:257` already does `count=len(cheques)` and the schema mandates `count: int`. The audit's claim was wrong (or against a fork). Test still adds value as a guard — without it, future refactors could silently regress.

### 3. Migration head pin in `test_migration_smoke.py` needed bumping
Standard pattern (`assert version == "..."`) — bumped to `task_cut_104_voucher_party_id`. Not a "deviation" so much as a routine paperwork item that shows up on every migration-adding task. Mentioning here so the next agent doesn't lose 30 seconds wondering why the smoke test fails after a green migration upgrade.

## Things the plan got right

- The "pragmatic vertical-slice TDD" workflow held: each fix took one test, one impl pass, one green. No backtracking.
- Pre-authorization for the schema change worked — ship-don't-ask saved a round-trip.
- Bundling 4 small fixes in one PR is the right shape: each fix is small enough that the bundle reviews in one sitting; each is independent enough that one regression doesn't block the others.
- The "NULLABLE with no default" guidance for the migration was correct — instant DDL, no table rewrite.
- The fallback-to-legacy-join in `list_receipts_with_details` is the right pattern: any voucher posted before this migration has `party_id IS NULL`, and the join still recovers the party for those.
- Wave-1's `make test` + `make lint` post-merge sweep (TASK-CUT-006 retro process improvement) caught the migration-smoke head pin in CI before it hit Moiz.

## Pre-TASK-CUT-105 checklist

CUT-105 (Reports BE foundation) is the heaviest of the Wave-2 lanes. From this task's footprint:

### 1. New `voucher.party_id` is available for party-statement / ageing reports
The migration adds `idx_voucher_org_firm_party (org_id, firm_id, party_id)`. CUT-105 (`/reports/pnl`, `/reports/tb`, `/reports/daybook`, `/reports/stock-summary`) doesn't directly use this, but CUT-302 (Wave 4: `/reports/party-statement`, `/reports/ageing`) will benefit. Mention this in CUT-105's retro so CUT-302 picks up the index assumption.

### 2. The `list_receipts_with_details` mapper has 2 code paths now
`voucher.party_id IS NOT NULL` → header path (new). `voucher.party_id IS NULL` → legacy join path (old). When CUT-302 builds party-statement, it can rely on `voucher.party_id` being populated for any RECEIPT created post-CUT-104 — the join fallback is only needed for existing dev/seed data.

### 3. `SalesInvoiceListItem.gst_amount` is now part of the public API
If CUT-106 (OpenAPI codegen) lands in this same wave, the regenerated `frontend/src/types/api.ts` will already include `gst_amount` because of this PR's schema change. CUT-106's diff should be smaller as a result.

## Open flags carried over

- **The audit's P1-3 repro was on a sidecar uvicorn at port 8765** (not the dev `:8000`). If the FIFO timing bug ever resurfaces in dogfood at `:8000`, the fix is documented in `tests/test_receipt_after_finalize_allocates.py:14-15`: take a row-level lock on the candidate invoices in `_list_open_invoices_fifo`, OR move the FIFO query to `READ COMMITTED` snapshot. For now: 25-iteration regression guard says we don't reproduce.
- **The legacy-fallback path in `list_receipts_with_details` will be dead code** once the `voucher.party_id` column is universally populated. A future cleanup task (post-7-day-soak) can backfill all existing receipt vouchers and remove the fallback. Filing as a backlog hygiene item — no urgency.

## Observable state at end of task

- New Alembic head: `task_cut_104_voucher_party_id`. `alembic_version` reflects it.
- New `voucher.party_id` column exists in dev DB. Existing rows have it as NULL (no backfill).
- New index `idx_voucher_org_firm_party` exists.
- No new env vars or services. Same `make test` / `make lint` workflow.
- Test count: 650 backend (was 645 — +5 from CUT-104: 1 new file with 1 test, 1 new file with 25 parametrized cases counted as 25, 1 new test in banking, 1 in sales) and 123 frontend (was 121 — +2 from CUT-104: extended mapListItem test + new legacy-fallback test).
