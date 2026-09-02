# TASK-205 retro — in-use delete guards for BOM / Design / Operation-Master

**Date:** 2026-09-02
**Branch:** fix/issue-205
**Commit:** `<sha>` (on branch; not yet merged)
**Plan:** GitHub issue #205 comment (implementation plan)

## Summary

Replicated Routing's shipped in-use delete guard into the three master soft-deletes that were missing it. `delete_bom` now refuses (422) when a non-CLOSED, non-deleted MO references the BOM; `delete_design` refuses when a live BOM, live routing, or non-CLOSED MO references it; `delete_operation_master` refuses when a live routing edge or an active MO's operation references it. The two masters that were also missing an audit emit (`delete_design`, `delete_operation_master`) now emit `audit_log` `action="delete"` rows, matching `delete_routing`. No schema, migration, router, permission, or Pydantic change. TDD red confirmed (all 8 refuse/audit tests failed with 204-not-422 / missing-audit before the guards, pass after). Lint (ruff check + format), mypy, and the affected pytest suites (test_bom, test_manufacturing_masters, test_routing, test_mo, test_mo_completion, test_routing_flow, test_seed_demo_manufacturing) are all green. Not merged — pipeline orchestrator integrates.

## Deviations from plan

### 1. `specs/api-phase3.yaml` could not be annotated with the 422 response
Plan said: document the 422 in-use response on the three DELETE operations in `specs/api-phase3.yaml`. Reality: those DELETE operations do not exist in that spec. `api-phase3.yaml` is an aspirational design-level spec using a `/manufacturing/designs/{id}` prefix with a `patch` and an `archive` op — no `delete`, and no `/operation-masters` path at all. The real endpoints (`/designs/{id}`, `/boms/{id}`, `/operation-masters/{id}` DELETE) were shipped in TASK-TR-A02/A03 without any OpenAPI entry.
- **Fixed by:** not fabricating mismatched entries; filed FUP-205-C in TASKS.md to add the real master CRUD (incl. DELETE 204 + 422) to the spec.
- **Why not caught in planning:** the plan assumed the endpoints were already in the phase-3 spec.
- **Impact on later tasks:** none beyond the filed follow-up.

## Things the plan got right (no deviation)

- The `_has_blocking_mo` reference (`routing_service.py:268`, `delete_routing:562`) transplanted cleanly.
- The exact referencing columns table was accurate (design ← bom/routing/MO; bom ← MO.bom_id; op-master ← routing_edge + mo_operation).
- Placing the BOM guard inside the existing partition advisory lock (after the re-read) required no restructuring.
- The routers already map `AppValidationError` → 422 with the same envelope; no router change needed, exactly as predicted.

## Pre-next-task checklist

### 1. Demo-tenant data repair (from #205 plan §9)
The QA campaign already soft-deleted a BOM, a design, and an op-master while they were still referenced, orphaning live rows. Run the detect query in the #205 plan §9 against the demo tenant and either un-delete or reseed. Non-demo hits → escalate to Moiz. Not done here (this branch is code + tests only, against `test_205`).

## Open flags carried over

- **FUP-205-A** (TASKS.md): cost-centre delete has the same latent gap; its FKs are SET NULL (graceful), so deferred.
- **FUP-205-B** (TASKS.md): `create_mo` doesn't take the BOM partition advisory lock, so a delete-vs-create-MO interleave at READ COMMITTED is still possible — same residual posture as the shipped Routing guard.
- **FUP-205-C** (TASKS.md): 404-vs-422 on GET of a deleted master (P3 read-side finding) + adding the master DELETE endpoints to the OpenAPI spec.

## Observable state at end of task

- Test DB `test_205` migrated to head; no migration added.
- Guards are org-scoped (`org_id` filter as defense-in-depth on RLS) and only consider live referencing rows (`deleted_at IS NULL`); CLOSED MOs never block (COMPLETED does).
