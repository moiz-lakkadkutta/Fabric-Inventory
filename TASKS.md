# TASKS.md — Ordered Task Backlog for Claude Code

Each task is completable in 1-4 hours and maps to the 12-week plan. Pick the next **Ready** task; only Ready tasks have no blockers. Update status after each session.

> **2026-04-27 — Backend-first execution.** Frontend design is still in progress, so every UI task (Login UI, Dashboard, Admin panel, list/create screens, etc.) is marked **Deferred — frontend design pending** and should not be picked up. Pick the next **Ready** task from the backend pool only. The "Frontend Phase" picks up wholesale once the design system lands. Backend tasks that previously listed a UI task as blocker (TASK-027, TASK-032, TASK-061a all named TASK-021) have been re-pointed at the backend predecessor (TASK-011 Item CRUD) so they unblock cleanly.

---

## Milestone 1 — Week 1: Project Bootstrap

### TASK-001: Repository scaffolding & Makefile
**Status:** Done  
**Blocks:** TASK-002, TASK-003, TASK-004, TASK-005  
**Files touched:** Makefile, .env.example, .gitignore, pyproject.toml, package.json, docker-compose.yml, .github/workflows/ci.yml

**Scope:**
- Create root Makefile with targets: `make setup`, `make dev`, `make test`, `make lint`, `make migrate`, `make seed`, `make deploy`, `make backup`.
- Create `.env.example` template (DB_URL, JWT_SECRET, etc.; all dummy values).
- Create `.gitignore` (node_modules, __pycache__, .env, *.pyc, .venv, dist, build).
- Scaffold `pyproject.toml` (poetry) with Python 3.12, FastAPI, SQLAlchemy, Alembic, pytest, ruff, mypy.
- Scaffold `package.json` (pnpm) with React 18, TypeScript, Vite, Tailwind, shadcn/ui, Vitest, Playwright.
- Create `docker-compose.yml` with services: postgres (16), redis (latest), api (FastAPI dev), web (Vite dev).
- Create GitHub Actions CI workflow: on push, run pytest + vitest + ruff + mypy. Fail if violations.

**Acceptance:**
- [ ] `make setup` installs Python + Node deps, creates .env from .env.example, initializes test DB.
- [ ] `make dev` starts all services in docker-compose (Postgres, Redis, FastAPI, Vite).
- [ ] `make test` runs pytest + vitest + returns exit code 0 if passing.
- [ ] `make lint` runs ruff + prettier; returns exit code 1 if violations.
- [ ] GitHub Actions runs on every push and reports status.
- [ ] Stranger clones repo, runs `make setup && make dev`, sees localhost:5173 (Vite) and localhost:8000 (FastAPI) running in < 10 min.

**Approximate time:** 3 hours  
**Notes:**
- Use uv for Python package management (faster than poetry for CI).
- Use pnpm (faster than npm).
- Docker Compose watch mode for hot reload (Vite + uvicorn).

---

