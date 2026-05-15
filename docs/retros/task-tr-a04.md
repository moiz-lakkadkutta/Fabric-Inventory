# TASK-TR-A04 retro — Routing service + router with DAG validation

**Date:** 2026-05-15
**Branch:** task/tr-a04-routing
**Plan:** part of `~/.claude/plans/read-all-the-files-cozy-eich.md` (Phase A — Manufacturing masters)

## Summary

Shipped the Routing aggregate on top of the `routing` + `routing_edge`
tables that landed in A01. `routing_service.py` owns DAG validation,
threshold rules, advisory-lock-serialised create, atomic edge replace,
soft delete, and the in-use guard against non-CLOSED manufacturing
orders. `manufacturing.py` router exposes POST/GET-list/GET-detail/PATCH
edges/DELETE under `/routings`, each gated on the new
`manufacturing.routing.{write,read}` RBAC slugs (Salesperson denied at
write; Accountant + Production Manager + Owner read; only Production
Manager + Owner write). Lint (ruff + mypy whole tree) and the full
backend pytest suite (957 tests, 22 new for routing) all pass; pre-
existing JV failures are unrelated (org-creation bypass colliding with
SEC1's NOT NULL `encrypted_dek`) and present on `main`. OpenAPI snapshot
and FE types regenerated.

## Deviations from plan

### 1. Single `write` permission instead of split write verbs
Plan implied four permissions per entity (`create / update / read /
delete`) mirroring Design / OperationMaster / CostCentre. Routing only
got `manufacturing.routing.{write,read}` because routing edits flow
through "replace edges" (atomic re-validation of the whole DAG) — there
is no partial-edge PATCH, so splitting create/update/delete adds
ceremony without any RBAC boundary that means anything to the user.
- **Fixed by:** `app/service/rbac_service.py` — two slugs, doc comment
  explaining the asymmetry.
- **Why not caught in planning:** the implication only fell out after
  the schema decision to replace edges as a set.
- **Impact on later tasks:** zero. MO (A05) will probably re-evaluate
  per-state slugs (RELEASE / CLOSE) because state transitions there
  *are* meaningfully different from each other.

## Things the plan got right (no deviation)

- Advisory lock keyed on `(org_id, firm_id, code)` via
  `hashtext(:k)::bigint` matches `bom_service._advisory_lock_partition`
  exactly — the comment in BOM about Postgres widening 32-bit hashtext
  into the 64-bit slot transfers verbatim.
- Soft-delete + `IntegrityError` → 422 retry message belt-and-braces
  pattern survived a deliberate stress test (`monkeypatch` forces
  `_next_version_number` to 1 after a soft-delete; the DB unique fires;
  the response is a clean 422 with `VALIDATION_ERROR`).
- Composition over inheritance: design / operation ownership is checked
  via `manufacturing_masters_service.get_design /
  get_operation_master`. No private cross-module imports.

## Cycle-detection algorithm choice

Iterative DFS with three-coloring (WHITE = unvisited, GRAY = on stack,
BLACK = done). A GRAY hit during recursion is a back-edge → cycle.
Picked it over Kahn's topo-sort because:

1. **Earliest-witness rejection.** DFS returns `True` the instant it
   finds the offending back-edge; Kahn must compute every in-degree
   then peel zero-degree nodes until it stalls. For human-sized
   routings (cut → stitch → finish → QC, a couple dozen edges max) the
   constant factor is irrelevant, but the code is shorter.
2. **Stack-based, not recursive.** Routings are small but a recursion
   limit blow-up on a future "macro routing" composed of nested sub-
   routings would be a nasty regression. The explicit
   `list[(node, neighbours)]` stack sidesteps it.
3. **Self-loops handled upfront.** They're caught before DFS in
   `_validate_edges` with a clearer error message; the cycle check
   would also catch them but `"self-loop"` reads better than `"cycle"`
   when `from == to`.

The implementation is in `_detect_cycle` (routing_service.py:129) and
the test (`test_create_routing_rejects_cycle`) uses the canonical
A→B→C→A triangle.

## Pre-TASK-TR-A05 checklist (Manufacturing Order header + state
machine)

### 1. Read A04's `_has_blocking_mo` helper before designing MO state
`routing_service._has_blocking_mo` already declares the contract: a
non-CLOSED, non-deleted MO blocks routing edits / deletes. A05 must
keep `MoStatus` aligned (DRAFT / RELEASED / IN_PROGRESS / CLOSED /
CANCELLED — exact enum is in `app/models/manufacturing.py:MoStatus`).
Don't introduce a sixth state without revisiting the routing block
predicate.

### 2. Decide on MO → Routing FK semantics
Routing has `version_number`; A04 didn't surface it in the API.
Question for A05: when an MO is released against Routing v1 and v2 is
later created, does the MO follow v2 or stay on v1? Recommendation:
**stay on v1** (snapshot semantics — MOs are historic). If A05 wants
"latest active", that's a different endpoint
(`GET /routings/active?design_id=...`) and not in A04 scope.

### 3. Idempotency keys are wired but not asserted in router
Like BOM (A03), the router accepts `Idempotency-Key` as a header but
deduplication is `app/utils/idempotency.py`'s job at the middleware
layer. A05 should not re-implement idempotency in the service; just
plumb the header through.

### 4. `make openapi-snapshot` requires `pnpm install` in the worktree
The frontend `node_modules/` is not symlinked from the main checkout.
First run in a fresh worktree errors with `openapi-typescript: command
not found`. Run `cd frontend && pnpm install` once per worktree.

## Open flags carried over

- **Routing header PATCH not implemented.** A future task can add
  rename / change-design / activate-version. A04 deliberately scoped
  it to "replace edges" only — header edits weren't on the plan and
  there is no UI demand yet.
- **No `RoutingResponse.name` field.** The DDL has no `name` column on
  `routing` (it's per-design); the request body accepts `name` for
  audit-log purposes only. If the FE needs to surface a routing name,
  decision is whether to derive it (Design.name + version) or add a
  column.
- **Pre-existing JV test failures on main.** `test_journal_voucher_*`
  fails because the JV tests insert `Organization` rows bypassing
  `identity_service.register_organization` which is where SEC1 wired
  the `encrypted_dek` generation. Out of A04 scope; should be a
  follow-up against C01.

## Observable state at end of task

- Dedicated test DB `fabric_erp_tra04_test` is at migration head
  `task_tr_sec1_organization_dek`. Created by the prior agent;
  `backend/.env` in this worktree (gitignored) points at it.
- All 22 new routing tests + 935 pre-existing tests pass. 9 JV tests
  fail with the SEC1 / C01 collision noted above — same on `main`.
- Worktree at `~/fabric-worktrees/tr-a04-routing` should be removed
  after the PR merges.
