# Fabric & Ladies-Suit ERP

<!-- Replace <owner>/<repo> once the GitHub repo URL is finalized. -->
[![CI](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/<owner>/<repo>/actions/workflows/ci.yml)

Multi-tenant cloud ERP for the Indian ladies-suit / fabric textile trade. Track procurement, inventory, manufacturing, sales, and accounting—with full GST compliance and non-GST workflows as first-class citizens.

**Status:** Design phase complete → Pre-implementation (Week 1 kickoff planned)

**Plan finalized** (locked decisions — see [CLAUDE.md](./CLAUDE.md) for the full list):

- Solo build with Claude Code + AI agents, 12-week MVP, bootstrap budget (~₹10–25k/month).
- Dogfood on Moiz's own textile business first (currently on Vyapar).
- **Migration:** Vyapar `.vyp` primary; Tally XML + Excel template adapters alongside.
- **GST compliance:** full machinery (PoS engine, PDF tax invoices, GSTR-1 prep, IRN payload JSON) built in Phase 1; actual NIC/GSP API call feature-flagged off (below ₹5 Cr threshold today; flip when needed).
- **Deferred to Phase 2+:** offline mode, WhatsApp API, e-invoice IRN submission, e-way bill, manufacturing MOs, mobile PWA.

Next action: open a session with Claude Code in this repo and run `TASK-001` from [TASKS.md](./TASKS.md).

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [CLAUDE.md](./CLAUDE.md) | Instructions for Claude Code sessions in this repo |
| [docs/architecture.md](./docs/architecture.md) | System design, tenancy, modules, principles |
| [docs/implementation-plan.md](./docs/implementation-plan.md) | 12-week MVP timeline, scope decisions, budget |
| [TASKS.md](./TASKS.md) | Ordered task list for Claude Code to execute |
| [docs/review.md](./docs/review.md) | Design review, known issues, fixes |
| [schema/ddl.sql](./schema/ddl.sql) | Postgres schema (multi-tenant, RLS-enabled) |
| [specs/api-phase1.yaml](./specs/api-phase1.yaml) | Phase-1 REST API surface |
| [specs/screens-phase1.md](./specs/screens-phase1.md) | Phase-1 UI screens inventory |
| [specs/invoice-lifecycle.md](./specs/invoice-lifecycle.md) | Invoice state machine and accounting flow |
| [specs/place-of-supply-tests.md](./specs/place-of-supply-tests.md) | GST place-of-supply validation fixtures |

---

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2, Alembic
- **Frontend:** React 18+, TypeScript, Vite, Tailwind CSS, shadcn/ui
- **Database:** PostgreSQL 16 (multi-tenant with RLS)
- **Deployment:** Docker, Hetzner (single box for MVP), GitHub Actions CI
- **Security:** TLS, AES-256 field encryption, JWT + MFA, RLS enforcement

---

## Getting Started (Development)

Once code exists, a fresh clone will look like:

```bash
# Clone and enter
git clone <repo>
cd fabric-erp

# Install and set up
make setup
cp .env.example .env    # Configure your DB/API keys

# Run locally
make dev                 # Starts Postgres, FastAPI, React dev server via docker-compose

# Test and lint
make test
make lint

# Migrate schema
make migrate
```

Full documentation in [CLAUDE.md](./CLAUDE.md) under "Commands."

---

## Design Principles

1. **Tenant isolation first** — RLS enforces org_id on every row.
2. **Non-GST is not an afterthought** — GST and non-GST firms are peers.
3. **The suit is composite** — parts (dupatta, sleeves, etc.) are first-class in inventory and job work.
4. **Boring tech, clean monolith** — FastAPI + Postgres. Extract services only when they hurt.
5. **Server-authoritative, client-optimistic** — drafts offline; numbers, taxes, postings on server.
6. **Every mutation is auditable** — append-only log per organization.

---

## Project Status

- Schema design ✓
- Architecture and principles ✓
- API spec outline ✓
- Screen inventory ✓
- Known issues documented (see [docs/review.md](./docs/review.md))
- Code scaffolding → Week 1 of implementation plan

No production deployment yet. Dogfooding starts Week 2 with schema fixtures and core API.

---

## License & Confidentiality

Proprietary. All documents and code are confidential to Moiz and Fabric ERP.

---

**Last updated:** 2026-04-24  
**Owner:** Moiz  
**Next milestone:** Week 1 bootstrap (TASK-001)
