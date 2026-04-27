# Critical Code Review

**Reviewer:** Me (with production-engineer hat on, not my sales hat)
**Scope:** Everything shipped across the repo so far
**Bias disclosure:** I wrote most of this, so I'm grading my own work. Corrected for self-flattery by grepping before writing.

---

## TL;DR

**The design work is solid. The artifacts are not yet "production-ready" — they are "design-ready." There's a gap between them.**

Things that would keep me up at night if I ran `psql -f ddl.sql` tomorrow morning:

- **The DDL won't load as-is.** `CREATE EXTENSION IF NOT EXISTS uuid-ossp;` is a syntax error.
- **Soft-delete is claimed everywhere but implemented on 15 of 102 tables.** ~85% of the schema is *advertised* as having `deleted_at` but doesn't.
- **Only 32 of 102 tables have `created_by`; 39 have `updated_at`.** The "standard audit columns" promised in the spec are on the minority of tables.
- **The OpenAPI spec has zero `Idempotency-Key` support** — despite the architecture's explicit offline-sync requirements. The Phase-3 agent claimed to add it; they lied. It's defined once and never referenced by any operation.
- **Two CSS-in-prototype bugs break the design.** `alpinejs@3.x.x` is not a valid tag; `@apply` in `<style>` doesn't work with Tailwind CDN (which we use). Half the custom styles silently don't apply.
- **Place-of-supply tests rely on masked GSTINs (`27AXXXX...`)** where real format validation matters. A test suite that doesn't use well-formed data will not catch a bug where GSTIN-state-extraction is wrong.

None of these are fatal; all are fixable in a morning. But "senior architect-level design + junior implementation details" is exactly the pattern that blows up at pilot.

---

## P0 — Bugs that prevent the artifacts from working

### P0-1. DDL: `uuid-ossp` extension syntax error

`schema/ddl.sql:7`
```sql
CREATE EXTENSION IF NOT EXISTS uuid-ossp;
```

Hyphens must be quoted in Postgres identifiers. This statement errors out:
```
ERROR:  syntax error at or near "-"
```

**Fix:**
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

**Better fix:** just remove it. The DDL uses `gen_random_uuid()` (from `pgcrypto`, which we already enable). `uuid-ossp` is unused — 100% of PK defaults reference `gen_random_uuid()`, which is part of pgcrypto/Postgres 13+. Ship without it.

### P0-2. Prototype: `@apply` inside `<style>` with Tailwind CDN

`prototype/index.html:15, 22-25`
```css
.focus-ring { @apply focus-visible:ring-2 focus-visible:ring-blue-600 ...; }
.status-badge { @apply inline-flex items-center px-2 ...; }
.status-draft { @apply bg-slate-100 text-slate-700; }
```

Tailwind's Play CDN does **not** process `@apply` inside custom `<style>` blocks. It compiles utility classes at runtime based on what's in the DOM. These `.status-*` classes will show up with zero Tailwind styles applied.

**Fix:** inline the utility classes in the HTML, or switch to `tailwindcss@next` JIT CDN setup that does support it (`<script src="https://cdn.tailwindcss.com?plugins=..."></script>` with a config). Simplest patch: replace every `class="status-badge status-draft"` with `class="inline-flex items-center px-2 py-1 text-xs font-medium rounded-full bg-slate-100 text-slate-700"`.

### P0-3. Prototype: invalid Alpine.js version tag

`prototype/index.html:9`
```html
<script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
```

`3.x.x` is not a valid semver range — the convention is `3` or `3.x`. unpkg may redirect, may not, and this is brittle. In a pinned production artifact, always use a specific version.

**Fix:** `alpinejs@3.14.1` (or whatever the current 3.x is at time of pin).

### P0-4. OpenAPI: Idempotency-Key header claimed but not applied

Phase 1: 0 references. Phase 3: 1 reference (definition only — never on any operation). Both architecture §17.8.2 and manufacturing-pipeline.md §5 explicitly require idempotency for offline sync — the whole Android write-path depends on it.

**Fix:** define `IdempotencyKey` as a header parameter in `components/parameters` and reference it on every mutating operation (POST/PATCH/DELETE). Spot-applied at minimum to invoice finalize, MO release, operation dispatch, operation receive, payment post — anywhere an Android device might retry.

---

### P0-5. DDL: schema didn't actually load — three real bugs (added retroactively in TASK-004)

