# TASK-CUT-203 retro — Sales Order + Delivery Challan FE wired live

**Date:** 2026-05-10
**Branch:** task/CUT-203-so-dc-fe-live
**Wave:** 3 (Procurement + Sales lifecycle + PDF + Stock)
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 3 row W3-C

## Summary

`/sales/orders` and `/sales/delivery-challans` are now live screens
(no longer `<Placeholder>` routes). The flow is end-to-end: pick a
customer → build a Sales Order → confirm it → click "Build DC" →
adjust qty per line → Issue. Both FE + BE round-trip with idempotency
keys, paise/rupees mapping, and lifecycle pills that reflect the BE
status.

The backend was already complete (`backend/app/routers/sales.py` had
the SO + DC routers from TASK-032/033 — confirmed via grep before
starting). This task was strictly a frontend integration: hand-rolled
`lib/api/{sales-orders,delivery-challans}.ts` thin wrappers, paired
with `lib/queries/{sales-orders,delivery-challans}.ts` hook modules
and six page components.

`pnpm test` 41 files / 187 tests / 0 failed (was 160 → +27 new across
mappers + flow tests). `pnpm lint`, `pnpm prettier --check`, and
`pnpm tsc --noEmit` all clean. `cd backend && uv run ruff check .`
clean.

## Deviations from plan

### 1. Route renamed from `/sales/challans` → `/sales/delivery-challans`

The pre-CUT-203 sidebar + topbar used the short `/sales/challans` slug.
The cutover-plan task brief explicitly named the route
`/sales/delivery-challans`, which also matches the BE path
(`/delivery-challans`) and is more discoverable in URLs. Renamed both
the sidebar link (`components/layout/Sidebar.tsx`) and the topbar
breadcrumb map (`components/layout/TopBar.tsx`), and added a redirect
from the old `/sales/challans` to the new one so any stale tab keeps
working. Zero breaking change for users; the redirect is a one-liner.

### 2. Sales Orders + Delivery Challans have no click-dummy mock

The retro for CUT-101 carefully preserved the IS_LIVE-vs-mock dual
branching for parties (the click-dummy had pre-baked party fixtures).
For SO + DC there's never been a click-dummy fixture because the
routes were `<Placeholder>` from day one. The mock branch in the new
query modules therefore returns an empty list for reads and throws a
"Mock mode: live-only" error for writes. The dev-server keeps running
in mock mode because the empty list rendrs fine; if a developer hits
`+ New SO` in mock mode, the alert tells them what to do. This avoids
inventing fictitious mock SO data that would diverge from the real
schema.

### 3. Backend `DCResponse.status` is `string`, not the `DCStatus` enum

The codegen output types DC `status` as a free-form `string` (the BE
schema declared it `str` for forward-compat — see comment in
`models/sales.py`). FE code wants the enum so the status-pill switch
is exhaustive. The DC mapper casts at the boundary (one line:
`(b.status ?? 'DRAFT') as BackendDCStatus`) and drops the type
imprecision into a single place. Future tightening of the BE schema
to declare `status: DCStatus` is a one-line OpenAPI/codegen refresh
and removes the cast.

### 4. Files initially landed in the wrong worktree (CUT-101 retro called this out)

The CUT-101 retro warned: *"when in a worktree, sanity-check the first
file Write/Edit by listing the target dir before assuming the absolute
path resolved correctly."* I tripped on it anyway — the first six
Write calls used the canonical `/Users/moizp/fabric/...` path instead
of the agent's `/Users/moizp/fabric/.claude/worktrees/agent-…/`
worktree path, so the files landed in the main repo. Caught it the
moment vitest reported "No test files found" and moved them with `mv`.
No content lost; ~30 seconds of flailing. Filing this here so the next
agent doesn't repeat (the lesson hardens with each new occurrence —
maybe scaffolding tooling that auto-prefixes the worktree path?).

## Things the plan got right (no deviation)

- The BE was indeed already shipped (TASK-032 + TASK-033). The 4-hour
  estimate held: the entire task was FE wiring + tests + retro, no
  backend work needed. The cutover plan's note that the BE might not
  be there was the correct hedge but the time-box wasn't tested.
- The vertical-slice TDD pattern from CUT-101 / CUT-102 ports cleanly
  to SO/DC: thin BE wrapper → query hook with mappers → page
  components → unit tests for mappers → flow tests for pages. ~20-25
  min from RED test to GREEN per layer once the pattern was loaded.
