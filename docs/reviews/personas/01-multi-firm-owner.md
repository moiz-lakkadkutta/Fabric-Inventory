# Persona Review 01 — The Multi-Firm Managing Owner

**Reviewer:** Claude Code (product analyst) · **Date:** 2026-06-20
**Build:** live backend `http://localhost:8000` (Demo Co / demo@example.com), read-only DB `fabric-postgres-1`, code @ `main`
**Companion doc:** `docs/reviews/product-review-2026-06-20.md` (23 findings). This review does **not** repeat those; it references them by number where they intersect the multi-firm story (esp. #18, #21, #22).

---

## Persona & jobs-to-be-done

Moiz-style owner runs **2–4 legal entities under one company group**: e.g. a GST trading firm + a non-GST cash firm, or a trading firm + a manufacturing firm. They share the **same customers, suppliers, karigars, item catalogue and staff**, but each firm has its **own GSTIN, own invoice number series, own books (P&L/TB), own bank accounts**. Their daily jobs: (1) bill from whichever firm the deal sits in, (2) **not** re-key the same customer/item into every firm, (3) move stock/money between their own firms, (4) at month/year end see **both per-firm books and a consolidated group picture** (group receivables, group stock, group P&L).

---

## Multi-firm capability today (evidence)

The architecture is **genuinely multi-firm-aware** — this is a real strength, not a bolt-on:

- **Data model supports N firms per org.** `firm` is a first-class table FK'd to `organization` (`backend/app/models/identity.py:111-158`), with **per-firm** legal identity: `gstin`, `gst_registration_type`, `has_gst`, `state_code`, `pan`, `cin`, `fy_start_month`, `invoicing_mode` (`identity.py:124-150`). So a GST firm + a non-GST firm (`has_gst=false`) coexist cleanly — exactly the headline use case.
- **Masters are org-shared by default, not firm-siloed.** `party.firm_id` and `item.firm_id` are **nullable** (`masters.py:143-147`, `:330-332`); `list_parties` returns rows where `firm_id == active firm OR firm_id IS NULL` (`masters_service.py:206-209`). DB confirms the shared model is what's actually used: **147 of 148 parties and 223 of 227 items have `firm_id = NULL`** (org-shared). → A customer entered once is visible to every firm. This is the right call and removes the biggest multi-firm pain (re-keying masters per firm).
- **Per-user firm access list exists.** `user_firm_scope` table (`identity.py:356-387`) maps users→firms with an `is_primary` flag.
- **Firm switching works end-to-end.** Login returns `available_firms` (`auth.py:353`); `/auth/switch-firm` re-issues a JWT with the new `firm_id`, but **only after** verifying the firm is in the user's org (404 if not) **and** the user has ≥1 permission there (403 if not) (`auth.py:630-705`). Frontend `FirmSwitcher.tsx` drives it with optimistic UI + `/me` refetch. **Verified live:** Demo Co `/auth/me` → `available_firms` = 1 firm (`DEMOFIRM`), JWT carries `firm_id`.
- **Per-firm number series.** Voucher / MO / job-work / SO / DC / invoice numbering is keyed `UNIQUE (org_id, firm_id, series, number)` (`accounting.py:113-115`, `manufacturing.py:471-473`, `jobwork.py:91-93`, `sales_service._allocate_*`). Each firm gets independent document numbering. 
- **Per-firm feature flags.** Flags resolve by firm: `resolve_flags_for_firm(firm_id=...)` (`auth.py:730-733`), cache invalidated on switch (`auth.py:697`). So `gst.einvoice.enabled` can be ON for the GST firm and OFF for the cash firm. 
- **Per-firm books.** Reports (`reports_service.compute_pnl/tb/daybook/stock_summary`) and dashboard KPIs all take an explicit `firm_id` and filter `Voucher.firm_id == firm_id` (`reports_service.py:157-158, 326-327, 443-444`); system ledgers shared via `firm_id IS NULL` (`reports_service.py:350-352`). Books are correctly isolated per firm.
- **The schema even anticipates inter-firm transactions:** `inter_firm_relationship` table with `relationship_type ∈ {TAX_INVOICE, BRANCH_TRANSFER, STOCK_JOURNAL}` and a `default_pricing_policy ∈ {LANDED_COST, COST_PLUS_MARKUP, CUSTOM, STANDARD_COST}` + `transfer_price_markup_pct` (`schema/ddl.sql:1736-1749, 2403-2413`).

**Net:** the *foundations* a multi-firm owner needs are mostly already in the schema and auth layer. The gaps are at the **operations/UI/consolidation** layer.

---

## Gaps & missing capabilities (ranked — what blocks a real multi-firm owner)

1. **[BLOCKER] You cannot create a second firm through the product.** Only **signup** creates a firm (one firm, `auth.py:195`). `/firms` is in the API spec (`specs/api-phase1.yaml:1631, 1710`) but **not implemented — `GET /firms` → 404 (verified live)**, and there is no firm router (no firm CRUD in any `backend/app/routers/*.py`). The `admin.firm.manage` permission exists and the FirmSwitcher shows an **"Add a firm" button that is a dead placeholder** (no handler; `FirmSwitcher.tsx:221-227`). DB confirms reality: of 228 orgs, **only 2 have 2 firms; 226 have exactly 1.** → The headline persona literally cannot set up their second firm without a DB insert. This is the #1 thing to build.

2. **[BLOCKER] No consolidated / group reporting.** Every report and the dashboard **hard-require a single active firm** and refuse org-wide views: `_require_active_firm` raises if `firm_id is None` (`reports.py:72-83`, `dashboard.py:30-40`). There is no group P&L, group TB, group receivables, or group stock — the owner must switch firm-by-firm and add it up in their head/Excel. For someone whose whole reason to use one system is *seeing the group*, this is a core miss.

3. **[HIGH] No inter-firm operations.** The `inter_firm_relationship` table is **schema-only**: no model, no service, no router, no API (grep across `backend/app/{models,service,routers,schemas}` → zero hits). So **inter-firm stock transfer, branch transfer, inter-firm sale/purchase, and moving a party balance between firms do not exist.** In textile groups this is daily (trading firm buys, manufacturing firm consumes; stock shuttles between entities). Today the only workaround is booking a normal sale + purchase by hand in each firm, with no linkage and double master upkeep on stock.

4. **[MEDIUM — authorization gap] `firm_id` in the request body is trusted on sales & procurement writes.** Manufacturing routers correctly reject a token/body firm mismatch (`if current_user.firm_id is not None and body.firm_id != current_user.firm_id: raise` — `manufacturing.py:799, 1074, 1326, 1431`). **Sales and procurement do NOT** — they pass `firm_id=body.firm_id` straight through (`sales.py:107, 277, 618`; `procurement.py:124, 329, 507`), and the only downstream check is `_ensure_firm_in_org`, which validates the firm is in the **org**, not that it is the user's **active/permitted** firm (`sales_service.py:104-109`). `user_firm_scope` is **never consulted on any write path** (referenced only in `auth.py`). → In a multi-firm org, a user scoped to Firm A can post a sales order / PO / purchase invoice **into Firm B** by putting B's `firm_id` in the body. Org RLS still contains it (no cross-tenant leak — see product-review S1), and most orgs have one firm so it's latent today, but it is a genuine intra-org cross-firm authorization hole that grows the moment firm #2 exists. Fix: apply the manufacturing-style `body.firm_id == current_user.firm_id` guard (or a `user_firm_scope` check) uniformly.

5. **[MEDIUM] Shared-master uniqueness will collide across firms.** Number series are per-firm, but **party/item `code` uniqueness is `(org_id, firm_id, code)`** (`masters.py:132, 319`). With the shared (`firm_id NULL`) pattern that's fine, but if an owner ever creates a firm-scoped party in Firm A and a shared party with the same code, or wants the *same* customer code reused per firm, the constraint model is ambiguous and there's no UI to even choose "shared vs this-firm-only." No screen exposes `party.firm_id` at all — the owner can't tell or control whether a master is shared or firm-private.

6. **[LOW] Per-firm config has no management UI.** `firm.gstin / has_gst / fy_start_month / invoicing_mode / bank / godown` exist on the model but there is no firm-settings screen (no firm router). Per-firm GSTIN, per-firm series prefixes, per-firm feature flags can't be edited by the owner.

7. **[LOW] Cosmetic FY/firm context leaks.** `FirmSwitcher.tsx:11` hardcodes `FY_LABEL = 'FY 2025-26'` for **all** firms regardless of each firm's `fy_start_month`; ties into product-review #20 (FY label off-by-one).

---

## Edge cases tested (probe → result)

- **Can the owner add a firm in-app?** `GET /firms` with Demo owner token → **HTTP 404 Not Found** (endpoint unimplemented). FirmSwitcher "Add a firm" has no click handler. → **No.**
- **`available_firms` / switcher contents** (live `/auth/me`): exactly one firm `{code: DEMOFIRM, name: Demo Firm}`; JWT `firm_id` populated. Switcher renders it; nothing to switch to in the demo org.
- **Cross-org firm switch** (code-verified): `/auth/switch-firm` to a firm in another org → 404, not 403 — same no-leak posture as RLS (`auth.py:651-660`). Good.
- **Firm-id spoof on a write** (live, intentionally-invalid payload, rejected): `POST /sales-orders` with a foreign `firm_id` → 422 on **schema** fields (`so_date`, `series`, `lines` required) — i.e. firm_id is **not** rejected at the router; it is only checked later by `_ensure_firm_in_org` against **org** membership, never against the caller's JWT firm or `user_firm_scope`. Confirms gap #4 by code path. (No record created.)
- **RLS level** (schema-wide): all **99** RLS policies key on `org_id = current_setting('app.current_org_id')` (`ddl.sql:117…`); **no policy references `app.current_firm_id`** and the session var is never set (`dependencies.py:38, 64` set only `app.current_org_id`). → **Tenant isolation is org-level; firm isolation is entirely application-layer** (and, per #4, unevenly enforced).
- **Consolidated report** (code-verified): no endpoint accepts "all firms" / org-level; `_require_active_firm` blocks firm-less sessions (`reports.py:72`, `dashboard.py:30`). → **No group view exists.**

---

## Customizations required (textile-multi-firm specific)

1. **Firm management module** — `POST/PATCH /firms` + an admin "Firms" screen (name, legal name, GSTIN, has_gst, state, FY start, series prefixes, default godown/bank), gated by the already-defined `admin.firm.manage`. Wire the dead "Add a firm" button.
2. **Inter-firm stock transfer** — implement on the existing `inter_firm_relationship` + a transfer document: pick `BRANCH_TRANSFER` vs `TAX_INVOICE` (intra-state branch transfer needs no tax; cross-state/GST firm needs an IGST tax invoice), price by `LANDED_COST`/`COST_PLUS_MARKUP`. This is the textile group's bread-and-butter (trading↔manufacturing).
3. **Group consolidation toggle** on P&L / TB / Receivables / Stock — "This firm ▾ / All firms" selector that sums across `available_firms` (Owner-only), with per-firm columns + group total. Pairs naturally with fixing party-khata #22 (a *group* khata is what the owner actually wants: one customer's total exposure across all their firms).
4. **Shared-vs-firm-scoped master control** — surface `party.firm_id`/`item.firm_id` in the master forms ("Shared across all firms" vs "Only <Firm>"), default Shared.
5. **Uniform firm-authorization guard** on sales/procurement writes (close gap #4), ideally a single dependency that asserts `body.firm_id ∈ user_firm_scope(current_user)`.

---

## Top UX boosts (ranked)

1. **Firm CRUD + "Add a firm" wired up** — *why:* without it the headline persona can't even onboard their second entity; everything else is moot. *Effort: M* (model+router+schema+screen; permission already exists).
2. **Group consolidation view (P&L / TB / receivables / stock, per-firm columns + total)** — *why:* the single biggest reason a multi-firm owner adopts one system over separate Tally companies; today they still need Excel. *Effort: M* (loop existing per-firm report fns over `available_firms`, sum; Owner-gate).
3. **Inter-firm stock transfer document** — *why:* daily textile-group operation; schema already there, zero app surface. *Effort: L* (new doc + dual GST/branch posting + valuation handoff).
4. **Group party khata** (one customer's outstanding across all the owner's firms, drill-down per firm) — *why:* textile trade lives on khata; an owner thinks "how much does Lakshmi owe me *in total*," not per firm. *Effort: M* (depends on fixing review #22 first).
5. **Uniform body-`firm_id` authorization guard on sales/procurement** — *why:* closes a real intra-org cross-firm write hole before firm #2 exists and it becomes exploitable; cheap and high-trust. *Effort: S* (copy the manufacturing-router check).
6. **Per-firm settings screen** (GSTIN, has_gst, FY start, series prefix, feature flags) so each firm's identity is editable in-app — *why:* a GST firm + cash firm need different config and there's nowhere to set it. *Effort: M*.
7. **Firm context made obvious everywhere** — colour-tag/header chip per firm, real per-firm FY label (drop the hardcoded `FY 2025-26`), and a firm badge on every document/list so the owner never bills from the wrong entity. *Why:* mis-firm billing is a costly, hard-to-reverse error. *Effort: S*.
