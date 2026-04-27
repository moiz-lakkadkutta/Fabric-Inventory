# TASK-011 retro — Item + SKU CRUD + UOM/HSN catalog reads

**Date:** 2026-04-27
**Branch:** task/011-item-sku-crud
**Commit:** `<sha>` (pre-merge)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md`

## Summary

Shipped Item + SKU CRUD end-to-end + read-only UOM/HSN catalog endpoints.
12 service methods (`backend/app/service/items_service.py`), 4 routers
(`/items`, `/skus`, `/uoms`, `/hsn`) under one `items.py` file, Pydantic
schemas appended to `app/schemas/masters.py`. 56 new tests (35 service + 21
router) including an RLS isolation test mirroring the TASK-010 pattern.
All 219 tests pass; ruff + format + mypy strict clean across 54 source files.

## Deviations from plan

### 1. Split into `items_service.py` instead of extending `masters_service.py`

Plan said "extend masters_service.py". Reality: `masters_service.py` was
already ~300 lines focused on Party. Adding 12 Item/SKU methods would push
it past 600 lines and mix two domains.

- **Fixed by:** new file `backend/app/service/items_service.py`. CLAUDE.md
  rule "If a file grows beyond ~400 lines, split it" was the trigger.
- **Why not caught in planning:** plan scoped scaffolding scope, not file
  budget.
- **Impact on later tasks:** TASK-022 (stock ledger) onwards will continue
  the one-domain-per-service-file pattern.

### 2. UOM / HSN are read-only in this task; full CRUD deferred

Plan said "CRUD on all four". Reality: UOM and HSN are catalog tables —
seed-data territory. Writing full CRUD now means seed data + admin UI work
that belongs in TASK-015 + a future admin-panel task.

- **Fixed by:** shipped `GET /uoms` and `GET /hsn` (with search). Create /
  update / delete deferred. Service module exposes `list_uoms` and `list_hsn`
  with explicit `org_id` filter.
- **Why not caught in planning:** the plan assumed catalog CRUD was the
  same shape as Item CRUD.
- **Impact on later tasks:** TASK-015 (seed data) populates UOM and HSN.
  An admin-panel task later (TASK-019 area) gets the create/update endpoints
  if a real UOM / HSN management workflow is needed. For MVP, seeded rows
  are enough.

### 3. SKU is keyed under Item ownership, not just org

The model has `sku.org_id` plus `sku.item_id` FK. The service ensures the
parent Item is owned by the caller's org *before* allowing SKU writes —
otherwise a client could create a SKU under any UUID and bypass org
boundary at the SKU layer.

- **Fixed by:** `create_sku` / `list_skus_for_item` call `get_item(...)`
  first, which raises `AppValidationError("not found")` for cross-org
  Item ids. Tested explicitly.
- **Why not caught in planning:** SKU was framed as "just a variant" —
  the cross-org ownership question wasn't surfaced.
- **Impact on later tasks:** every nested-resource service from now on
  must verify the parent's org ownership (e.g. PartyAddress, PartyBank,
  Order Lines, etc.).

## Things the plan got right (no deviation)

- The TASK-014 ORM scaffold for Item / Sku / Uom / Hsn was ready out of
  the box — no model edits needed in this task.
- Permission catalog already had `masters.item.{create,update,read}` —
  SKU shares Item perms (single permission domain for both).
- The TASK-010 pattern (sync Session, kw-only signatures, explicit
  `org_id`, RLS-with-non-bypassrls-test) ported cleanly.
- Single-author, no-Tier-3 path — kept the schema/state consistency
  invariant intact.

## Pre-TASK-012 checklist

### 1. TASK-012 is the Login UI (frontend)

Pivots to React + Vite + Tailwind + shadcn/ui. The frontend scaffold
(`frontend/`) is in place from TASK-003 + the lock-confirmation. Read:
- `frontend/src/api/auth.ts` if it exists; otherwise stub the call signatures
  matching `specs/api-phase1.yaml` auth section
- `backend/app/routers/auth.py` for the request/response shapes
- `specs/screens-phase1.md` SCR-AUTH-001 (Login) and SCR-AUTH-002 (MFA)

The auth service returns `access_token` (15-min), `refresh_token` (14-day),
`requires_mfa` flag, `permissions[]`. Frontend store should snapshot
permissions at login and refresh on `/auth/refresh` rotation.

### 2. The PII regex pattern (`_GSTIN_REGEX`, `_PAN_REGEX`) lives in `masters_service`

If a frontend form needs same-shape client-side validation, mirror the
regex in `frontend/src/utils/validation.ts` rather than re-deriving. Single
source-of-truth note for TASK-020/021.

### 3. UOM and HSN seed data is empty

`GET /uoms` and `GET /hsn` return `count: 0` for any unseeded org. TASK-015
must seed the standard catalog (METER, KG, PIECE, ROLL, BOX, … for UOM;
top ~50 HSN codes for textile trade per the architecture doc).

## Open flags carried over

- **Real PII encryption** (Phase 2): unchanged from TASK-010.
- **Inter-firm Item visibility** (architecture §16.2.6): currently a
  firm-scoped item is visible to that firm + org-level views. If we ever
  want strict per-firm isolation (different firms must NOT see each other's
  items), the `or_(firm_id == X, firm_id IS NULL)` rule needs adjusting.
  Decide in Wave 4 with Moiz.
- **Item / SKU rename / re-code workflow**: code is immutable. If a real
  use-case for rename emerges, the workflow is "soft-delete + re-create
  with same code under a new namespace" — needs explicit design.

## Observable state at end of task

- New file: `backend/app/service/items_service.py` (12 functions).
- New file: `backend/app/routers/items.py` (4 routers, 11 endpoints).
- Extended: `backend/app/schemas/masters.py` with Item / SKU / UOM / HSN
  schemas (10 new classes).
- `backend/main.py` registers all 4 new routers.
- New tests: `tests/test_item_service.py` (35), `tests/test_item_routers.py` (21).
- The `rls_isolation_test_role` Postgres role created in TASK-010 is
  reused; this task adds GRANT SELECT, INSERT on `item` to it (idempotent).
- Docker test container `fabric-task010-pg` on `localhost:5499` continues
  to be the local verification target (no rebuild needed for TASK-011).
