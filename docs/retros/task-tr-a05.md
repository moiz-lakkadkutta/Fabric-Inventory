# TASK-TR-A05 retro — MO creation + lifecycle

**Date:** 2026-05-15
**Branch:** task/tr-a05-mo-lifecycle (worktree `~/fabric-worktrees/tr-a05-mo`)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Manufacturing A-track)

## Summary

Shipped the Manufacturing Order header lifecycle: a new `mo_service.py`
that creates an MO in `DRAFT` and materializes its `mo_material_line` /
`mo_operation` children from a chosen BOM + routing, plus four state-
machine methods (`release` / `start` / `complete` / `close`). Endpoints
under `/manufacturing/mo` cover create + list + get + the four
lifecycle POSTs. Two new RBAC perms (`manufacturing.mo.read`,
`manufacturing.mo.write`) wired into the catalog + OWNER / ACCOUNTANT /
PRODUCTION_MANAGER roles (SALESPERSON deny verified in tests).
19 new integration tests in `tests/test_mo.py`; full backend suite
(996 tests) still green. `ruff check` + `ruff format` + `mypy .`
all clean. OpenAPI snapshot + frontend `api.ts` regenerated.

## Deviations from plan

### 1. MO model field names diverge from the task spec

Plan said `mo_number_series`, `qty_to_produce`, `planned_start_date /
planned_end_date` on the `manufacturing_order` model. The A01 model
actually carries `series` + `number`, `planned_qty`, and `mo_date`
(single date) — no `planned_end_date` column.

- **Fixed by:** the service signature still accepts
  `qty_to_produce` / `planned_start_date` / `planned_end_date` (validates
  end ≥ start when both present) and maps them onto the ORM fields:
  `planned_qty = qty_to_produce`, `mo_date = planned_start_date`.
  `planned_end_date` is validated but currently not persisted; flagged
  in the open-flags section.
