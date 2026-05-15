# TASK-TR-A06 retro — Material issue from MO (money-touching)

**Date:** 2026-05-15
**Branch:** `task/tr-a06-material-issue` (worktree `~/fabric-worktrees/tr-a06-mi`)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Manufacturing A-track)

## Summary

Shipped the Material Issue service + endpoints: a new `material_issue_service.py`
that issues raw materials from stock against a `RELEASED` / `IN_PROGRESS` MO,
decrements `mo_material_line.qty_issued`, posts a balanced GL voucher
(DR `1310 Work-in-Process` / CR `1300 Inventory`), and auto-starts the MO on
first issue. Two new tables (`material_issue` + `material_issue_line`) via a
new Alembic migration plus a new `voucher_type` enum value `MATERIAL_ISSUE`.
Two new RBAC perms (`manufacturing.material_issue.read` / `.write`).
Sixteen integration tests in `tests/test_material_issue.py`; full backend
suite (1028 + 16 = 1044 tests) green after a one-line bump of
`test_migration_smoke`'s pinned head revision. `ruff check`, `ruff format`,
`mypy .` all clean. OpenAPI snapshot + FE `api.ts` regenerated.

## Open items needing Moiz sign-off before merge

### 1. New seeded ledger code `1310 Work-in-Process`

`seed_service._SYSTEM_LEDGERS` grew one row. Per CLAUDE.md "Ask vs. Decide":
new ledger codes count as money/tax-touching. Default-seeded, INVENTORY-class,
ASSET parent, non-control, active. Fresh signups pick it up automatically;
**existing orgs (Moiz's dev box, future trial customers) do NOT get the row
retroactively** — `seed_coa` only runs at signup. Two options for the
backfill:

- (a) One-off management command that loops over existing orgs and calls
  `seed_coa(session, org_id=...)` under an admin GUC. Idempotent; takes
  seconds. **Recommended.**
- (b) Wait until each org's next signup-triggered re-seed. Fragile — there
  is no such trigger; signup creates new orgs, not re-seeds existing ones.
  An existing org would never get the new ledger this way.

The PR ships the seed change but not the backfill. Plan is route (a) — a
one-line `python -c` invocation against prod when this lands; the team-lead
review is the right gate to confirm.

### 2. Alembic migration adds two new tables + enum value

`task_tr_a06_material_issue` adds `material_issue` + `material_issue_line`
(both with `org_id` + RLS + audit cols per CLAUDE.md) AND extends the
`voucher_type` Postgres enum with `MATERIAL_ISSUE`. Per CLAUDE.md "Ask vs.
Decide" new tables are an Ask-Moiz gate; the trial-plan approval covers this
Manufacturing-spine task explicitly but flagging here for explicit sign-off.

## Deviations from plan

### 1. `MoMaterialLine` model is leaner than the task spec assumed

Task spec named the columns `qty_required_total`, `qty_returned`, `is_optional`,
and a relationship to `Item`. The A01 model only has `mo_material_line_id` /
`manufacturing_order_id` / `item_id` / `qty_required` (NOT `_total`) /
`qty_issued` / `qty_scrap` / `lot_id` — no `qty_returned`, no `is_optional`,
no eager Item relationship.

- **Fixed by:** the service only touches `qty_issued`. Schema gaps for
  `qty_returned` / `is_optional` carried forward from the A05 retro; A06
  doesn't need them to ship.
- **Why not caught in planning:** task spec was written against an idealised
  schema; A05's retro had already flagged the gaps but the A06 spec wasn't
  updated.
- **Impact on later tasks:** A11 (WIP cost settlement) will want
  `qty_returned`. A07 (per-operation progress) probably also wants
  `is_optional` so optional components can be issue-on-demand. Both are
  one-line schema adds via Alembic; tracked in A05's "Open flags carried
  over" list and unchanged here.

### 2. Item cost source: `stock_position.current_cost` (weighted average)

The plan offered "`item.standard_cost` or `weighted_avg_cost` — pick whichever
Item field exists". Neither exists on `Item`. The weighted-average cost is
maintained per-position on `stock_position.current_cost` by
`inventory_service.add_stock`.

- **Fixed by:** the service reads `current_cost` from the position with the
  largest on-hand for `(item, optional lot)`. Persisted on each MI line as
  `unit_cost` + `line_value` so reprints stay historical even after future
  cost-basis drift.
- **Why not caught in planning:** the plan assumed an Item-level cost
  attribute. Real cost basis lives where the stock lives.
- **Impact on later tasks:** A11 needs to project WIP → finished-goods
  cost using these per-line values. Persisting `line_value` (not
  recomputing on read) means A11 can sum without re-walking
  `stock_position`.

### 3. Zero-cost stock short-circuits with a 422 instead of bubbling

If every position's `current_cost` is null/zero, the GL voucher would be
₹0 / ₹0 — a row that trips the post-flush balance invariant. The service
detects zero total value before posting and raises a clear 422 so the user
knows to set a cost basis (via a stock adjustment) first.

- **Why caught here:** pretty much by accident — wrote the post-flush
  balance check first (mirroring `accounting_service.post_journal_voucher`),
  saw a test fail with a generic "unbalanced" error, decided that was
  worse than an early "set your cost basis" message.
- **Impact:** dedicated test
  `test_cannot_issue_with_zero_total_value` pins the friendly error.

### 4. Auto-start MO on first issue (RELEASED → IN_PROGRESS)

Plan called this out as a design choice. Picked **auto-start** because the
alternative (require explicit `start_mo` POST first) is friction for the
common case: a Production Manager who releases an MO almost always issues
materials immediately. The retro flags the trade-off — a UI that wants
"issue without starting" would need a flag or a separate endpoint; until
that's a real ask, auto-start wins on UX.

- Wired via a service-internal `mo_service.start_mo` call when the MO's
  current status is `RELEASED`. No-op when already `IN_PROGRESS`.

### 5. Voucher `series` re-uses the MI series

The task plan didn't specify the voucher series. Picked `"MI"` (same as the
MI header series, default) so the GL voucher number tracks the MI number
in parallel. Independent allocators (different `voucher_type`) so there's
no collision with the future SALES_INVOICE / JOURNAL / RECEIPT vouchers
that already use other series like `"SI"` / `"JV"` / `"RV"`.

