# TASK-TR-A03 retro — deviations from plan and pre-next checklist

**Date:** 2026-05-15
**Branch:** task/tr-a03-bom
**Commit:** `<sha>` (PR open, not merged — Track A spine, needs review)
**Plan:** TASK-TR-A03 brief (Manufacturing track, wave A continuation)

## Summary

Shipped the BOM (Bill of Materials) service + router on top of A01 (`bom` /
`bom_line` ORM models) and A02 (Design CRUD). New files:

- `backend/app/service/bom_service.py` — the lifecycle owner: `create_bom`,
  `get_bom`, `list_boms`, `activate_bom`, `delete_bom`. Composes against
  `manufacturing_masters_service.get_design` (design ownership) and
  `items_service.get_item` (finished-item + line-item ownership) — no
  reach-around into other domains.
- `backend/tests/test_bom.py` — 15 integration tests covering all the
  invariants below.

Updated:

- `backend/app/schemas/manufacturing.py` — added `BomLineInput`,
  `BomLineResponse`, `BomCreateRequest`, `BomResponse`, `BomListResponse`.
- `backend/app/routers/manufacturing.py` — added a fourth sibling router
  `boms_router` with the five endpoints (`POST /boms`, `GET /boms`,
  `GET /boms/{id}`, `POST /boms/{id}/activate`, `DELETE /boms/{id}`).
- `backend/app/service/rbac_service.py` — added 4 new permission slugs
  (`manufacturing.bom.{create,update,read,delete}`). Owner via `_ALL_PERMS`;
  Production Manager full CRUD; Accountant + Salesperson read only;
  Warehouse none.