- **Why not caught in planning:** task spec was written against an
  imagined schema; A01 (PR #106) picked the shorter column names.
- **Impact on later tasks:** A07 (per-operation progress) will need a
  schema add for `planned_end_date` if the UI surfaces it; cheap
  follow-up.

### 2. `MoStatus.CANCELLED` does not exist

Plan asked for `cancel_mo` (DRAFT/RELEASED → CANCELLED). The
`mo_status` Postgres enum (and Python `MoStatus`) ships with
DRAFT/RELEASED/IN_PROGRESS/COMPLETED/CLOSED — no `CANCELLED`.

- **Fixed by:** documented the gap inline in `mo_service.py` and the
  router; did not add the enum value (out-of-scope schema change for
  a service task). Spec explicitly allowed this.
- **Why not caught in planning:** see deviation #1; spec described a
  target schema, not the as-shipped one.
- **Impact on later tasks:** trivial follow-up — one Alembic
  `ALTER TYPE mo_status ADD VALUE 'CANCELLED'` + a `cancel_mo` service
  method mirroring the other transition helpers.

### 3. `MoMaterialLine` model is leaner than the spec

Plan asked the material lines to carry `uom` + `is_optional` +
`qty_returned`. The A01 model only has `item_id` / `qty_required` /
`qty_issued` / `qty_scrap` / `lot_id`. We dropped the extras at
materialization time (BOM is the source of truth for uom + is_optional
anyway, looked up via the persisted `bom_id` FK).

- **Fixed by:** noted on `mo_service.create_mo`; the wire response
  `MoMaterialLineResponse` only surfaces what's stored.
- **Impact on later tasks:** A06 (material issue) reads from these
  rows; column set is enough for a “planned vs issued vs scrap”
  picture. `qty_returned` becomes a follow-up if the UI surfaces
  rework returns.

## Things the plan got right

- Advisory-lock pattern from `bom_service` / `routing_service`
  translated 1:1 to the MO-number partition.
- `accounting_service._allocate_voucher_number` was a clean template
  for `_allocate_mo_number` — same `max(int) + 1` + zero-pad shape.
- The `current_user.firm_id is not None && body.firm_id == current_user.firm_id`
  defense-in-depth check from the routing router worked unchanged.
- `audit_service.emit` already has a per-firm `firm_id` kwarg so
  every MO mutation emits cleanly.

## MO-number allocation strategy

Per `(org_id, firm_id, series)` partition, default series `"MO"`.

1. Acquire a transaction-scoped Postgres advisory lock on
   `mo_number:{org}:{firm}:{series}` (key matches the DB unique's
   column set; namespace prefix avoids collision with sibling
   `bom:` / `routing:` locks).
2. Read `coalesce(max(number)::int, 0)` over the partition, increment,
   zero-pad to 4 digits → `"0001"`, `"0002"`, …
3. The DB unique
   `manufacturing_order_org_id_firm_id_series_number_key` is the
   defense-in-depth; an `IntegrityError` translates to a 422 with
   a "retry the request" message rather than a 500.

Fiscal-year-stamped series (`MO/2026-27`) is wired through the
`series` parameter on `create_mo` but not yet surfaced in the API
body (the request schema declines `series` from the client today —
defaulting server-side). A future config layer can let firms pick
their own series prefix without touching the allocator.

## Pre-TASK-TR-A06 checklist

### 1. Drop a `cancel_mo` follow-up ticket

Single-migration task: `ALTER TYPE mo_status ADD VALUE 'CANCELLED'`
+ matching enum + `cancel_mo` service method (DRAFT or RELEASED →
CANCELLED, refuse from IN_PROGRESS / COMPLETED / CLOSED). One Alembic
migration, one new method, two tests.

### 2. Decide whether A06 also writes `produced_qty` on COMPLETED

This task's `complete_mo` only flips the status — it does not bump
`produced_qty` (the A01 model has the column with a default of 0).
A06 (material issue) probably should not touch it either; A11
(finished-goods receipt + WIP cost settlement) is the right home.
Pin this in the A11 design note before A06 lands so we don't
accidentally double-write.

### 3. Confirm topological order is enough for A06's issue flow

`_topological_order_operations` returns operations in a Kahn-order
deterministic sequence. A06 will issue material against the MO; if
the UI wants strict "issue against op #1 first" ordering, the BFS
chosen here gives a deterministic answer. If A06 expects user-
visible reordering, we'll need to surface an additional
`operation_sequence` PATCH endpoint.

## Open flags carried over

- **`planned_end_date` not persisted.** Accepted at the wire layer
  for forward compatibility, but **not validated and not stored**.
  Originally the service rejected `end < start`, but PR #121's review
  flagged that as misleading (a 201 implied the value was saved); the
  validation was removed in the review-follow-up commit. If A07 surfaces
  a Gantt chart, add the column via Alembic, re-introduce the
  `end >= start` check, and update `create_mo` to write it.
- **`narration` not persisted.** The service accepts a `narration`
  kwarg, but the MO header has no narration column. We currently
  pipe it through to the audit-log `reason` field as a stop-gap.
  A focused schema add (`manufacturing_order.narration TEXT`) is
  the right fix.
- **`bom_line.is_optional` not respected on persistence.** The A01
  `mo_material_line` table has no `is_optional` column, so we cannot
  record the flag. PR #121's review-follow-up makes the service
  **skip optional BOM lines entirely** at materialization time (the
  conservative choice — an MO under-issues rather than over-issues).
  The right long-term fix is a schema add on `mo_material_line` so
  A06 can branch on the flag (issue required vs ask-before-issue for
  optional). One Alembic migration + a couple of service tweaks.
- **Cancellation path.** See deviation #2 + checklist #1.

## PR #121 review follow-ups (committed in this branch)

- **M1: optional BOM lines.** `create_mo` now skips
  `bom_line.is_optional=True` lines (see "Open flags" above for the
  long-term schema add). Combined with M4 below, an MO whose entire BOM
  is optional/soft-deleted fails fast with a clear 422.
- **M2: narrow IntegrityError catch.** Mirrored the C01 JV pattern
  (`accounting_service.post_journal_voucher`, commit 63cec7b): only
  translate to "MO number race" when
  `manufacturing_order_org_id_firm_id_series_number_key` shows up in
  `IntegrityError.orig`; everything else (FK violations, etc.) bubbles.
- **M3: deterministic topological order.** Two-layer defense.
  (a) `Routing.edges` relationship now `order_by` =
  `(from_operation_id, to_operation_id)` so the edge list itself is
  stable. (b) `_topological_order_operations` breaks Kahn-frontier ties
  by `operation_master_id` UUID (cheap full-sort on a frontier that's
  always <200 ops). Diamond DAGs (A→B, A→C, B→D, C→D) now produce
  identical `operation_sequence` across MO creations.
- **M4: all-soft-deleted/optional BOM guard.** If after the M1 skip
  the material-line count is zero, raise
  `AppValidationError("BOM … has no active required lines")`.
- **Minors:** strengthened body-detail assertions on the four
  state-transition tests; added `test_create_mo_rejects_routing_from_different_firm`
  and `test_create_mo_emits_audit_log_on_each_state_transition`;
  added M-specific tests for each follow-up.

## Observable state at end of task

- The worktree's `backend/.env` points at a dedicated test DB
  `fabric_erp_tra05_test` (provisioned with `CREATE DATABASE ... OWNER
  fabric` + `GRANT ALL ... TO fabric_app`). Migrations applied to
  HEAD before tests ran. `.env` is gitignored.
- Two new RBAC perms in the system catalog
  (`manufacturing.mo.read` / `manufacturing.mo.write`). Existing
  orgs pick them up automatically at next signup-time
  `seed_system_permissions` call.
- New mo_service-side advisory-lock namespace `mo_number:`. No
  collision with the existing `bom:` / `routing:` namespaces.
- Tests use `_seed_mo_world()` which signs up a fresh org per test
  + creates {Design, 3 raw items, 1 finished item, active BOM, 3
  ops, linear routing}. Each test is independently runnable.