Three inline `UNIQUE (..., COALESCE(...))` constraints prevented `make migrate` from ever succeeding on a fresh Postgres before TASK-004:

1. `user_role` line 195 — `UNIQUE (user_id, role_id, COALESCE(firm_id, '00…0'))`
2. `stock_position` line 661 — `UNIQUE (org_id, firm_id, item_id, COALESCE(lot_id, '00…0'), location_id)`
3. `budget` line 1975 — `UNIQUE (firm_id, fy_year, COALESCE(cost_centre_id, '00…0'), ledger_id, month)`

Postgres disallows expressions inside an inline `UNIQUE` constraint; only `UNIQUE INDEX` accepts expressions.

A fourth bug surfaced in the same window: PATCH 1's `audit_sweep` `DO` block iterated over every public table to add `deleted_at` and a partial index on `(org_id) WHERE deleted_at IS NULL`. `alembic_version` lives in the same schema, doesn't have `org_id`, and shouldn't have audit columns at all → `column "org_id" does not exist`.

**Fix (TASK-004):** Each inline `UNIQUE (..., COALESCE(...))` was converted to a separate `CREATE UNIQUE INDEX` with the COALESCE expression (legal in indexes). `alembic_version` was added to the `audit_sweep` exempt list. Schema now loads cleanly on a fresh Postgres.

**Lesson:** ship a CI smoke test that runs `alembic upgrade head` against a real Postgres and asserts the table count, so this regression class can't return silently.

---

## P1 — Correctness gaps that will bite in testing

### P1-1. DDL: "standard audit columns" not standard

The spec stated:
> *Standard columns on every table: `created_at`, `updated_at`, `created_by`, `updated_by`, `deleted_at`.*

Actual counts (grep on `ddl.sql`):

| Column | Tables having it | % coverage |
|---|---|---|
| `created_at` | ~102 | ~100% |
| `updated_at` | 39 | 38% |
| `created_by` | 32 | 31% |
| `updated_by` | (not counted, fewer) | <30% |
| `deleted_at` | 15 | 15% |

Soft-delete on 15% of tables is not a soft-delete strategy — it's a foot-gun. Code paths will assume soft-delete works everywhere, hit a table that hard-deletes, and lose data.

**Fix:** either
(a) Add the missing columns to every tenant-scoped table via a migration. This is ~70 ALTER statements but structurally uniform.
(b) Drop the promise. Only `created_at` is universal; the rest are per-table decisions. Update the spec to match reality.

Recommendation: (a) — for a GST-audited product, retention matters, and soft-delete is the simplest way to honour 6-year retention while still letting users "delete" things.

### P1-2. DDL: inconsistent ON DELETE behaviour

278 `REFERENCES` clauses; only 176 have explicit `ON DELETE` (134 RESTRICT, 42 CASCADE). 102 FKs default to `NO ACTION` — semantically similar to RESTRICT but differs in deferred-constraint behaviour and is inconsistent.

**Fix:** pass through once with a policy —
- Owning child (e.g. `voucher_line` → `voucher`): CASCADE.
- Reference (e.g. `sales_invoice.salesperson_id` → `app_user`): SET NULL.
- Business key (e.g. `party_id`, `item_id`, `ledger_id`): RESTRICT.

### P1-3. DDL: `mo_operation` lacks `firm_id` in base schema; patch added it nullable

Base table (`ddl.sql:1078-1091`) has `org_id` only. My patch adds `firm_id UUID REFERENCES firm(firm_id)` — **nullable**. RLS with `firm_id IS NULL OR firm_id = current_setting(...)` is the usual escape hatch, but that's a policy we did not explicitly set. Once migration populates firm_id, it should be `NOT NULL`. As-is, a mis-written query could leak rows across firms within an org.

**Fix:** after data backfill, `ALTER TABLE mo_operation ALTER COLUMN firm_id SET NOT NULL;` plus an RLS policy scoped on both org + firm.

### P1-4. DDL: `uom` and `hsn` tables lack RLS

Both are catalogs. Intent is probably "global, shared across all tenants". That's fine *if*:
- Orgs can't write to them (only a system role can).
- No per-org customization (e.g. firm-specific UOMs) exists.

If either fails — e.g. a user wants to add "Thaan" as a UOM specific to their shop — and they're shared globally, you've leaked a catalog mutation across tenants. Worse, you have no RLS to prevent it.

