# fix-live-search retro: live search and party khata showed click-dummy data

**Date:** 2026-10-23
**Branch:** fix/live-search-and-placeholders
**Commit:** see PR (not merged; PENDING MOIZ SIGN-OFF)
**Plan:** none (investor-demo polish pass)

## Summary

Several screens still read from the click-dummy fixtures in `@/lib/mock/*` in live mode:

- The command palette searched mock parties, items and invoices. Results opened detail
  pages that returned 404.
- The khata KPIs and invoice list on Party detail were computed from the mock
  `invoices` fixture, so every real party showed ₹0 and "No transactions".
- InventoryList linked rows to mock lots by `sku_id`.

The Sales sidebar also listed three "Coming soon" `<Placeholder>` pages, and the
onboarding wizard offered a Vyapar import that did nothing.

Fixes (frontend only):

1. **Command palette.** In live mode the palette takes its party, item and invoice
   entries from the real hooks: `useParties`, `useItems` and `useInvoices`. Mock mode
   still uses the static fixtures, so the synchronous mock tests are unchanged. The hook
   is chosen by `IS_LIVE` at module level, which is safe under rules-of-hooks. The body
   only mounts while the palette is open, so the app no longer fetches the three lists
   on every page load. Live item entries now go to `/masters/items/:id` instead of
   `/inventory`. The party subtitle drops empty parts, because live parties have no
   city.
2. **Party detail.** Added a new `usePartyInvoices(partyId)` hook. In live mode it calls
   `GET /invoices?party_id=…&limit=200`, using the server-side filter so the firm-wide
   200-row cap can't drop a party's invoices. In mock mode it filters the mock store.
   - Total billed, Received and Overdue are sums over integer paise. Draft, discarded
     and cancelled invoices are excluded.
   - Outstanding uses the closing balance from `usePartyStatement` when the user has
     `accounting.report.view`. Without that permission it falls back to billed minus
     received.
   - The table drops DISCARDED invoices, labels drafts, and shows loading and error
     states.
3. **Sidebar and onboarding.** Removed Quotes, Returns and Credit control from the Sales
   sub-nav. Their routes and TopBar crumbs stay, so deep links still work. Removed the
   Vyapar option from the onboarding opening-balance step. `importMode` was never sent
   to `/auth/signup`, so the option did nothing.
4. **InventoryList.** In live mode `sampleLot` is now always `undefined`. Stock-summary
   rows carry no lot id, and fetching lots per row would be N+1 requests.

**Verification:**
- vitest: 106 files, 612 tests passed. The baseline on `origin/main` was 603, not the
  607 in the brief. This PR adds 9 tests: 4 for the live palette, 3 for the live party
  khata, 1 for the sidebar and 1 for live InventoryList. The Onboarding Vyapar test was
  rewritten, so the count there is unchanged.
- `tsc --noEmit`, eslint and prettier on the changed files are clean.

## Deviations from plan

### 1. Outstanding comes from the party statement; the other three KPIs come from invoices
The brief preferred the party-statement endpoint. That endpoint needs
`accounting.report.view`, which a party viewer may not have. Its totals also cover the
fiscal year to date and include credit notes, which doesn't fit "Total billed" or
"Received". So only Outstanding uses the GL closing balance, which also covers Vyapar
opening balances. The other three KPIs come from invoices.
- **Impact:** for a party with an opening balance, Outstanding ≠ Billed − Received. This
  is correct for a khata, but a viewer may ask about it. A "Ledger balance" caption
  under the figure is a possible follow-up.

### 2. KPIs now exclude drafts
Draft, confirmed, discarded and cancelled invoices no longer count toward "Total billed".
The old code counted every status. This only changes how totals are displayed, not
tax or GL logic. Moiz should still confirm it.

## Things the plan got right (no deviation)

- Every live data source the fix needed already existed: list hooks, the `party_id`
  filter on `/invoices`, and `usePartyStatement`. No backend change was needed.

## Pre-next-task checklist

### 1. Demo data check
Open a seeded party on the demo box and confirm its Outstanding matches the Reports →
Party statement closing balance.

## Open flags carried over

- The "Khata · invoices & receipts" table still lists only invoices. Receipts and
  vouchers come from the party statement, which is not yet rendered here.
- The palette's live lists are capped at `limit=200`. A larger firm needs a server-side
  `q=` search, which `/invoices` already supports.
- Live InventoryList rows have no drill-down. They need a lot id or item link in the
  stock-summary response.
- The Placeholder routes for TASK-038 and TASK-055 remain reachable by URL.

## Observable state at end of task

- No databases or containers were created. The work was done in an isolated agent
  worktree, not `~/fabric-worktrees/fix-live-search`, because the sandbox blocked that
  path.
