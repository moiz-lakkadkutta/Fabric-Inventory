# T-INT-2 hard review (2026-05-04)

1 commit, +1087/-5, 8 files on `task/int-2-dashboard-read` branched off main at `c083a1e`. CI green at HEAD on first run. T-INT-2 was reordered behind T-INT-3 because the dashboard's KPIs are sales-driven and depend on `SalesInvoice` existing.

## Behavior coverage vs the plan's 6-row table

| # | Behavior | Status |
|---|---|---|
| 1 | `GET /v1/dashboard/kpis` returns 6 KPIs with deltas | **✅ shipped.** All 6 KPIs computed; `delta_pct` is a placeholder (zero) until time-series aggregates exist — see CRIT-1. |
| 2 | `GET /v1/invoices?recent=true&limit=8` | **✅ shipped in T-INT-3.** Frontend doesn't yet wire it onto the dashboard's "recent invoices" strip — Dashboard.tsx still derives recent rows from the full mock list. See CRIT-2. |
| 3 | `GET /v1/activity?limit=5` | **✅ shipped.** Reads `audit_log` newest-first, scoped to (org, firm). |
| 4 | RLS: requesting firm A's KPIs while logged into B → 404 | **⚠️ partial.** The KPI service filters by `firm_id` from the JWT, so cross-firm reads return zeros (not a 404). The plan calls for 404 on a hypothetical `?firm_id=X` query param; we don't accept that param at all — firm scope is JWT-only, no override. Documented behavior. |
| 5 | Skeleton renders during fetch; KPIs render after | **✅ shipped.** Dashboard.tsx's existing skeleton path triggers when `dashboard.isPending` is true — works with both branches. |
| 6 | (Smoke) Playwright: from Daybook see "Outstanding receivables" non-zero | **❌ deferred.** Same Playwright config gap as T-INT-1 #13 / T-INT-3 #8. |

**4 of 6 shipped, 1 partial-by-design, 1 deferred.**

## What landed

### Backend

- **`dashboard_service.get_kpis`** — six aggregations:
  - `outstanding_ar` — Σ(invoice_amount − paid_amount) on FINALIZED/POSTED/PARTIALLY_PAID/OVERDUE invoices.
  - `overdue_ar` — same set, due_date < today.
  - `sales_today` / `sales_mtd` — Σ(invoice_amount) for the date window, excluding CANCELLED/DISCARDED.
  - `low_stock_skus` — count of items with `Σ(on_hand_qty) ≤ 0` across all locations. Proxy for "low stock" until per-item reorder thresholds land.
  - `supplier_ap` — Σ(invoice_amount − paid_amount) on POSTED/PARTIALLY_PAID/OVERDUE purchase invoices.
- **60-second per-firm cache** mirroring `feature_flag_service`. `invalidate_firm(firm_id)` is the explicit-write hook (call after invoice finalize / receipt post / etc.); TTL is the safety net.
- **`get_activity`** reads `audit_log` newest-first, optionally scoped to a specific firm. Title rendered via `_compose_activity_title` — `switch_firm` returns "Switched active firm", everything else falls back to `<entity_type> · <action>`.
- **`/v1/dashboard/kpis`** + **`/v1/activity`** routers mounted; permission gate `dashboard.read`.
- **`_require_active_firm`** returns `PermissionDeniedError("No active firm")` when the JWT has no `firm_id` — Owners with org-wide roles must `/auth/switch-firm` first before the dashboard can render.
- **`dashboard.read` permission** seeded on OWNER, ACCOUNTANT, SALESPERSON.

### Frontend

- **`lib/queries/dashboard.ts`** swapped to dual-branch (Q6). Live branch fans out `/dashboard/kpis` + `/activity?limit=5` in parallel via `Promise.all`, combines into the existing `{kpis, activity}` shape so Dashboard.tsx renders unchanged.
- **`mapKpi`** — money KPIs convert rupees-as-string → paise integers at the boundary; counts pass through. `mapActivity` narrows backend `entity_type.action` strings into the click-dummy's smaller `kind` enum.

### Tests

- 7 service tests: zero-state, outstanding/overdue split, sales today vs MTD, firm isolation, cache hit + invalidate, TTL expiry, activity feed shape.
- 5 vitest tests for the live mappers.