**Fix:**
- If truly global: add a `GRANT SELECT ... TO application_role; REVOKE INSERT/UPDATE/DELETE ...`. Don't rely on the application to not insert.
- If tenant-customizable: enable RLS + add `org_id`.

### P1-5. DDL patch: `ALTER TABLE` changes `NOT NULL` without setting default first

My patch does:
```sql
ALTER TABLE sales_invoice
  ADD COLUMN IF NOT EXISTS lifecycle_status invoice_lifecycle_status NOT NULL DEFAULT 'DRAFT';
```

Good — `DEFAULT 'DRAFT'` back-fills existing rows. But:
```sql
ALTER TABLE purchase_invoice
  ADD COLUMN IF NOT EXISTS lifecycle_status purchase_invoice_status NOT NULL DEFAULT 'DRAFT';
```

Works for purchase_invoice too. However for `paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0` — this fires a full table rewrite on big tables in Postgres < 11. On 11+ it's a metadata-only change. **Make sure the deploy target is Postgres 16**, as claimed, or document the downtime implication.

**Fix:** the migration runner should `SET statement_timeout` before DDL and have a go/no-go for table sizes. Documented elsewhere? No. Add to runbook.

### P1-6. DDL patch: `payment_allocation` CHECK constraint is correct but fragile

```sql
CONSTRAINT chk_payment_alloc_target CHECK (
    (sales_invoice_id IS NOT NULL)::int +
    (purchase_invoice_id IS NOT NULL)::int = 1
)
```

The cast-to-int-and-sum trick is clever but non-obvious. A maintainer will see this and not understand the invariant.

**Fix:** add a comment:
```sql
-- Exactly one of sales_invoice_id / purchase_invoice_id must be non-null.
CONSTRAINT chk_payment_alloc_one_target CHECK (
    num_nonnulls(sales_invoice_id, purchase_invoice_id) = 1
)
```
`num_nonnulls` is Postgres native since 9.6 and self-documenting.

### P1-7. Place-of-supply tests: GSTINs are masked placeholders

Sample scenarios use `GSTIN: 27AXXXX...`. A real test suite will need full, well-formed, **state-code-matching** GSTINs so the state-extraction logic is exercised. `27AXXXX...` passes a naive regex; `27ABCDE1234F1Z5` is a realistic one.

**Fix:** generate a fixture of ~15 realistic GSTINs with known state codes and distinctive PAN segments; reference by fixture name in scenarios.

### P1-8. Architecture doc: inter-firm transfer engine references an undefined price

`architecture.md` §17.2.6 says "Auto-raises Sales Invoice from A to B at configured transfer price (default = current landed cost)" — but there's no `transfer_price_policy` column on `inter_firm_relationship`. My ERD claims `default_pricing` but the actual DDL table definition does not. Check:

```
$ grep -A 10 "CREATE TABLE inter_firm_relationship" ddl.sql
```
Confirm — the column is not there. Dependents downstream will fail.

**Fix:** `ALTER TABLE inter_firm_relationship ADD COLUMN default_pricing_policy VARCHAR(30) NOT NULL DEFAULT 'LANDED_COST'`.

### P1-9. Screens-phase1 and DDL disagree about Manufacturing scope

Phase-1 DDL includes the entire manufacturing module (manufacturing_order, mo_operation, etc.). Phase-1 screens explicitly defer manufacturing to Phase 3. So you ship tables nobody can write to in Phase 1 — dead schema. It's harmless functionally but it's wasted real estate and noise for early users.

**Fix:** either (a) drop manufacturing tables from Phase-1 DDL and re-introduce in Phase-3 migration, or (b) mark manufacturing tables as "Phase 3" in DDL section headers so nobody wires up API endpoints that read an always-empty table and silently "work". Recommendation: (b) — the effort to rename later dwarfs the noise.

### P1-10. Prototype: mock data "Production" card references "₹18 L at job-workers" — inconsistent with Kanban totals

