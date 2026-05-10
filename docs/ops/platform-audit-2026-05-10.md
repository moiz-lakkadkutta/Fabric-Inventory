# Platform audit — 2026-05-10 (v2, engineer hand-off)

**Auditor:** Claude (lead-engineer hat, honest + critical)
**For:** the engineer who will pick this up — fix the bugs, complete the gaps, and ship the platform Moiz can run his textile firm on.
**Method:** static read of the full FE/BE tree, OpenAPI introspection, end-to-end curl flow against a sidecar uvicorn (the dev `:8000` is wedged — see P0-1), and a route-by-route browser walk via Chrome DevTools MCP at `http://localhost:5174`. Screenshots at `docs/ops/audit-2026-05-10-screenshots/*.png`.

---

## TL;DR — what this platform actually is today

Out of ~80 backend endpoint+method combinations that exist, the frontend wires **14**. The other ~66 are implemented and tested in the BE but the FE is still on click-dummy `fakeFetch` fixtures. Almost every primary CTA on every page (`+ New PO`, `+ New MO`, `+ New party`, `Print PDF`, `Export CSV`, `Adjust stock`, `Invite user`, `Reconcile bank`, etc.) opens a `ComingSoonDialog` instead of calling the API. Five sub-routes are full-page `<Placeholder>`s.

So end-to-end, the only flows that actually transact are: **login → dashboard → invoice list/detail → create draft → finalize → record receipt**. Everything else is a beautiful, convincing demo that does nothing.

There is also a stack of latent quality issues that need to be fixed before this can run a real shop: CORS rejecting every browser request, Onboarding wizard that doesn't sign you up, idempotency cache leaking refresh tokens, mock identity bleeding into the live UI chrome, error copy that says "the mock layer hiccupped" in production. Each is captured below with file paths and acceptance criteria.

**Net: ~25–30% of the way to Moiz's personal-use production system. About 6–10 weeks of focused work for one engineer to close, plus 3–4 weeks of net-new backend (reports, manufacturing, job-work, admin/invite, party import, PDF rendering).**

---

## Section 1. The state of every nav route (browser walk)

Captured 2026-05-10 at `http://localhost:5174`. Live API is at `http://localhost:8000` but every cross-origin call is blocked by CORS (P0-2). Wherever the FE has a `fakeFetch` branch, the page renders mock data and the user can't tell the data isn't real. Wherever the FE is on `IS_LIVE`, the page renders an empty state or a `Couldn't load this view — The mock layer hiccupped` error (P1-1).

