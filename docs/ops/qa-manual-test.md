# Fabric ERP — manual QA test guide

**Audience**: anyone with the repo running locally (Moiz, future contractor, friendly customer's IT person).
**Scope**: everything that's wired live as of TASK-INT-12 (post-stabilization sweep). Cosmetic / mock-only flows are flagged so you don't waste time on them.
**Estimated time**: ~3–4 hours for a full pass; ~45 min for the smoke subset (sections 0–4 + 7).

**Recent rewrites** (this guide was updated alongside the INT-7…INT-12 stabilization sweep):
- API paths are unversioned (`/invoices`, `/receipts`, `/dashboard/kpis`) — no `/v1/` prefix.
- Error envelope is canonical for ALL responses incl. validation 422s (INT-8).
- Per-org email model: same email + different org name is intentional (INT-10).
- Inter-state always IGST regardless of value; the ₹2.5L threshold is a `gstr1_section` flag (INT-11).
- Dashboard KPIs: 5 cards (drop `low_stock_skus`, `supplier_ap`; add `gst_collected_mtd`) (INT-12).
- DB role split: runtime now connects as `fabric_app` (NOBYPASSRLS); RLS is enforced for real (INT-9).

Each test has a result box: `[ ] PASS`, `[ ] FAIL` (file follow-up), or `[ ] SKIP` (with reason). When something fails, screenshot the network panel + the `request_id` from the response body — every API error envelope carries one for tracing.

---

## 0 · Pre-flight

Before running any test, all five must be green.

- [ ] **0.1** `docker compose ps` shows `postgres` and `redis` as `(healthy)`.
- [ ] **0.2** `curl -s localhost:8000/live` returns `{"status":"live"}`.
- [ ] **0.3** `curl -s localhost:8000/ready` returns `{"db":true,"redis":true,"status":"ready"}`.
- [ ] **0.4** `curl -s localhost:5173` returns Vite HTML (i.e. the frontend dev server is up).
- [ ] **0.5** `frontend/.env` contains `VITE_API_MODE=live`. Without it, every test below silently hits mock fixtures and looks like it passes.

If 0.5 was wrong, fix it and **restart** `pnpm dev` (Vite reads `.env` at boot, not on hot-reload).

---

## 1 · Auth — signup + login + token lifecycle

### 1A · Signup (new org)

- [ ] **1.1** Visit `http://localhost:5173/signup` (or `/login` → "Create org" link). Fill: unique email, password ≥ 8 chars, org name, firm name, state code `MH`. Submit.
- [ ] **1.2** Browser lands on `/dashboard`. No console errors.
- [ ] **1.3** Network panel shows `/auth/signup` → 201 → `/auth/me` (firm_id null) → `/auth/switch-firm` → second `/auth/me` (firm_id populated). This is the auto-switch from CRIT-2.
- [ ] **1.4** Top-bar shows the firm name. `/auth/me` response carries `permissions`, `flags`, `available_firms` (1 entry).
- [ ] **1.5** Postgres check (psql): `SELECT name FROM organization;` shows the new org. `SELECT email FROM "user";` shows your email.

### 1B · Signup — duplicate email (per-org email model)

The multi-tenancy model is **per-org email scoping**: same email under
DIFFERENT orgs is intentional and allowed (user can be member of org A
personally and org B at work with the same address).

- [ ] **1.6** Open an incognito window; try to sign up with the same email + same org name. Expect 409 with envelope `{code:"USER_EMAIL_TAKEN", title:"Email already registered", detail:"…", status:409}`. UI shows a friendly inline error, not a generic toast.
- [ ] **1.6b** Try to sign up with the same email + a NEW org name. Expect 201 (intentional — per-org scoping). The new org has its own user row with the same email.

### 1C · Login

- [ ] **1.7** Logout from the original window (header menu → Logout). Lands on `/login`. Network: `/auth/logout` 200, then `/auth/me` 401 if it fires.
- [ ] **1.8** Log in with the same credentials → `/dashboard` again. Same firm context.
- [ ] **1.9** Wrong password → `/auth/login` returns 401 with envelope `INVALID_CREDENTIALS`. Form shows inline error, no redirect.
- [ ] **1.10** Wrong org name (same email + password) → 401 (auth scoped per org). Same behavior.

### 1D · MFA (optional — only if MFA is enabled for your user)

- [ ] **1.11** If `/auth/login` returns `requires_mfa: true`, the UI lands on `/login/mfa`. Enter the TOTP from your authenticator. Success → `/dashboard`.
- [ ] **1.12** Invalid code (`000000` is the mock sentinel — works in mock mode only) → 401 envelope `MFA_INVALID`, no redirect.
- [ ] **1.13** Live mode + mismatched TOTP → 401 `MFA_INVALID`. Backend uses real TOTP verification.

### 1E · Refresh + token expiry

- [ ] **1.14** Hard-refresh `/dashboard`. Still authenticated (httpOnly refresh cookie did its job).
- [ ] **1.15** Wait > 15 minutes (the access token TTL) and click any nav item. Network shows `/auth/refresh` → 200 → original request retried automatically. No flicker, no logout-and-back.
- [ ] **1.16** In DevTools → Application → Cookies, find `fabric_refresh`. Confirm it's HttpOnly + (in non-dev) Secure + SameSite=Lax + path `/auth`.

### 1F · Auto-switch corner cases

- [ ] **1.17** New owner with one firm: auto-switch happened (covered in 1.3). Re-login again — same path repeats cleanly.
- [ ] **1.18** *Skip if you only have one firm.* Multi-firm user (manually `INSERT INTO firm …`): `/auth/me` shows `available_firms: [2 entries]`, no auto-switch fires, top-bar shows firm picker.

---

## 2 · Dashboard read

Prereq: at least one finalized invoice (do section 5 first), or empty-state.

- [ ] **2.1** `/dashboard` renders without errors. Network: `/dashboard/kpis` + `/activity` both 200.
- [ ] **2.2** KPI cards show exactly **5 cards** (post-INT-12): `outstanding_ar`, `overdue_ar`, `sales_today`, `sales_mtd`, `gst_collected_mtd`. The pre-INT-12 cards `low_stock_skus` and `supplier_ap` were dropped — they were always 0 in live mode (inventory + purchase modules aren't wired live yet). Numbers reasonable for current data (₹0 for fresh org).
- [ ] **2.3** Activity feed shows last 10 events (signup, finalize, receipt). Empty-state copy is human, not "No data".
- [ ] **2.4** Hard-refresh; KPIs cached for 60s server-side (per `dashboard_service.invalidate_firm`). Post a new receipt → wait 60s → KPIs update on next refresh.

---

## 3 · Sales — invoice list + detail (read)

Prereq: at least one invoice in the DB (use 5A or pre-seed via curl in step 0.6 below).

### 3.0 · Pre-seed (one-time, if you don't want to depend on UI create)

```bash
TOKEN="<paste from /auth/login>"

# create a customer party
curl -s -X POST localhost:8000/parties \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"name":"Anjali Saree Centre","party_type":"CUSTOMER","is_customer":true,"state_code":"MH","gstin":"27ABCDE1234F1Z5"}' | jq

# create an item with HSN
curl -s -X POST localhost:8000/items \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"name":"Chiffon Silk","uom":"METER","gst_rate":"5","hsn_code":"5407"}' | jq
```

Save both UUIDs — you'll need them for 5A.

### 3A · Invoice list

- [ ] **3.1** Visit `/sales/invoices`. Network: `GET /invoices` 200. Table renders.
- [ ] **3.2** Empty state (fresh org): friendly empty card, not a blank table.
- [ ] **3.3** With ≥ 1 invoice: row shows series/number, party name, date, total, paid, status pill.
- [ ] **3.4** Click a row → navigates to `/sales/invoices/{id}`.
- [ ] **3.5** URL filter (e.g. `?status=DRAFT`) narrows server-side. Verify in network panel.

### 3B · Invoice detail

- [ ] **3.6** Detail page shows pill matching status, line items, subtotal, GST, grand total, paid, outstanding.
- [ ] **3.7** Out-of-state customer with IGST tax_type: GST line shows IGST split, not CGST+SGST.
- [ ] **3.8** Bill-of-supply (NIL_LUT tax_type): doc_type pill reads "Bill of supply", no GST column.
- [ ] **3.9** Print button opens "coming soon" dialog (TASK-051 not yet shipped) — that's expected.

---

## 4 · Sales — invoice create (UI gap — see notes)

**⚠ Known gap**: `InvoiceCreate.tsx` populates customer + item dropdowns from mock fixtures (`parties.ts` and `items.ts` are still mock-only). The POST itself works against the live API; the UI just hands it bogus UUIDs. Until T-INT-6 wires masters live, **create invoices via curl**, not the UI.

### 4A · Create via API

Using `PARTY_ID` and `ITEM_ID` from 3.0:

```bash
curl -s -X POST localhost:8000/invoices \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{
    \"firm_id\":\"<your firm_id>\",
    \"party_id\":\"$PARTY_ID\",
    \"invoice_date\":\"2026-05-05\",
    \"due_date\":\"2026-05-20\",
    \"ship_to_state\":\"MH\",
    \"lines\":[{\"item_id\":\"$ITEM_ID\",\"qty\":\"100\",\"price\":\"3000.00\",\"gst_rate\":\"5\",\"sequence\":1}]
  }" | jq
```

- [ ] **4.1** 201 with envelope containing `sales_invoice_id`, `series`, `number`, `lifecycle_status:"DRAFT"`. Save the ID.
- [ ] **4.2** Refresh `/sales/invoices` in browser → new row visible at top.
- [ ] **4.3** psql: `SELECT lifecycle_status, invoice_amount, gst_amount FROM sales_invoice ORDER BY created_at DESC LIMIT 1;` — DRAFT, totals correct, GST = subtotal × rate.

### 4B · Validation

- [ ] **4.4** Missing `Idempotency-Key` header → 400 envelope `IDEMPOTENCY_KEY_MISSING`. Backend rejects every mutating endpoint without one.
- [ ] **4.5** Empty `lines: []` → 400 with `field_errors.lines` populated.
- [ ] **4.6** `qty: 0` → 400 envelope, line-level field error.
- [ ] **4.7** Non-existent `party_id` (random UUID) → 404 `PARTY_NOT_FOUND` or FK envelope.

### 4C · Idempotency

- [ ] **4.8** Re-submit the exact same body + same `Idempotency-Key` → returns the **original** response (same `sales_invoice_id`), no second row in DB. Verify count: `SELECT count(*) FROM sales_invoice;`.
- [ ] **4.9** Same body + **different** key → creates a **new** invoice with the next sequential number.

---

## 5 · Sales — invoice finalize (state machine + GL posting)

Prereq: at least one DRAFT invoice (from 4A).

### 5A · Finalize happy path

- [ ] **5.1** From `/sales/invoices/{id}`, click **Finalize**. Network: `POST /invoices/{id}/finalize` → 200.
- [ ] **5.2** Pill flips to FINALIZED. Print button still shows the coming-soon dialog.
- [ ] **5.3** psql: `SELECT lifecycle_status FROM sales_invoice WHERE sales_invoice_id = …;` → `FINALIZED`.
- [ ] **5.4** psql: voucher posted —
  ```sql
  SELECT line_type, ledger_id, amount FROM voucher_line
   WHERE voucher_id = (SELECT voucher_id FROM voucher
                       WHERE reference_type='sales_invoice'
                       ORDER BY created_at DESC LIMIT 1);
  ```
  Three rows: 1 DR (AR ledger 1200), 2 CR (Sales 4000 + Output GST 2200/2300/2400 depending on split). DR total = CR total.
- [ ] **5.5** psql: `SELECT total_debit, total_credit FROM voucher ORDER BY created_at DESC LIMIT 1;` — equal.

### 5B · Finalize stale-state (multi-tab)

- [ ] **5.6** Open the same invoice in tab B. In tab A, finalize. In tab B, click Finalize → 409 envelope `INVOICE_STATE_ERROR`. UI shows "stale, refresh" banner + Refresh button.
- [ ] **5.7** Click Refresh → page re-fetches, pill is FINALIZED, banner cleared.

### 5C · Finalize idempotency

- [ ] **5.8** With an already-DRAFT invoice, fire two POSTs back-to-back with the same `Idempotency-Key`. Only one finalize event in audit log.

### 5D · Place-of-supply correctness

Repeat 4A for each:

**INT-11 fix**: inter-state supply is **always IGST** regardless of value. The ₹2.5L threshold is a GSTR-1 reporting bucket flag (`gstr1_section: B2CL` for high-value, `B2CS` for low-value), NOT a tax-type flip. Pre-INT-11 the code (and this guide) were wrong on 5.11.

- [ ] **5.9** **Intra-state B2B** (seller MH, customer MH, GSTIN). Finalize. GL has CGST + SGST split, no IGST line. `tax_type=CGST_SGST`. `gstr1_section=B2B`.
- [ ] **5.10** **Inter-state B2C above ₹2.5L** (seller MH, customer GJ, no GSTIN, total > 2,50,000). Finalize. `tax_type=IGST`, `pos_state=GJ`, `gstr1_section=B2CL` (invoice-wise filing).
- [ ] **5.11** **Inter-state B2C below ₹2.5L** (seller MH, customer GJ, no GSTIN, total < 2,50,000). Finalize. `tax_type=IGST` (per actual GST law — pre-INT-11 was CGST_SGST, that was the bug), `pos_state=GJ`, `gstr1_section=B2CS` (consolidated filing).
- [ ] **5.12** **Bill of supply** (NIL_LUT tax type or composition firm). No GST line in voucher. `doc_type=BILL_OF_SUPPLY`. *Note*: composition-firm trigger is **deferred to TASK-INT-14**; today, COMPOSITION firms still emit TAX_INVOICE. NIL_LUT export under LUT works.

---

## 6 · Receipts — post + FIFO allocation + list

Prereq: at least one FINALIZED invoice (from 5A) with paid_amount = 0.

### 6A · Post happy path (UI)

- [ ] **6.1** From `/sales/invoices/{id}`, click **Record payment**. Form opens.
- [ ] **6.2** Enter half the outstanding amount, mode **CASH**, no reference. Save. Network: `POST /receipts` 201.
- [ ] **6.3** Invoice pill flips to **PARTIALLY_PAID**, paid increments, outstanding shrinks. Same on hard refresh.
- [ ] **6.4** Record another receipt for the **remaining** outstanding via mode **UPI**. Pill → **PAID**, outstanding = ₹0.
- [ ] **6.5** psql: 2 voucher rows with `voucher_type='RECEIPT'`. 2 payment_allocation rows pointing at the same invoice. AR ledger DR vs CR balanced (across both vouchers).

### 6B · Receipts list

- [ ] **6.6** Visit `/accounting` → Receipts tab. Both rows visible. Newest first.
- [ ] **6.7** Each row shows: party_name (not blank), mode column ("Cash" / "Upi"), allocated invoice numbers in last column (e.g. `RT/2526/0001`).
- [ ] **6.8** Network: single `GET /receipts?limit=100`. No N+1 follow-ups for party/allocations (CRIT-1 fix).

### 6C · FIFO across multiple invoices

- [ ] **6.9** Create 2 finalized invoices for the same party — invoice X (older date, ₹50k), invoice Y (newer, ₹30k).
- [ ] **6.10** Post a single ₹60k receipt. Expected: ₹50k to X (full), ₹10k to Y (partial). X → PAID, Y → PARTIALLY_PAID.
- [ ] **6.11** psql: `SELECT sales_invoice_id, amount FROM payment_allocation WHERE voucher_id = …;` — 2 rows, amounts ₹50,000 + ₹10,000.

### 6D · Over-allocation

- [ ] **6.12** Post a receipt for ₹100k against a party whose outstanding is ₹40k. Voucher posts; allocations cover ₹40k; remainder visible in audit log: `SELECT changes->'after'->>'unallocated' FROM audit_log WHERE entity_type='banking.receipt' ORDER BY created_at DESC LIMIT 1;` → "60000".

### 6E · Mode validation

- [ ] **6.13** POST receipt with `"mode":"CHEQUE"` → 400 envelope, "mode" field error. Only CASH/BANK/UPI allowed (CRIT-3).
- [ ] **6.14** POST receipt with amount `0` → 400 `RECEIPT_AMOUNT_INVALID` or similar. Negative amount → same.

### 6F · Idempotency

- [ ] **6.15** Re-submit the same receipt body + same `Idempotency-Key` → returns the original voucher_id, no new voucher in DB.

---

## 7 · Cross-firm RLS isolation

- [ ] **7.1** In an incognito window, sign up a **second org** (different email, different org name). Create one party + one invoice there.
- [ ] **7.2** In the original window, hit `GET /invoices?limit=100` directly. Org B's rows do **not** appear, even though tokens are valid.
- [ ] **7.3** Try to fetch Org B's invoice by its UUID from Org A's session: `GET /invoices/<org-B-id>` → 404, not 403 or 200. (RLS hides existence.)
- [ ] **7.4** psql as a non-superuser session: `SET app.current_org_id = '<org-A-id>'; SELECT count(*) FROM sales_invoice;` — only Org A's count.

---

## 8 · Error envelopes (Q8a contract)

**INT-8 fix**: every error response — **including Pydantic validation
422s** — now matches `{code, title, detail, status, field_errors,
request_id}`. The pre-INT-8 raw-FastAPI `{detail: [...]}` shape is
gone. `field_errors` is a flat dotted-key map: `body.lines.0.qty`,
`path.sales_invoice_id`, `query.limit`, `header.idempotency-key`. The
leading scope segment is preserved so the FE knows whether to surface
the message to a form (`body.*`) or a banner (`path.*`/`query.*`).

`request_id` appears in BOTH the response body AND the `X-Request-ID`
header with the same value (per INT-8's `RequestContextMiddleware`).

- [ ] **8.1** 401 (expired token, manually clobbered) → envelope `TOKEN_INVALID`, banner appears, refresh attempt or redirect to login.
- [ ] **8.2** 403 (call an endpoint your role doesn't have) → envelope `PERMISSION_DENIED`. UI shows inline message, not a generic toast.
- [ ] **8.3** 404 (random UUID) → envelope, generic "Not found" UI.
- [ ] **8.4** 409 (state conflict — e.g. finalize twice) → envelope, stale banner.
- [ ] **8.5** 422 (validation) → envelope `VALIDATION_ERROR` with `field_errors` as `{"body.lines.0.qty": ["must be > 0"], …}`; form highlights the bad fields by binding `name="lines.0.qty"` to the FE form library.
- [ ] **8.6** 500 (forced — kill Postgres mid-request) → envelope `UNKNOWN`, no stack trace leaked. After Postgres restart, retry succeeds.
- [ ] **8.7** Compare `body.request_id` to `X-Request-ID` response header — they must be identical (same UUID v4). Tester can copy-paste from either.

---

## 9 · Click-dummy regions (mock-only)

These render fixtures only. Click-through is fine for visual QA but **do not file FAIL on backend behavior** — there is none.

- [ ] **9.1** `/masters/parties` — list, create, edit. UI works against fixtures.
- [ ] **9.2** `/masters/items` — same.
- [ ] **9.3** `/purchase/orders`, `/purchase/grn`, `/purchase/pi` — fixtures.
- [ ] **9.4** `/inventory` — fixtures.
- [ ] **9.5** `/jobwork` — fixtures (Phase 3 backend not built).
- [ ] **9.6** `/manufacturing` — fixtures (Phase 3).
- [ ] **9.7** `/reports` (TB, P&L, GSTR-1, Stock, Daybook) — fixtures.
- [ ] **9.8** Voucher kinds **other than** RECEIPT (Journal/Payment/Contra/Expense) — fixtures.

---

## 10 · UI polish + accessibility

- [ ] **10.1** Each list page (invoices, receipts, parties) has a **loading skeleton**, not a blank screen, while data fetches.
- [ ] **10.2** Each list page has an **empty state** with a CTA (e.g. "Create your first invoice").
- [ ] **10.3** Each form has at least one field with `aria-label` / `<label htmlFor>` — Tab key reaches every input in visual order.
- [ ] **10.4** Mobile viewport (Chrome DevTools → 375 px width): tables scroll horizontally without breaking layout. Sidebar collapses.
- [ ] **10.5** Dark mode (system pref): every text/contrast ratio readable. No white-on-white or black-on-black.
- [ ] **10.6** Keyboard shortcut **⌘K** opens the command palette. Search "invoices" → navigates.

---

## 11 · Performance smoke

- [ ] **11.1** Dashboard cold load < 1.5 s on local (`docker stats` shows postgres CPU < 30%).
- [ ] **11.2** Invoice list with 100 rows < 800 ms server-time (visible in network panel "Time").
- [ ] **11.3** No request fires more than 3× during a single page render (check network panel — filter by XHR).

---

## 12 · Soak (overnight)

- [ ] **12.1** Leave the dashboard tab open overnight. Morning: still authenticated, no console errors, KPIs stable.
- [ ] **12.2** `docker compose logs postgres api | grep -iE 'error|fatal|traceback'` — no new entries since soak start.

---

## Sign-off

- [ ] All boxes ticked OR each unchecked one has a follow-up note: "blocked by issue #N", "deferred to T-INT-6 — masters wiring", "WONTFIX — mock-only".
- [ ] Bug list filed (one issue per real defect; group cosmetic ones).
- [ ] Decision recorded at the bottom of this file: GO (proceed to friendly-customer trial) / NO-GO (ship fixes first, list them).

---

## Test runs

<!--
Append one entry per full pass. Example:

### 2026-05-05 — Moiz, post-PR-INT-5 dogfood

- Sections 0–8: 96/100 boxes green.
- Section 9: skipped (mock-only).
- Section 10: 4/6 (mobile sidebar collapse jittery on first open; cosmetic, filed #47).
- Section 11: all green; dashboard cold load 720 ms.
- Section 12: ran 14 hours. Clean.
- Decision: GO. T-INT-6 (masters live) starts Monday.
-->
