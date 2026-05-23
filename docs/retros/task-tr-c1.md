# TASK-TR-C1 retro — Fresh-signup → demoable bundle

**Date:** 2026-05-23
**Branch:** task/tr-c1-fresh-signup-demoable
**Commit:** (to land on merge)
**Plan:** ad-hoc bundle from QA re-audit 2026-05-23

## Summary

Bundled four small fixes that all sit on the "first 5 minutes of a brand-new org" path so a fresh signup leaves the user in a demoable state instead of stranded.

1. **Backend:** `/auth/signup` now calls `inventory_service.get_or_create_default_location` after firm insert so every new firm starts with a `MAIN` warehouse (`code='MAIN'`, `WAREHOUSE`, `is_active=true`). Backfill not required — only new signups need this. New integration test `tests/test_signup_seeds_default_location.py` pins the contract; three pre-existing tests in `tests/test_locations_router.py` updated to match the new "fresh firm has 1 location" reality.
2. **Frontend (MoCreateWizard, Section 1 Quantity):** removed `Math.max(0, …)` clamp that allowed qty to fall below the `min={1}` constraint, added `step={1}`, and added an inline comment so future audits know there is *no* `max` cap. Manual reproduction of the audit's `valuemax="0"` claim wasn't possible (no `max=` attribute existed in HEAD), so the defensive fix is to honour `min=1` strictly and document the absence of a cap.
3. **Makefile (`seed-demo`):** prepended `ENVIRONMENT=$${ENVIRONMENT:-dev}` so `crypto.get_master_kek()` falls back to the dev KEK instead of raising `PIIConfigError`. Mirrors the `RUN_ENV` env-prepend pattern the backend `run` target uses. Verified end-to-end: `make seed-demo` boots cleanly and seeds 18 parties / 15 items / 3 POs / 5 SIs / 1 JWO.
4. **Frontend (MoCreateWizard, DesignSelector):** added an empty-state CTA inside the listbox region that distinguishes "no designs at all" (fresh-signup case) from "search returned nothing". The empty-state shows a short message plus a link to `/manufacturing` (the closest existing route — there is no `/manufacturing/designs` route yet). The wizard "Next" gate is unchanged.

**Verification:** backend `pytest -q` = 1186 passed (REDIS_URL required for 7 pre-existing idempotency-replay tests; documented in the conftest). Frontend `pnpm test` = 447 passed across 82 files. `pnpm lint` and `pnpm typecheck` clean. Backend `ruff check` + `ruff format --check` clean.

## Deviations from plan

### 1. Audit's `valuemax="0"` claim couldn't be reproduced verbatim
The audit reported a quantity spinbutton with `valuemax="0"` rejecting input. Reading the actual `MoCreateWizard.tsx` showed no `max=` attribute on the qty input — just `min={1}` and a `Math.max(0, ...)` clamp on the onChange handler.
- **Fixed by:** Tightening the clamp to `Math.max(1, ...)` and adding `step={1}` so the field can never produce a value below `min=1`. Added an explicit code comment that no `max` cap exists. If the audit's screen-reader/devtools snapshot was reading `aria-valuenow=0` (qty briefly held 0 between keystrokes when the user cleared the field), the new clamp eliminates that window.
- **Why not caught in planning:** the audit description "valuemax='0'" mis-named the attribute; the real symptom was the clamp letting qty fall below `min`.
- **Impact on later tasks:** zero. The fix is strictly safer than the prior code.

### 2. Three existing location-router tests had to be updated
The pre-C1 contract was "fresh firm has 0 locations". This task inverts that, so three tests in `tests/test_locations_router.py` were rewritten:
- `test_list_locations_empty_for_fresh_firm` → `test_list_locations_returns_seeded_default_for_fresh_firm`.
- `test_create_location_returns_201_with_full_row` now picks a distinct code (`GODOWN-B`) to exercise the create-success path without colliding with the seeded `MAIN`.
- `test_create_location_duplicate_code_returns_envelope_error` is now a stronger test — the very first POST of `MAIN` 409s because signup already seeded it.
- **Fixed by:** Direct edits in `tests/test_locations_router.py` with TASK-TR-C1 references.
- **Why not caught in planning:** the spec said "Backfill NOT required" and "Existing fixture-built test orgs can stay empty" — that's true for fixtures but not for tests that signup-then-assert. The fast feedback loop here was running `make test` and reading three predictable failures.
- **Impact on later tasks:** none — the new contract is the safer one.

## Things the plan got right (no deviation)

- `inventory_service.get_or_create_default_location` already existed as an idempotent helper. The signup wire-in was one extra import + 3 lines — no duplication of the bootstrap logic.
- `make seed-demo` failure mode was exactly as described (`PIIConfigError` from `crypto.get_master_kek` when `ENVIRONMENT` isn't `dev`). The fix recipe (mirror `run` target's env prepend) worked verbatim.
- Frontend wizard tests (16 tests) didn't need changes — the new clamp + empty-state are additive.

## Pre-next-task checklist

### 1. Ship a Designs-management screen so the C1 empty-state CTA has a real destination
Right now the empty-state CTA points to `/manufacturing` (the pipeline kanban), which is the closest existing route. When a proper `/manufacturing/designs` list/create lands, update the `<Link to="/manufacturing">` in `MoCreateWizard.tsx` (search for `TASK-TR-C1` comment in `DesignSelector`).

### 2. Watch for follow-up audit findings on the qty input
If a future audit still reports `valuemax` or `aria-valuemax` issues on the qty field, the real cause is upstream of `MoCreateWizard.tsx` — most likely the `Input` wrapper in `frontend/src/components/ui/input.tsx`. The wrapper passes `{...rest}` cleanly today, so a regression would mean someone added an attribute injection.

## Open flags carried over

- No FE route for `/manufacturing/designs` yet (CTA currently routes to `/manufacturing`). Will close out with the Designs CRUD task.
- 7 pre-existing idempotency-replay tests in the backend require `REDIS_URL` to pass (they fail-silent without it because the dedup middleware no-ops). Not introduced or aggravated by this task; flagging for a future conftest hardening.

## Observable state at end of task

- Fresh signup now produces a tenant with: 1 firm + 1 location (`MAIN` warehouse) + system catalog (UOMs, HSN, COA) + OWNER role.
- `make seed-demo` runs cleanly on a fresh `backend/.env` (copy from `.env.example`). With Redis + Postgres up via docker-compose, the command finishes in a couple of seconds.
- No new migrations, no new schema. RLS rules and audit columns inherit from the existing `Location` model.