The added Production card on Dashboard hardcodes "₹18 L" but the Kanban column footers sum to ~₹25 L across stages (if I mentally sum the agent's mock data). A demo user will click through and see the numbers don't match — credibility loss. Small bug, but it's the kind of thing a careful demo finds in the first 30 seconds.

**Fix:** have the Dashboard card compute from the same mock-data object, not hardcode.

---

## P2 — Consistency and polish

### P2-1. Enum naming

DDL mixes styles:
- `voucher_status` (pre-patch), `invoice_lifecycle_status` (patch) — inconsistent. Pick one: short (`voucher_status`) or prefixed-long (`invoice_lifecycle_status`) and commit.
- `location_type`, `mo_type`, `operation_type` — fine.

### P2-2. Index names

Pre-patch DDL uses `idx_<table>_<col>` mostly. My patch uses `idx_si_lifecycle_status`, `idx_mo_op_state` — shorter prefix. Inconsistent with existing. Rename to `idx_sales_invoice_lifecycle_status` etc for consistency.

### P2-3. `sales_invoice` now has both `status` (voucher_status) and `lifecycle_status` (invoice_lifecycle_status)

My patch added `lifecycle_status` without dropping the old `status`. The two will drift. A `SELECT` that reads one and a trigger that updates the other = bug waiting to happen.

**Fix:** migration plan:
1. Phase-1 release ships both.
2. Back-fill lifecycle_status from status (done in patch notes).
3. Phase-2 release drops `status` column.

Document this two-release deprecation explicitly.

### P2-4. OpenAPI: response schemas often `type: object` without properties

Phase-3 agent reported "Leaner `type: object` schemas OK for less-core entities" — which was my instruction. But downstream code-gen tools (TypeScript types, Python Pydantic) will produce useless `Record<string, unknown>` for these. That's acceptable for a skeleton, not for a v1 freeze. Priority fix before any client-SDK generation.

### P2-5. Specs/architecture.md is now ~1500+ lines

It started as an architecture doc and absorbed:
- Gap audit (§16)
- Gap resolutions (§17)
- Roadmap (§17.12)

It's past useful reading length for onboarding. Break into:
- `architecture.md` — the principles and module overview (compact)
- `decisions/` — ADRs for each significant choice
- `roadmap.md` — phase timeline

### P2-6. No `LICENSE`, no `README.md` at repo root

A new engineer opening the directory sees `architecture.md`, `schema/`, `specs/`, `prototype/`, `review.md` — which is which? What's the entrypoint? What's the status of each?

**Fix:** add a `README.md` that points to:
- Architecture start: `architecture.md` → Table of Contents
- Data layer: `schema/erd.md` + `schema/ddl.sql`
- API: `specs/api-phase1.yaml` + `specs/api-phase3.yaml`
- UI: `specs/screens-phase1.md` + `specs/screens-manufacturing.md` + `prototype/index.html`
- Critical flows: `specs/invoice-lifecycle.md` + `specs/manufacturing-pipeline.md` + `specs/place-of-supply-tests.md`
- Known issues: `review.md`

---

## P3 — Quality of life

### P3-1. DDL has no migration framework scaffolding

It's a 2200-line flat DDL file. To actually ship this, you'd need to split into Alembic migrations (or equivalent). Initial migration is easy (this becomes `0001_initial.py`); patch is `0002_phase1_forward_compat.py`; etc.

Without this scaffolding, any schema change requires manual diff-and-patch — which, for an RLS-heavy schema, is error-prone.

### P3-2. No seed / fixture scripts

Spec says "Pre-seeded India-standard COA at org creation". Where's the seed file? Empty. Ditto for default roles, permissions, HSN codes, UOMs, standard operations.

**Fix:** `schema/seed/` with:
- `coa_india_standard.sql`
- `roles_and_permissions.sql`
- `hsn_textile.sql`
- `uom_base.sql`
- `operation_master_textile.sql`

### P3-3. No type-generation from DDL

For a TypeScript frontend, hand-writing types is how schemas drift. Something like `pg-to-ts`, Prisma's introspection, or Supabase's type-gen should be wired up.

### P3-4. Prototype loads 3 CDN scripts synchronously

Tailwind CDN compiles utilities in-browser. Combined with Lucide icons and Alpine, first paint on a cold CDN is ~1.5s. For a design prototype that's fine. For production we'd need either Tailwind's JIT-compiled output or UnoCSS.

### P3-5. Spec drift: architecture.md lists `decision` but schema/erd.md entity is `design`

Minor — the high-level ERD uses `design` (which matches DDL). Architecture doc §5.6.3 uses "design" throughout too. Consistent on the important axis. Noted only because I almost renamed it.

### P3-6. Place-of-supply tests don't cover round-tripping

"On POS compute, does the invoice's `place_of_supply_state` match?" is a unit test. The test suite doesn't specify the assertion API, just the expected-output table. Add pytest snippet at the end showing how a test is structured.

---

## Security & compliance — honest review

| Concern | Assessment |
|---|---|
| **RLS universally enforced** | 96/100 tables covered. Missing on `uom`, `hsn` — intentional if global, accidental otherwise. Verify. |
| **PII encryption via envelope** | Declared in patch + architecture; 38 BYTEA columns. The actual KMS integration is design-level only — no code to verify. This is a "trust me it'll work" at present. |
| **Audit log hash-chaining** | Declared at DDL level. No code emits the chain. First integration test should assert "n rows → n hashes where each references prev". |
| **RBAC permission tagging** | Every API op has `x-permission`. No code enforces it. Pattern is right; the wire-up remains. |
| **Offline + IRN hard block** | Specified in invoice-lifecycle.md §4 checklist. Not encoded anywhere runnable yet. |
| **Idempotency-Key** | **Gap.** Specified in specs, absent from API skeletons. |
| **MFA for Admin** | Specified in architecture §4. API has `/auth/mfa/*` endpoints. No enforcement logic sketched. |
| **GST 6-year retention** | Relies on `deleted_at` honoured by soft-delete. Currently 15% of tables have it. **Material risk for compliance.** |

The security model is *coherent on paper*. Its biggest risk is that the design is complete while the implementation contract is not — there's no tested, working code to prove the design. This is normal for a design-phase deliverable; flagging it because "architecture looks secure" can become "product shipped insecurely" without a hard transition gate.

---

## What's good (not here for flattery; here because it's worth keeping)

- **Non-GST as first-class, not special-cased.** This is a genuine architectural move; most textile ERPs bolt it on later.
- **DAG routing for operations.** Correct textile reality; simpler systems that force linear routing will frustrate users after three MOs.
- **SKU-level variants for size.** Apparel standard; many systems skip it.
- **Bill-to-ship-to modelled in test suite.** Compliance engineers will open the place-of-supply doc and find their case already covered.
- **Stock ledger as append-only with stage dimension.** Enables the Kanban view without a separate WIP store.
- **Event table for manufacturing with idempotency key.** Forward-compatible for CQRS/read-models later.
- **Every state transition is an explicit action with an API verb, not a generic UPDATE.** Prevents the classic ERP failure mode where "what state is this thing in?" depends on which column you look at.

---

## Recommended 1-day cleanup

Stop adding features for a day; fix the real issues first.

**Morning (P0 fixes):**
1. Remove `CREATE EXTENSION uuid-ossp`; validate `psql -f ddl.sql` runs clean.
2. Inline Tailwind utilities in prototype; remove `@apply` from `<style>`. Test visually.
3. Pin Alpine to `@3.14.1`.
4. Add `IdempotencyKey` header parameter + apply to ~20 mutating operations in both API specs.

**Afternoon (P1 fixes):**
5. Add `deleted_at`, `updated_at`, `created_by`, `updated_by` to every tenant-scoped table missing them (~70 ALTERs; uniform pattern).
6. Fix FK `ON DELETE` policy consistency (one pass with the policy table above).
7. Make `mo_operation.firm_id` NOT NULL after backfill; update RLS policy.
8. Decide `uom` / `hsn` scope — global or tenant — and enforce via GRANTs or RLS.
9. Add `default_pricing_policy` to `inter_firm_relationship`.
10. Make prototype Dashboard's Production card compute from Kanban mock data, not hardcode ₹18 L.

**Late afternoon (P2 polish):**
11. Fix index-naming consistency.
12. Write a README.md at repo root pointing to everything.
13. Document the `status` / `lifecycle_status` dual-column deprecation plan explicitly.

By end of day, `psql -f ddl.sql` is clean, prototype looks correct, APIs are idempotency-ready, and the README tells a new engineer where to start. Nothing feature-shaped has shipped — but *nothing lies to the reader* anymore.

---

## What I would not ship without

Before calling Phase 1 "implementable" I'd want:

1. **`./bin/setup`** that runs the DDL against a throwaway Postgres and exits 0.
2. **`./bin/test-rls`** that spawns two tenant sessions and asserts cross-tenant read returns 0 rows on every table.
3. **One end-to-end test** that creates an org → firm → user → party → item → invoice → posts voucher → reads trial balance. If that test passes, the minimum viable vertical is real.
4. **Idempotency tests**: double-submit the same invoice finalize with the same key; assert second call returns the first's response, not a duplicate.
5. **A README with the 4 commands above**.

Everything on disk today is the *design* to build against. It is not the *thing*. The distinction matters.
