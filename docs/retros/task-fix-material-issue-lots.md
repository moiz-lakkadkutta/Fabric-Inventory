# fix-material-issue-lots retro: material issue to an MO now handles lots

**Date:** 2026-10-23
**Branch:** task/fix-material-issue-lots
**Commit:** PR open, not merged. PENDING MOIZ SIGN-OFF (touches stock movement and WIP costing)

## Summary

A verification pass found that issuing material to an MO ignored lots. `material_issue_service.issue_materials` always called `inventory_service.remove_stock(lot_id=None)`, and the MO screen never sent a `lot_id`. Since #202, GRN receipts put stock into per-lot positions, so a lot-received fabric failed with "No stock … / Insufficient stock" even with stock on hand. (The on-hand pre-check summed across all lots and passed. The write targeted the NULL-lot position only.)

The fix reuses the #202 pattern used by DC dispatch, sales COGS and stock adjustment:
- An explicit `lot_id` goes to `remove_stock(lot_id=…)`.
- No `lot_id` goes to `remove_stock_fifo`.

Each consumed position becomes its own `material_issue_line`, valued at the `unit_cost` the stock writer stamped on the OUT ledger row (that position's `current_cost`). The WIP voucher is the sum of those line values. No schema change.

The FE issue dialog gains a per-line "Lot" select. It defaults to "Auto (FIFO)", lists only lots with stock on hand from `GET /lots?item_id=`, and omits `lot_id` for Auto.

Verification:
- Backend: ruff check, ruff format, and mypy are clean over the whole tree.
- New `tests/test_material_issue_lots.py` (5 tests) passes. It was red first: the FIFO and NULL-lot-first cases returned 422.
- The manufacturing, inventory, stock-adjustment, DC, COGS, job-work and seed-demo suites pass.
- FE: MoDetail vitest (39, including 2 new) passes; typecheck, eslint and prettier are clean.

## Deviations from plan

### 1. Valuation is now taken from the consumed position, not "most recently updated position"
Before, the line cost was the `current_cost` of whichever position for the (item, lot) had the latest `updated_at`, read *before* the move. That position was not necessarily the one consumed. Now the cost is the `unit_cost` on the OUT ledger row(s) the writer actually produced. Sales COGS (`_post_cogs_for_invoice`) uses the same basis. For a NULL-lot-only item at one location, the result is identical (existing tests unchanged). This is not a new costing treatment, but it is a WIP-value change for multi-position items, so it's flagged for Moiz.

### 2. The zero-total-value guard moved after the stock writes
Values are only known after consumption, so the guard now fires after the stock writes. It still raises `AppValidationError` (422), and the request transaction rolls back the stock moves.

### 3. One requested line can produce several `material_issue_line` rows
A FIFO issue that spans 2 lots returns 2 response lines with the same `mo_material_line_id`. `mo_material_line.qty_issued` is still bumped once by the requested qty. The request schema is unchanged. The `specs/api-phase1.yaml` description documents this. `sum_wip_cost_pool` reads voucher lines, so it is unaffected.

## Things the plan got right (no deviation)

- `remove_stock_fifo` from #202 was reusable as-is; no new consumption helper.
- The explicit-lot backend path already worked. The gap there was FE-only.

## Open flags carried over

- **Multi-location:** an issue still runs at one location, the one with the most qty for the item (summed across lots for FIFO). If that location is short while the firm total is enough, it fails with "Insufficient stock". This was already out of scope until A11.
- **Pre-check with duplicate lines:** duplicate request lines for the same MO line are pre-checked against stock one line at a time, not combined. The writer still refuses an over-draw, so there is no incorrect posting, only a later error message.
- **Tracking type not enforced:** a LOT/BATCH-tracked item can still be issued with Auto. That matches DC dispatch and adjustment behaviour. Making lot selection mandatory for tracked items would be a product decision.

## Observable state at end of task

- Local test runs used a cloned DB `test_fixlots` (from `test_template`) on Homebrew PG14.
- Docker was down, so Redis on :6379 came from a scratch fakeredis `TcpFakeServer` forced to RESP2. The stock fakeredis TCP server speaks RESP3 nulls (`_`), which redis-py's RESP2 parser rejects.
