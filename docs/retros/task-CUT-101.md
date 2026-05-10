# TASK-CUT-101 retro — Parties FE wired live

**Date:** 2026-05-10
**Branch:** task/CUT-101-parties-fe-live
**Wave:** 2 (Masters live + Banking live + Reports BE foundation)
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 2 row W2-A

## Summary

`/masters/parties` and `/masters/parties/:id` now read from the live backend (`GET /parties`, `GET /parties/{party_id}`) when `IS_LIVE` is true; the click-dummy mock branch is preserved per Q6. The "+ New party" button opens a real form that POSTs to `/parties` with the four-boolean role mapping. Edit on the detail page PATCHes. The InvoiceCreate customer dropdown (which already uses `useCustomers()`) now serves real party UUIDs in live mode — the user-visible bug from the platform audit (`p_001` UUID validation 422 on POST /invoices) is closed for the customer side.

`make test` (frontend vitest 128 / 128 + backend pytest 121 unit / 502 integration-skipped) green; `make lint` (eslint + prettier + tsc) green.

## Deviations from plan

### 1. `Party` shape uses `kind` (lowercase), not `role` (uppercase)
The task spec said the click-dummy already had `role: 'CUSTOMER' | …` on its Party shape — it doesn't; it has `kind: 'customer' | …`. Renaming to `role` would have rippled into seven files (mock fixtures, JobWorkOverview, CommandPalette, …) — all out of CUT-101's lane. Kept `kind` as the lowercase legacy field, added `PartyRole` (uppercase) as a separate type for forms / mappers, plus the four `is_X` boolean flags as optional fields on `Party`. The role-mapping unit tests assert on the uppercase enum (BE→FE shim) as the spec required. No caller breakage.

### 2. `outstanding` and `city` default to 0 / '' on live shape
The BE `/parties` list endpoint doesn't include a per-party `outstanding_amount` field today (despite what the task brief implied); outstanding is computed via a join through sales_invoice + payment_allocation. Same for `city` — there is no city column on the Party row; address lives in `party_address`. Mapped both to safe defaults at the boundary; PartyDetail's khata KPIs read from the click-dummy invoice fixtures (zero in live mode for a fresh org), with a code comment pointing to TASK-CUT-302 (`/reports/party-statement`) which is the right place to compute these from real data. No correctness loss — just the per-row "Outstanding" column shows ₹0 for live rows. Acceptable for the wave gate.

### 3. Test files initially landed in the wrong worktree
First Edit/Write calls created the test files at `/Users/moizp/fabric/...` instead of the agent's worktree at `/Users/moizp/fabric/.claude/worktrees/agent-a30514fc51e1dfe8b/...` (the working-directory was the worktree but I'd been using absolute paths starting with `/Users/moizp/fabric/`). Caught when `pnpm test` reported "No test files found." Moved files into the worktree; no actual content lost. **Lesson for next agent: when in a worktree, sanity-check the first file Write/Edit by listing the target dir before assuming the absolute path resolved correctly.**

## Things the plan got right (no deviation)

- Vertical-slice TDD worked cleanly: one failing integration test (RED) → minimum impl (GREEN) → next slice. 17 tests written, no horizontal "all tests then all code" regression.
- `vi.mock('@/lib/api/mode')` pattern from `Onboarding.test.tsx` is reusable verbatim. Worked first try.
- `lib/api/parties.ts` (thin wrappers) + `lib/queries/parties.ts` (composes + mock branch) split mirrors `invoices.ts` and is the right grain.
- `Dialog` component supported the New / Edit forms without changes; `Field` + `Input` components are reusable for production-grade form ergonomics with no extra deps.
- Q6 IS_LIVE branching in queryFn keeps both code paths tree-shakeable at build time without runtime overhead.

## Pre-TASK-CUT-102 (Items + SKUs FE) checklist

### 1. Items live wiring repeats this exact pattern
The CUT-102 agent should `cp` the structure of `lib/api/parties.ts` + `lib/queries/parties.ts` for items: thin BE wrappers + mock-branched query hooks + `_internal` exports for unit tests. The role/kind shim is parties-specific; CUT-102 has its own (item_type → FE `type`).

### 2. After CUT-102 lands, verify the InvoiceCreate end-to-end manually
With both parties + items live, the Wave 2 demo step "build a 2-qty × ₹500 invoice" should succeed against a fresh-signup live tenant. If it 422s, suspect either `firm_id` (signup gives org-wide JWT; auto-switch helper in `identity.ts:maybeAutoSwitchSingleFirm` should kick in) or `place_of_supply_state` (we send the FE party `state_code` as `ship_to_state`).

### 3. Heads-up for CUT-104 (P1 fix bundle)
CUT-104 is in flight in a sibling worktree and adds `voucher.party_id`. Has zero overlap with this PR. No coordination needed.

### 4. CUT-106 (OpenAPI codegen) supersedes the hand-written `BackendParty*` interfaces
Once CUT-106 lands, the `BackendParty`, `BackendPartyCreateBody`, `BackendPartyPatchBody` interfaces in `lib/api/parties.ts` should be replaced by `components['schemas']['PartyResponse']` etc. Trivial PR; no behavior change.

## Open flags carried over

- **Per-row outstanding column on live `/parties` list.** Currently always ₹0. Resurfaces in TASK-CUT-302 (`/reports/party-statement` BE) and / or a future `outstanding_amount` field added to the `PartyResponse` schema. Defer until a user complains; CSV / GSTR-1 reports don't need it on the list view.
- **City field on Party.** Backend has no city column; address is in `party_address`. Click-dummy's "City · GSTIN" cell now shows just "GSTIN" for live rows. Either add a city projection to the list endpoint or drop the column from the table — TBD when a real user calls it out.
- **Tax-status detail in form.** `NewPartyDialog` infers `REGULAR` if GSTIN is present, else `UNREGISTERED`. Composition / Consumer / Overseas need an "Advanced" disclosure. Not a Wave 2 blocker.

## Observable state at end of task

- Worktree at `/Users/moizp/fabric/.claude/worktrees/agent-a30514fc51e1dfe8b`, branch `task/CUT-101-parties-fe-live` off `origin/main`.
- 7 files touched: 3 modified, 4 new (incl. tests + retro). Diff is `~400 LOC` net-add with the bulk in the `NewPartyDialog` form scaffolding.
- Backend untouched. No Alembic migration. No OpenAPI delta — endpoints already existed.
- Frontend vitest: 32 files / 128 tests / 0 failed. Lint + tsc clean.