- The `IS_LIVE` ternary at the queryFn boundary keeps both code paths
  tree-shakeable at build time. Mock mode raises a clean error for
  unsupported writes (no risk of accidentally posting to a non-existent
  fake server).
- The CUT-104 `gst_amount` mapper precedent gave us the pattern for
  the SO `total_amount` (rupees-string → paise-int with null-safe
  default) without any rework.
- CUT-106 codegen types (`@/types/api`) replaced what would have been
  ~80 lines of hand-rolled `BackendSO*` / `BackendDC*` interfaces.
  The thin BE wrapper module just aliases the codegen output.

## Pre-CUT-204 (Stock adjustments FE) checklist

### 1. The pattern is now load-and-go

CUT-204 should `cp` the structure of `lib/api/sales-orders.ts` +
`lib/queries/sales-orders.ts` for stock adjustments: thin BE wrappers
in `api/`, query module with paise mapping in `queries/`, one
component test, one mapper test. The `_internal` exports for unit
tests are a stable contract.

### 2. Wave 3 demo step 4 should now succeed

The Wave 3 demo says: *"Visit `/sales/orders`. Build an SO to ACME.
Confirm. Build a DC against it. Issue."* All three transitions are
wired. The "Build DC" deep-link from SalesOrderDetail passes
`?so_id=...` and the DeliveryChallanCreate page pre-fills lines from
the SO's open quantity. Manual verification is pending the wave-3
demo doc.

### 3. Open flag — no edit/cancel-DC affordances

DCs only support DRAFT → ISSUED. Soft-delete-DRAFT (BE supports it
via `DELETE /delivery-challans/{id}`) is not surfaced in the UI. If a
user creates a DC by mistake and never issues it, they'll see a
permanent DRAFT row in the list. Acceptable for Wave 3; surface a
follow-up if a real user asks.

### 4. SOs + DCs assume `me.firm_id` is set

Both create flows guard with `if (!me?.firm_id)` and surface a clean
"No active firm" error. CUT-107 (liveSignup auto-switch) covered the
fresh-signup case. The guard is defensive — should never trigger in
practice — but it's the right posture if the user logs in via an
older session pre-CUT-107.

## Open flags carried over

- **Mock-mode writes throw.** A dev running `VITE_API_MODE=mock` who
  clicks "Save SO" gets an alert with "Mock mode: Sales Orders are
  live-only." This is documented in the queryFn but is a friction
  point if anyone wants to demo the click-dummy with SO/DC. Adding
  in-memory fake stores (like `parties.ts` does) would close it; not
  worth the maintenance cost given Wave 5 phases the click-dummy out.
- **DC line `price` is editable in free-form mode but unconditional
  in SO-linked mode.** The SO line price flows through to the DC
  line on auto-fill. If the user wants to override, they can edit the
  rate cell. Whether that's the right policy (vs. always-read-only
  from the SO) is a product decision; flagged for Wave-3 demo
  feedback.
- **DC `total_amount` is "indicative".** The BE computes it as
  `sum(price * qty)` across lines but DCs do not post tax or affect
  the GL. The detail page sidebar copy makes this explicit ("DC posts
  stock removal only. Tax flows on the invoice issued against this
  DC.").
- **No invoice-from-DC affordance yet.** The Wave-3 demo doesn't
  require it (the user can issue an invoice manually citing the DC
  number in notes). Wiring "Bill from DC" is a Wave-3 polish or
  Wave-4 item — defer until a real user complains.

## Observable state at end of task

- Worktree at `/Users/moizp/fabric/.claude/worktrees/agent-a0dd3e0c6938716cb`,
  branch `task/CUT-203-so-dc-fe-live` off `origin/main`.
- 11 files touched: 8 new (4 in `lib/`, 6 page components, 4 tests),
  3 modified (`App.tsx`, `Sidebar.tsx`, `TopBar.tsx`).
- Backend untouched. No Alembic migration. No OpenAPI delta — the
  endpoints already existed and codegen types were already current
  on `main` (verified via grep against `frontend/src/types/api.ts`).
- Frontend vitest: 41 files / 187 tests / 0 failed (+27 new).
- `pnpm exec eslint .`, `pnpm exec prettier --check .`,
  `pnpm exec tsc --noEmit` all clean.
- Backend `uv run ruff check .` clean.
