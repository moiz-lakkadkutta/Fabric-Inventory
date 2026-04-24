# CLAUDE.md — Operating Manual for Claude Code

This file is read at the start of every session in this repository. It defines the technical stack, conventions, and decision-making authority so Claude Code can move fast with confidence.

---

## Project Overview

**What:** Cloud ERP for the Indian ladies-suit / fabric textile trade. Solo founder (Moiz) is using Claude Code as his co-engineer to build and dogfood the MVP for his own business first.

**Who for:** Initially Moiz's own firm(s). After Week 12, a friendly customer's trial. Long-term: SaaS for 100s of similar textile shops (suppliers, job workers, retailers).

**Why:** Current tooling (Tally, Vyapar, Excel) doesn't handle non-GST workflows, job work with part-level tracking, or multi-firm accounting cleanly. Building the right thing in the right language (Python + React + Postgres) cuts months off future customization. Dogfooding forces honest product decisions early.

---

## Finalized product decisions (locked; do not re-derive)

These were confirmed by Moiz. Do not change them without his explicit sign-off.

1. **Team:** Solo (Moiz) + Claude Code + AI agents. No human contractors.
2. **First user:** Moiz's own textile business(es). Dogfood first, then friendly customers, then broad SaaS.
3. **Timeline:** 12-week MVP. Ruthlessly cut scope to hit this.
4. **Budget:** Bootstrap — ~₹10–25k/month total. Single Hetzner CX22, self-hosted Postgres, free-tier services. Scale up only when first paying customer lands.
5. **Migration source:** **Vyapar `.vyp` is the primary adapter** (that's what Moiz runs on today). Tally XML + Excel template adapters ship alongside in the same `MigrationAdapter` protocol so future non-Vyapar customers onboard without new code. TB reconciliation target: ±₹1 against Vyapar.
6. **GST compliance strategy:** Moiz is currently below the ₹5 Cr e-invoice threshold. **We build the full GST machinery in Phase 1** — place-of-supply engine, correct IGST vs CGST+SGST calc, GST-compliant PDF invoices, GSTR-1 data prep, IRN JSON payload — but hold back the actual NIC/GSP API call behind `feature_flag.key = 'gst.einvoice.enabled'` (default FALSE per firm). When a firm crosses ₹5 Cr turnover or a paying customer already above that threshold arrives, flipping the flag + subscribing to a GSP (Cygnet / Masters India / IRIS) is a 1-week drop-in, not a 2-month refactor. Same pattern for e-way bill (`gst.eway.enabled` flag).
7. **Non-GST is first-class.** Bill of Supply, Cash Memo, Estimate are native document types — no "GST-off" hack.
8. **Manufacturing (MO + routing + QC) is Phase 3.** Schema is in place in Phase 1 (tables exist, feature-flagged off). APIs + UI ship in Phase 3.
9. **Mobile / offline / WhatsApp automation** are Phase 4+. Until then, manual Web WhatsApp works fine.

---

## Tech Stack (Pinned Versions)

**Backend:**
- Python 3.12+
- FastAPI 0.115+ (async, OpenAPI-native)
- SQLAlchemy 2.0+ (ORM + Core for migrations)
- Alembic (schema versioning)
- Pydantic 2.0+ (request/response validation)
- pytest 8.0+ (unit & integration tests)
- pytest-asyncio (async test support)
- python-dotenv (secrets management)

**Frontend:**
- Node 20+ (LTS)
- React 18.3+
- TypeScript 5.3+
- Vite 5.0+ (dev server & build)
- Tailwind CSS 3.4+ (via CDN for prototyping, npm for built)
- shadcn/ui (component library)
- React Hook Form 7.50+ (form state)
- TanStack Query 5.0+ (server state)
- Vitest (unit tests)
- Playwright 1.40+ (E2E tests)

**Infrastructure & Database:**
- PostgreSQL 16 (multi-tenant, RLS-enabled, pgcrypto + uuid extensions)
- Docker (dev environment + production image)
- Docker Compose (local stack: Postgres + FastAPI + Vite dev server + Redis)
- Redis (Celery broker, cache, rate-limit — future Celery workers for e-invoice, WhatsApp, etc.)
- Hetzner CX22 (single box: ~₹800/month for prod)
- GitHub Actions (CI: test + lint on every push)
- S3-compatible backup (B2 or Hetzner Object Storage)

**Security:**
- JWT (OAuth2 password grant + refresh)
- MFA (TOTP, optional for users; mandatory for Admin)
- TLS 1.3 everywhere
- Postgres RLS (row-level security enforces org_id on every query)
- Field-level encryption (PII: GSTIN, PAN, bank accounts — AES-256-GCM per org)
- Sentry (error tracking, free tier)

---

## Repository Structure (Once Code Exists)

```
fabric-erp/
├── README.md                          # This file
├── CLAUDE.md                          # (This file)
├── TASKS.md                           # Task backlog for Claude Code
│
├── docs/
│   ├── architecture.md                # System design & principles
│   ├── implementation-plan.md         # 12-week MVP plan
│   └── review.md                      # Known issues & fixes
│
├── backend/
│   ├── pyproject.toml                 # Python deps + tool config (ruff, pytest)
│   ├── Makefile                       # make dev, make test, make migrate, etc.
│   ├── .env.example                   # Template for .env (never commit .env)
│   ├── main.py                        # FastAPI app entry point
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py                  # Settings (DB URL, JWT secret, etc.)
│   │   ├── models/                    # SQLAlchemy ORM models (auto-generated from DDL)
│   │   │   ├── __init__.py
│   │   │   ├── identity.py            # Organization, Firm, User, Role
│   │   │   ├── masters.py             # Party, Item, SKU, UOM, HSN
│   │   │   ├── procurement.py         # PO, GRN, PI, PILine
│   │   │   ├── inventory.py           # Stock, Lot, Ledger, Adjustment
│   │   │   ├── sales.py               # Sales Invoice, SILine, Delivery Challan
│   │   │   ├── accounting.py          # Voucher, VoucherLine, JournalLine, ChequeClear
│   │   │   └── audit.py               # AuditLog (append-only per org)
│   │   ├── schemas/                   # Pydantic models (request/response)
│   │   │   ├── __init__.py
│   │   │   ├── identity.py
│   │   │   ├── masters.py
│   │   │   ├── ... (mirror of models/)
│   │   │   └── common.py              # Pagination, ErrorResponse, etc.
│   │   ├── service/                   # Business logic (no HTTP layer)
│   │   │   ├── __init__.py
│   │   │   ├── identity_service.py    # User, org, role, permission checks
│   │   │   ├── invoice_service.py     # Invoice state machine, postings, PDFs
│   │   │   ├── inventory_service.py   # Stock, lots, adjustments
│   │   │   ├── gst_service.py         # Place-of-supply, tax calc, GSTR prep
│   │   │   └── ... (one per domain)
│   │   ├── routers/                   # FastAPI routers (request -> service -> response)
│   │   │   ├── __init__.py
│   │   │   ├── auth.py                # POST /auth/login, /auth/refresh, /auth/mfa-verify
│   │   │   ├── masters.py             # CRUD on parties, items, etc.
│   │   │   ├── procurement.py         # PO, GRN, PI endpoints
│   │   │   ├── inventory.py
│   │   │   ├── sales.py               # Invoice create/finalize/cancel endpoints
│   │   │   ├── accounting.py          # Voucher, reports, TB endpoints
│   │   │   └── ... (one per domain)
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py                # JWT decode, org_id extraction
│   │   │   ├── rls.py                 # SET app.current_org_id before query
│   │   │   ├── audit.py               # Log mutations (except reads)
│   │   │   └── errors.py              # Global error handler
│   │   ├── db.py                      # SQLAlchemy engine, session maker
│   │   ├── dependencies.py            # FastAPI Depends() helpers (get_current_user, etc.)
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── crypto.py              # Field encryption (envelope model)
│   │       ├── pagination.py          # Cursor-based pagination
│   │       ├── timestamp.py           # TZ helpers (UTC storage, Asia/Kolkata display)
│   │       └── idempotency.py         # Idempotency-Key parsing & dedup
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/                  # Migration files (auto-generated from schema/)
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py                # pytest fixtures (test DB, auth token, etc.)
│   │   ├── test_auth.py               # Unit tests for auth service
│   │   ├── test_invoice_service.py    # Integration tests (real DB, RLS, transactions)
│   │   ├── test_rls.py                # Cross-org RLS isolation tests
│   │   ├── test_gst_*_rules.py        # GST place-of-supply logic (use fixtures from specs/)
│   │   └── ... (one test file per service module)
│   └── schema/
│       ├── ddl.sql                    # Base schema (never edit; use Alembic for changes)
│       └── patches/                   # SQL patches (from review.md fixes)
│
├── frontend/
│   ├── package.json                   # Node deps + scripts (dev, build, test, lint)
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── .env.example
│   ├── index.html
│   ├── public/                        # Assets, icons, logos
│   └── src/
│       ├── main.tsx                   # React entry point
│       ├── App.tsx                    # Root router + layout
│       ├── api/                       # Fetch wrappers (POST /v1/invoices, etc.)
│       │   ├── client.ts              # Axios instance with JWT + tenant headers
│       │   ├── auth.ts                # /auth/* endpoints
│       │   ├── masters.ts             # Party, Item endpoints
│       │   ├── sales.ts               # Invoice endpoints
│       │   ├── accounting.ts          # Reports, TB, P&L endpoints
│       │   └── ... (one per domain)
│       ├── components/                # Reusable React components
│       │   ├── ui/                    # shadcn/ui (buttons, forms, modals, etc.)
│       │   ├── layout/                # Header, Sidebar, ErrorBoundary
│       │   ├── forms/                 # InvoiceForm, PartyForm, etc.
│       │   ├── tables/                # DataTable, InvoiceLineTable, etc.
│       │   ├── icons/                 # App-specific SVG icons
│       │   └── dialogs/               # Confirmation, error, print dialogs
│       ├── pages/                     # Page components (one per route)
│       │   ├── auth/                  # Login, MFA, Invite
│       │   ├── dashboard/
│       │   ├── sales/                 # InvoiceList, InvoiceDetail, InvoiceCreate
│       │   ├── purchase/
│       │   ├── inventory/
│       │   ├── accounting/            # Reports, TB, COA, Vouchers
│       │   ├── masters/               # Party, Item, SKU screens
│       │   └── admin/                 # Firm, User, Role management
│       ├── hooks/                     # Custom React hooks
│       │   ├── useAuth.ts             # Auth state + login/logout
│       │   ├── useQuery.ts            # Wrapper around TanStack Query
│       │   ├── useForm.ts             # Wrapper around React Hook Form
│       │   └── ... (domain-specific)
│       ├── store/                     # Global state (Zustand or Redux)
│       │   ├── authStore.ts           # User, org, firm, permissions
│       │   ├── uiStore.ts             # Modals, notifications, theme
│       │   └── ... (minimal)
│       ├── utils/
│       │   ├── api.ts                 # Error handling, retry logic
│       │   ├── format.ts              # Currency, date formatting (Asia/Kolkata)
│       │   ├── validation.ts          # Client-side form validation
│       │   └── ...
│       ├── styles/                    # Global CSS (Tailwind overrides)
│       │   └── globals.css
│       └── types/
│           ├── api.ts                 # Autogen from OpenAPI spec
│           └── domain.ts              # Custom types (not from API)
│       ├── __tests__/
│           ├── unit/                  # Component unit tests (Vitest)
│           └── e2e/                   # Playwright E2E tests
│
├── schema/
│   ├── ddl.sql                        # Base schema (from /backend/schema/ddl.sql)
│   └── patches/                       # Fixes from review.md
│
├── specs/
│   ├── api-phase1.yaml                # OpenAPI 3.1 spec
│   ├── screens-phase1.md              # 42-screen inventory
│   ├── invoice-lifecycle.md           # State machine, workflows
│   ├── place-of-supply-tests.md       # GST validation fixtures
│   └── ... (other detailed specs)
│
├── docker-compose.yml                 # Services: postgres, redis, api (dev), web (dev)
├── Dockerfile                         # Multi-stage: backend + frontend
├── .dockerignore
├── .gitignore                         # Never commit: .env, node_modules, *.pyc, __pycache__, .venv
├── .github/
│   └── workflows/
│       ├── ci.yml                     # On push: pytest, vitest, ruff, mypy
│       └── deploy.yml                 # On tag: build image, push to registry, deploy
│
├── docker-compose.yml
├── Makefile
└── (This file: CLAUDE.md)
```

---

## Coding Conventions

### Naming

| Context | Convention | Example |
|---------|-----------|---------|
| Python vars, functions, modules | `snake_case` | `invoice_id`, `calculate_gst_amount()`, `gst_service.py` |
| Python classes | `PascalCase` | `SalesInvoice`, `GSTCalculator` |
| JavaScript/TypeScript vars, functions | `camelCase` | `invoiceId`, `calculateGstAmount()`, `useInvoiceQuery()` |
| React components | `PascalCase` | `<InvoiceForm />`, `<InvoiceLineTable />` |
| Database tables | `snake_case`, plural for transactional, singular for masters | `sales_invoice`, `party` |
| Database columns | `snake_case` | `created_at`, `paid_amount` |
| Enum values | `UPPER_SNAKE_CASE` | `DRAFT`, `CONFIRMED`, `FINALIZED` |

### File & Module Organization

- **One aggregate per module.** If a file grows beyond ~400 lines, split it (e.g., `invoice_service.py` → `invoice_service.py` + `invoice_posting_service.py`).
- **Service layer owns business logic.** Routers are thin: parse request → call service → return response.
- **Models (SQLAlchemy) are dumb.** They define schema only; all logic is in services.
- **Schemas (Pydantic) are strict.** Request schemas validate input; response schemas enforce API contracts.

### Money

- **Always `NUMERIC(18,2)` in Postgres.** Never float.
- **Python: use `Decimal` from `decimal` module.** Never float.
- **JavaScript: store as integers (paise, not rupees) in memory, display with formatting.** Or use a money library like `dinero.js`.
- **Example:
  ```python
  # Python
  from decimal import Decimal
  amount = Decimal('1000.50')  # ₹1000.50
  
  # JavaScript
  const amount = 100050;  // 100050 paise = ₹1000.50
  display: (amount / 100).toFixed(2)  // "1000.50"
  ```

### Timestamps

- **Storage:** Always `TIMESTAMPTZ` in Postgres, stored in UTC.
- **Python:** Use `datetime.datetime.now(tz=pytz.UTC)` or `datetime.datetime.now(tz=timezone.utc)`.
- **JavaScript:** Store as ISO 8601 strings or Unix timestamps; format for display using `toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })`.
- **UI display:** Always "Asia/Kolkata" timezone (per architecture principle).

### Idempotency

- **Every mutating endpoint** (POST, PATCH, DELETE) MUST support the `Idempotency-Key` header.
- **Format:** UUID v4, client-generated.
- **Implementation:** Before state change, hash the key; if the hash is in Redis, return the cached response (same status, body). Otherwise, execute, cache the response for 24h, return.
- **Note:** This is critical for offline Android sync (see architecture §17.8.2).

### State Machines

- **Every stateful entity has an explicit state column** (e.g., `sales_invoice.lifecycle_status`).
- **State changes are events, not generic UPDATEs.** Service methods like `finalize_invoice()` change state, not `update_invoice(lifecycle_status='FINALIZED')`.
- **Invalid transitions are errors.** E.g., can't move from PAID to DRAFT.

### Error Handling

- **Custom exceptions in `app/exceptions.py`:**
  ```python
  class InvoiceStateError(Exception):
      pass
  
  class InsufficientStockError(Exception):
      pass
  ```
- **Router catches exceptions and returns appropriate HTTP status:**
  ```python
  @app.post("/invoices/{id}/finalize")
  async def finalize_invoice(id: UUID, ...):
      try:
          result = await invoice_service.finalize(id)
          return result
      except InvoiceStateError as e:
          raise HTTPException(status_code=400, detail=str(e))
      except PermissionError as e:
          raise HTTPException(status_code=403, detail="Permission denied")
  ```

### Testing

- **Unit tests** cover service logic in isolation (mocked DB).
- **Integration tests** cover full flow with a test DB (RLS enabled, transactions rolled back after each test).
- **E2E tests** cover critical user journeys (Playwright): login → create invoice → finalize → check PDF.
- **RLS isolation tests** verify a user in Org A cannot read Org B's data.
- **Test database is real Postgres** (not SQLite) so RLS and transactions behave like prod.

**Example:**
```python
# tests/test_invoice_service.py
@pytest.mark.asyncio
async def test_finalize_invoice_posts_to_ledger(session_with_org_a):
    """Invoice finalize should post GL lines and change state."""
    # Arrange
    invoice = await invoice_service.create(
        org_id=session_with_org_a.org_id,
        firm_id=...,
        party_id=...,
        amount=Decimal('1000.00'),
        ...
    )
    
    # Act
    finalized = await invoice_service.finalize(invoice_id=invoice.id)
    
    # Assert
    assert finalized.lifecycle_status == InvoiceLifecycleStatus.FINALIZED
    gl_lines = session.execute(
        select(JournalLine).where(JournalLine.ref_invoice_id == invoice.id)
    ).scalars().all()
    assert len(gl_lines) == 2  # Debit AR, Credit Revenue
    assert sum(jl.amount for jl in gl_lines) == Decimal('0')  # Balanced
```

### Authentication & RLS

- **Every endpoint receives `current_user: User` from middleware.**
- **Every service method receives `org_id: UUID` and `firm_id: UUID` explicitly.** Never infer from user.
- **RLS is enforced automatically on queries:**
  ```python
  # In middleware, before each request:
  session.execute("SET LOCAL app.current_org_id = %s", (user.org_id,))
  ```
- **No hard-coded org_id overrides.** If a service method needs to bypass RLS, it's a bug.

### Permissions

- **Never use role names in code.** Always use fine-grained permission checks.
- **Example:**
  ```python
  # Wrong:
  if user.role.name == "Accountant":
      return True
  
  # Right:
  if user.has_permission('accounting.voucher.post'):
      return True
  ```

### Soft Delete

- **All transactional tables have `deleted_at TIMESTAMPTZ DEFAULT NULL`.**
- **Logical deletes set `deleted_at = NOW()`.** Never hard-delete except in cleanup jobs.
- **Queries automatically filter `deleted_at IS NULL`** (add to RLS policy or service layer, not every query).

### Audit

- **Every mutation writes to `audit_log` table:**
  ```python
  audit_log_service.log(
      org_id=org_id,
      user_id=current_user.id,
      entity_type='SalesInvoice',
      entity_id=invoice.id,
      action='finalize',
      before=invoice.dict_before,
      after=invoice.dict_after,
      timestamp=now(),
  )
  ```

---

## Commands to Create (Scaffolding Week 1)

These Makefile targets don't exist yet but should be the first artifacts:

| Command | Purpose |
|---------|---------|
| `make setup` | `uv sync` (Python) + `pnpm install` (Node) + create `.env` from `.env.example`. Test DB init deferred to TASK-004. |
| `make dev` | Start docker-compose stack: Postgres + FastAPI (uvicorn) + React (Vite) + Redis. Watch all files, hot-reload. |
| `make test` | Run pytest (backend) + vitest (frontend) + Playwright E2E. Stop on first failure. |
| `make test-watch` | Same as test but re-run on file change. |
| `make lint` | ruff check + format (Python), eslint + prettier (JS). Fail if violations. |
| `make lint-fix` | Auto-fix ruff + prettier violations. |
| `make migrate` | Run alembic upgrade head. Check downtime implications for prod schema changes. |
| `make migrate-create` | Generate an empty Alembic migration (user then writes the SQL). |
| `make seed` | Load seed fixtures (test parties, items, ledgers) into dev DB. |
| `make deploy` | Build Docker image, push to registry, deploy to Hetzner. Automated from GitHub Actions on tag. |
| `make backup` | Snapshot Postgres and upload to S3. Run daily in prod (automated). |

---

## Testing Strategy

### Unit Tests (pytest)

- **Service methods in isolation.** Mock or use dependency injection for external calls (S3, email, etc.).
- **Fast:** < 100ms per test.
- **Location:** `tests/test_<service>.py`.

### Integration Tests (pytest + real test DB)

- **Full flow with RLS, transactions, schema constraints.** Create fixture with test org, firm, users.
- **Example:** create invoice → finalize → check GL ledger entries → receipt applied → check allocation.
- **Fast enough:** < 500ms per test (transaction rollback is fast in Postgres).
- **Location:** `tests/test_<entity>_integration.py`.

### E2E Tests (Playwright)

- **Critical user journeys only.** Not every screen.
- **Example:** login → create party → create invoice → finalize → download PDF → logout.
- **Slow:** 5-10s per test. Run in CI but not on every local save.
- **Location:** `frontend/__tests__/e2e/*.spec.ts`.

### RLS Isolation Tests (pytest)

- **Create two test orgs (A, B); create user in A.** Query org B's data; RLS should block.
- **Verify:** user A cannot read firm B's invoices, even with direct IDs.
- **Location:** `tests/test_rls.py`.

### GST Validation Tests (pytest)

- **Use fixtures from `specs/place-of-supply-tests.md`.** Generate realistic GSTINs per state.
- **Test all 30 scenarios: IGST, CGST+SGST, inter-state, intra-state, composite, overseas, etc.**
- **Location:** `tests/test_gst_place_of_supply.py`, `tests/test_gst_tax_invoice.py`.

---

## How to Start a New Feature (5-Step Loop)

Every feature from now on follows this pattern:

1. **Check the docs.** Read `docs/architecture.md` § relevant to feature, then `specs/`.
2. **Write the failing test first.** Integration test covering happy path + one error case.
3. **Create a migration.** `make migrate-create`, then write `ALTER TABLE` or `CREATE TABLE`.
4. **Implement service + router + React component.** Start with service (no HTTP). Then router (thin). Then React (optimistic UI).
5. **Run `make test && make lint` before commit.** All tests pass, no linting violations.

**Example (Add PAN field to Party):**

1. Check: Party is in `docs/architecture.md` §5.3.1 and `specs/screens-phase1.md` Masters section.
2. Test:
   ```python
   async def test_party_pan_optional():
       party = await party_service.create(org_id=..., name="...", pan=None)
       assert party.pan is None
   ```
3. Migration: `ALTER TABLE party ADD COLUMN pan BYTEA;`
4. Service: `party_service.create(..., pan=...)`.
5. Router: `POST /parties` schema includes `pan: Optional[str]`.
6. React: `<PartyForm>` includes PAN field.
7. Test & lint.

---

## What NOT to Do (Cost-of-Mistakes Checklist)

These will blow up the project if broken:

- **Don't put business logic in routers.** Service layer owns it. Routers are HTTP wrappers.
- **Don't commit secrets** (API keys, DB passwords). Use `.env` (gitignored) and AWS Secrets Manager / Doppler for prod.
- **Don't use `service_role` bypass in application code.** RLS is the security model. Bypass it only in migrations.
- **Don't use float for money.** Ever. Use `Decimal` (Python) or `NUMERIC(18,2)` (Postgres).
- **Don't hard-delete.** Use soft-delete (`deleted_at`). Hard delete is for PII wipe-outs under GDPR, not normal deletions.
- **Don't add endpoints without OpenAPI spec.** Update `specs/api-phase1.yaml` with the endpoint, parameters, and `x-permission`.
- **Don't add a table without RLS.** Every tenant-scoped table has `org_id` + RLS policy + audit columns (`created_at`, `deleted_at`).
- **Don't ship a feature without at least one integration test.** Unit tests are optional. Integration tests are mandatory for business logic.
- **Don't skip migrations.** Code-first schema changes → data loss on deploy. Alembic first, always.
- **Don't merge without a review.** Even with Claude Code, a second pair of eyes catches typos and logic errors.

---

## Ask vs. Decide: Decision Authority

| Decision | Authority | How to Act |
|----------|-----------|-----------|
| UI/UX tweaks (button label, form layout, color) | Claude Code | Make the call, commit. Brief mention in PR description. |
| New endpoint (within spec) | Claude Code | Implement, test, commit. |
| New table or schema change | **Moiz** | Propose in PR comment with migration. Ask for sign-off before merging. |
| Money field or tax logic change | **Moiz** | Discuss in PR. Pair with CA if touching GST. |
| Scope: add a feature not in plan | **Moiz** | Ask before starting. Risk of week waste on edge cases. |
| Tech stack change (e.g., swap Postgres for MySQL) | **Moiz** | Ask upfront. Risk of incompatibility with RLS, migrations. |
| Security or auth changes | **Moiz** | Ask. Risk of tenant leaks, privilege escalation. |

---

## Code Review Checklist (Before Every Commit)

- [ ] All tests pass (`make test`).
- [ ] No linting violations (`make lint`).
- [ ] Money is `Decimal` (Python) or `NUMERIC(18,2)` (Postgres); never float.
- [ ] Timestamps are `TIMESTAMPTZ`, stored UTC.
- [ ] Service method receives `org_id` + `firm_id` explicitly.
- [ ] Every mutating endpoint has `Idempotency-Key` support.
- [ ] New table has `org_id` + RLS policy + `created_at`, `deleted_at`.
- [ ] New endpoint is in OpenAPI spec with correct `x-permission`.
- [ ] Error messages are actionable (e.g., "Cannot finalize: stock qty < ordered qty" not "Validation failed").
- [ ] Migrations are backward-compatible (if they aren't, flag it as a breaking change in PR description).

---

## Key Documentation to Read First

When starting a session:

1. **docs/architecture.md** — skim § headers. Read § relevant to your task (e.g., § 5.7 for sales invoice).
2. **TASKS.md** — pick the next Ready task.
3. **specs/** — read the spec for your feature (api-phase1.yaml, screens-phase1.md, etc.).
4. **docs/review.md** — skim to know what's broken; reference fixes if they're in your path.

Don't re-read the whole architecture. It's 300+ lines. Jump to the relevant section.

---

## Sessions & Continuity

- **Each session starts fresh.** Clone the repo, `make setup`, pick the next Ready task from TASKS.md.
- **Tasks are ordered by dependency.** Don't skip. If a task is Ready, it has no blockers.
- **Commit frequently.** One focused commit per task (or per 2-4 hour chunk). Brief message: `TASK-NNN: short description`.
- **Update TASKS.md after committing.** Mark task as Done, move blockers to Ready if they're unblocked.
- **If you discover a bug in design**, flag it in PR description with links to specs/architecture. Ask for a design review if it's a blocker.

---

## Monitoring & Observability (Future)

Once deployed:

- **Errors:** Sentry free tier for error tracking.
- **Logs:** CloudWatch or Loki for structured logs.
- **Metrics:** Prometheus for latency, RPS, error rates.
- **Uptime:** Grafana dashboards + PagerDuty alerts (if paying customer exists).

For MVP (Weeks 1-12), focus on correctness and test coverage. Observability is nice-to-have.

---

**Version:** 0.1  
**Last updated:** 2026-04-24  
**Owner:** Moiz  
**Next:** Pick TASK-001 from TASKS.md