| Route | Component | Renders | Data source | What works | What's broken/missing |
|---|---|---|---|---|---|
| `/` | `Dashboard.tsx` | "Daybook · Wednesday, 30 Apr 2026 · all numbers in ₹ for Rajesh Textiles, Surat" + Recent invoices empty + Today panel empty | live (`useDashboard`) | Layout chrome | KPIs + activity rows blank because CORS blocked the API. Header chip "Rajesh Textiles · 24AAACR5055K1Z5" comes from **mock fixtures** (UserMenu/FirmSwitcher/AppLayout), not from `authStore`. Hardcoded date string suggests another mock leak. Screenshot `01-home.png`. |
| `/sales/invoices` | `InvoiceList.tsx` | Error card: "Couldn't load this view — The mock layer hiccupped" + Retry button | live (`useInvoices`) | Filters, search box | Same CORS root cause. Error copy is wrong (P1-1). `Export CSV` button → `useComingSoon('TASK-046')`. Screenshot `02-sales-invoices.png`. |
| `/sales/invoices/new` | `InvoiceCreate.tsx` | Pre-filled customer "Anjali Saree Centre" + line "Georgette Cotton 44…" + Subtotal ₹145.00 + GST ₹7.25 + Grand total ₹152.25 + Save draft / Finalize | **mock parties + mock items** even in live mode | Form layout, GST math, document-type selector | Customer/Item dropdowns query mock fixtures (parties.ts, items.ts are 100% `fakeFetch`). Save draft / Finalize would post a **mock party_id and mock item_id** to the live `POST /invoices` and 422 on UUID validation. The form is unusable end-to-end until parties + items are wired. Screenshot `04-invoice-create.png`. |
| `/sales/invoices/:id` | `InvoiceDetail.tsx` | (could not exercise without a live invoice) | live (`useInvoice`) | Detail mapper, finalize/receipt mutations | `Print invoice (GST-compliant PDF)` → `useComingSoon('TASK-051')`. No PDF rendering exists. |
| `/sales/quotes` | `<Placeholder task="TASK-038">` | "Coming soon (TASK-038)." | none | nothing | No FE, no BE for quotes. Screenshot `03-sales-quotes-placeholder.png`. |
| `/sales/orders` | `<Placeholder task="TASK-038">` | same | none | nothing | **BE exists** (`/sales-orders` × 5 endpoints). FE just hasn't been built. |
| `/sales/challans` | `<Placeholder task="TASK-033">` | same | none | nothing | **BE exists** (`/delivery-challans` × 4). FE missing. |
| `/sales/returns` | `<Placeholder task="TASK-038">` | same | none | nothing | No BE, no FE. |
| `/sales/credit-control` | `<Placeholder task="TASK-055">` | same | none | nothing | No BE (only `customer_credit_profile` table). FE missing. |
| `/purchase` | `PurchaseOrderList.tsx` | 3-way match table: 8 POs from "Surat Silk Mills" / "Coimbatore Yarn Imports" / "Gujarat Cotton Co." | mock (`usePurchaseOrders`) | Visual layout, status pills, 3-way match indicators | All data is mock. `+ New PO` → `useComingSoon('TASK-028')`. `Receive GRN` → `useComingSoon('TASK-027')`. Inline status pills are decorative — not interactive. Screenshot `05-purchase.png`. |
| `/inventory` | `InventoryList.tsx` | 8-row SKU table with on-hand, status mix bars, lots count, reorder threshold | mock (`useInventory`) | Visual | All data mock. `+ New GRN` → `useComingSoon('TASK-027')`. `Adjust stock` → `useComingSoon('TASK-024')`. Screenshot `06-inventory.png`. |
| `/inventory/lots/:id` | `LotDetail.tsx` | not walked | mock | — | mock-only |
| `/manufacturing` | `ManufacturingPipeline.tsx` | 6-column kanban (Planned / Cutting / Embroidery / Stitching / QC / Packed) × 6 cards with order numbers, due dates, customer names, progress bars | mock (`useManufacturing`) | Visual | **No BE.** CLAUDE.md decision #8 says Phase 3, but the route is in the primary nav so users will click it. `+ New MO` → `useComingSoon('TASK-050')`. `View list` → `useComingSoon('TASK-052')`. Screenshot `07-manufacturing.png`. |
| `/jobwork` | `JobWorkOverview.tsx` | 5 karigar cards (Imran Khan / Salim Sheikh / Pooja Devi / Naseem Begum / Rakesh Patel) + active jobs table with sent/returned/wastage | mock (`useJobwork`) | Visual | **No BE.** Tables `job_work_order` etc. exist but no router. `+ Send out` → `useComingSoon('TASK-032')`. `Receive back` → `useComingSoon('TASK-034')`. Screenshot `08-jobwork.png`. |
| `/accounting` | `AccountingHub.tsx` | "0 receipts · 6 vouchers" — Receipts tab empty, Vouchers tab has 6 mock rows | **mixed**: receipts list = live, vouchers = mock | Receipts list mapper ✓ | Receipts shows 0 because CORS blocked the call (real backend has data). Vouchers tab = `useVouchers()` mock. `+ New receipt` → `useComingSoon('TASK-042')` (so users can't even use the working `POST /receipts` from this page — only from InvoiceDetail). `+ New voucher` → `useComingSoon('TASK-044')`. `Reconcile bank` → `useComingSoon('TASK-045')`. Screenshot `09-accounting.png`. |
| `/reports` | `ReportsHub.tsx` | "Apr 2026 · FY 2025-26 · vs Mar 2026" with full P&L: Total income ₹16.36 L, COGS -₹10.14 L, Gross profit ₹6.22 L, Net profit ₹3.60 L, plus Tax invoices / Bill of supply / Karigar payouts / Salaries / Rent / Electricity rows. Tabs: P&L, Trial balance, GSTR-1, Stock, Daybook | mock (`useReports`) | Visual layout per tab | **All 5 reports are 100% mock.** No backend exists. `Print` and `Export` → `useComingSoon('TASK-046')`. This is the single biggest unbuilt piece — **no GSTR-1, no P&L, no TB, no daybook, no stock report ever computes anything against real data.** Screenshot `10-reports.png`. |
| `/masters/parties` | `PartyList.tsx` | 15-row party table (Anjali Saree Centre / Devi Fashions / Lakshmi Suit House / …) with kind chips (CUSTOMER/SUPPLIER/KARIGAR/TRANSPORTER), GSTIN, outstanding balance | mock (`useParties`) | Visual | All mock. `+ New party` → `useComingSoon('TASK-020')`. `Import` → `useComingSoon('TASK-019' Vyapar/CSV)`. **BE has full CRUD** (`/parties` × 5 methods). Screenshot `11-masters-parties.png`. |
| `/masters/parties/:id` | `PartyDetail.tsx` | not walked | mock | — | mock |
| `/admin` | `AdminHub.tsx` | 5-user table (Moiz Lakkadkutta / Naseem Begum / Pooja Devi / Rajesh Patel CA / Salim Sheikh — with 1 Pending invite) + 4 Roles (Owner/Sales/Accountant/Warehouse) + Audit log link | mock (no live wiring at all) | Visual | All mock. `+ Invite user` → `useComingSoon('TASK-021')`. `+ Add role` → `useComingSoon('TASK-022')`. **No backend admin endpoints exist** for invite/list-users/manage-roles even though `app_user`, `role`, and `user_role_assignment` tables are populated. The "Salim Sheikh — Invite sent 2 d ago" row is fictional. Screenshot `12-admin.png`. |
| `/login` | `Login.tsx` | Form: Organization "Rajesh Textiles" + Email "moiz@rajeshtextiles.in" + Password (pre-filled) + "Remember this device for 30 days" + Sign in + Forgot password / Set up your business | live (`useLogin`) | Form fields ✓ | Form is pre-filled with credentials that aren't actually in the DB → submit will fail. CORS blocks the call regardless. No captcha / rate-limit. Screenshot `13-login.png`. |
| `/mfa` | `Mfa.tsx` | (not walked but verified live wiring exists in `lib/queries/identity.ts:120-148`) | live | TOTP verify ✓ | — |
| `/forgot` | `Forgot.tsx` | Form: "Reset your password — Enter your email and we'll send a reset link." + email field + Send reset link | mock (no backend) | Form layout | **No backend.** `/auth/forgot` doesn't exist in OpenAPI. Submitting sends the email into a void. Misleading. Screenshot `15-forgot.png`. |
| `/invite` | `Invite.tsx` | "You've been invited to Rajesh Textiles, Surat — Role: Accountant — Invited by: Rajesh Patel · Owner — Permissions: Sales · Accounts · Reports — Expires: 04 May 2026" + Accept & set password / Decline | mock (no backend) | Form layout | **No backend.** Cannot actually accept an invite. Screenshot `16-invite.png`. |
| `/onboarding` | `Onboarding.tsx` | 3-step wizard (Org / Firm / Opening balances) — pre-filled "Rajesh Patel Holdings" / GSTIN "24ABCDE1234F1Z5" / "Import from Vyapar (.vyp)" | **no API call at all** | Wizard state machine ✓ | "Commit & finish" is `navigate('/')` (`Onboarding.tsx:102`) — there is no `useSignup` mutation. Wizard has **no password field, no state_code field**. Vyapar import option is fictitious — no adapter exists. **Net effect: there is no path from the running web app to a usable account.** Screenshot `14-onboarding.png`. |

### What this means for "is it usable today?"

It is not. End-to-end, with a fresh browser and the running services:

1. The user lands on `/login` with pre-filled credentials that don't exist → click Sign in → CORS error in console → stuck on `/login`.
2. The user clicks "Set up your business" → fills the wizard → clicks "Commit & finish" → lands on `/` unauthenticated → the dashboard chrome renders Moiz's mock firm name + an empty Daybook panel + an error card on Sales invoices. **The user has not signed up. There is no account.**
3. Even with a working login, every single mutation outside "draft an invoice → finalize → record a receipt" is gated to a `Coming soon` modal.

---

## Section 2. Bugs and broken behaviors (with file paths)

Severity legend:
- **P0** — blocks any usage / corrupts data / leaks credentials. Fix in week 1.
- **P1** — visible defect that a real user will hit on day one. Fix before any friendly customer.
- **P2** — quality / hygiene. Fix as you touch the area.

### P0-1. `:8000` uvicorn returns 500 on every external HTTP request

- **Symptom:** `curl localhost:8000/auth/signup` (and any POST/PATCH) returns the generic envelope `{"code":"UNKNOWN","status":500,"request_id":...}` for unique payloads. Same code via in-process `TestClient(app)` and same code via a sidecar `uvicorn main:app --port 8765` both succeed (verified during this audit).
- **Likely cause:** the `--reload`-launched dev server (PID 68022, started 2026-05-10 12:24 PM) has wedged on something — the actual traceback is on the user's tty, not in any log file. CORS isn't the cause (CORS rejection happens browser-side without reaching the server; the 500s here have a server-assigned `request_id`).
- **Reproducer (just for the next engineer):**
  ```bash
  curl -s -X POST http://localhost:8000/auth/signup \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: $(uuidgen | tr A-Z a-z)" \
    -d '{"email":"x@example.com","password":"strong-password-1","org_name":"X","firm_name":"HQ","state_code":"MH"}'
  # → HTTP 500
  cd backend && uv run uvicorn main:app --port 8765 &
  curl -s -X POST http://localhost:8765/auth/signup … # → HTTP 201
  ```
- **Fix:** restart `:8000` (`pkill -f 'uvicorn main:app' ; cd backend && uv run uvicorn main:app --reload --port 8000`). Add a `make dev-restart` Makefile target so this is a one-keystroke recovery.
- **Acceptance:** `curl -X POST localhost:8000/auth/signup …` returns 201 for a fresh org.

### P0-2. CORS rejects every browser API call (FE on :5174, BE allowlist :5173)

- **Symptom:** every fetch from the browser fails with `Access to fetch at 'http://localhost:8000/...' from origin 'http://localhost:5174' has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on the requested resource`.
- **Root cause:** `backend/.env` has `CORS_ORIGINS=http://localhost:5173`, hard-coded in `backend/app/config.py:17`. The user's actual dev server ended up on port 5174 (5173 was likely already taken by an older Vite instance). FE config in `frontend/.env` correctly points at `:8000` — but `:8000` doesn't allow `:5174` as an origin.
- **Fix options (pick one):**
  1. (preferred) Add a Vite proxy in `frontend/vite.config.ts`: `server.proxy = { '/api': { target: 'http://localhost:8000', rewrite: p => p.replace(/^\/api/, '') } }`, then change `frontend/.env` to `VITE_API_BASE_URL=/api`. Removes CORS entirely (same-origin), lets prod behind Caddy work without env diffs.
  2. Update `backend/.env` to `CORS_ORIGINS=http://localhost:5173,http://localhost:5174`. Quick but fragile.
- **Acceptance:** open `http://localhost:5174/` in a fresh browser, hit `/dashboard/kpis` via DevTools network, get 200.

### P0-3. Onboarding wizard never calls the backend

- **Files:** `frontend/src/pages/auth/Onboarding.tsx:42-103`. Step 3's "Commit & finish" button (`line 102`) is `<Button onClick={() => navigate('/')}>` — there is no `useSignup` mutation, no API call, nothing.
- **Backend side:** `POST /auth/signup` works perfectly (verified end-to-end during this audit; returns full token pair, seeds RBAC + UOM + HSN + COA catalogs). Schema requires `email`, `password`, `org_name`, `firm_name`, `state_code` (2-char), `gstin` optional.
- **Frontend gaps:**
  - No password field anywhere in the wizard.
  - No `state_code` field — would need to be derived from GSTIN's first 2 chars or asked explicitly.
  - The "Import from Vyapar (.vyp)" option in step 3 is fictitious — no Vyapar adapter exists in the BE (CLAUDE.md decision #5 says it's the *primary* migration adapter, but `grep -r 'vyapar' backend/` returns zero matches in app code).
- **Fix:** wire `OpeningStep` "Commit & finish" to a `useSignup` mutation that posts to `/auth/signup`, mirrors `useLogin` (`lib/queries/identity.ts:72-93`) for token storage. Add the password field. Either remove the Vyapar option or label it "(coming soon)".
- **Acceptance:** open `/onboarding`, fill the wizard, click "Commit & finish" → user is created in `app_user`, `firm` row exists in DB, JWT is in `authStore`, user lands on `/` and sees their actual data (KPIs all zero on a fresh org).

### P0-4. Idempotency cache stores `Set-Cookie: fabric_refresh=…` — replays leak refresh tokens

- **File:** `backend/app/middleware/idempotency.py:127-139`. Cached payload includes `dict(response.headers)`. For `/auth/signup` and `/auth/login`, the headers include `Set-Cookie: fabric_refresh=<JWT>; HttpOnly; Max-Age=1209599; SameSite=lax`.
- **Verified:** during this audit, `redis-cli get idem:/auth/signup:f262...` returned the full cached envelope including the cookie header with the refresh JWT in plaintext.
- **Threat:** the threat model in CLAUDE.md says refresh tokens are httpOnly and rotated. With this cache, **anyone with the same `Idempotency-Key` (logged in client telemetry, leaked in error reports, intercepted by a proxy) gets back the original refresh-token cookie for 24h.**
- **Fix:** in `idempotency.py:127-139`, before persisting `dict(response.headers)`, drop `set-cookie` and `authorization` keys (case-insensitive). For auth endpoints specifically, treat them like `/auth/refresh` — add `/auth/login` and `/auth/signup` to `IDEMPOTENT_BY_DESIGN_PATHS` so they always re-execute and issue a fresh token pair.
- **Acceptance:** `redis-cli get idem:/auth/signup:<key>` after a signup contains no `set-cookie` header. A replay with the same key returns the same `200`/`201` body but a freshly-rotated refresh cookie.

### P0-5. Mock identity bleeds into the live UI chrome

- **Files:**
  - `frontend/src/components/layout/UserMenu.tsx:7,42,60,63` — imports `currentUser` from `@/lib/mock` for monogram, legal name, email, role.
  - `frontend/src/components/layout/FirmSwitcher.tsx:8,39,44` — imports `firms` from `@/lib/mock` for the firm chip.
  - `frontend/src/pages/Dashboard.tsx:9` — imports `formatINRCompact, formatRelative, formatAgeing` from `@/lib/mock` (formatters; safe).
- **Effect:** even when CORS works and `authStore.me` is populated, the topbar chip, user avatar, and Dashboard's "Rajesh Textiles, Surat" subtitle all come from hard-coded mock fixtures rather than `useMe()`. A fresh org's actual firm name will never appear in the UI.
- **Fix:** swap `currentUser` → `useMe()` in `UserMenu`, swap `firms` → `me.available_firms` in `FirmSwitcher`. Render the active firm using `me.firm_id` cross-referenced against `me.available_firms`. Move pure formatters out of `lib/mock` into `lib/format` so future mock removal doesn't hit them.
- **Acceptance:** sign up "Audit Co" / firm "HQ" → topbar shows "HQ" not "Rajesh Textiles". `/admin` shows the real signed-in user.

### P1-1. Sales Invoice list error copy: "The mock layer hiccupped"

- **File:** find via `grep -rn "mock layer hiccupped" frontend/src` (was visible at `/sales/invoices` after CORS rejection — screenshot `02-sales-invoices.png`).
- **Fix:** rewrite the error component to surface the actual `ApiError.title`/`detail`/`code` from the envelope. Distinguish CORS / network / 401 / 5xx. Add a developer hint in dev mode (`import.meta.env.DEV`) showing the request_id.
- **Acceptance:** triggering a 500 on `/invoices` shows "Internal server error · request_id: …" instead of "mock layer hiccupped."

### P1-2. Receipts list loses `party_id` / `party_name` for unallocated receipts

- **File:** `backend/app/service/receipt_service.py:335-405` (`list_receipts_with_details`). The function derives party only via `payment_allocation` → `sales_invoice` → `party`. A receipt with zero allocations (legitimate case: cash deposit before any invoice exists, OR P1-3's timing bug) has no party link.
- **Verified:** during this audit, receipt `voucher_id=0eb047bf` (525 rupees, party `a5971f7e`) returns `party_name: null, allocations: []` in `GET /receipts`. The voucher table has no `party_id` column on the header.
- **Fix:** add `party_id UUID NULL` to `voucher` (Alembic migration), populate it in `receipt_service.post_receipt`, prefer `voucher.party_id` in the list join (fall back to the allocation join only for legacy rows).
- **Acceptance:** post a receipt for a party with no open invoices → `GET /receipts` returns the receipt with `party_id` and `party_name` populated.

### P1-3. POST /receipts may skip allocation against a present FINALIZED invoice (timing)

- **Repro from this audit:** in a fresh tenant, the curl chain `POST /invoices (DRAFT) → POST /invoices/{id}/finalize (FINALIZED) → POST /receipts (525)` returned `allocations=[]`. The very next `POST /receipts (500)` against the same now-FINALIZED invoice **did** allocate. So the bug is at the boundary of "just-finalized" → "next request."
- **Suspect:** `_list_open_invoices_fifo` (`receipt_service.py:108-128`) reads through a snapshot that hasn't seen the finalize commit yet, OR the RLS GUC isn't set up identically in the receipt request's connection.
- **Action:** add `tests/test_receipts_after_finalize_allocates.py` that signs up → creates → finalizes → posts a receipt within the same async sequence and asserts `allocations` is non-empty. If it reproduces, the fix is probably to take a row-level lock on the candidate invoices when querying, or move the FIFO query to `READ COMMITTED` snapshot explicitly. If it doesn't reproduce, write the test anyway — it's a critical invariant.
- **Acceptance:** test passes 1000 times with no flakes.

### P1-4. No protected-route gate — unauthenticated users see the full app chrome with mock data

- **Files:** `frontend/src/App.tsx`, `frontend/src/components/layout/AppLayout.tsx`. There is no `<RequireAuth>` wrapper — opening `/`, `/sales/invoices`, `/admin` etc. with no token renders the whole layout shell, the mock firm chip, the empty data panels, and the CORS-error states. `useAuthBootstrap` (`hooks/useAuth.ts`) does try `/auth/refresh` on mount but doesn't redirect on failure.
- **Fix:** add a `<RequireAuth>` element that reads `useAuthStatus()`. While `'unknown'` show a splash; on `'unauthenticated'`, `<Navigate to="/login" replace />`. Wrap the AppLayout `children` in App.tsx.
- **Acceptance:** open `/` in a fresh incognito window → redirected to `/login` immediately, no mock chrome visible.

### P1-5. Login form pre-filled with credentials that aren't real

- **File:** `frontend/src/pages/auth/Login.tsx`. Pre-fills "Rajesh Textiles", "moiz@rajeshtextiles.in", and a password. These don't exist in the DB → submit fails. Confusing for a first-time user.
- **Fix:** drop the defaults entirely (production), or guard them with `import.meta.env.DEV`.

### P1-6. `Forgot password` form sends email into void

- **File:** `frontend/src/pages/auth/Forgot.tsx`. **No `/auth/forgot` endpoint exists in OpenAPI.** Backend has no password-reset flow at all.
- **Fix:** either (a) hide the link until the BE flow ships, or (b) build it: BE endpoint `POST /auth/forgot {email, org_name}` → email a one-time JWT-signed reset link → `POST /auth/reset {token, new_password}`. Use a real email provider (Mailgun/Postmark), not console.log.
- **Acceptance:** request reset → receive email → set new password → log in.

### P1-7. `Invite` page accepts invitations that don't exist

- **File:** `frontend/src/pages/auth/Invite.tsx`. **No invite endpoints in BE.**
- **Fix:** BE `POST /admin/invites {email, role_code, firm_id}` → email a signed token → `GET /invites/{token}` returns the invite payload, `POST /invites/{token}/accept {password}` creates the user + assigns the role. Then wire FE.

### P1-8. `Cheques` list returns `count: null`

- **File:** `backend/app/routers/banking.py` `list_cheques`. Other list endpoints return `count: <int>`. Fix: compute `count = len(items)` (or a `SELECT COUNT(*)` if proper pagination).
- **Acceptance:** `GET /cheques` returns `{"items":[],"count":0}`.

### P1-9. Invoice list mapper hard-codes `subtotal: 0, gst_total: 0`

- **File:** `frontend/src/lib/queries/invoices.ts:165-183` (`mapListItem`). The list endpoint omits `gst_amount` so the FE can't show per-row tax columns. Currently returns `subtotal: 0, gst_total: 0`.
- **Fix:** add `gst_amount` to `BackendSalesInvoiceListItem` (BE: `app/schemas/sales.py` SalesInvoiceListItem) and to the SELECT projection. FE mapper computes `subtotal = total - gst_total`.
- **Acceptance:** invoice list table shows correct GST and subtotal columns.

### P2-1. Vyapar import option in Onboarding wizard is fictional

- **File:** `frontend/src/pages/auth/Onboarding.tsx:277-280` advertises ".vyp parsing". No adapter exists in `backend/`.
- **Fix:** scope decision per CLAUDE.md decision #5 — Vyapar adapter is supposed to be the primary migration path. Either build it (multi-week, separate task) or label "Coming soon."

### P2-2. JWT timestamps look weird (year 2026 — but this is correct)

- **Note for the next reader:** signup response shows `iat: 1778397014, exp: 1778398001`. Decodes to ~2026-05-10. Matches "today" per system clock. **Not a bug.** Logged here so no one wastes time on it.

### P2-3. Test database leaks into dev DB

- **Symptom:** `app_user` table has ~20 `u-{hex}@example.com` rows; `organization` has matching `Org-{hex}` rows. These came from `backend/tests/test_auth_routers.py` running against the dev DB, not a sandbox.
- **Fix:** point integration tests at a separate `fabric_erp_test` DB (set `DATABASE_URL` in `pyproject.toml` `[tool.pytest.ini_options]` env or a `conftest.py` fixture). Add `truncate` fixture per test.

### P2-4. Money-on-the-wire dual representation

- **Issue:** BE serializes `Decimal` as rupees-string (`"1050.00"`); FE immediately converts to paise integers; UI converts back to rupees for display. Eight pairs of mappers (`rupeesToPaise` / `paiseToRupees`) have to stay in sync. Source of bugs as more endpoints get wired.
- **Fix (post-MVP):** standardize on rupees-Decimal-string everywhere; use a single utility (`Dinero` or `decimal.js`) for arithmetic in the FE. Out of scope for this audit but worth flagging.

### P2-5. No FE↔BE schema codegen

- Each `lib/queries/*.ts` re-declares `interface BackendXxx` by hand. OpenAPI is at `/openapi.json` — perfect input for `openapi-typescript`. Add a `pnpm run gen:types` step. Eliminates drift bugs that will multiply as more endpoints get wired.

---

## Section 3. Coming-soon inventory — every CTA / route that opens a placeholder

This is the work backlog the next engineer needs to pick from. Each row is a `useComingSoon` modal trigger or a `<Placeholder>` route in the app today. Tasks are referenced by their TASK-NNN id from `TASKS.md`.

| Where (route) | CTA / sub-route | Component file:line | Gated to | BE built? |
|---|---|---|---|---|
| `/sales/invoices` | "Export CSV" button | `pages/sales/InvoiceList.tsx:42` | TASK-046 | No |
| `/sales/invoices/:id` | "Print invoice (GST-compliant PDF)" | `pages/sales/InvoiceDetail.tsx:42` | TASK-051 | No (PDF rendering doesn't exist) |
| `/sales/quotes` | (whole page) | `App.tsx:42` Placeholder | TASK-038 | No |
| `/sales/orders` | (whole page) | `App.tsx:43` | TASK-038 | **Yes — `/sales-orders` × 5** |
| `/sales/challans` | (whole page) | `App.tsx:46` | TASK-033 | **Yes — `/delivery-challans` × 4** |
| `/sales/returns` | (whole page) | `App.tsx:48` | TASK-038 | No |
| `/sales/credit-control` | (whole page) | `App.tsx:51` | TASK-055 | No |
| `/purchase` | "+ New PO" | `pages/purchase/PurchaseOrderList.tsx:28` | TASK-028 | **Yes — `/purchase-orders` × 6** |
| `/purchase` | "Receive GRN" | `pages/purchase/PurchaseOrderList.tsx:24` | TASK-027 | **Yes — `/grns` × 4** |
| `/inventory` | "+ New GRN" | `pages/inventory/InventoryList.tsx:31` | TASK-027 | Yes — `/grns` |
| `/inventory` | "Adjust stock" | `pages/inventory/InventoryList.tsx:27` | TASK-024 | **Yes — `/stock-adjustments` × 2** |
| `/manufacturing` | "+ New MO" | `pages/manufacturing/ManufacturingPipeline.tsx:18` | TASK-050 | **No** (Phase 3 per CLAUDE.md) |
| `/manufacturing` | "View list" | `pages/manufacturing/ManufacturingPipeline.tsx:14` | TASK-052 | No |
| `/jobwork` | "+ Send out" | `pages/jobwork/JobWorkOverview.tsx:28` | TASK-032 | **No** |
| `/jobwork` | "Receive back" | `pages/jobwork/JobWorkOverview.tsx:24` | TASK-034 | No |
| `/accounting` | "+ New receipt" | `pages/accounting/AccountingHub.tsx:37` | TASK-042 | **Yes — `/receipts`** (already wired in InvoiceDetail; just hook it up here too) |
| `/accounting` | "+ New voucher" | `pages/accounting/AccountingHub.tsx:37` | TASK-044 | No top-level `/vouchers` POST endpoint — only via `/receipts` and the under-the-hood GL postings. |
| `/accounting` | "Reconcile bank" | `pages/accounting/AccountingHub.tsx:33` | TASK-045 | No |
| `/reports` | "Print report (PDF)" | `pages/reports/ReportsHub.tsx:35` | TASK-046 | **No reports BE at all** |
| `/reports` | "Export report (CSV / Excel)" | `pages/reports/ReportsHub.tsx:39` | TASK-046 | No |
| `/masters/parties` | "+ New party" | `pages/masters/PartyList.tsx:40` | TASK-020 | **Yes — `/parties` × 5** |
| `/masters/parties` | "Import (CSV / Vyapar .vyp)" | `pages/masters/PartyList.tsx:36` | TASK-019 | **No Vyapar adapter** |
| `/admin` | "+ Invite user" | `pages/admin/AdminHub.tsx:90` | TASK-021 | **No** |
| `/admin` | "+ Add role" | `pages/admin/AdminHub.tsx:94` | TASK-022 | No (RBAC seeds 4 roles; no CRUD endpoint for custom roles) |
| `/forgot` | "Send reset link" | `pages/auth/Forgot.tsx` | (none — silently mock) | **No `/auth/forgot` endpoint** |
| `/invite` | "Accept & set password" | `pages/auth/Invite.tsx` | (none — silently mock) | **No invite endpoints** |
| `/onboarding` | "Commit & finish" | `pages/auth/Onboarding.tsx:102` | (none — silently mock; this is **P0-3**) | **Yes — `/auth/signup`** |

That's **24 distinct work items** behind `useComingSoon` / `<Placeholder>` / silent-mock buttons. Eight already have BE built; sixteen need BE+FE.

---

## Section 4. What's missing for "production for personal use"

If "production for personal use" means: Moiz can run his actual textile firm on this — every invoice, every receipt, every payment, every party, every stock move, every GST filing — without ever falling back to Vyapar. Here's the gap list, ordered by impact-to-block-a-real-day-of-business.

### Tier 1 — must-haves to even open the shop on day one

These are non-negotiable for a textile firm that sells, buys, holds stock, and files GSTR-1 monthly.

1. **Working signup** (P0-3 + P0-2): can't have a platform if you can't onboard.
2. **Parties CRUD wired** (`/masters/parties` + `+ New party`): every invoice needs a real party_id. Currently the InvoiceCreate dropdown sources mock IDs that the BE will reject.
3. **Items CRUD wired** (`+ New item` doesn't even exist; PartyList style): same reason.
4. **Invoice creation actually works against real party + item IDs.** Currently broken because of (2) and (3).
5. **Invoice PDF rendering** (TASK-051). A textile firm can't hand a customer a digital PDF link — they need a printed/PDF Tax Invoice with seller GSTIN, buyer GSTIN, place of supply, HSN, IGST/CGST/SGST split, signature panel, terms. **No PDF rendering exists yet.** Use WeasyPrint or ReportLab in BE; expose `GET /invoices/{id}/pdf` returning `application/pdf`.
6. **Bank accounts + receipts + cheques screens** (`/accounting`): the receipts BE is wired but the FE only allows posting from InvoiceDetail. A real shop needs to log direct-credit receipts (no invoice yet), cheque-in-hand receipts that haven't cleared, etc. Schema already has `cheque` table + `bank_account` table.
7. **Purchase orders + GRN + PI 3-way match** (`/purchase`): inbound goods, supplier invoices, ITC capture. BE has `/purchase-orders`, `/grns`, `/purchase-invoices` ready. FE has the screen but every CTA is a placeholder.
8. **Stock adjustments + lot tracking** (`/inventory`): opening stock entry, monthly count corrections, damage write-off. BE has `/stock-adjustments` ready.
9. **Reports — at minimum: P&L, Trial balance, GSTR-1 prep, Daybook, Stock summary.** This is the single biggest unbuilt piece. **No reports BE exists.** A textile firm cannot file GSTR-1 without it. Build:
   - `GET /reports/pnl?from=&to=` — accrual P&L by ledger group.
   - `GET /reports/trial-balance?as_of=` — ledger balances.
   - `GET /reports/gstr1?period=YYYY-MM` — B2B / B2C(L) / B2C(S) / Export / HSN-summary buckets in the GSTR-1 schema.
   - `GET /reports/daybook?date=` — per-day voucher list.
   - `GET /reports/stock-summary?as_of=` — per-SKU on-hand × valuation (FIFO or weighted-avg).

### Tier 2 — needed within month one of real use

10. **Forgot-password flow** (P1-6) — somebody will lose their MFA + password.
11. **User invite + role management** (P1-7 + TASK-021/022) — Moiz will want to give his accountant access at some point.
12. **Sales orders + delivery challans** (`/sales/orders`, `/sales/challans`): textile sales are often "send sample → DC out → SO → invoice". BE for both exists.
13. **Job-work send-out + receive-back** (`/jobwork`): textile firms job-work cutting/embroidery/stitching/dyeing. Schema exists, no BE router. Needed for accurate stock and ITC-04.
14. **CSV / Excel export of every list view** (TASK-046): customers will demand "send me my ledger as Excel". The FE shows an Export button on every list — wire it.

### Tier 3 — needed before a friendly customer

15. **Bank reconciliation** (`Reconcile bank`, TASK-045): match bank-statement CSV against posted vouchers.
16. **Invoice cancel / discard / credit-note** (no UI today): regulatory must.
17. **GST e-invoice + e-way bill** (CLAUDE.md decision #6): the machinery is all built and feature-flag-gated. Once Moiz crosses the ₹5 Cr threshold, flip the flag. **Verified:** `feature_flag` table has `gst.einvoice.enabled` and `gst.eway.enabled` per-firm. UI to toggle the flag does not exist (`/admin` is mock).
18. **Returns flow** (`/sales/returns`, `/purchase/returns`): rare-but-real edge case in textile.

### Tier 4 — nice to have

19. **Manufacturing pipeline + BOM** (CLAUDE.md decision #8 says Phase 3 — schema exists, no BE).
20. **Vyapar `.vyp` import** (CLAUDE.md decision #5): Moiz's actual migration path.
21. **WhatsApp send / e-mail-invoice flow** (CLAUDE.md decision #9 — Phase 4+).
22. **Mobile / offline / PWA** (CLAUDE.md decision #9).

### Operational gaps (not features — but required for prod)

23. **Postgres backups.** No automated dump → S3 / Hetzner Object Storage. CLAUDE.md `make backup` placeholder exists in the Commands table but no implementation in `Makefile`.
24. **Sentry not wired.** `frontend/src/lib/sentry.ts` reads `VITE_SENTRY_DSN` but `.env.example` has no DSN. Backend has nothing.
25. **HTTPS in dev.** Refresh-cookie is `Secure=False` in dev (`backend/app/routers/auth.py:73`). For self-host on Hetzner, deploy behind Caddy with auto-LE cert.
26. **Logs collection.** `structlog` writes JSON to stdout — not aggregated anywhere. Add Loki/Promtail or just `logrotate` + file persistence.
27. **Healthcheck depth.** `/healthz` returns `{}` ; `/ready` checks DB. Neither verifies Redis is reachable for idempotency. Add a Redis ping to `/ready`.
28. **Migration adapter from Vyapar** (item 20). Moiz's actual data lives in Vyapar today.

---

## Section 5. Suggested 8-week fix plan (one engineer)

### Week 1 — make it usable
- P0-1 restart `:8000` + add `make dev-restart`.
- P0-2 Vite dev proxy (or BE CORS update).
- P0-3 wire Onboarding → `/auth/signup`. Add password field. Drop Vyapar option.
- P0-4 strip cookie headers from idempotency cache. Exempt `/auth/login` + `/auth/signup`.
- P0-5 swap mock identity → `useMe()` / `me.available_firms` in UserMenu + FirmSwitcher.
- P1-4 add `<RequireAuth>` gate.
- P1-1 fix invoice list error copy.
- **End of week 1: a fresh user can sign up, sign in, draft an invoice, finalize, get a receipt. The UI no longer leaks mock identity.**

### Week 2 — masters wired
- Parties FE (TASK-019, TASK-020): list + detail + create + edit. Connect InvoiceCreate's customer dropdown.
- Items FE: same shape as parties; Connect InvoiceCreate's item dropdown.
- Auto-populate UOM + HSN dropdowns from `/uoms` and `/hsn`.
- **End of week 2: invoice create end-to-end with real parties + items.**

### Week 3 — money in
- Receipt screen on `/accounting` (TASK-042). Vouchers list (BE: add `GET /vouchers`).
- Bank accounts CRUD (BE wired; FE missing).
- P1-2 + P1-3 receipts party-id + allocation timing.

### Week 4 — money out + stock in
- Purchase orders FE (TASK-028) + GRN intake (TASK-027) + PI post (no current TASK).
- Stock adjustments screen (TASK-024).
- Sales orders + delivery challans FE (TASK-033, TASK-038).

### Week 5 — print + export
- Invoice PDF rendering (TASK-051). WeasyPrint server-side.
- Reports BE: `/reports/pnl`, `/reports/tb`, `/reports/daybook`, `/reports/stock-summary` (TASK-046 backend).
- ReportsHub wired live (TASK-046 frontend).
- Export CSV + PDF buttons on every list (TASK-046 export).

### Week 6 — GSTR-1 + admin
- `/reports/gstr1?period=` BE — bucket invoices into B2B / B2C(L) / B2C(S) / Export / HSN-summary.
- GSTR-1 download (JSON → ready for offline tool / GSP later).
- Admin invite + role CRUD (TASK-021, TASK-022, BE+FE).
- Forgot-password flow (BE + FE).

### Week 7 — job-work + reconciliation
- Job-work BE (TASK-032/034 — `/job-work-orders`, `/job-work-bills`, `/itc04`).
- Job-work FE.
- Bank reconciliation BE+FE (TASK-045).

### Week 8 — hardening + ops
- Backup automation (`make backup` + cron).
- Sentry wired front + back.
- HTTPS via Caddy in prod.
- Vyapar adapter `(.vyp)` MVP path: at least parties + ledger opening balances.
- Test DB isolation; clean up the dev-DB test rows.

This gets Moiz to a state where every operational flow except manufacturing (Phase 3) and WhatsApp (Phase 4) works. After that, friendly-customer trial + e-invoice flag-flip for ₹5 Cr threshold are 1-week tasks, not months.

---

## Section 6. Quick reference — files to touch

For the engineer scanning for "where do I start":

**Frontend:**
- `App.tsx` — route table; replace 5 `<Placeholder>`s with real pages.
- `lib/queries/*.ts` — every file that has `fakeFetch` is a wiring target. 11 files; 4 have partial live wiring.
- `pages/auth/Onboarding.tsx:102` — the single line that breaks signup.
- `components/layout/{UserMenu,FirmSwitcher,AppLayout}.tsx` — purge mock identity.
- `pages/Placeholder.tsx` — keep, but it should be reachable from fewer places.
- `components/ui/coming-soon-dialog.tsx` — `useComingSoon` is the marker for "this CTA is not wired yet". `grep -rn 'useComingSoon' frontend/src` is your worklist.

**Backend:**
- `routers/` — 11 files, all healthy. New routers needed: `reports.py`, `admin.py` (invites + roles), `jobwork.py`, `password_reset.py`.
- `service/receipt_service.py:335-405` — fix P1-2.
- `service/receipt_service.py:108-128` — likely site of P1-3 fix.
- `middleware/idempotency.py:127-139` — strip cookies (P0-4).
- `app/config.py:17` + `.env` — CORS allowlist (P0-2).

**Schema:**
- `voucher` table needs `party_id UUID NULL` for P1-2.
- All `manufacturing_*`, `bom*`, `job_work_*`, `inward_challan_*`, `itc04_*`, `customer_credit_profile` tables exist with no router — Tier-3/4 work.

---

## Section 7. Caveats — what this audit did NOT cover

- I did not run the full pytest suite. Quick smoke tests passed; coverage of GST place-of-supply edge cases (IGST inter-state, NIL_LUT export, NIL_NOT_A_SUPPLY, composite, B2C-without-state) is in `tests/test_gst_*` but not exercised live during this audit.
- I did not stress-test the idempotency middleware under concurrent retries.
- I did not audit the migration history for backward-compatibility breaks.
- I did not run the Playwright suite. Last known to pass per recent retros.
- I did not benchmark P95 latency on any endpoint; perf budget is unverified.
- Mobile / responsive behavior was not exercised — the browser walk used a desktop viewport.

Screenshots from this audit live at `docs/ops/audit-2026-05-10-screenshots/01-home.png` … `16-invite.png`. Use them to compare against post-fix renders.