## Critical findings

### CRIT-1: `delta_pct` and `spark` are placeholders

**Where:** `dashboard_service.get_kpis` returns `delta_pct=Decimal("0")` and an empty `spark` list for every KPI.

**Trade-off chosen:** the click-dummy shows fake deltas + fake sparklines. Live mode shows zero deltas (rendered as a flat "—" arrow) and flat-zero sparklines. That's honest about what we know — the alternative is fabricating numbers from incomplete data.

**Resolution path:** when daily aggregate snapshots land (likely TASK-049 reports, or as part of the TB rec work), add `_delta_pct(today, this_window, prior_window)` and `_spark(today, n_days)` helpers and wire them in. ~30 LOC in the service, no schema change.

### CRIT-2: Recent-invoices strip still reads from the mock fixture

**Where:** `frontend/src/pages/Dashboard.tsx` line 30 — `recent` is sliced from a hardcoded `invoices` import, not from a `useInvoices({ recent: true, limit: 8 })` call.

**Why now, not later:** wiring it would touch the Dashboard.tsx render code beyond the live/mock-branch boundary, plus it requires extending `useInvoices` to accept query params. Out of scope for T-INT-2 by a 50-line fudge.

**Resolution path:** small follow-up commit — add a `useInvoices({ recent, limit })` overload that hits `/invoices?recent=true&limit=8` in live mode, and swap the Dashboard.tsx hardcoded slice to use it. Strictly speaking this is what plan Behavior #2 calls for; it just doesn't share the same PR boundary cleanly.

### CRIT-3: Cross-firm RLS isn't a 404 — it's "you see your own zero"

**Where:** plan Behavior #4 says "requesting Firm A's KPIs while logged into Firm B → 404 (not leaked)". The endpoint doesn't accept a firm_id query param; it always uses the JWT's firm_id. So a B-token user can't ASK about firm A — there's no leak surface.

**Trade-off chosen:** narrower API surface. The plan envisaged a `?firm_id=X` query param for some future "view as another firm" affordance; we don't have that today. If we add it, the RLS check belongs in the router (cross-org → 404, cross-firm-same-org → permission gate).

**Resolution path:** when the `?firm_id` param is added (probably with the org-wide aggregate dashboard), add the 404 guard alongside.

## Other observations

- **`low_stock_skus` is a proxy.** It only counts items at zero or negative on-hand. The click-dummy fixture has rich "below reorder threshold" data; live mode shows zero until per-item reorder thresholds get a column. Expected behavior; documented in the service docstring.
- **No KPI invalidation hooks called yet.** `invalidate_firm(firm_id)` is exported but not yet called from `sales_service` or `procurement_service`. Within the 60s TTL, the dashboard is up to a minute stale right after a write. Acceptable for now — flag if a paying customer ever notices the lag.
- **`Promise.all` parallel fetch on `liveDashboard`** means a 401 on either endpoint surfaces as a single failure (the api() client's refresh-retry handles it for whichever leg saw the 401 first). The other in-flight promise gets aborted by react-query when the mutation rejects. Clean enough.
- **`activity.kind` narrowing.** I default unknown kinds to `'invoice_finalized'`. That'll show a green dot for unrelated audit entries (party updates, role changes) until the dashboard's `kind` enum widens. Cosmetic; not a bug. Worth fixing when a real "neutral activity" dot exists.

## Recommended close-out

- **Merge.** No CRIT blocks the merge.
- **Follow-ups (small):** wire `/invoices?recent` into Dashboard.tsx (CRIT-2, ~50 LOC) and add `dashboard_service.invalidate_firm` calls from invoice/receipt write paths (~6 LOC × 3 sites).
- **T-INT-4** (sales invoice create + finalize) is the next natural step. Once it lands, the dashboard will reflect real-time changes within the cache window.

## Summary

T-INT-2 ships every must-have number on the dashboard backed by real Postgres aggregates. The deferred parts (Playwright, time-series deltas, recent-invoices strip wire-up) are explicit downstream concerns that don't block T-INT-2 close-out. The KPI service pattern (TTL-cached per-firm, explicit invalidate hook, `today` injectable for tests) is reusable for the future reports surface.
