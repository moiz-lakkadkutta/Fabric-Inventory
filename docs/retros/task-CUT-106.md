# TASK-CUT-106 retro — OpenAPI codegen for FE types

**Date:** 2026-05-10
**Wave:** 2
**Branch:** `task/CUT-106-openapi-codegen`
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 2 row CUT-106)

## Summary

Replaced the four hand-written `interface BackendXxx` blocks in `lib/queries/{invoices,dashboard,accounts,identity}.ts` (12 interfaces, ~140 LOC) with type aliases that pull from a codegen-derived `frontend/src/types/api.ts`. The codegen reads from a committed OpenAPI snapshot at `frontend/scripts/openapi-snapshot.json` produced by a tiny in-process Python script (`frontend/scripts/dump-openapi.py`). CI now blocks PRs that drift either layer:

1. BE schema → snapshot drift (someone added a pydantic field but forgot to refresh the snapshot)
2. snapshot → codegen drift (someone refreshed the snapshot but forgot `pnpm gen:types`)

Final state: 31 vitest files / 118 tests / 0 failures; `pnpm lint` + `pnpm typecheck` clean; backend `ruff` + `mypy` untouched and green; `pnpm gen:types`, `pnpm check:types`, `pnpm gen:types:live`, and `make openapi-snapshot` all work end-to-end. The unused YAML-derived `api.generated.ts` was removed (no consumers, superseded by `api.ts`).

## Deviations from plan

### 1. Replaced the YAML-derived `api.generated.ts` instead of leaving it alongside

The pre-existing `frontend/src/types/api.generated.ts` (5,943 LOC, generated from `specs/api-phase1.yaml` via the older `openapi:gen` script) had **zero importers** in the codebase — confirmed by `grep -rn "api.generated\|from '@/types/api"`. The plan didn't ask for its removal, but having both `api.ts` (live FastAPI) and `api.generated.ts` (hand-maintained YAML spec) was confusing — they use different schema names (`SalesInvoiceResponse` vs `Invoice`), so future contributors would be unsure which to import. Deleted it as part of this cutover so there's exactly one codegen output.

- **Fixed by:** `git rm frontend/src/types/api.generated.ts`; replaced `openapi:gen`/`openapi:check` scripts with `gen:types`/`check:types` in package.json; updated `.prettierignore` accordingly.
- **Why not caught in planning:** the plan was written with the assumption that `api.generated.ts` was alive. Static check showed otherwise.
- **Impact on later tasks:** zero. Other agents have only ever written hand-rolled `BackendXxx` interfaces.

### 2. Codegen surfaced 3 real schema mismatches the hand-written interfaces hid

The task notes warned this might happen ("if you hit a tsc error, that's the codegen catching a real schema mismatch — don't paper over it"). Three concrete cases:

- **`series` is required-with-default in `SalesInvoiceCreateRequest`.** Hand-written `BackendCreateBody` omitted it. The FE was relying on pydantic's server-side default `"RT/2526"`. Fix: send `series: 'RT/2526'` explicitly in `buildCreateBody` so the wire type matches the schema. No-op on the wire (BE still applies the default).
- **`allocations` is optional in `ReceiptListItem` and `ReceiptResponse`.** BE schema declares `list[...] = Field(default_factory=list)`; pydantic emits this as optional. Hand-written `BackendReceiptListItem.allocations` was non-nullable. Fix: `(b.allocations ?? []).map(...)` in the mappers.
- **`SalesInvoiceResponse` has 5 fields the hand-written `BackendSalesInvoice` was missing:** `bill_to_address`, `delivery_challan_id`, `finalized_at`, `salesperson_id`, `ship_to_address`. Fix: added them to the test fixtures (real BE responses already include them; the FE just hadn't been declaring them in its types).

- **Fixed by:** see above; all three are minimal additions to either the test fixtures (`invoices.live.test.ts`) or the runtime mappers (`accounts.ts`, `invoices.ts`).
- **Why not caught in planning:** these were real BE-FE drifts that only the codegen could catch — that's the whole point of this task. The task notes called this out explicitly; no surprise.
- **Impact on later tasks:** Wave 2 agents working on receipts (CUT-103, CUT-104) and Wave 3 agents working on PDF/InvoiceDetail (CUT-205) inherit cleaner types. The codegen now catches future BE additions automatically.

### 3. Snapshot generated from in-process FastAPI, not from `:8000`

Plan had `gen:types` hit `http://localhost:8000/openapi.json`. That requires a live BE for every codegen run, which (a) doesn't work in CI, (b) is racy if Wave 2's CUT-103/CUT-105 are mid-edit when this task lands. The committed-snapshot approach is more deterministic.

- **Fixed by:** `frontend/scripts/dump-openapi.py` imports the FastAPI app in-process (no live server, no DB, no Redis — just Settings env vars), writes JSON with `sort_keys=True` so diffs are stable. `pnpm gen:types` reads from the snapshot. `pnpm gen:types:live` is added as a convenience for "regenerate against my running BE" during local dev.
- **Why not caught in planning:** plan partially anticipated this ("commit the openapi.json snapshot at `frontend/scripts/openapi-snapshot.json`") — implementation followed the spirit, with `pnpm gen:types` reading the snapshot rather than the live URL.
- **Impact on later tasks:** zero — agents who change BE schemas can run `make openapi-snapshot` to refresh both files in one shot.

## Things the plan got right (no deviation)

- `openapi-typescript` was already in `devDependencies` from a prior task — no `pnpm add`.
- `components['schemas']['X']` style is exactly what the codegen produces; the hand-written interfaces were drop-in compatible after a name swap (no call-site rewrites except the 3 schema-drift cases above).
- The two-layer CI guard (snapshot vs BE in-process; codegen vs snapshot) cleanly separates the two failure modes for clear error messages.
- Backend mypy was untouched — the dump script lives in `frontend/scripts/` so it's not part of the BE typecheck surface.

## Pre-TASK-CUT-201 (Wave 3) checklist

### 1. After Wave 2's other PRs land, refresh the snapshot

CUT-101 (parties FE), CUT-102 (items+SKUs), CUT-103 (banking + vouchers), CUT-104 (receipts P1), CUT-105 (reports BE) are landing in parallel. Each one likely added new endpoints/schemas to the BE that aren't yet in `frontend/scripts/openapi-snapshot.json`. After they all merge to `main`:

```bash
git pull origin main
make openapi-snapshot       # refreshes snapshot + regens api.ts
git add frontend/scripts/openapi-snapshot.json frontend/src/types/api.ts
git commit -m "TASK-CUT-106-followup: re-codegen after Wave 2 BE landings"
```

CI's `openapi-drift` job will block any PR opened after that point if the snapshot is stale.

### 2. Wave 3 agents (CUT-201..205) should consume `components['schemas']['X']` directly

Pattern is now established. Don't write `interface BackendXxx { … }` blocks in any new query file — import from `@/types/api` instead. If a schema doesn't exist in the snapshot, it's because the BE hasn't shipped that endpoint yet — escalate or wait.

### 3. Pydantic `Field(default=...)` semantics in OpenAPI

Worth knowing for future schema work: `series: str = Field(default="RT/2526")` becomes a **required-with-default** property in OpenAPI (3.1) — it's not the same as `Optional[str]`. When you want a field that the FE can omit, use `field: T | None = None` instead. The codegen makes this distinction visible in TypeScript: required-with-default is `field: string`, while truly-optional is `field?: string | null`.

## Open flags carried over

- **`MeResponse` in `store/auth.ts` is still hand-written.** It mirrors the codegen `components['schemas']['MeResponse']` but is declared in store/auth.ts (where it's used as part of `AuthState`) rather than imported from the codegen. Out of scope for CUT-106 (the task explicitly listed only 4 query files). Future cleanup task: replace the local declaration with `type MeResponse = components['schemas']['MeResponse']`. Watch out: the codegen makes `available_firms` and `flags` optional (because pydantic's `Field(default_factory=...)`); the auth store currently treats them as required.
- **Test setup file `test-setup.ts` builds a `MeResponse` literal** with all fields populated. If we ever swap to the codegen type, the literal will need adjusting (see above).
- **Zod / runtime validation is NOT included.** The codegen is types-only — wire payloads are still trusted by structure at the boundary. If a malformed BE response sneaks past CI, the FE will crash at the mapper. Out of scope; revisit if we ever see this happen in practice.

## Observable state at end of task

- `frontend/scripts/dump-openapi.py` is an executable Python script. It imports the FastAPI app from `backend/main.py` in-process — needs `uv run` for dependency resolution.
- New CI job `openapi-drift` on every push/PR. Adds ~30s to CI by re-installing both BE + FE deps, but fails-fast — most PRs won't trigger an actual diff.
- `make openapi-snapshot` is the one-command refresh. Add to muscle memory after any BE schema change.
- `frontend/src/types/api.ts` is 5,918 LOC of generated types — committed for offline TS resolution + jsdom test imports. `.prettierignore` ignores both it and the snapshot JSON.