- `backend/main.py` — wired `boms_router`.
- `frontend/scripts/openapi-snapshot.json` + `frontend/src/types/api.ts` —
  regenerated via `dump-openapi.py` + `pnpm gen:types` (A02 retro flagged
  this gotcha; doing it inline so frontend doesn't drift).

TDD discipline: started with the failing
`test_create_first_bom_for_finished_item_gets_version_1_active` (404 →
schema → service → router → wire-up → 201). Then a vertical slice per
invariant. The strongest invariant test
(`test_only_one_active_bom_per_finished_item_invariant`) issues a sequence
of create / activate / delete operations and then queries the DB directly
to assert exactly one active row.

**Verification:**

- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean.
- `uv run mypy .` — clean across 202 source files.
- `uv run pytest -q` — full suite green; 15 new BOM tests + everything
  pre-existing pass.
- `pnpm gen:types && pnpm check:types` — clean. Frontend types include the
  new `BomCreateRequest` / `BomResponse` shapes.

## Headline invariants & how they're enforced

### Version auto-bump

The unique constraint on `bom` is `(firm_id, finished_item_id,
version_number)` — there is no `code` column. `create_bom`:

1. Looks up the partition for `(org_id, design_id, finished_item_id)` via
   `_lock_partition` (which I'll describe under "concurrency" below).
2. Computes `next_version = max(existing.version_number or 0) + 1`, or `1`
   if the partition is empty.
3. Inserts the new BOM with `is_active=True`.
4. Demotes any existing actives in the partition to `is_active=False`.

All four steps execute in the caller's session / transaction. If any
step fails, the whole BOM goes away. Audit emit is the last write.

### Exactly-one-active

`_demote_other_active_boms` (used by `create_bom` + `activate_bom`) and
`_promote_next_active_bom` (used by `delete_bom`) are the only paths that
touch `is_active`. Each is called inside the same transaction as the
mutation that triggered it, so the database never sees a multi-active
state at commit boundaries within a single writer.

`test_only_one_active_bom_per_finished_item_invariant` exercises a
3-BOM lifecycle (create v1, v2, v3 → activate v2 → delete v3 → activate
v1), then opens a fresh session, sets the RLS GUC, and counts active
rows. Exactly one. This is the safety net that catches any future
refactor that breaks the invariant.

### Concurrency

`_lock_partition` uses `SELECT ... FOR UPDATE` against every non-deleted
BOM row in the partition. Two concurrent `create_bom` calls for the same
`(design_id, finished_item_id)` serialize on this lock — the second
writer blocks until the first commits, then reads the now-updated
partition state and bumps the version correctly. Without the row lock,
two concurrent writers could both observe an empty partition, both
assign `version=1`, and the second would fail the unique constraint.
With the lock, the second writer sees the first's v1 and correctly
picks v2.

Belt-and-braces would be a partial unique index
(`CREATE UNIQUE INDEX bom_one_active_per_partition ON bom (design_id,
finished_item_id) WHERE is_active AND deleted_at IS NULL`). I chose not
to add it this PR — the row lock plus the service-level invariant test
is enough for MVP, and a future migration can layer the index on
without code change.

## Deviations from plan

### 1. `firm_id` lives in the request body, not derived from the JWT
The plan called for service signatures with explicit `firm_id`, and I
wired the router so that `POST /boms` takes `firm_id` in the
`BomCreateRequest` body (matching the A02 pattern for
`DesignCreateRequest`). Initially I tried `current_user.firm_id` but the
auth signup flow issues tokens with `firm_id=None`. Read paths
(`get_bom`, `activate_bom`, `delete_bom`) take only `org_id` — the BOM
row carries its own `firm_id`, and `get_bom` defense-in-depth-filters by
`org_id` only. This matches `items_service.get_item`.
- **Fixed by:** schema + router shape; service signatures still take
  `firm_id` explicitly on `create_bom` (per CLAUDE.md invariant).
- **Why not caught in planning:** plan said "explicit `firm_id`" but
  didn't specify whether it's per-call or per-token; the
  signup-vs-switch-firm distinction was the wrinkle.
- **Impact on later tasks:** A04 (routing) will face the same question
  — same answer: body for create, org-scoped for reads.

### 2. PATCH on BOM header / lines deferred to A03b
Per the plan brief. Edits in textile-trade BOMs go through "create a new
version" — once a BOM has shipped material, you don't mutate it. The
service does not expose `patch_bom` or `update_bom_lines`. If A03b
proves the need, it's a straight additive change.

### 3. Baseline test pollution flake
First pre-task `uv run pytest -q` showed 209 failed + 160 errored. After
the second clean run (excluding `test_masters_models.py` /
`test_item_service.py` which had stale-schema `encrypted_dek NOT NULL`
errors), the suite ran 813 tests clean. The root cause was a previous
session's DB schema not matching the current ORM (`encrypted_dek`
column exists in the DB but not the model). Running `test_orm_ddl_drift`
re-wipes + remigrates the schema and clears the state. Not introduced
by A03 — pre-existing, but worth a watch.
- **Fixed by:** ran `pytest tests/test_orm_ddl_drift.py` before the BOM
  tests; everything passed thereafter.
- **Impact on later tasks:** if the DB drifts again,
  `test_orm_ddl_drift` is the canary; running it first resets state.

## Things the plan got right (no deviation)

- Composition over inheritance worked cleanly:
  `manufacturing_masters_service.get_design` and `items_service.get_item`
  both already raise `AppValidationError` on missing / cross-org rows, so
  the BOM service just calls them and the 422 propagates.
- The `bom`-table model from A01 was structurally complete — no DDL or
  Alembic migration needed for A03.
- `audit_service.emit` shape accepted the new entity type
  (`manufacturing.bom`) without change.
- The Idempotency-Key middleware sits in front of every router; BOM's
  mutating endpoints declare the header parameter for OpenAPI
  completeness but don't add service-layer dedup, matching every other
  router in the codebase.
- The frontend codegen step from A02 ran cleanly once `pnpm install`
  filled `node_modules`.

## Pre-TASK-TR-A04 (Routing) checklist

Ordered by what will bite first.

### 1. Routing has the same "versioned with auto-bump" shape as BOM
Look at `Routing` in `app/models/manufacturing.py`: it has
`(firm_id, code, version_number)` unique key + `is_active` + `created_by`
FK. Same template applies:
- `routing_service.py` (new file).
- `_lock_partition` + `_next_version_number` + `_demote_other_active_*`
  + `_promote_next_active_*` mirror what BOM does, with the partition
  keyed on `(firm_id, code)` — *not* `(design_id, ...)` because
  `Routing.design_id` is the design, but the unique constraint uses
  `code` not `design_id`. Worth re-reading the model carefully before
  implementing.

### 2. RoutingEdge DAG validation is service-layer
`RoutingEdge.from_operation_id → to_operation_id` defines a DAG. The
service must reject:
- Self-loops (`from == to`).
- Cycles (will need a topological-sort check in `create_routing` or
  `add_edge`).
- Edges referring to operations not in this org.

### 3. The `Routing.created_by` FK is inline (like Bom + Design)
Mirror A03's pattern: don't use AuditByMixin for `created_by` /
`updated_by` on Routing — the FK is inline in DDL, plain UUID for
sweep-added `updated_by`. See `Bom` for the exact shape.

### 4. The `manufacturing_masters_service` module is already untouched by A03
Per the plan, BOM lives in its own `bom_service.py`. Same call for A04
— `routing_service.py`. Keeps single-responsibility per file.

## Open flags carried over

- **No partial unique index for the one-active invariant.** Row-level
  lock + service-layer test is sufficient for MVP. A future migration
  could add `CREATE UNIQUE INDEX ... WHERE is_active AND deleted_at IS
  NULL` as belt-and-braces. Tracked here, not blocking.
- **`patch_bom` deferred to A03b.** Currently you have to create a new
  version to "edit" a BOM. If real users push back on this UX, A03b
  ships header-PATCH (notes / metadata only) while keeping line edits
  via versioning.
- **Outward / inward challan FK on `MoOperation`.** Still plain UUIDs
  (A01 flagged this) — re-add the FK when the jobwork target tables are
  remodelled. Not on A03 / A04's path.
- **Baseline test flakiness when DB schema drifts.** See deviation §3.
  Running `test_orm_ddl_drift` first resets state.

## Observable state at end of task

- New endpoints under `/boms` — visible in OpenAPI under the
  `manufacturing` + `bom` tag pair.
- 4 new permissions seeded automatically into every new org on signup
  (via `rbac_service.seed_system_permissions`). Existing orgs will only
  pick them up if re-seeded.
- No DB migration. `bom` + `bom_line` already exist (A01).
- Frontend types regenerated; new `BomCreateRequest` / `BomResponse`
  shapes available to FE work in a future Track B task.