### TASK-002: FastAPI boilerplate & middleware
**Status:** Done  
**Blocks:** TASK-006, TASK-007, TASK-008  
**Files touched:** backend/main.py, backend/app/config.py, backend/app/db.py, backend/app/middleware/*, backend/app/exceptions.py

**Scope:**
- Create FastAPI app entry point (`backend/main.py`).
- Config module (DB connection string, JWT secret, environment detection, logging).
- SQLAlchemy engine + session maker (async with create_all off, migrations only).
- Middleware: CORS, error handler (catch exceptions, return JSON error), logging.
- RLS middleware (stub): parse JWT, extract org_id, set `SET LOCAL app.current_org_id`.
- Global error handler: catch custom exceptions and return appropriate HTTP status.
- Health check endpoint (`GET /health`).
- OpenAPI schema endpoint (`GET /openapi.json`).

**Acceptance:**
- [ ] `make dev` starts FastAPI; `curl http://localhost:8000/health` returns `{"status": "ok"}`.
- [ ] All startup/shutdown events defined.
- [ ] Error handler returns `{"detail": "...", "error_code": "..."}` for exceptions.
- [ ] RLS middleware logs parsed org_id (or errors on missing JWT).
- [ ] OpenAPI schema is valid.

**Approximate time:** 2.5 hours  
**Notes:**
- Use pydantic for config validation.
- Middleware runs in order: CORS → logging → RLS → error handler.

---

### TASK-003: React + Vite + Tailwind scaffolding
**Status:** Done  
**Blocks:** TASK-012, TASK-013  
**Files touched:** frontend/vite.config.ts, frontend/tsconfig.json, frontend/tailwind.config.ts, frontend/index.html, frontend/src/main.tsx, frontend/src/App.tsx, frontend/src/styles/globals.css

**Scope:**
- Vite config with React + TypeScript.
- Tailwind CSS (CDN in dev, npm build for prod).
- Root App component with routing skeleton (React Router v6).
- Basic layout: header, sidebar, main content.
- Global styles (reset, utilities).
- 404 page.

**Acceptance:**
- [ ] `make dev` serves frontend on localhost:5173.
- [ ] Vite hot-reload works (edit component, see change in browser instantly).
- [ ] Tailwind classes work (e.g., `<div class="bg-blue-500">` renders blue).
- [ ] Routing structure ready (Dashboard, Sales, Purchase, Accounts, etc. as navigation items).
- [ ] No TypeScript errors (strict mode on).

**Approximate time:** 1.5 hours  
**Notes:**
- Use shadcn/ui for component library (install first button + card components).
- Router setup: use `createBrowserRouter` + `RouterProvider`.

---

### TASK-004: Postgres DDL schema bootstrap
**Status:** Done  
**Blocks:** TASK-009, TASK-010, TASK-015  
**Files touched:** backend/schema/ddl.sql, backend/alembic/env.py, backend/alembic/script.py.mako

**Scope:**
- Copy DDL from `schema/ddl.sql` (fix the `uuid-ossp` syntax error from docs/review.md).
- Create Alembic migration folder structure.
- Initialize Postgres in docker-compose with health check.
- `make migrate` target runs `alembic upgrade head`.
- Test database auto-creates on `make setup`.

**Acceptance:**
- [ ] `make migrate` loads schema without errors.
- [ ] Postgres ready for connections (health check passes).
- [ ] Alembic history tracked (alembic_version table exists).
- [ ] All tables exist; RLS enabled where specified.
- [ ] `psql -d fabric_erp -c "SELECT count(*) FROM information_schema.tables" → 102 tables (or thereabouts)`.

**Approximate time:** 1 hour  
**Notes:**
- Fix P0-1 from docs/review.md: `uuid-ossp` → `"uuid-ossp"` (quoted).
- Or remove uuid-ossp if not used; schema uses `gen_random_uuid()` from pgcrypto.

---

### TASK-005: GitHub Actions CI setup
**Status:** Done  
**Blocks:** (none; gate for merges)  
**Files touched:** .github/workflows/ci.yml, .github/workflows/deploy.yml (stub)

**Scope:**
- Create CI workflow: on every push to main and on PRs.
- Run pytest (backend tests) with Postgres service.
- Run vitest + Playwright (frontend tests).
- Run ruff check, mypy, prettier, eslint.
- Fail if any violation.
- Report results in GitHub PR status.
- Create stub deploy workflow (on tag; to be filled in later).

**Acceptance:**
- [ ] Push to a branch triggers CI workflow.
- [ ] All checks run in parallel (where possible).
- [ ] Fail gracefully if one check fails (next checks still run for visibility).
- [ ] Status badge shows in README (e.g., "CI: Passing").

**Approximate time:** 1.5 hours  
**Notes:**
- Use `services:` in workflow for Postgres (avoids complex setup).
- Cache node_modules and pip packages between runs.

---

## Milestone 2 — Week 2: Auth + RBAC + Core Masters

### TASK-006: SQLAlchemy models scaffold (identity)
**Status:** Done  
**Blocks:** TASK-007, TASK-014, TASK-015  
**Files touched:** backend/app/models/identity.py

**Scope:**
- SQLAlchemy ORM models (not raw DDL):
  - `Organization` (org_id PK, name, admin_email, timezone, feature_flags JSONB, audit columns).
  - `Firm` (firm_id PK, org_id FK, code, name, has_gst bool, gstin BYTEA, audit columns).
  - `AppUser` (user_id PK, org_id FK, email unique per org, password_hash, mfa_enabled, is_active, audit columns).
  - `Role` (role_id PK, org_id FK, code, name, is_system_role).
  - `Permission` (permission_id PK, code like "sales.invoice.create", description).
  - `RolePermission` (role_id FK, permission_id FK, unique together).
  - `AuditLog` (log_id PK, org_id FK, entity_type, entity_id, action, before JSON, after JSON, user_id, timestamp).
- All models use `Base` from SQLAlchemy declarative.
- Relationships defined (e.g., `User.org → Organization`, `Role.permissions → [Permission]`).
- All inherit standard audit columns (created_at, updated_at, created_by, deleted_at).

**Acceptance:**
- [ ] Models compile (no import errors).
- [ ] Relationships work (e.g., `user.org`, `role.permissions`).
- [ ] All models have RLS policy defined (or stub commented).
- [ ] Alembic can auto-detect models (if models file is imported in env.py).

**Approximate time:** 2 hours  
**Notes:**
- For encrypted fields (GSTIN, PAN), use `BYTEA` type; encryption happens in service layer, not model.
- `AuditLog` is append-only; no update/delete, only insert.

---

### TASK-007: Auth service (JWT + password + MFA)
**Status:** Done  
**Blocks:** TASK-016, TASK-017  
**Files touched:** backend/app/service/identity_service.py

**Scope:**
- `register_user(email, password, org_id, firm_id)` → hash password, create user, return user_id.
- `login(email, password)` → verify password, generate JWT (15 min access token, 14-day refresh token), return both.
- `refresh_token(refresh_token)` → validate refresh token in Redis, issue new access + refresh, return both.
- `enable_mfa(user_id)` → generate TOTP secret, return QR code.
- `verify_totp(user_id, code)` → verify 6-digit code against secret.
- `verify_jwt(token)` → decode and return payload (org_id, firm_id, user_id, permissions).
- Password hash using `bcrypt` (cost factor 12).
- JWT sign/verify using `PyJWT` and RS256 (or HS256 for MVP).

**Acceptance:**
- [ ] `login()` returns valid JWT that `verify_jwt()` can decode.
- [ ] Refresh token validates and issues new pair.
- [ ] MFA enable returns QR code (pyotp).
- [ ] TOTP verify works.
- [ ] Invalid password returns error.
- [ ] All functions have unit tests.

**Approximate time:** 2.5 hours  
**Notes:**
- Store refresh tokens in Redis with expiry (14 days).
- JWT payload includes org_id, firm_id, user_id, list of permission codes.

---

### TASK-008: Auth routers (login, refresh, MFA, signup)
**Status:** Done  
**Blocks:** TASK-011, TASK-012  
**Files touched:** backend/app/routers/auth.py

**Scope:**
- `POST /auth/signup` → request: {email, password, org_name, firm_name}; response: {user_id, access_token, refresh_token}.
- `POST /auth/login` → request: {email, password}; response: {access_token, refresh_token, requires_mfa: bool}.
- `POST /auth/mfa-verify` → request: {user_id, totp_code}; response: {access_token, refresh_token}.
- `POST /auth/refresh` → request: {refresh_token}; response: {access_token, refresh_token}.
- `POST /auth/logout` → invalidate refresh token.
- Error handling: invalid creds, MFA required, token expired, etc.
- All endpoints return standard error format from global error handler.

**Acceptance:**
- [ ] Signup creates org + firm + user.
- [ ] Login returns tokens.
- [ ] MFA verify works.
- [ ] Refresh issues new pair.
- [ ] Logout invalidates token in Redis.
- [ ] All endpoints have integration tests.

**Approximate time:** 2 hours  
**Notes:**
- Signup is public (no auth required).
- All others require valid JWT in Bearer header.

---

### TASK-009: RBAC service (role creation, permission assignment)
**Status:** Done  
**Blocks:** TASK-018, TASK-019  
**Files touched:** backend/app/service/rbac_service.py

**Scope:**
- Seed system roles on org creation: Owner, Accountant, Salesperson, Warehouse, Production Manager.
- Each role has a preset bundle of permissions (from docs/architecture.md).
- `get_user_permissions(user_id, firm_id)` → query role_permission for user's role, return set of permission codes.
- `has_permission(user_id, firm_id, permission_code)` → boolean check.
- `assign_role(user_id, firm_id, role_id)` → user has role in firm (can be different role in another firm).
- `create_custom_role(org_id, name, permissions)` → Owner only.

**Acceptance:**
- [ ] System roles seeded on org creation.
- [ ] `has_permission()` works for all system roles.
- [ ] Custom roles can be created.
- [ ] A user can have different roles in different firms.
- [ ] All functions have unit tests.

**Approximate time:** 1.5 hours  
**Notes:**
- System roles are immutable for MVP (Owner can modify custom roles only).

---

### TASK-010: Party model, CRUD service, router
**Status:** Done  
**Blocks:** TASK-020, TASK-021  
**Files touched:** backend/app/models/masters.py, backend/app/service/masters_service.py, backend/app/routers/masters.py

**Scope:**
- Model: `Party` (party_id, org_id, firm_id, type [SUPPLIER, CUSTOMER, KARIGAR, TRANSPORTER], name, gstin [encrypted], pan [encrypted], email, phone [encrypted], address, city, pincode, credit_limit, tax_status [REGULAR, COMPOSITION, UNREGISTERED], is_active, audit columns).
- Service: `create_party()`, `update_party()`, `list_parties()`, `get_party()`, `soft_delete_party()`.
- Router: `POST /parties`, `PATCH /parties/{id}`, `GET /parties`, `GET /parties/{id}`, `DELETE /parties/{id}`.
- RLS: parties filtered by org_id + firm_id.
- Validation: email unique per org, GSTIN format check (basic), name required.

**Acceptance:**
- [x] Create party returns party_id.
- [x] List parties shows only org's + firm's parties (RLS enforced; defense-in-depth org_id filter at app layer).
- [x] Update party works; timestamp updated.
- [x] Soft delete sets deleted_at; list doesn't return deleted parties.
- [x] Encryption for GSTIN + PAN (dummy for MVP; service-layer placeholder).
- [x] All endpoints have integration tests + RLS isolation tests.

**Approximate time:** 2.5 hours  
**Notes:**
- For MVP, encryption is a stub (store plaintext in encrypted field; real encryption in Phase 2).
- GSTIN regex: `\d{2}[A-Z]{5}\d{4}[A-Z]1[Z0-9A-Z]`.

---

### TASK-011: Item + SKU model, CRUD service, router
**Status:** Done  
**Blocks:** TASK-022, TASK-023  
**Files touched:** backend/app/models/masters.py (extend), backend/app/service/masters_service.py (extend), backend/app/routers/masters.py (extend)

**Scope:**
- Models: 
  - `Item` (item_id, org_id, firm_id, code, name, description, item_type [RAW, SEMI_FINISHED, FINISHED, SERVICE], uom_id, hsn_id, opening_qty, opening_value, is_active, tracking_type [BATCH, LOT, SERIAL, NONE], audit columns).
  - `SKU` (sku_id, item_id, variant_name [e.g., "Red-M"], cost, selling_price, audit columns).
  - `UOM` (uom_id, code, name, uom_type [METER, PIECE, KG, etc.]).
  - `HSN` (hsn_id, code, description, gst_rate_pct).
- Service: CRUD for all four models.
- Router: `POST /items`, `PATCH /items/{id}`, `GET /items`, etc. Same for SKU, UOM, HSN.

**Acceptance:**
- [x] Create item with SKU variant works.
- [x] List items shows variants as nested (via GET /items/{id}/skus).
- [x] HSN + UOM linked correctly (catalog read endpoints; full seed in TASK-015).
- [x] RLS enforced: can't see other firm's items (defense-in-depth org_id at app layer + RLS isolation test).
- [x] All endpoints have integration tests.

**Approximate time:** 2.5 hours  
**Notes:**
- UOM and HSN are potentially org-wide (not firm-scoped in this MVP), but RLS still enforces org_id.
- SKU is the actual saleable unit; Item is the template.

---

### TASK-012: Login UI (auth form, JWT storage, routing)
**Status:** Deferred — frontend design pending (backend gates TASK-003, TASK-008 already Done)  
**Blocks:** TASK-024, TASK-025  
**Files touched:** frontend/src/pages/auth/Login.tsx, frontend/src/api/auth.ts, frontend/src/hooks/useAuth.ts, frontend/src/store/authStore.ts

**Scope:**
- Login page: email + password fields, sign-in button, "Forgot password?" link, "Sign up" link.
- Form validation (client-side): email format, password required.
- On sign-in: call `POST /auth/login`, store access + refresh tokens in localStorage + memory (Zustand store), redirect to Dashboard.
- If MFA required: show MFA prompt (TASK-013).
- Error display: invalid creds, network error, etc.
- Logout: clear tokens, redirect to login.
- Auth guard: protect routes; if no token, redirect to login.

**Acceptance:**
- [ ] Login form renders.
- [ ] Submit calls API and stores tokens.
- [ ] Redirect to dashboard works.
- [ ] Logout clears tokens.
- [ ] Protected routes redirect to login if not authenticated.
- [ ] No TypeScript errors.

**Approximate time:** 2 hours  
**Notes:**
- Use Zustand for auth state (minimal, clean).
- Store tokens in localStorage for persistence across page reloads.
- Use React Router `<ProtectedRoute>` or redirect in useEffect.

---

### TASK-013: MFA UI (TOTP input, QR setup)
**Status:** Deferred — frontend design pending (also gated by TASK-012)  
**Blocks:** (none; TASK-012 depends on this being optional)  
**Files touched:** frontend/src/pages/auth/MFA.tsx, frontend/src/pages/auth/MFASetup.tsx, frontend/src/api/auth.ts (extend)

**Scope:**
- MFA prompt: if login returns `requires_mfa: true`, show 6-digit input.
- Auto-submit on 6 digits entered.
- Error if invalid code.
- MFA setup page: show QR code (from backend), user scans with Authenticator app, then verify 6-digit code.

**Acceptance:**
- [ ] MFA input form renders after login if required.
- [ ] 6-digit auto-submit works.
- [ ] QR code displays on setup page.
- [ ] Verify works.

**Approximate time:** 1.5 hours  
**Notes:**
- QR code generated server-side (pyotp.totp_uri); pass as image data URL to frontend.

---

### TASK-014: SQLAlchemy models scaffold (masters)
**Status:** Done  
**Blocks:** TASK-010, TASK-011  
**Files touched:** backend/app/models/masters.py (new file)

**Scope:**
- Models (from TASK-010, TASK-011 scope): Party, Item, SKU, UOM, HSN, PriceList, COA.
- Each model has org_id, firm_id (where applicable), RLS policy, audit columns.

**Acceptance:**
- [ ] All models compile and import without error.

**Approximate time:** 1 hour  
**Notes:**
- COA is seeded once per org (not user-created in MVP).

---

### TASK-015: Seed data fixture (parties, items, GL accounts)
**Status:** Done  
**Blocks:** TASK-026  
**Files touched:** backend/app/seeds.py, backend/Makefile (make seed target)

**Scope:**
- Create a seed script that runs on `make seed`.
- Seed test org + firm + test user (email: test@example.com, password: password123).
- Seed system roles + permissions.
- Seed 10 supplier parties + 5 customer parties.
- Seed 20 items (fabrics, threads, buttons, finished suits).
- Seed standard Indian COA (Assets, Liabilities, Equity, Revenue, Expense heads).
- Seed UOMs (Meter, Piece, KG, etc.).
- Seed HSN codes (sample 6 codes with GST rates).

**Acceptance:**
- [ ] `make seed` runs without error.
- [ ] Database contains seeded data.
- [ ] Trial balance (sum of GL accounts) = 0.

**Approximate time:** 2 hours  
**Notes:**
- Seed script should be idempotent (safe to run multiple times).

---

### TASK-016: Permission checks in routers
**Status:** Done  
**Blocks:** TASK-020, TASK-021, TASK-022, TASK-023  
**Files touched:** backend/app/dependencies.py, backend/app/routers/*.py

**Scope:**
- Create dependency: `Depends(current_user)` and `Depends(require_permission("permission.code"))`.
- Add permission check to sensitive endpoints:
  - `POST /parties` → requires `party.create`.
  - `PATCH /parties/{id}` → requires `party.edit`.
  - `POST /items` → requires `inventory.item.create`.
  - Etc.
- Return 403 Forbidden if permission denied.

**Acceptance:**
- [ ] Unauthorized request returns 403.
- [ ] Authorized request proceeds.
- [ ] Permissions match docs/architecture.md list.

**Approximate time:** 1 hour  
**Notes:**
- Use dependency injection with FastAPI `Depends()`.

---

### TASK-017: Refresh token rotation + Redis integration
**Status:** Ready (TASK-007 Done; basic rotation already in DB session table — this swaps the store)  
**Blocks:** (none; nice-to-have for W1 but can defer to W2)  
**Files touched:** backend/app/service/identity_service.py (extend), backend/app/db.py (add Redis client)

**Scope:**
- On login, issue refresh token + store in Redis with expiry (14 days).
- On refresh, validate token exists in Redis, issue new pair, invalidate old token.
- On logout, delete token from Redis.

**Acceptance:**
- [ ] Refresh token persists in Redis.
- [ ] Old token invalidated after refresh.
- [ ] Logout clears token.

**Approximate time:** 1 hour  
**Notes:**
- Redis client in `backend/app/db.py`, shared across services.

---

### TASK-018: Dashboard page (stub layout)
**Status:** Deferred — frontend design pending (also gated by TASK-012)  
**Blocks:** (none; can build on in W3+)  
**Files touched:** frontend/src/pages/Dashboard.tsx

**Scope:**
- Show welcome message "Hello, Moiz" (from JWT).
- Show current firm + org.
- Navigation sidebar with links to Sales, Purchase, Inventory, Accounts, Masters, Admin.
- Card layout (4 columns) for quick stats:
  - Receivables (total unpaid invoices).
  - Payables (total unpaid bills).
  - Inventory value (total stock @ cost).
  - Cash balance (manual entry for MVP; auto-fetch later).

**Acceptance:**
- [ ] Dashboard renders.
- [ ] Logged-in user's name shows.
- [ ] Navigation links present.
- [ ] Cards render (hardcoded values OK for now).

**Approximate time:** 1.5 hours  
**Notes:**
- Stats will be wired to actual data in W3+.

---

### TASK-019: Admin panel (user, role, firm management stub)
**Status:** Deferred — frontend design pending (backend gate TASK-009 Done; also gated by TASK-012)  
**Blocks:** (none; full wireup in W2 later)  
**Files touched:** frontend/src/pages/admin/Users.tsx, frontend/src/pages/admin/Roles.tsx, frontend/src/pages/admin/Firms.tsx

**Scope:**
- Admin pages (Owner + Admin role only):
  - Users: list, invite, deactivate.
  - Roles: list, edit permissions (Owner only).
  - Firms: list, create (Owner only).
- For MVP, these are CRUD screens with tables + forms.

**Acceptance:**
- [ ] Pages render.
- [ ] Tables display (hardcoded data OK).
- [ ] Forms render with fields.

**Approximate time:** 2 hours  
**Notes:**
- Wire to actual API in TASK-016 onward.

---

### TASK-020: Party list + create UI
**Status:** Deferred — frontend design pending (backend gates TASK-011, TASK-016 already Done)  
**Blocks:** TASK-027  
**Files touched:** frontend/src/pages/masters/PartyList.tsx, frontend/src/pages/masters/PartyForm.tsx, frontend/src/api/masters.ts

**Scope:**
- Party list page: table with name, type, email, GST status, credit limit columns.
- Sort by name, type.
- Filter by type (supplier/customer).
- Create party button → modal/page with form (name, type, email, phone, address, GST status, credit limit).
- On save: call `POST /parties`, refresh list.
- Edit party: click row → form modal.
- Soft delete: confirm dialog, call `DELETE /parties/{id}`.

**Acceptance:**
- [ ] List renders with test parties (from seed).
- [ ] Create form works, submits to API, refreshes list.
- [ ] Edit form pre-fills, submits PATCH.
- [ ] Delete soft-deletes.

**Approximate time:** 2.5 hours  
**Notes:**
- Use React Hook Form for form state.
- Use TanStack Query for API state.

---

### TASK-021: Item + SKU list + create UI
**Status:** Deferred — frontend design pending (backend gates TASK-011, TASK-016 already Done)  
**Blocks:** TASK-028  
**Files touched:** frontend/src/pages/masters/ItemList.tsx, frontend/src/pages/masters/ItemForm.tsx, frontend/src/api/masters.ts (extend)

**Scope:**
- Item list: table with code, name, type, UOM, HSN, qty (opening), value.
- Create item form: code, name, type (dropdown), UOM (dropdown), HSN (dropdown), opening qty + value.
- SKU sub-form (collapse): for each SKU, color + size + cost + selling_price.
- Edit/delete same flow as parties.

**Acceptance:**
- [ ] List renders.
- [ ] Create item with SKU works.
- [ ] SKU shown in detail view.

**Approximate time:** 2.5 hours  
**Notes:**
- SKU is optional for MVP; can start with simple items, add SKU later.

---

## Milestone 3 — Week 3: Inventory

### TASK-022: Stock ledger + position service
**Status:** Done  
**Blocks:** TASK-029, TASK-030, TASK-031  
**Files touched:** backend/app/models/inventory.py, backend/app/service/inventory_service.py

**Scope:**
- Models:
  - `StockLedger` (ledger_id, org_id, firm_id, item_id, warehouse_id, lot_id, txn_date, qty_in, qty_out, cost_per_unit, total_value, reference_type [GRN, SO, Adjustment], reference_id, audit columns).
  - `StockPosition` (item_id, warehouse_id, current_qty, reserved_qty, available_qty, avg_cost, total_value).
  - `Lot` (lot_id, item_id, mfg_date, expiry_date, tracking_id, audit columns).
- Service:
  - `add_stock(item_id, warehouse_id, qty, cost_per_unit, lot_id, reference_type, reference_id)` → append to ledger, update position.
  - `remove_stock(...)` → same, qty_out.
  - `get_position(item_id, warehouse_id)` → return StockPosition.
  - `reserve_stock(item_id, warehouse_id, qty)` → increment reserved_qty (for SO).
  - `unreserve_stock(...)` → decrement reserved_qty.
- FIFO cost calculation: `avg_cost` = sum(total_value) / sum(qty) from all in ledger entries.

**Acceptance:**
- [ ] Add stock creates ledger entry + updates position.
- [ ] Position reflects current + reserved + available.
- [ ] Average cost calculated correctly.
- [ ] All functions have unit tests.

**Approximate time:** 2.5 hours  
**Notes:**
- Warehouse is a location master (not modeled yet; use default warehouse for W3).

---

### TASK-023: Stock adjustment service + router
**Status:** Blocked by TASK-022, TASK-016  
**Blocks:** TASK-031  
**Files touched:** backend/app/service/inventory_service.py (extend), backend/app/routers/inventory.py

**Scope:**
- `POST /stock-adjustments` → request: {item_id, warehouse_id, qty_change, reason, reference}.
- Validates: item exists, warehouse exists, qty_change != 0.
- Calls `inventory_service.adjust_stock(...)` → appends "Adjustment" entry to ledger, updates position.
- Returns adjustment_id.
- GET /stock-adjustments → list adjustments (org's, firm's).

**Acceptance:**
- [ ] Create adjustment updates stock position.
- [ ] Ledger entry created with reference_type = "Adjustment".

**Approximate time:** 1 hour  
**Notes:**
- Reason field is free-text (physical count, shrinkage, theft, etc.).

---

### TASK-024: Opening balance import UI (wizard)
**Status:** Deferred — frontend design pending (also gated by TASK-022 backend, TASK-012 frontend)  
**Blocks:** TASK-032  
**Files touched:** frontend/src/pages/onboarding/OpeningBalance.tsx, frontend/src/api/masters.ts (extend)

**Scope:**
- Onboarding wizard (shown on first login):
  - Step 1: Choose import mode (None / Upload CSV / Manual entry).
  - Step 2: If CSV, upload file with columns: item_code, qty, cost_per_unit. Preview table.
  - Step 3: If Manual, enter items one-by-one in a grid.
  - Step 4: Summary + confirm button.
- On confirm: call API to import opening balance.

**Acceptance:**
- [ ] Wizard renders.
- [ ] CSV upload + preview works.
- [ ] Manual entry works.
- [ ] Confirm calls API.

**Approximate time:** 2 hours  
**Notes:**
- CSV validation: check column names, data types.

---

### TASK-025: Opening balance import service
**Status:** Blocked by TASK-022, TASK-015  
**Blocks:** TASK-032  
**Files touched:** backend/app/service/inventory_service.py (extend), backend/app/routers/inventory.py (extend)

**Scope:**
- `POST /inventory/opening-balance` → request: {items: [{item_code, qty, cost_per_unit}]}.
- Validates: items exist (by code), qty > 0, cost > 0.
- For each item: create lot + add_stock(..., reference_type="OpeningBalance").
- Returns summary (items imported, total value).

**Acceptance:**
- [ ] Import creates stock ledger entries for each item.
- [ ] Stock position reflects imported qty.

**Approximate time:** 1.5 hours  
**Notes:**
- Opening balance is transactionless (no PO, no GRN); treated as a special ledger entry.

---

### TASK-026: Dashboard wiring (stats from DB)
**Status:** Backend portion Ready once TASK-015 + TASK-022 land (`GET /dashboard/stats` endpoint); UI wiring Deferred — frontend design pending  
**Blocks:** (none; nice-to-have for milestone completion)  
**Files touched:** frontend/src/pages/Dashboard.tsx (extend), backend/app/routers/reports.py (new endpoint)

**Scope:**
- Wire dashboard stats to actual DB queries:
  - Receivables = sum of unpaid sales invoices.
  - Payables = sum of unpaid purchase invoices.
  - Inventory value = sum of stock positions @ cost.
  - Cash = manual entry (hardcoded for now; banking integration in W8).
- Create API endpoint: `GET /dashboard/stats` → returns {receivables, payables, inventory_value, cash}.

**Acceptance:**
- [ ] Dashboard stats query DB.
- [ ] Numbers update after transactions.

**Approximate time:** 1.5 hours  
**Notes:**
- Cache stats for 5 min (Redis) to avoid repeated queries.

---

## Milestone 4 — Week 4: Procurement

### TASK-027: Purchase Order model + service
**Status:** Done  
**Blocks:** TASK-033  
**Files touched:** backend/app/models/procurement.py (new), backend/app/service/procurement_service.py (new)

**Scope:**
- Models:
  - `PurchaseOrder` (po_id, org_id, firm_id, po_number, po_date, supplier_id, status [DRAFT, APPROVED, CONFIRMED, PARTIAL_GRN, FULLY_RECEIVED, CANCELLED], total_amount, audit columns).
  - `POLine` (po_line_id, po_id, item_id, qty_ordered, uom_id, unit_price, total_price, grn_qty_received, audit columns).
- Service:
  - `create_po(supplier_id, lines: [{item_id, qty, unit_price}])` → creates PO + lines, status DRAFT, assigns po_number.
  - `confirm_po(po_id)` → status CONFIRMED.
  - `cancel_po(po_id)` → status CANCELLED (if no GRN received).
  - `list_pos(...)` → filter by status, supplier.

**Acceptance:**
- [ ] Create PO assigns document number + status DRAFT.
- [ ] Confirm PO changes status.
- [ ] PO number is unique, gapless per FY.
- [ ] All functions have unit tests.

**Approximate time:** 2 hours  
**Notes:**
- PO number format: `PO/2025-26/0001` (FY/serial).

---

### TASK-028: GRN (Goods Received Note) model + service
**Status:** Blocked by TASK-027  
**Blocks:** TASK-034, TASK-035  
**Files touched:** backend/app/models/procurement.py (extend), backend/app/service/procurement_service.py (extend)

**Scope:**
- Models:
  - `GRN` (grn_id, org_id, firm_id, grn_number, grn_date, po_id, supplier_id, status [DRAFT, ACKNOWLEDGED, IN_PROCESS, RETURNED, CLOSED], total_qty_received, audit columns).
  - `GRNLine` (grn_line_id, grn_id, po_line_id, item_id, qty_received, lot_id, mfg_date, expiry_date, audit columns).
- Service:
  - `create_grn(po_id, lines: [{po_line_id, qty_received, lot_id}])` → creates GRN, status DRAFT, generates grn_number, calls stock ledger service.
  - `receive_grn(grn_id)` → status ACKNOWLEDGED, finalizes stock, updates PO.grn_qty_received.
  - `list_grns(...)` → filter by status, po_id.

**Acceptance:**
- [ ] Create GRN assigns grn_number.
- [ ] Receive GRN updates stock position.
- [ ] PO line's grn_qty_received incremented.
- [ ] If grn_qty > po_qty, warn (not error, for MVP loose validation).

**Approximate time:** 2 hours  
**Notes:**
- GRN is the point at which stock increases in the ledger.

---

### TASK-029: Purchase Invoice model + service
**Status:** Blocked by TASK-028  
**Blocks:** TASK-036  
**Files touched:** backend/app/models/procurement.py (extend), backend/app/service/procurement_service.py (extend)

**Scope:**
- Models:
  - `PurchaseInvoice` (pi_id, org_id, firm_id, pi_number, pi_date, supplier_id, grn_id, status [DRAFT, CONFIRMED, POSTED], total_amount, igst_amount, cgst_amount, sgst_amount, tax_amount_total, audit columns).
  - `PILine` (pi_line_id, pi_id, grn_line_id, item_id, qty_invoiced, unit_price, hsn_id, igst_rate, cgst_rate, sgst_rate, line_total, audit columns).
- Service:
  - `create_pi(supplier_id, grn_id, lines: [{grn_line_id, unit_price, [tax_rates]}])` → creates PI, status DRAFT.
  - `confirm_pi(pi_id)` → status CONFIRMED, validates supplier ledger (3-way match loose).
  - `post_pi(pi_id)` → status POSTED, calls accounting_service to post GL lines.
  - `list_pis(...)` → filter by status, supplier.

**Acceptance:**
- [ ] Create PI assigned pi_number.
- [ ] Confirm PI validates 3-way match (loose: warn if amount mismatch).
- [ ] Post PI creates GL voucher.

**Approximate time:** 2 hours  
**Notes:**
- 3-way match: PO qty vs GRN qty vs PI qty (loose for MVP = warn, don't block).
- PI posting creates GL entries: Debit Inventory (or COGS), Credit AP (Accounts Payable).

---

### TASK-030: Supplier Ledger service
**Status:** Blocked by TASK-029  
**Blocks:** TASK-037  
**Files touched:** backend/app/service/procurement_service.py (extend)

**Scope:**
- Service:
  - `get_supplier_balance(supplier_id, as_of_date)` → sum of all unpaid PIs (PI.status != PAID).
  - `get_supplier_ledger(supplier_id, from_date, to_date)` → transaction list [PI created, payment applied, CN created].
  - `allocate_payment(supplier_id, payment_amount, invoices: [{pi_id, amount}])` → manual allocation.
  - FIFO auto-allocation (Week 8, TASK-041).

**Acceptance:**
- [ ] Supplier balance = sum of unpaid PI amounts (after payments).
- [ ] Ledger shows all transactions.
- [ ] Manual allocation updates invoice state.

**Approximate time:** 1.5 hours  
**Notes:**
- Ledger is read-only (mutations happen in payment service).

---

### TASK-031: PO + GRN + PI UI (forms + lists)
**Status:** Deferred — frontend design pending (backend gates TASK-028, TASK-029; also TASK-020 frontend)  
**Blocks:** TASK-038  
**Files touched:** frontend/src/pages/procurement/PurchaseOrder.tsx, frontend/src/pages/procurement/GRN.tsx, frontend/src/pages/procurement/PurchaseInvoice.tsx, frontend/src/api/procurement.ts

**Scope:**
- PO creation form:
  - Select supplier (dropdown from parties).
  - Add line items (item, qty, unit price).
  - Submit → create PO.
  - List POs with status filter.
- GRN form (after PO selected):
  - Show PO lines, enter qty_received + lot_id.
  - Submit → create GRN.
  - List GRNs with status.
- PI form (after GRN selected):
  - Show GRN lines, enter unit_price + tax rates.
  - Submit → create PI.
  - List PIs with status.

**Acceptance:**
- [ ] All forms render.
- [ ] Submits call correct APIs.
- [ ] Lists show data.

**Approximate time:** 3 hours  
**Notes:**
- Use multi-step form (PO → GRN → PI) or separate pages.

---

## Milestone 5 — Week 5: Sales

### TASK-032: Sales Order model + service
**Status:** Ready (was: Blocked by TASK-021 UI — re-pointed at TASK-011 Item CRUD service, which is Done)  
**Blocks:** TASK-039  
**Files touched:** backend/app/models/sales.py (new), backend/app/service/sales_service.py (new)

**Scope:**
- Models:
  - `SalesOrder` (so_id, org_id, firm_id, so_number, so_date, customer_id, status [DRAFT, CONFIRMED, PARTIAL_DC, FULLY_DISPATCHED, INVOICED, CANCELLED], total_amount, audit columns).
  - `SOLine` (so_line_id, so_id, item_id, qty_ordered, uom_id, unit_price, discount_pct, total_price, dc_qty_dispatched, invoice_qty_invoiced, audit columns).
- Service:
  - `create_so(customer_id, lines: [{item_id, qty, unit_price, discount_pct}])` → creates SO, status DRAFT, assigns so_number, calls reserve_stock.
  - `confirm_so(so_id)` → status CONFIRMED, soft-reserves stock.
  - `cancel_so(so_id)` → status CANCELLED, unreserves stock.

**Acceptance:**
- [ ] Create SO reserves stock (reserved_qty incremented).
- [ ] Confirm SO finalizes reservation.
- [ ] Cancel SO unreserves.

**Approximate time:** 2 hours  
**Notes:**
- SO is optional (can go straight from quote to invoice in some workflows).

---

### TASK-033: Delivery Challan model + service
**Status:** Blocked by TASK-032, TASK-022  
**Blocks:** TASK-040  
**Files touched:** backend/app/models/sales.py (extend), backend/app/service/sales_service.py (extend)

**Scope:**
- Models:
  - `DeliveryChallan` (dc_id, org_id, firm_id, dc_number, dc_date, so_id, customer_id, status [DRAFT, ISSUED, ACKNOWLEDGED, INVOICED, CLOSED], audit columns).
  - `DCLine` (dc_line_id, dc_id, so_line_id, item_id, qty_dispatched, lot_id, audit columns).
- Service:
  - `create_dc(so_id, lines: [{so_line_id, qty_dispatched, lot_id}])` → creates DC, status DRAFT.
  - `issue_dc(dc_id)` → status ISSUED, removes stock from position (calls stock ledger with qty_out, reference_type="DC").

**Acceptance:**
- [ ] Create DC.
- [ ] Issue DC removes stock from position.

**Approximate time:** 1.5 hours  
**Notes:**
- DC is physical dispatch note; stock leaves warehouse on ISSUED, not on Invoice finalization.

---

### TASK-034: Sales Invoice model + state machine service
**Status:** Blocked by TASK-033  
**Blocks:** TASK-041  
**Files touched:** backend/app/models/sales.py (extend), backend/app/service/sales_service.py (extend), backend/app/service/invoice_service.py (new)

**Scope:**
- Models:
  - `SalesInvoice` (si_id, org_id, firm_id, si_number, si_date, customer_id, dc_id, status [DRAFT, CONFIRMED, FINALIZED, POSTED, PARTIALLY_PAID, PAID, OVERDUE, CANCELLED], total_amount, tax_amount_total, audit columns).
  - `SILine` (si_line_id, si_id, item_id, qty_invoiced, uom_id, unit_price, hsn_id, igst_rate, cgst_rate, sgst_rate, line_total, audit columns).
- State machine service (`invoice_service.py`):
  - `create_invoice(...)` → status DRAFT, no document number.
  - `confirm_invoice(si_id)` → status CONFIRMED, soft-reserve remaining qty if any.
  - `finalize_invoice(si_id)` → status FINALIZED, assigns si_number, calls post_invoice.
  - `post_invoice(si_id)` → status POSTED, creates GL voucher entries.
  - `cancel_invoice(si_id)` → status CANCELLED (only from DRAFT/CONFIRMED), reverses GL + stock.

**Acceptance:**
- [ ] Invoice state transitions work per state machine.
- [ ] Finalize assigns document number.
- [ ] Post creates GL entries.
- [ ] Cancel reverses GL + stock.

**Approximate time:** 2.5 hours  
**Notes:**
- See specs/invoice-lifecycle.md for detailed state machine.

---

### TASK-035: Sales Invoice PDF generation (basic template)
**Status:** Blocked by TASK-034  
**Blocks:** TASK-042  
**Files touched:** backend/app/service/invoice_service.py (extend), backend/app/routers/sales.py

**Scope:**
- Install `reportlab` or `weasyprint` for PDF generation.
- Template: invoice header (logo, invoice #, date), customer details, line items (item, qty, price, tax), total + tax breakdown, payment terms.
- Endpoint: `GET /invoices/{id}/pdf` → generates PDF on-the-fly, returns as attachment.

**Acceptance:**
- [ ] PDF generates without error.
- [ ] Contains invoice data.
- [ ] Downloads with correct filename.

**Approximate time:** 1.5 hours  
**Notes:**
- For MVP, basic template is fine (Moiz can customize later).

---

### TASK-036: GST calc service (place-of-supply logic)
**Status:** Blocked by TASK-034, TASK-004  
**Blocks:** TASK-043  
**Files touched:** backend/app/service/gst_service.py (new)

**Scope:**
- Service:
  - `calculate_tax(firm_id, customer_id, item_id, qty, unit_price)` → returns igst_rate, cgst_rate, sgst_rate, tax_amount based on:
    - Firm's state (from firm.state_code).
    - Customer's state (from party.state_code).
    - Item's HSN (from hsn.gst_rate_pct).
    - Rule: if firm.state == customer.state → CGST + SGST; else → IGST; if export → 0%.
  - `get_place_of_supply_rules()` → reference data (30 scenarios from specs/place-of-supply-tests.md).
- For MVP, simplified: no composite GSTIN, no RCM subtlety. Just intra-state vs inter-state.

**Acceptance:**
- [ ] CGST + SGST for intra-state (e.g., Guj firm → Guj customer).
- [ ] IGST for inter-state.
- [ ] Rates match HSN.

**Approximate time:** 1.5 hours  
**Notes:**
- Full 30-scenario test suite in W7 (TASK-043).

---

### TASK-037: Customer Ledger service
**Status:** Blocked by TASK-034, TASK-030  
**Blocks:** (none; mirrors supplier ledger)  
**Files touched:** backend/app/service/sales_service.py (extend)

**Scope:**
- Service (mirrors procurement_service):
  - `get_customer_balance(customer_id, as_of_date)`.
  - `get_customer_ledger(customer_id, from_date, to_date)`.

**Acceptance:**
- [ ] Customer balance = sum of unpaid SIs.

**Approximate time:** 0.5 hours  
**Notes:**
- Duplicate of supplier ledger; refactor into generic ledger service later.

---

### TASK-038: Sales Order + DC + Invoice UI (forms + lists)
**Status:** Deferred — frontend design pending (backend gates TASK-033, TASK-034)  
**Blocks:** TASK-044  
**Files touched:** frontend/src/pages/sales/*.tsx, frontend/src/api/sales.ts

**Scope:**
- Similar to procurement (TASK-031):
  - SO form → DC form → Invoice form.
  - List views with status filters.

**Acceptance:**
- [ ] Forms render and submit.
- [ ] Lists show data.

**Approximate time:** 3 hours  
**Notes:**
- Can be simplified: skip SO/DC for MVP, go straight invoice (Moiz decides).

---

### TASK-039: Non-GST Sales Invoice variant
**Status:** Blocked by TASK-034, TASK-036  
**Blocks:** TASK-044  
**Files touched:** backend/app/models/sales.py (extend), backend/app/service/sales_service.py (extend)

**Scope:**
- For non-GST firms, invoice variant "Bill of Supply" or "Cash Memo" (no tax lines, no IGST/CGST/SGST).
- Model field: `invoice_type` [INVOICE, BILL_OF_SUPPLY, CASH_MEMO].
- Service: `calculate_tax()` returns 0 for non-GST firm.
- UI: dropdown to select invoice type on create.

**Acceptance:**
- [ ] Non-GST invoice has no tax lines.
- [ ] UI lets user pick invoice type.

**Approximate time:** 1 hour  
**Notes:**
- Firm.has_gst flag determines default; user can override per invoice.

---

## Milestone 6 — Week 6: Accounting Engine

### TASK-040: Chart of Accounts seeding + COA model
**Status:** Blocked by TASK-015  
**Blocks:** TASK-045, TASK-046  
**Files touched:** backend/app/models/accounting.py (new), backend/app/seeds.py (extend)

**Scope:**
- Model:
  - `ChartOfAccounts` (coa_id, org_id, code [e.g., "1000"], name, account_type [ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE], parent_coa_id [for hierarchy], is_balance_sheet_account bool, audit columns).
- Seed with standard Indian COA:
  - Assets: 1000-1999 (current, fixed).
  - Liabilities: 2000-2999.
  - Equity: 3000-3999.
  - Revenue: 4000-4999.
  - Expense: 5000-5999.
  - Samples: 1010 Cash, 1020 Bank, 1100 Inventory, 2010 AP, 3010 Capital, 4010 Sales, 5010 COGS.

**Acceptance:**
- [ ] COA seeded on org creation.
- [ ] Accounts organized by type.

**Approximate time:** 1 hour  
**Notes:**
- COA is per-org, can be customized post-launch.

---

### TASK-041: Voucher model + auto-posting rules
**Status:** Blocked by TASK-040, TASK-029, TASK-034  
**Blocks:** TASK-047, TASK-048  
**Files touched:** backend/app/models/accounting.py (extend), backend/app/service/accounting_service.py (new)

**Scope:**
- Models:
  - `Voucher` (voucher_id, org_id, firm_id, voucher_number, voucher_date, voucher_type [SALES_INVOICE, PURCHASE_INVOICE, PAYMENT, RECEIPT, JOURNAL, CONTRA, DEBIT_NOTE, CREDIT_NOTE, OPENING_BAL], reference_id [si_id, pi_id, payment_id], status [DRAFT, POSTED, RECONCILED, VOIDED], audit columns).
  - `VoucherLine` (line_id, voucher_id, coa_id, debit_amount, credit_amount, description, audit columns).
  - `JournalLine` (journal_line_id, voucher_id, account_id, debit_amount, credit_amount, audit columns) — alias for VoucherLine.
- Service (`accounting_service.py`):
  - `create_voucher(voucher_type, reference_id, ...)` → status DRAFT.
  - `post_voucher(voucher_id)` → status POSTED, freezes amounts (can't edit).
  - Auto-posting rules (hardcoded for MVP, move to config later):
    - Sales Invoice → Debit AR (1200), Credit Sales Revenue (4010).
    - Purchase Invoice → Debit COGS (5010), Credit AP (2010).
    - Receipt → Credit AR (1200), Debit Bank (1020).
    - Payment → Debit AP (2010), Credit Bank (1020).

**Acceptance:**
- [ ] Voucher created on invoice post.
- [ ] GL entries balanced (debit = credit).
- [ ] Account balances reflect vouchers.

**Approximate time:** 2 hours  
**Notes:**
- Auto-posting is the critical glue; get it right.

---

### TASK-042: Journal voucher (manual GL entry) service + router
**Status:** Blocked by TASK-041  
**Blocks:** TASK-049  
**Files touched:** backend/app/service/accounting_service.py (extend), backend/app/routers/accounting.py (new)

**Scope:**
- Service:
  - `create_journal_voucher(journal_date, lines: [{account_id, debit_amount, credit_amount, description}])` → creates Voucher + VoucherLines, validates debit = credit.
  - `post_journal(voucher_id)` → status POSTED.
- Router:
  - `POST /journal-vouchers` → creates.
  - `GET /journal-vouchers` → list.
  - `GET /journal-vouchers/{id}` → detail.

**Acceptance:**
- [ ] Journal creation validates balanced.
- [ ] Post works.

**Approximate time:** 1.5 hours  
**Notes:**
- Journal is for non-standard GL entries (rounding errors, adjustments, etc.).

---

### TASK-043: Trial Balance report service + router
**Status:** Blocked by TASK-041  
**Blocks:** TASK-050  
**Files touched:** backend/app/service/reports_service.py (new), backend/app/routers/reports.py (new)

**Scope:**
- Service:
  - `get_trial_balance(org_id, firm_id, as_of_date)` → query GL, sum debit/credit per account, return sorted list.
  - Validate: sum_debit = sum_credit (should always be true if auto-posting is correct).
- Router:
  - `GET /trial-balance?as_of_date=2025-04-30` → returns JSON list [account_code, account_name, debit, credit].

**Acceptance:**
- [ ] TB queries posted vouchers.
- [ ] Totals debit = credit.
- [ ] All accounts shown (even if 0 balance).

**Approximate time:** 1.5 hours  
**Notes:**
- TB is the foundation for P&L and BS.

---

### TASK-044: Sales Invoice UI wiring + state transition buttons
**Status:** Deferred — frontend design pending (backend gate TASK-034; also TASK-038 frontend)  
**Blocks:** TASK-051  
**Files touched:** frontend/src/pages/sales/InvoiceDetail.tsx, frontend/src/api/sales.ts (extend)

**Scope:**
- Invoice detail page:
  - Show invoice header (number, date, customer, amount), line items, state badge.
  - Action buttons (context-sensitive per state):
    - DRAFT: Edit, Confirm, Delete.
    - CONFIRMED: Edit (limited), Finalize, Unconfirm.
    - FINALIZED: Finalize status, show GL postings, Print PDF, Cancel.
    - PAID: View only.
  - On click: call API (e.g., `PATCH /invoices/{id}/finalize`), refresh state.

**Acceptance:**
- [ ] Buttons appear based on state.
- [ ] Click calls API.
- [ ] State updates in UI.

**Approximate time:** 2 hours  
**Notes:**
- Use Zustand or React Query for optimistic updates.

---

### TASK-045: P&L report service + router
**Status:** Blocked by TASK-043  
**Blocks:** TASK-052  
**Files touched:** backend/app/service/reports_service.py (extend), backend/app/routers/reports.py (extend)

**Scope:**
- Service:
  - `get_profit_loss(org_id, firm_id, from_date, to_date)` → query GL, sum revenue - expense, return P&L structure.
  - Handle opening balance + FY dates.
- Router:
  - `GET /profit-loss?from_date=...&to_date=...` → returns JSON [revenue_line_item, expense_line_item, ...profit].

**Acceptance:**
- [ ] P&L shows revenue, expense, profit/loss.
- [ ] Matches TB closing equity change (approximately).

**Approximate time:** 1.5 hours  
**Notes:**
- For FY, use Firm.fy_start_month (default April) to auto-calculate FY dates.

---

### TASK-046: Balance Sheet report service + router
**Status:** Blocked by TASK-043  
**Blocks:** TASK-052  
**Files touched:** backend/app/service/reports_service.py (extend), backend/app/routers/reports.py (extend)

**Scope:**
- Service:
  - `get_balance_sheet(org_id, firm_id, as_of_date)` → query GL, sum assets/liabilities/equity, return BS structure.
- Router:
  - `GET /balance-sheet?as_of_date=...` → returns JSON [asset_section, liability_section, equity_section].

**Acceptance:**
- [ ] BS shows assets = liabilities + equity.
- [ ] Equity matches TB equity + P&L profit/loss.

**Approximate time:** 1.5 hours  
**Notes:**
- BS is a snapshot at a specific date.

---

## Milestone 7 — Week 7: GST Engine

### TASK-047: Place-of-supply test fixtures (30 scenarios)
**Status:** Blocked by TASK-036, TASK-004  
**Blocks:** TASK-048  
**Files touched:** backend/tests/test_gst_place_of_supply.py, specs/place-of-supply-tests.md (reference)

**Scope:**
- Implement all 30 test scenarios from `specs/place-of-supply-tests.md`:
  - Intra-state (Guj firm → Guj customer) → CGST + SGST.
  - Inter-state (Guj firm → Maha customer) → IGST.
  - Composite GSTIN (supplier) → no GST.
  - Exports → zero-rated.
  - ... (30 scenarios total).
- Use realistic GSTINs (state code-based).
- All tests must pass.

**Acceptance:**
- [ ] All 30 test scenarios pass.
- [ ] Each scenario covers calculate_tax() with real GSTIN data.

**Approximate time:** 2 hours  
**Notes:**
- Use pytest parameterization for cleaner test code.
- Generate GSTINs with matching state codes (e.g., 27AXXXX for state code 27).

---

### TASK-048: Tax invoice + GSTR-1 prep service
**Status:** Blocked by TASK-047, TASK-034  
**Blocks:** TASK-053  
**Files touched:** backend/app/service/gst_service.py (extend), backend/app/service/sales_service.py (extend)

**Scope:**
- Service:
  - `generate_tax_invoice(si_id)` → JSON structure with invoice data + HSN, taxable value, IGST, CGST, SGST per line + total.
  - `prepare_gstr1(org_id, firm_id, from_date, to_date)` → JSON export of all posted invoices (for manual GSTR-1 filing). Format matches GST portal schema.
- Tests: verify tax line items, totals.

**Acceptance:**
- [ ] Tax invoice JSON correct.
- [ ] GSTR-1 export valid JSON.

**Approximate time:** 1.5 hours  
**Notes:**
- GSTR-1 filing (portal upload) is manual for MVP (Phase 2).

---

### TASK-049: Credit Note (sales return) service + state machine
**Status:** Blocked by TASK-034, TASK-048  
**Blocks:** TASK-054  
**Files touched:** backend/app/models/sales.py (extend), backend/app/service/sales_service.py (extend)

**Scope:**
- Model:
  - `CreditNote` (cn_id, org_id, firm_id, cn_number, cn_date, original_invoice_id, customer_id, reason, status [DRAFT, FINALIZED, POSTED], audit columns).
  - `CNLine` (cn_line_id, cn_id, si_line_id, item_id, qty_returned, unit_price, tax_amount, audit columns).
- Service:
  - `create_credit_note(si_id, lines: [{si_line_id, qty_returned}])` → creates CN, status DRAFT.
  - `finalize_credit_note(cn_id)` → status FINALIZED, assigns cn_number.
  - `post_credit_note(cn_id)` → status POSTED, posts negative GL (reverses original SI posting), adds stock back.
  - CN reverses: revenue, tax, AR balance.

**Acceptance:**
- [ ] Create CN linked to SI.
- [ ] Post CN reverses GL + stock.
- [ ] SI marked as "partially paid" if CN < SI.

**Approximate time:** 2 hours  
**Notes:**
- Full CN workflow: create → finalize → post → customer receives adjustment note.

---

### TASK-050: RCM flag + compliance (purchase invoice, non-GST supplier)
**Status:** Blocked by TASK-029, TASK-048  
**Blocks:** (none; compliance feature, low-blocking)  
**Files touched:** backend/app/models/procurement.py (extend), backend/app/routers/procurement.py (extend)

**Scope:**
- Model: add `rcm_applicable bool` flag to PurchaseInvoice.
- Service: validate RCM rule (certain supplier types/HSNs trigger RCM).
- Router: show RCM checkbox on PI entry; if checked, GL posting reverses (buyer pays tax on behalf of supplier).

**Acceptance:**
- [ ] RCM flag saveable on PI.
- [ ] GL posting reflects RCM (if any).

**Approximate time:** 1 hour  
**Notes:**
- RCM is complex; for MVP, just flag + warn. Don't auto-block.

---

## Milestone 8 — Week 8: Receipts + Payments + Allocation

### TASK-051: Payment voucher service + allocation
**Status:** Blocked by TASK-041, TASK-030  
**Blocks:** TASK-055, TASK-056  
**Files touched:** backend/app/models/accounting.py (extend), backend/app/service/accounting_service.py (extend)

**Scope:**
- Models:
  - `Payment` (payment_id, org_id, firm_id, payment_date, supplier_id, payment_mode [CASH, CHEQUE, BANK_TRANSFER, UPI], amount, reference_number, audit columns).
  - `PaymentAllocation` (allocation_id, payment_id, pi_id, allocated_amount, audit columns).
- Service:
  - `create_payment(supplier_id, payment_mode, amount, ...)` → creates Payment, status DRAFT.
  - `post_payment(payment_id)` → status POSTED, creates GL voucher (Debit AP, Credit Bank/Cash).
  - `allocate_payment(payment_id, allocations: [{pi_id, amount}])` → creates PaymentAllocations, updates PI state (if fully allocated → PAID).

**Acceptance:**
- [ ] Payment GL posting works.
- [ ] Allocation updates PI state.
- [ ] Supplier balance decreases on allocation.

**Approximate time:** 2 hours  
**Notes:**
- FIFO auto-allocation in TASK-052.

---

### TASK-052: Receipt voucher service + FIFO allocation
**Status:** Blocked by TASK-041, TASK-037, TASK-051  
**Blocks:** TASK-057  
**Files touched:** backend/app/service/accounting_service.py (extend)

**Scope:**
- Models:
  - `Receipt` (receipt_id, org_id, firm_id, receipt_date, customer_id, payment_mode, amount, reference_number, audit columns).
  - `ReceiptAllocation` (allocation_id, receipt_id, si_id, allocated_amount, audit columns).
- Service (mirrors Payment):
  - `create_receipt(customer_id, amount, ...)` → creates Receipt, status DRAFT.
  - `post_receipt(receipt_id)` → status POSTED, creates GL voucher (Debit Bank/Cash, Credit AR).
  - `allocate_receipt(receipt_id, allocations: [{si_id, amount}])` → manual allocation.
  - `auto_allocate_fifo(receipt_id)` → FIFO: allocate to oldest unpaid SI first, move to next if surplus.

**Acceptance:**
- [ ] Receipt GL posting works.
- [ ] Auto-allocation FIFO correct.
- [ ] SI state updates to PAID if fully allocated.

**Approximate time:** 2 hours  
**Notes:**
- FIFO is simplest for MVP; other methods (weighted, highest balance first) later.

---

### TASK-053: Bank account + Cheque register models
**Status:** Ready (TASK-004 Done)  
**Blocks:** TASK-058  
**Files touched:** backend/app/models/accounting.py (extend)

**Scope:**
- Models:
  - `BankAccount` (bank_id, org_id, firm_id, account_name, account_number [encrypted], ifsc_code, bank_name, account_type [SAVINGS, CURRENT], current_balance, audit columns).
  - `Cheque` (cheque_id, org_id, firm_id, cheque_number, bank_id, payment_id, issue_date, clear_date, status [ISSUED, CLEARED, BOUNCED, POST_DATED, STOPPED, CANCELLED], audit columns).
- Service:
  - `create_bank_account(...)`.
  - `issue_cheque(bank_id, payment_id, cheque_number, amount, ...)` → creates Cheque, status ISSUED.
  - `clear_cheque(cheque_id)` → status CLEARED, updates payment as confirmed.

**Acceptance:**
- [ ] Bank account created.
- [ ] Cheque linked to payment.

**Approximate time:** 1 hour  
**Notes:**
- Bank reconciliation (manual) comes later.

---

### TASK-054: Expense voucher (miscellaneous expense) service
**Status:** Blocked by TASK-041  
**Blocks:** (none; nice-to-have for W8)  
**Files touched:** backend/app/models/accounting.py (extend), backend/app/service/accounting_service.py (extend)

**Scope:**
- Service:
  - `create_expense(expense_date, account_id, amount, description, reference)` → creates Voucher, posts directly (Debit Expense, Credit Cash/Bank).

**Acceptance:**
- [ ] Expense voucher created + posted.
- [ ] GL reflects expense.

**Approximate time:** 1 hour  
**Notes:**
- Expense is simplified; no detailed breakdowns for MVP.

---

### TASK-055: Payment + Receipt UI (forms + lists)
**Status:** Deferred — frontend design pending (backend gates TASK-051, TASK-052; also TASK-020 frontend)  
**Blocks:** TASK-059  
**Files touched:** frontend/src/pages/accounting/Payment.tsx, frontend/src/pages/accounting/Receipt.tsx, frontend/src/api/accounting.ts

**Scope:**
- Payment form:
  - Select supplier, payment mode (dropdown), amount, cheque # (if applicable).
  - Show unpaid invoices list; allow manual allocation or auto-FIFO.
  - Submit → create Payment + Allocations.
- Receipt form (similar):
  - Select customer, mode, amount.
  - Show unpaid invoices; manual or auto-FIFO allocation.
- Lists: show payment/receipt history, status.

**Acceptance:**
- [ ] Forms render.
- [ ] Submit works.
- [ ] Allocations shown.

**Approximate time:** 2 hours  
**Notes:**
- Allocation UI is the tricky part; consider a side-by-side table of invoices.

---

### TASK-056: Bank reconciliation (manual CSV upload)
**Status:** Blocked by TASK-053  
**Blocks:** (none; Phase 2 candidate)  
**Files touched:** backend/app/service/accounting_service.py (extend), backend/app/routers/accounting.py (extend)

**Scope:**
- Service:
  - `reconcile_bank(bank_id, statement_csv)` → parse CSV (date, amount, description), match to cheques/vouchers, flag unmatched.
- Router:
  - `POST /bank-reconciliation` → upload CSV, returns reconciliation summary.

**Acceptance:**
- [ ] CSV parsed.
- [ ] Matches found.

**Approximate time:** 1.5 hours  
**Notes:**
- Manual for MVP (user matches); auto-match later.

---

## Milestone 9 — Week 9: Reports

### TASK-057: Ledger detail report (account history, running balance)
**Status:** Blocked by TASK-043  
**Blocks:** TASK-060  
**Files touched:** backend/app/service/reports_service.py (extend), backend/app/routers/reports.py (extend)

**Scope:**
- Service:
  - `get_ledger(org_id, firm_id, account_id, from_date, to_date)` → query GL voucher lines, compute running balance, return list [date, description, reference, debit, credit, balance].
- Router:
  - `GET /ledger?account_id=...&from_date=...&to_date=...` → returns JSON.

**Acceptance:**
- [ ] Ledger shows all transactions for account.
- [ ] Running balance correct.

**Approximate time:** 1 hour  
**Notes:**
- Ledger is critical for audit; accuracy essential.

---

### TASK-058: Ageing report (AR/AP by bucket: 0-30, 30-60, 60-90, 90+)
**Status:** Blocked by TASK-051, TASK-052  
**Blocks:** TASK-060  
**Files touched:** backend/app/service/reports_service.py (extend), backend/app/routers/reports.py (extend)

**Scope:**
- Service:
  - `get_ageing(org_id, firm_id, as_of_date, type [AR, AP])` → for each unpaid invoice, calculate days overdue, bucket into age ranges, return grouped summary [bucket, count, amount].
- Router:
  - `GET /ageing?type=AR&as_of_date=...` → returns JSON.

**Acceptance:**
- [ ] Ageing buckets invoices correctly.
- [ ] Totals match AR/AP balance.

**Approximate time:** 1.5 hours  
**Notes:**
- Ageing is used to chase overdue payments.

---

### TASK-059: Stock summary report (qty, value @ avg cost)
**Status:** Blocked by TASK-022  
**Blocks:** TASK-060  
**Files touched:** backend/app/service/reports_service.py (extend), backend/app/routers/reports.py (extend)

**Scope:**
- Service:
  - `get_stock_summary(org_id, firm_id, as_of_date)` → query StockPosition, return [item_code, item_name, qty, avg_cost, total_value].
- Router:
  - `GET /stock-summary?as_of_date=...` → returns JSON.

**Acceptance:**
- [ ] Stock summary shows all items.
- [ ] Total stock value matches balance sheet inventory asset (approximately).

**Approximate time:** 1 hour  
**Notes:**
- Stock value is critical for BS.

---

### TASK-060: Party statement report (customer/supplier ledger, balance)
**Status:** Blocked by TASK-037, TASK-030, TASK-057  
**Blocks:** (none; reportware complete)  
**Files touched:** backend/app/service/reports_service.py (extend), backend/app/routers/reports.py (extend)

**Scope:**
- Service:
  - `get_party_statement(org_id, firm_id, party_id, from_date, to_date)` → return [date, invoice#, description, debit, credit, balance] for party.
- Router:
  - `GET /party-statement?party_id=...&from_date=...&to_date=...` → returns JSON.

**Acceptance:**
- [ ] Statement shows all transactions for party.
- [ ] Balance matches party ledger balance.

**Approximate time:** 1 hour  
**Notes:**
- Party statement is sent to customers/suppliers.

---

## Milestone 10 — Week 10: Data Migration

### TASK-061a: MigrationAdapter protocol + normalized intermediate format
**Status:** Blocked by TASK-011, TASK-040 (was: TASK-021 UI — re-pointed at TASK-011 Item CRUD service, which is Done; TASK-040 COA still pending)
**Blocks:** TASK-061b, TASK-061c, TASK-061d, TASK-062
**Files touched:** `backend/app/service/migration/__init__.py`, `backend/app/service/migration/adapter.py`, `backend/app/service/migration/intermediate.py`

**Scope:**
- Define `MigrationAdapter` Protocol (Python `typing.Protocol`) with methods:
  - `detect(file_bytes: bytes) -> bool` — return True if this adapter can handle the file.
  - `parse(file_bytes: bytes, passphrase: Optional[str]) -> NormalizedImport` — produce intermediate format.
  - `name() -> str`.
- Define `NormalizedImport` dataclass (Pydantic model) covering: parties[], items[], uoms[], ledgers[], opening_gl[], opening_stock[], historical_invoices[] (optional), historical_receipts[] (optional), source_metadata.
- Central `MigrationService.import(file_bytes, adapter_hint: Optional[str], passphrase: Optional[str])` that auto-detects or uses hint, returns `NormalizedImport` + list of validation warnings.
- Warning/error structure with row-level anchors so UI can highlight bad rows.

**Acceptance:**
- [ ] Protocol + dataclasses are typed and serialisable.
- [ ] Unit test: feeding unknown bytes → "no adapter matches" error, not crash.

**Approximate time:** 2 hours
**Notes:** Make it genuinely pluggable — new adapters add a file, no core changes. This is why all three formats share one service module.

---

### TASK-061b: Vyapar `.vyp` backup adapter (PRIMARY — Moiz's current system)
**Status:** Blocked by TASK-061a
**Blocks:** TASK-062
**Files touched:** `backend/app/service/migration/vyapar_adapter.py`, `backend/tests/service/migration/test_vyapar_adapter.py`, `backend/tests/fixtures/vyapar_sample.vyp`

**Scope:**
- `.vyp` is Vyapar's proprietary backup format: encrypted SQLite database with known key derivation (reverse-engineered in public tooling; confirm with current Vyapar version before starting).
- If encrypted, prompt for passphrase; fail cleanly if wrong.
- Extract:
  - Parties (name, phone, GSTIN, state, addresses, opening balance).
  - Items (name, category, primary UOM, HSN, tax rate, opening stock qty + value).
  - Ledgers (party-specific ledgers, bank accounts, cash, COA if custom).
  - Opening GL balances.
  - Historical invoices (last 12 months — optional; user can skip to keep import lean).
- Map Vyapar's concepts to ours: Vyapar "Party" → our `party` (infer supplier/customer from transaction direction); Vyapar "Item" → our `item` + one `sku` (no variants in Vyapar); Vyapar "Sale/Purchase" → our `sales_invoice`/`purchase_invoice` (simplified; drop line-level discount tiers if not present).
- Handle the tricky bits: Vyapar stores amounts in paise or rupees depending on version — detect and normalize to `Decimal` rupees. Vyapar lot-tracking is item-level; create one synthetic "Opening" lot per item per §17.2.1 of architecture.

**Acceptance:**
- [ ] Parser extracts Moiz's real `.vyp` file without crashing.
- [ ] Unit test fixture with a sanitized sample `.vyp` produces expected `NormalizedImport`.
- [ ] Row-count diff report: "Imported 142 parties, 287 items, 14 ledgers, 3,411 invoices".

**Approximate time:** 6 hours (the longest single task in the MVP — partially because Vyapar's format is mildly hostile and partially because this blocks dogfood)
**Notes:**
- Research the Vyapar `.vyp` format against Moiz's actual backup before writing the parser. Spike in W4 (task is in W10, but 30-min discovery spike no later than W4 de-risks the whole week).
- Use SQLCipher (or the Python `pysqlcipher3` binding) if encryption is present.
- If Vyapar changes format mid-project, fall back to their Excel export + TASK-061c.

---

### TASK-061c: Excel template importer (fallback + for non-Vyapar customers)
**Status:** Blocked by TASK-061a
**Blocks:** TASK-062
**Files touched:** `backend/app/service/migration/excel_adapter.py`, `backend/tests/fixtures/migration_template.xlsx`, `frontend/public/templates/migration-template.xlsx`

**Scope:**
- Define a multi-sheet Excel template: `Parties`, `Items`, `OpeningStock`, `OpeningLedger`, `BankBalances`. Column schema per sheet is versioned (embedded in a hidden sheet).
- Parser validates per row, produces `NormalizedImport` with row-level error anchors.
- Template is downloadable from the migration UI with pre-filled examples (so users know what the shape is).
- Uses `openpyxl`.

**Acceptance:**
- [ ] Parser reads the template; produces correct `NormalizedImport` on the sample fixture.
- [ ] Validation catches: missing GSTIN on REGULAR party, negative qty, unknown HSN, out-of-range GST rate, duplicate codes.
- [ ] Template is stored as a static asset the UI links to.

**Approximate time:** 3 hours
**Notes:** Easier than Vyapar because we control the format. This is the fallback when Vyapar parsing fails *and* the onboarding path for customers on plain Excel / Tally Prime exports.

---

### TASK-061d: Tally XML adapter (Phase-1 stub, production-ready Phase-2)
**Status:** Blocked by TASK-061a
**Blocks:** (none in Phase 1)
**Files touched:** `backend/app/service/migration/tally_adapter.py`, `backend/tests/fixtures/tally_sample.xml`

**Scope:**
- Parse Tally's "Export Masters" XML and "Export Vouchers" XML.
- Handle known elements (parties, stock items, ledgers, vouchers); log unknowns without crashing.
- Ship with a small sanitized Tally sample in fixtures (obtainable from any Tally user online; scrub real data).
- Intentionally minimal: covers the 80% of Tally users with default configs. Tally's customization surface is huge — we do NOT try to cover it all pre-emptively.

**Acceptance:**
- [ ] Parser reads the sample fixture and produces expected `NormalizedImport` for masters.
- [ ] Unknown elements logged with XPath, not swallowed.
- [ ] Explicit "Tally support is Phase-2 polish; test coverage limited to documented schemas" banner in the UI.

**Approximate time:** 3 hours
**Notes:**
- Use `xml.etree.ElementTree`.
- Real Tally-user onboarding in Phase 2 will almost certainly surface edge cases; invest there when the customer is real.

---

### TASK-062: Opening balance import + TB reconciler (format-agnostic)
**Status:** Blocked by TASK-061b, TASK-061c, TASK-015
**Blocks:** TASK-063
**Files touched:** `backend/app/service/migration/importer.py`, `backend/app/routers/migration.py` (new)

**Scope:**
- Single `import(normalized: NormalizedImport, mode: DRY_RUN | COMMIT)` that works for any adapter's output.
- DRY_RUN: validate + preview; no DB writes; returns full summary.
- COMMIT: in one transaction — insert parties, items, skus, ledgers, opening vouchers (voucher_type=OPENING_BAL), opening stock positions.
- `reconcile(expected_tb: dict, actual_tb: dict)` → per-account delta; highlights > ₹1 mismatches.
- Router endpoints:
  - `POST /migration/preview` (multipart: file + optional passphrase + optional adapter hint) → `NormalizedImport` JSON + warnings.
  - `POST /migration/commit` with idempotency-key → `{status, summary, reconciliation}`.
  - `GET /migration/reconciliation/{run_id}` → full report.

**Acceptance:**
- [ ] Same commit path works for Vyapar + Excel + Tally-sourced data.
- [ ] DRY_RUN + COMMIT produce identical summaries (apart from `status`).
- [ ] Reconciliation catches a planted ₹5 mismatch in test fixture.

**Approximate time:** 2 hours
**Notes:** All imports post OPENING_BAL vouchers dated the day before the new system's go-live date.

---

### TASK-063: Migration sign-off workflow (Moiz + CA approval)
**Status:** Blocked by TASK-062
**Blocks:** (none; gate to dogfood)
**Files touched:** `frontend/src/pages/onboarding/MigrationSignoff.tsx`, `backend/app/routers/migration.py` (extend)

**Scope:**
- UI: side-by-side TB comparison (Vyapar-sourced TB vs our post-import TB), per-account delta column with color coding.
- "Approve" button disabled unless every account is within ±₹1 OR has a manual reason annotation.
- On approve: set flag `org.data_migration_complete = true`, unlock dogfood screens, log the reconciliation report to audit.
- On reject: allow re-upload (different file, different adapter) or manual entry.
- Export-to-PDF of the reconciliation report (so the CA can sign physically if they want).

**Acceptance:**
- [ ] Approval workflow works end-to-end.
- [ ] Flag set on approval; downstream screens unlock.
- [ ] Exported PDF is readable and includes both TBs.

**Approximate time:** 1.5 hours
**Notes:** Moiz's CA must review the TB before approval — this is the hard gate in the plan. Build the UX around that ritual, not as a dev-testing-only checkbox.

---

## Milestone 11 — Week 11: Dogfood + Bug Fixes

### TASK-064: Dogfood feedback loop (weekly backlog grooming)
**Status:** Blocked by TASK-063  
**Blocks:** (none; ongoing)  
**Files touched:** TASKS.md (this file), docs/implementation-plan.md (weekly updates)

**Scope:**
- Each week (W11, W12):
  - Moiz runs real invoices/payments through system.
  - Documents bugs + friction points.
  - Claude Code reviews feedback, prioritizes (blocker, high, low).
  - Fix blockers same week; defer cosmetics.
  - Update TASKS.md with new tasks or move blockers to Ready.

**Acceptance:**
- [ ] Feedback loop established.
- [ ] Bugs triaged + fixed.

**Approximate time:** Ongoing (not a single task)  
**Notes:**
- This is the core of Week 11; allocate significant time.

---

## Milestone 12 — Week 12: Hardening + Deployment

### TASK-065: Automated daily backups + weekly restore test
**Status:** Ready (TASK-001 Done; can land any wave but kept in W12 batch)  
**Blocks:** (none; gate to production)  
**Files touched:** backend/app/scripts/backup.py, docker-compose.yml (extend), Makefile (extend make backup)

**Scope:**
- Script: `backup.py` → pg_dump Postgres DB, compress, upload to S3 (or B2), log result.
- Cron job: run daily at 2 AM (off-peak).
- Restore test: weekly, restore from 1-week-old backup to test DB, verify table counts match.
- Makefile: `make backup` runs manually; `make restore-test` runs restore.

**Acceptance:**
- [ ] Daily backup completes.
- [ ] Restore succeeds.
- [ ] Backup size < 100 MB (for early dogfood).

**Approximate time:** 1.5 hours  
**Notes:**
- Use pg_dump for simplicity; `pg_basebackup` later if needed.

---

### TASK-066: Uptime monitoring + Sentry integration
**Status:** Ready (TASK-002 Done; Sentry stub in place — flips real DSN)  
**Blocks:** (none; observability)  
**Files touched:** backend/app/config.py (extend), backend/main.py (extend)

**Scope:**
- Sentry SDK integration: `pip install sentry-sdk[flask]` (or FastAPI extension).
- Initialize in `config.py` with DSN from .env.
- Capture errors automatically.
- Add health check endpoint: `GET /health` (always 200, logs request).
- Optional: simple ping from uptime monitor (free tier).

**Acceptance:**
- [ ] Errors sent to Sentry.
- [ ] Health check works.

**Approximate time:** 1 hour  
**Notes:**
- Sentry free tier sufficient for MVP.

---

### TASK-067: Deployment runbook + Moiz training
**Status:** Blocked by TASK-065, TASK-066  
**Blocks:** (none; handoff)  
**Files touched:** docs/DEPLOYMENT.md (new), docs/OPERATIONS.md (new)

**Scope:**
- Write deployment guide:
  - Prerequisites (Docker, SSH key, .env).
  - Build image: `docker build -t fabric-erp:latest .`.
  - Deploy to Hetzner: `make deploy` (or shell script).
  - Verify: check health endpoint, run smoke test.
  - Rollback: (revert to last image, restart).
- Operations runbook:
  - Daily: monitor Sentry, check backups.
  - Weekly: restore test, review logs.
  - Emergency: handle downtime, page Moiz.
- Train Moiz: pair on one deploy + one restore.

**Acceptance:**
- [ ] Docs written clearly.
- [ ] Moiz can run `make deploy` and `make backup` solo.

**Approximate time:** 2 hours  
**Notes:**
- After Week 12, Moiz owns ops; Claude Code is advisory.

---

### TASK-068: Friendly customer trial data import
**Status:** Blocked by TASK-063  
**Blocks:** (none; Phase 2 gate)  
**Files touched:** backend/app/service/migration_service.py (extend)

**Scope:**
- Identify friendly customer (textile shop, karigari, supplier from Moiz's network).
- Import their prior Vyapar / Tally / Excel data using the migration flow (TASK-061a-d + 062-063). Whichever adapter applies — no new code should be needed. If a new edge case surfaces, that's the signal that the adapter needs widening; log and address in the Phase-2 backlog.
- Verify TB matches their records.
- Run 1 week of transactions (invoices, payments).
- Gather feedback: UX, missing features, performance.
- Decide: ready for public launch or more hardening needed.

**Acceptance:**
- [ ] Second firm data imports cleanly.
- [ ] 1 week of live transactions stable.
- [ ] Feedback collected.

**Approximate time:** 3-4 hours (collaborative with second customer)  
**Notes:**
- This is a soft launch; not a full customer onboarding yet.

---

## Post-MVP Backlog (Phases 2+)

### TASK-069: e-Invoice IRN portal integration (Phase 2)
**Status:** Blocked by TASK-034  
**Blocks:** e-invoice feature  
**Files touched:** backend/app/service/gst_service.py (extend)

**Scope:**
- Integrate with GSP (Goods & Service Portal) or e-invoice portal API.
- On invoice finalization, if firm's turnover > ₹1.5cr, auto-submit to portal, get IRN, include in PDF.

---

### TASK-070: e-Way Bill integration (Phase 2)
**Status:** Blocked by TASK-033  
**Blocks:** e-way feature  
**Files touched:** backend/app/service/gst_service.py (extend)

**Scope:**
- Generate e-way bill JSON on DC issue, auto-submit to portal, get EWB #.

---

### TASK-071: WhatsApp invoice delivery (Phase 2)
**Status:** Blocked by TASK-035, TASK-016  
**Blocks:** WhatsApp feature  
**Files touched:** backend/app/service/notifications_service.py (new)

**Scope:**
- Official WhatsApp Business API integration (not Web WhatsApp).
- Send invoice PDF + summary to customer's WhatsApp.

---

### TASK-072: Mobile PWA (offline read-only cache) (Phase 2)
**Status:** Blocked by TASK-003  
**Blocks:** mobile feature  
**Files touched:** frontend/public/service-worker.js (new)

**Scope:**
- Service Worker for offline read-only caching.
- Cache reports, ledgers for offline view.

---

### TASK-073: Manufacturing Orders (MOs) (Phase 3)
**Status:** Blocked by TASK-011  
**Blocks:** manufacturing feature  
**Files touched:** backend/app/models/manufacturing.py (new)

**Scope:**
- Full MO flow (created in Phase-1 DDL, but no API/UI yet).
- Operations, QC, Kanban dashboard.

---

## Summary

**Total tasks:** 68 (Week 1-12) + 5 (Phase 2-3).  
**Week 1:** 5 tasks (bootstrap).  
**Week 2:** 11 tasks (auth, RBAC, masters, UI).  
**Week 3:** 5 tasks (inventory).  
**Week 4:** 5 tasks (procurement).  
**Week 5:** 7 tasks (sales).  
**Week 6:** 6 tasks (accounting).  
**Week 7:** 4 tasks (GST).  
**Week 8:** 7 tasks (payments/receipts).  
**Week 9:** 4 tasks (reports).  
**Week 10:** 3 tasks (migration).  
**Week 11:** 1 task (dogfood, ongoing).  
**Week 12:** 4 tasks (hardening + deployment).  

---

**Version:** 0.1  
**Last updated:** 2026-04-24  
**Owner:** Moiz  
**Next task to start:** TASK-001