## Things the plan got right

- The `_advisory_lock_partition` / `_allocate_*_number` pattern lifted 1:1
  from `mo_service` (which lifted from `bom_service`).
- `inventory_service.remove_stock` already supports the
  `(reference_type, reference_id)` tuple we need to link a stock ledger
  row back to the MI; no service-API change needed.
- `audit_service.emit` was already firm-aware so the audit row carries
  the right `firm_id`.
- The C01 hardening pattern (PR #120) on inactive/control ledger guard
  + IntegrityError narrowing translated 1:1 to the MI GL post.
- The `current_user.firm_id != body.firm_id` defense-in-depth check from
  A05's MO router worked unchanged.

## GL posting shape

Per material issue:

```
DR  1310 Work-in-Process       total_value
CR  1300 Inventory             total_value
```

Where `total_value = sum(qty_to_issue × stock_position.current_cost)` across
all issued lines. The voucher's `total_debit` and `total_credit` are persisted
on the header for fast TB roll-up.

## Schema additions

### Tables

- `material_issue` — one row per issue. PK `material_issue_id`. UNIQUE on
  `(org_id, firm_id, series, number)`. FK to `manufacturing_order` (RESTRICT)
  and `voucher` (RESTRICT, NULLABLE). RLS-enabled.
- `material_issue_line` — one row per issued component. PK
  `material_issue_line_id`. FK to `material_issue` (CASCADE),
  `mo_material_line` (RESTRICT), `item` (RESTRICT), `lot` (RESTRICT,
  NULLABLE). Columns: `qty_issued`, `unit_cost`, `line_value`,
  `stock_ledger_id` (plain UUID — append-only pointer, no FK).
  RLS-enabled.

### Enum

- `voucher_type` Postgres enum + Python `VoucherType` both grew
  `MATERIAL_ISSUE`. `ALTER TYPE ... ADD VALUE` is forward-only;
  downgrade leaves the value orphan-safe (no rows reference it post-
  downgrade because we just dropped the tables).

### Seeded ledger

- `1310 Work-in-Process` — INVENTORY type, ASSET parent, non-control,
  active. Idempotent re-seed via `seed_service.seed_coa`.

### RBAC

- `manufacturing.material_issue.write` — Production Manager, Owner.
- `manufacturing.material_issue.read` — Production Manager, Accountant,
  Owner.

## Pre-TASK-TR-A07 checklist

### 1. Decide where `qty_returned` lives (deferred from A05)

Manufacturing returns / scrap-out flows depend on it; current
`mo_material_line` has only `qty_required` / `qty_issued` / `qty_scrap`.
Two paths: (a) add a column via a one-line Alembic migration; or (b) add a
sibling `mo_material_return` table mirroring `material_issue`. The latter
mirrors the issue's audit shape but is heavier. Lean towards (a) until A11
shows a multi-row return is common.

### 2. Confirm WIP backfill plan with Moiz

Existing orgs (incl. Moiz's dev DB) won't have `1310 Work-in-Process` until
the one-off `seed_coa` reseed runs. The PR includes a note; the merge
gate is the right place to decide whether to ship the backfill in the same
release or as a follow-up.

### 3. A07 should consume the per-operation `qty_in` set by A05

This MI doesn't touch operation rows; A07 will. When an MO transitions
from RELEASED → IN_PROGRESS (now auto on first issue), the first
operation's `state` is still `PENDING`. A07 should not assume material
issue starts it.

## Observable state at end of task

- Test DB `fabric_erp_tra06_test` provisioned (owner `fabric`, `GRANT ALL`
  to `fabric_app`). `.env` in this worktree gitignored.
- New migration `task_tr_a06_material_issue` at head.
- New advisory-lock namespaces `mi_number:` — no collisions with
  `bom:` / `routing:` / `mo_number:`.
- New `voucher_type` enum value `MATERIAL_ISSUE` on the Postgres enum
  (forward-only; downgrade can't remove it).
- New seeded ledger `1310` on every fresh signup.
- Tests use the same `_seed_full_world` helper shape as A05; each test
  pre-stocks raws at ₹50/m so issues have a non-zero cost basis.
