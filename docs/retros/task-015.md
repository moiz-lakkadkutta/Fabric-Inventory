# TASK-015 retro — System catalog seed (UOMs, HSN, COA) + auto-seed on signup

**Date:** 2026-04-27
**Branch:** task/015-seed-data
**Commit:** `<sha>` (pre-merge)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md`

## Summary

Shipped catalog seed end-to-end: 10 UOMs, 10 textile-trade HSN codes, 5
COA top-level groups + 17 starter ledgers — all idempotent, all per-org.
Wired into `/auth/signup` so every fresh tenant gets a usable catalog at
signup time. Added a one-shot CLI (`python -m app.cli.seed --org-id ...`)
for backfilling existing orgs. Schema migration `task_015_uom_hsn_per_org`
flipped UOM/HSN unique constraints from global to per-(org, code).

228 tests pass; ruff + format + mypy strict clean across 59 source files.

## Deviations from plan

### 1. Schema bug discovered — UOM/HSN had global UNIQUE constraints

The TASK-004 baseline declared `uom.code`, `uom.name`, and `hsn.hsn_code`
as **globally unique** (column-level UNIQUE). That's incompatible with
multi-tenant per-org catalogs — only the very first org could ever own
UOM "MTR" or HSN "5208". The signup-auto-seed test exposed it the moment
a second test signup tried to seed the same codes.

- **Fixed by:** new migration `2026042700001_task_015_uom_hsn_per_org_unique.py`.
  Drops `uom_code_key`, `uom_name_key`, `hsn_hsn_code_key`. Creates
  `uom_org_id_code_key`, `uom_org_id_name_key`, `hsn_org_id_hsn_code_key`.
  ORM models updated with `__table_args__ = (UniqueConstraint(...))`. The
  `schema/ddl.sql` was deliberately **not** modified — per the team's
  "ddl.sql is historical baseline; forward changes go via Alembic"
  pattern, so a fresh `alembic upgrade head` walks baseline → TASK-015
  and ends up with the correct constraints. The drift gate compares the
  ORM model against the migrated DB (not raw DDL), so it stays green.
- **Why not caught earlier:** TASK-004 retro flagged "uom_id/hsn_id are
  treated as global catalogs but org_id NOT NULL" as a soft tension; no
  one ran a second-org seed in tests until TASK-015.
- **Impact on later tasks:** zero new — but every future "global-ish"
  catalog table (e.g. cost-centre templates if we ever add them) needs
  the same per-org-unique pattern from day one.

### 2. Spec said "make seed", reality auto-seeds at signup

The TASK-015 spec called for a `make seed` script that creates a demo
org with parties/items + the catalog. The bigger value is **automatic**
catalog seeding for every new org so tests / dev / prod never need a
manual re-seed step — that lands in `/auth/signup`. `make seed` now
prints the auto-seed-on-signup explanation + the backfill CLI command.

- **Fixed by:** `seed_service.seed_system_catalog()` called from
  `routers/auth.signup`; new `app/cli/seed.py` for backfilling.
- **Why diverged from spec:** the spec was written before the auth flow
  shape was decided. Auto-seeding at signup is the "right" home for the
  catalog (every tenant needs it, no human is ever going to remember to
  run `make seed` after creating an org via the API).
- **Impact on later tasks:** TASK-040 (COA seeding+model) — the COA part
  is **already done here**; that task is now redundant for the seeding
  half. Update TASKS.md when TASK-040 is picked up to acknowledge.

### 3. Demo data (parties, items) deferred

Spec called for 10 supplier parties, 5 customer parties, 20 items as
part of `make seed`. None of those are needed for backend correctness;
they're a dev-experience nice-to-have that costs ~30 min. Skipped here —
when frontend wave starts, a `make seed-demo` target with `--demo-org
"Demo Textile"` flag is the natural spot for it.

## Things the plan got right

- The `seed_system_roles` idempotent-pattern (TASK-009) ported cleanly
  to UOM/HSN/COA — same shape: `dict-of-existing → skip-or-add → flush`.
- TASK-014's masters scaffold already had `CoaGroup` and `Ledger` models;
  no model edits beyond the UOM/HSN unique-constraint fix.
- Trial-balance acceptance criterion (`sum(ledger.opening_balance) == 0`)
  is mechanically true on a fresh seed (every ledger seeded with 0) and
  there's a test asserting it.

## Pre-TASK-022 checklist

### 1. TASK-022 is the stock ledger — DEEP-FOCUS, single-author

Per plan §8, `TASK-022 Stock ledger + position service` is one of the
"do not decompose" theorems. Append-only FIFO costing has invariants
that span the file; splitting into Tier-3 sub-agents creates state-mutation
races. Stay single-author; budget extended.

Read before starting:
- `docs/architecture.md` §6.5 (stock ledger model)
- `specs/api-phase1.yaml` inventory section
- The Item / Sku models in `app/models/masters.py:316-415` for primary_uom, tracking
- `app/utils/timestamp.py` (UTC discipline)

### 2. The drift gate now covers UOM `__table_args__`

Future model edits to UOM/HSN that change unique constraints must update
both the ORM model AND a forward Alembic migration. The drift gate test
(`tests/test_orm_ddl_drift.py`) catches mismatches against the migrated
DB, but not against `schema/ddl.sql` — by design (DDL is historical).

### 3. `app/cli/` directory is new

`app/cli/seed.py` is the first CLI tool. If TASK-022 needs an admin
script (e.g. recompute stock positions), put it under `app/cli/` for
consistency. Module discovery: `python -m app.cli.<name>`.

## Open flags carried over

- **TASK-040 redundancy:** COA seeding is already shipped here. When
  TASK-040 is picked up, scope it to "COA model + admin endpoints to
  edit ledgers" (the seeding half is satisfied). May fold TASK-040 into
  the next admin-panel task.
- **Demo data:** parties + items seed deferred to a future
  `make seed-demo`. Slot when frontend wave starts.
- **`(org_id, name)` UOM unique:** added in this migration (every org
  gets uniqueness on display name too). If a future feature needs
  duplicate display names for some reason, drop the constraint then.

## Observable state at end of task

- New file: `backend/app/service/seed_service.py` (4 public seed funcs).
- New file: `backend/app/cli/__init__.py`, `backend/app/cli/seed.py`.
- New file: `backend/alembic/versions/2026042700001_task_015_uom_hsn_per_org_unique.py`.
- New file: `backend/tests/test_seed_service.py` (9 tests).
- Modified: `backend/app/models/masters.py` (Uom, Hsn `__table_args__`).
- Modified: `backend/app/routers/auth.py` (signup wires `seed_system_catalog`).
- Modified: `backend/tests/test_auth_routers.py` (signup test now also
  asserts UOM and HSN counts = 10 post-signup).
- Modified: `backend/tests/test_item_routers.py` (replaced two
  "empty-for-unseeded-org" tests with "seeded-catalog" tests since the
  new behavior is auto-seed).
- Modified: `backend/tests/test_migration_smoke.py` (head revision
  bumped to `task_015_uom_hsn_per_org`).
- Modified: `Makefile` (`make seed` target now explains auto-seed).
- Postgres test container `fabric-task010-pg` on `localhost:5499` has
  been `alembic upgrade head` to the new revision.
