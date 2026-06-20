# Persona 05 — Warehouse / Store Staff + Salesperson (Sales Floor)

**Reviewer:** Claude Code (product analyst) · **Date:** 2026-06-20
**Method:** Frontend source read (`frontend/src/`), backend code + live API probes (`localhost:8000`), read-only DB (`fabric-postgres-1`), screenshots `docs/reviews/screens-2026-06-20/`.
**Baseline:** the full product review `docs/reviews/product-review-2026-06-20.md` (findings referenced as **#N**, security as **S7**). This file does not repeat those; it reframes for the daily operational user and adds new evidence.

---

## 1. Persona & jobs-to-be-done

Two overlapping all-day operational users who live in the system, not in the books:

- **Salesperson / counter biller** — bill a walk-in or phone order *fast*: pick customer, scan/find items, set qty + rate, print/finalize. Throughput and "did it save?" feedback matter most. Repeats this dozens of times a day.
- **Warehouse / store staff** — receive goods against POs (GRN), count and adjust stock, dispatch via delivery challan, hand parts to karigars. Needs the truth of what is physically on the shelf, right now.

JTBD ranked by frequency: (1) bill a sale, (2) look up "do we have this / how much", (3) receive a PO, (4) dispatch/challan, (5) adjust/correct stock after a physical count, (6) hand work to a job-worker. They are not accountants — they should never need (and per role design, cannot reach) the GL, P&L, or trial balance.

---

## 2. What works well today (evidence)

- **Backend role gating is real and enforced.** `WAREHOUSE` and `SALESPERSON` are first-class seeded roles with hardcoded permission sets (`backend/app/service/rbac_service.py:322-393`), seeded per-org into `role`/`permission`/`role_permission`, snapshotted into the JWT at login (`identity_service.py:206-212`), and checked on **every** data endpoint via `require_permission()` (`dependencies.py:108-133`). DB confirms 5 system roles. This closes the open flag **S7** ("role gating untested") — it works at the API layer. (Detail in §5.)
- **Stock data model is genuinely strong.** `stock_position` carries `on_hand_qty`, `reserved_qty_mo`, `reserved_qty_so`, `in_transit_qty`, and a **generated** `atp_qty = on_hand - reserved_mo - reserved_so - in_transit` (`backend/schema/ddl.sql`), with a `CHECK (on_hand_qty >= 0)`. Mutations are real-time and concurrency-safe: `add_stock`/`remove_stock` write the `stock_ledger` row and the `stock_position` under `SELECT … FOR UPDATE` in one transaction (`inventory_service.py:226-419`).
- **GRN inbound is solid.** Received qty defaults to ordered qty for fast full receipts (`GrnCreate.tsx:46-59`); **partial receipt** is supported per-line with lot capture (`GrnCreate.tsx:217-251`), and `_recompute_po_status` rolls the PO to `PARTIAL_GRN`/`FULLY_RECEIVED` (`procurement_service.py:386-415`). Stock posts atomically at the `receive` action, with weighted-average cost blending.
- **SO-linked partial dispatch is the best flow in the app.** `DeliveryChallanCreate.tsx` deep-links from an SO (`?so_id=`), pre-fills each line with **remaining** qty `max(qty_ordered - qty_dispatched, 0)` (lines 108-119), locks the customer, and supports editing qty for partial dispatch. DC issue blocks negative stock atomically (`inventory_service.py:391-396`).
- **Stock adjustment with reason + approval trail.** `AdjustStockDialog.tsx` offers INCREASE/DECREASE/COUNT_RESET, a reason field, date, auto-selects the only location, and inline-creates a first warehouse when none exist. Backend stores `reason`, `requires_approval`, `approved_by/at` (`stock_service.py`).
- **Duplicate invoice numbers are impossible.** `UNIQUE(org,firm,series,number)` + gapless `max+1` allocation under a firm row lock (`sales_service.py:739-764`). Same for SO/DC. Concurrent-safe.
- **Low-stock badge in the inventory list.** `InventoryList.tsx:143-179` shows a "Low stock" pill and reddens the reorder column when `on_hand < reorder` — *in the UI*. (Caveat: the backend has no reorder field — see §3/§4.)
- **A real ⌘K command palette exists** (`hooks/useCommandPalette.tsx:17-26`, `components/layout/CommandPalette.tsx`), keyboard-navigable (↑↓/Enter/Esc), searching pages/parties/items/invoices.

---

## 3. Operational frictions & gaps (ranked, with interaction cost)

**F1 — The billing screen is not built for counter speed (P2, the headline gap).**
`pages/sales/InvoiceCreate.tsx`. The item picker is a plain native `<select>` listing **every** item with no search, typeahead, or barcode (lines 284-288). Rate starts at `0` and must be typed manually every line — **no last-price / price-list memory** (confirmed by code comment lines 76-79). **Zero keyboard shortcuts** in the form (no Enter-to-add-line, no Enter-to-finalize; grep found no key handlers in `pages/sales`). Best case single-line sale ≈ **3 interactions** (customer + first item auto-default, so type qty, type rate, click Finalize — and Finalize does draft+finalize in one handler, good). But each *additional* line is **open dropdown → scroll/scan full catalog → qty → rate ≈ 4-5 clicks**, and with hundreds of textile SKUs the no-search dropdown is unusable. The `barcode_ean13` field exists on the Item model (`lib/api/items.ts:71`) but is surfaced nowhere. A leftover hardcoded date `today = '2026-04-30'` (lines 100-101) ignores reality.

**F2 — Invoice finalize ignores stock entirely (P2, correctness).**
`finalize_invoice` (`sales_service.py:938-992`) only flips state and posts the GL voucher — **no stock decrement, no availability check**. You can bill and finalize an out-of-stock item with nothing stopping you. Stock is only touched when a **Delivery Challan is issued**. If the shop bills without always cutting a DC (common at a counter), inventory silently oversells and the stock ledger never reflects the sale. Also `item.allow_negative` (default `'NEVER'`) is **not read** by `remove_stock` — depletion is hard-blocked unconditionally, so the flag is dead. This is the single most trial-relevant correctness gap for this persona.

**F3 — No reorder / low-stock concept in the backend (P2).**
The `item` table has **no** `reorder_level`/`min_stock`/`safety_stock` column; grep across `backend/app` = zero matches; `stock-summary` has no threshold field. The UI low-stock badge (F-good above) compares against a `reorder` value the API never supplies — so it can't actually fire. Warehouse staff have **no "what to reorder" view**.

**F4 — Reserved vs Available (ATP) is invisible to floor staff (P2).**
The model computes `atp_qty`, but `GET /reports/stock-summary` returns only `on_hand_qty`, `avg_cost`, `valuation` — no `reserved`/`available`/`atp`. So a salesperson promising stock and a warehouse picker both see only gross on-hand, never "free to sell." The reservation machinery (`reserve_for_so`) is built but unused by current flows (all reserved qtys are 0 in demo data).

**F5 — No DC → Invoice action in the UI (P2).**
Code comments promise DC pricing "carries through to the invoice issued against this DC" (`DeliveryChallanCreate.tsx:465`), but **no "Bill this DC" / "Generate invoice" button exists** anywhere (grep `convert|invoice.?from|from.?dc` = nothing). Dispatch-then-bill, the natural warehouse→counter handoff, is broken in the frontend — the biller must re-key the whole sale.

**F6 — GRN grid shows truncated UUIDs instead of item names (P2).**
`GrnCreate.tsx:206-213` renders `line.item_id.slice(0,8)+'…'` for the Item column. Receiving staff literally cannot tell what they are counting. (Same FK-display disease as **#15/#17** but on a daily-use data-entry grid — worse.) `GrnDetail` also shows no per-line remaining/outstanding rollup, so you can't see how much of the PO is still open.

**F7 — No success feedback; no toast system at all (P2 UX).**
There is no toast/sonner component anywhere (grep = none). A successful bill/GRN/DC/adjust just `navigate()`s away with no "Saved ✓". On a noisy counter this gives the biller no confirmation the sale posted — they will re-submit or double-check, costing time and risking duplicates. The notifications popover is a static mock (`NotificationsPopover.tsx:16`).

**F8 — Tablet/counter ergonomics are thin (P2).**
Responsiveness is desktop-first column-reflow only (27/70 pages use any `md:`/`lg:`, mostly `md:grid-cols-*`). Billing/GRN/dispatch grids are wide tables in `overflow-x-auto` with hardcoded `minWidth` 640-880px — they **horizontally scroll** on a tablet, not reflow. Remove/trash buttons are 32px (`InvoiceCreate.tsx:346`), below the ~44px touch target. There is no counter/POS layout.

**F9 — ⌘K palette is mock-backed and navigation-only (P3).**
It imports static `lib/mock/*` (`CommandPalette.tsx:18-20`), so it does **not** reflect live records, and item entries mis-route to `/inventory` (line 181). Selecting only navigates — it cannot add an item to a bill or run an action. Strong shell, not wired to be the fast-find tool the floor needs.

**F10 — E-way bill: pure stub, no 50k trigger (P3, deferred per plan).**
`eway_bill` table + `sales_invoice.eway_bill_id/eway_status` columns exist but unused (0 rows); no ₹50,000 threshold logic anywhere (grep). Consistent with CLAUDE.md's feature-flag plan, but today there is **zero** warning when an invoice crosses the threshold — staff get no prompt.

**F11 — No total-row count on list endpoints (P3).**
List envelope `{items, limit, offset, count}` where `count` = current page size, not total rows. Clients can't show "page X of N" for long item/party lists without walking pages. `/items` default limit 50, capped at 200 (`?limit=300` → 422).

**F12 — Stock valuation reads ₹0 everywhere (P2, ties to #18/#21).**
Opening stock was seeded via adjustments with no cost, so `avg_cost`/`valuation` are 0.00 in `stock-summary`. Not floor-staff-facing directly, but any "stock value on hand" they glance at is wrong.

---

## 4. Permission / role reality (does gating actually work?)

**Backend: YES — genuinely enforced.** (Full evidence above; closes **S7**.)
- Every data endpoint carries `require_permission("resource.action")` (`dependencies.py:108-133`); I audited all routers — no ungated data endpoint (only `auth.py` is public). Counts e.g. sales=17, inventory=8, reports=9, manufacturing=51 endpoints, all gated.
- **SALESPERSON** (`rbac_service.py:322-360`) gets sales create/finalize/read, party + item read, stock + lot read, dashboard — but **NOT** `accounting.report.view`, no vouchers, no cost-centres, no purchase. So **P&L, Trial Balance, Daybook, and the stock-valuation report are blocked** (all gated on `accounting.report.view`, `reports.py:93/173/240/306/362`). Verified by 403.
- **WAREHOUSE** (`rbac_service.py:363-393`) gets item/party read, PO read, GRN create/read/approve, stock read, adjustment + transfer create, DC create/read/approve, jobwork, karigar dispatch/receive — but **no** `accounting.*` and **no** `sales.invoice.*`. So a pure warehouse user cannot bill, and an accountant/reports surface is closed to them.

**One design nuance to flag to Moiz:** per-unit **cost is visible to Salesperson** — `LotResponse.primary_cost` is returned under `inventory.lot.read` (held by Salesperson, `rbac_service.py:340`, with an explicit "see which lot is going out" comment) and `item.default_cost` under `masters.item.read`. They cannot see *margin/P&L*, but they **can** see purchase cost per lot/item. Deliberate and documented, not a leak — but decide whether counter staff should see what you paid.

**Frontend: NOT gated (cosmetic leak).** The sidebar renders all links for everyone (`Sidebar.tsx` — no permission filter); `RequireAuth.tsx` checks only auth, not permission. A Salesperson sees Accounting/Reports/P&L in the nav, clicks, the API 403s, and `ui/query-error.tsx:128-135` shows a "You don't have permission" lock card. Data is safe; the UX advertises features they can't use and wastes clicks. **Minor bug:** `MoCreateWizard.tsx:351` checks `manufacturing.mo.create` but the catalog only defines `manufacturing.mo.write` (`rbac_service.py:174`) — that FE gate is always false for real users.

---

## 5. Edge cases tested (probe → result)

| Probe | Result |
|---|---|
| Finalize invoice for out-of-stock item | **No block.** `finalize_invoice` never checks/decrements stock (`sales_service.py:938-992`). Oversell possible if no DC is cut. |
| Issue DC exceeding on-hand | **Blocked atomically.** `remove_stock` raises `Insufficient stock: on_hand=… < requested=…`, whole DC rolls back (`inventory_service.py:391-396`); DB `CHECK (on_hand_qty>=0)` backstops. |
| Duplicate invoice number (concurrent) | **Prevented.** `UNIQUE(org,firm,series,number)` + `max+1` under firm `FOR UPDATE` lock (`sales_service.py:739-764`). |
| `GET /items?limit=300` | `422 VALIDATION_ERROR` — limit capped 1..200. Pagination consistent across `/invoices`, `/parties`, `/stock-adjustments`. |
| `GET /inventory` / `/stock` | `404 Not Found` — stock is only via `/reports/stock-summary` (which is report-permission-gated, so Salesperson/Warehouse can read stock via `inventory.stock.read`? — note: stock-summary is under `accounting.report.view`, so **a pure warehouse role may not reach the stock-summary report** despite holding `inventory.stock.read`. Verify routing of stock visibility to the right permission.) |
| Stock adjustment with blank reason | **Accepted** — reason is `Optional`, not required (`schemas/inventory.py`). |
| Network blip / offline during bill | No offline support today; no optimistic queue; a failed mutation surfaces an inline `role="alert"` error but **no toast/retry** — biller must redo. |

> **Verify item flagged above:** stock visibility appears tied to `accounting.report.view` (the only path is the stock-summary *report*), yet Warehouse/Salesperson hold `inventory.stock.read` not `accounting.report.view`. If true, the roles designed to read stock cannot actually load the only stock screen. Worth a direct check before trial.

---

## 6. Customizations required (counter / tablet / textile floor)

- **Searchable + barcode-able item picker** (combobox over code/name/HSN/`barcode_ean13`, debounced, keyboard-driven) to replace the native `<select>` — the #1 unlock.
- **Last-price / party-price memory** auto-fill on item select (textile rate cards vary by party).
- **Fast-bill / counter POS layout** for tablets: large touch targets (≥44px), reflowing line entry, Enter-to-add-line, Enter-to-finalize, on-screen success confirmation.
- **Stock decrement on invoice finalize** (or enforce "invoice must dispatch via DC"), respecting `item.allow_negative`.
- **DC → Invoice one-click** to honor the dispatch→bill handoff.
- **Reorder levels per item/firm** + a "to reorder" / low-stock report fed by real thresholds.
- **ATP (available-to-promise) exposed** on the stock screen and item picker (reserved vs free).
- **Item names (not UUIDs)** on the GRN entry grid; controlled adjustment reason-codes.
- **E-way bill threshold prompt** at ₹50k (warn even while the GSP call stays flag-off).

---

## 7. Top UX boosts (ranked 1-8 — this persona pays back UX most)

| # | Boost | Why high-leverage | Effort |
|---|---|---|---|
| 1 | **Searchable/scannable item picker (combobox + barcode) on invoice & DC & GRN lines** | The single biggest speed gap; native `<select>` over hundreds of SKUs is unusable at the counter. Barcode turns a 5-click line into a scan. | **M** |
| 2 | **Last-price / party rate auto-fill on item select** | Eliminates manual rate typing every line (currently starts at 0); textile rates are per-party and repetitive. | **S-M** |
| 3 | **Decrement stock on invoice finalize (respect `allow_negative`) + oversell warning** | Closes the correctness hole (F2): today you can bill goods you don't have and the ledger never knows. Trial-critical. | **M** |
| 4 | **Keyboard-first billing + success toast** (Enter add-line / Enter finalize; "Saved ✓ — INV-…" toast) | Removes mouse round-trips and the "did it save?" anxiety; cuts re-submits/duplicates. No toast system exists today. | **S-M** |
| 5 | **Reorder levels + low-stock report (back the existing UI badge with real data)** | Warehouse has zero reorder visibility; the FE badge already exists but the field doesn't — quick win, high daily value. | **M** |
| 6 | **Expose ATP (reserved vs available) on stock screen + item picker** | Model already computes `atp_qty`; just surface it so floor staff stop overselling reserved stock. | **S-M** (API+FE) |
| 7 | **DC → Invoice one-click + item names on GRN grid** | Fixes the broken dispatch→bill handoff (F5) and unreadable receiving grid (F6) — both daily warehouse pain. | **M** |
| 8 | **Role-aware sidebar + tablet-friendly layout** | Hide nav a Salesperson/Warehouse can't use (stop the 403 dead-ends) and make billing/GRN grids reflow + touch-target ≥44px for counter tablets. | **M-L** |

---

### Verification note
Probes created no real records (only rejected invalid-payload + reads). No container restart, no seed, no writes. Stock-visibility-vs-permission routing (§5 "Verify item") and the `manufacturing.mo.create` FE string mismatch should be confirmed before trial.
