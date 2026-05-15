# TASK-TR-A02 retro — deviations from plan and pre-next checklist

**Date:** 2026-05-15
**Branch:** task/tr-a02-mfg-masters
**Commit:** `<sha>` (PR open, not merged — Track A spine, needs review)
**Plan:** TASK-TR-A02 brief (Manufacturing track, wave A)

## Summary

Shipped the CRUD surface for three Manufacturing-domain masters built on top
of the A01 ORM models: **Design**, **Operation Master**, **Cost Centre**.
New files:

- `backend/app/schemas/manufacturing.py` — Pydantic request / response / list
  envelopes for all three entities.
- `backend/app/service/manufacturing_masters_service.py` — sync `Session`-based
  service layer (`create_/get_/list_/patch_/delete_*` for each entity),
  kw-only signatures, explicit `org_id` filter on top of RLS,
  `audit_service.emit` on creates.
- `backend/app/routers/manufacturing.py` — three sibling APIRouters
  (`/designs`, `/operation-masters`, `/cost-centres`) with permission gates,
  Idempotency-Key headers, OpenAPI summaries.
- `backend/tests/test_manufacturing_masters.py` — 23 integration tests
  covering happy path, validation, PATCH semantics, soft-delete, cross-org
  isolation at the HTTP layer, and Salesperson permission gates.

Updated:

- `backend/app/service/rbac_service.py` — added 12 new permission slugs
  (`manufacturing.{design,operation_master,cost_centre}.{create,update,read,delete}`)
  and granted them across Owner (all via `_ALL_PERMS`), Accountant (read on
  design + operation_master; full CRUD on cost_centre), Salesperson (read on
  design + operation_master; nothing on cost_centre), Production Manager
  (full CRUD on design + operation_master; read on cost_centre).
- `backend/main.py` — wired the three new routers.

TDD discipline: started with the failing `test_create_design_returns_201`
(404 → schema → service → router → wire-up → 201). Vertical slice per
entity; cross-cutting RBAC tests added at the end.

**Verification:**

- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean (after `ruff format .` reformatted
  3 new files; no changes elsewhere).
- `uv run mypy .` — clean across 200 source files.
- `uv run pytest -q` — **868 passed** in 192s (was 836 at A01-merged
  baseline; +23 new tests + a few pre-existing flakies on first baseline
  run that came back green here).
- Baseline noise observed on first pre-task run: 4 RLS / reports_ageing
  tests reported "relation `organization` does not exist" — they passed on
  the post-change full run with no changes, so the failure mode is
  pre-existing flakiness in those fixtures (not introduced by A02).

## Deviations from plan

### 1. `CostCentreType` enum is smaller than I assumed when writing the patch test
First draft of `test_patch_cost_centre` used `"PRODUCT_LINE"` as a target value —
that's not in `CostCentreType` (the actual values are
`OUTLET / CHANNEL / SEASON / DESIGNER / SALESPERSON / DEPARTMENT`, a
retail / textile-shop-flavoured set, not a manufacturing-cost-pool one).
- **Fixed by:** test now uses `"CHANNEL"`.
- **Why not caught in planning:** I assumed the enum looked like a generic
  cost-accounting taxonomy; the actual taxonomy is more
  retail-textile-specific.
- **Impact on later tasks:** zero. Flag for the next wave: if MO costing
  needs `PRODUCT_LINE`-style cost pools, extend the enum then. For now
  `cost_centre_type` is just a tag and is nullable, so callers don't have
  to pick.

### 2. Idempotency-Key behaviour
Routers carry the standard `idempotency_key: str | None = Header(...)`
parameter for OpenAPI completeness, but the actual dedup is handled
upstream by `IdempotencyMiddleware`. No service-layer dedup added — same
shape as `routers/masters.py` and `routers/items.py`. The integration
tests for "duplicate code" therefore exercise the service-layer
validation (clean 422 with `VALIDATION_ERROR` code), not idempotency
replay.

## Things the plan got right (no deviation)

- Reusing the masters / items pattern (`SyncDBSession`, `require_permission`,
  PATCH semantics, soft-delete sharing the update permission) made the
  service + router layer near-mechanical.
- Existing `audit_service.emit` signature accepted the new entity types
  (`manufacturing.design`, etc.) without change.
- `signup` already creates a Primary firm, so tests can use `me["firm_id"]`
  directly without any extra fixture wiring.
- Salesperson role gating tests followed the
  `test_reports_routers.test_reports_require_accounting_report_view_permission`
  pattern verbatim.

## Pre-TASK-TR-A03 checklist

Ordered by what will bite first.

### 1. BOM service is on top of `Design`, `Item`, and `Uom`
`backend/app/models/manufacturing.py::Bom` requires `design_id`,
`finished_item_id`, and per-line `uom` (`uom_type` Postgres enum).
A03 will need to:
- Reuse `manufacturing_masters_service.get_design` to validate the design
  exists in the caller's org before creating a BOM.
- Reuse `items_service.get_item` (and SKU lookups) for `finished_item_id`
  + each `bom_line.item_id`.
- Pull UOM choices via the existing `Uom` catalog (`items_service.list_uoms`).

### 2. BOM versioning constraint is `(firm_id, finished_item_id, version_number)`
Not `(firm_id, code, version_number)` — there's no `bom.code` column. A03
service should auto-bump `version_number` (max + 1) when a new BOM is
created against an `(item, firm)` pair that already has one, or accept an
explicit version in the request. Tests should cover both.

### 3. BOM permissions follow the same pattern this PR established
Suggested slugs:
`manufacturing.bom.{create,update,read,delete}`. Owner gets all via
`_ALL_PERMS`; Production Manager + Accountant get read; Salesperson read
(for quoting); Warehouse none. Add to `rbac_service._SYSTEM_PERMISSIONS`
and grant lists in the same H3 block.

### 4. Routing is the mirror of BOM with `RoutingEdge` for the DAG
A04 will pick up `Routing` + `RoutingEdge`. The same vertical-slice TDD
flow worked here; suggest the same: failing test first, then schema →
service → router → wire-up. Edge validation (no self-loops, no cycles in
the DAG) is service-layer logic.

## Open flags carried over

- **Manufacturing's `cost_centre_type` taxonomy.** The current values feel
  retail-flavoured (`OUTLET / CHANNEL / SEASON / DESIGNER / SALESPERSON /
  DEPARTMENT`). When MO costing lands (Phase 3 per CLAUDE.md), we may need
  values like `PRODUCT_LINE` / `WORK_CENTRE`. Surfaces in the manufacturing
  service when `cost_pool` rollups land.
- **No service-layer dedup on Idempotency-Key.** Relies on
  `IdempotencyMiddleware` upstream. Same as all other masters.
- **Baseline test flakiness.** 4 tests (`test_rls_force`,
  `test_reports_ageing::test_ageing_empty_for_fresh_firm`) failed on the
  first pre-task baseline run with a "relation `organization` does not
  exist" psycopg2 error, then passed on the post-change full run. Looks
  like a test-setup / fixture-cache race in `fresh_org_id` /
  `org_scoped_session`. Worth a separate fix-task; not on A02's
  critical path.

## Observable state at end of task

- New endpoints under `/designs`, `/operation-masters`, `/cost-centres` —
  visible in OpenAPI under `manufacturing` tag.
- 12 new permissions seeded automatically into every new org on signup
  (via `rbac_service.seed_system_permissions`). Existing orgs will only
  pick them up if re-seeded; that's the same forward-compat caveat the
  module already documents.
- No DB migration. All three tables already exist (A01 + masters).
- No frontend work in this PR — that's a separate Track B task.
