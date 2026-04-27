# TASK-014 retro — masters ORM models scaffold

**Date:** 2026-04-27
**Branch:** task/014-masters-scaffold
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 2)

## Summary

`backend/app/models/masters.py` lands 14 ORM models for the masters domain mirroring `schema/ddl.sql` lines 285-569: `Party`, `PartyAddress`, `PartyBank`, `PartyKyc`, `Item`, `Sku`, `Uom`, `ItemUomAlt`, `Hsn`, `CoaGroup`, `Ledger`, `PriceList`, `PriceListLine`, `CostCentre`. Six Postgres ENUMs are bound (`tax_status`, `item_type`, `tracking_type`, `uom_type`, `supply_classification`, `cost_centre_type`) using `enum.StrEnum` + `PG_ENUM(create_type=False)`. 9 new tests cover schema-shape + 4 round-trip insert/query flows. The drift gate now spans all 25 modeled tables (11 identity + 14 masters); zero diffs against migrated DDL.

**Total suite: 121 passed against migrated Postgres**, ruff + format + mypy strict clean across **43 source files**, frontend lint + tsc clean.

## Deviations from plan

### 1. Included 7 tables beyond TASKS.md's 7 named entities

TASKS.md TASK-014 names "Party, Item, SKU, UOM, HSN, PriceList, COA". I added: `PartyAddress`, `PartyBank`, `PartyKyc`, `ItemUomAlt`, `PriceListLine`, `CostCentre`, plus split CoA into `CoaGroup` (hierarchy) + `Ledger` (GL accounts) — matching DDL.

Same precedent as TASK-006: tightly coupled child tables ship together to avoid same-file edit conflicts in TASK-010 / TASK-011 / TASK-040 / TASK-045.

### 2. Six PG ENUMs bound from masters

`PG_ENUM(EnumClass, name='postgres_enum_name', create_type=False, native_enum=True)` per enum. `create_type=False` so Alembic doesn't recreate types DDL already has. `native_enum=True` keeps Postgres-side type checking.

`enum.StrEnum` (Python 3.11+) replaces the older `(str, enum.Enum)` pattern that ruff `UP042` correctly flags.

### 3. Audit-sweep exempt list applied per-table

DDL audit_sweep DO block (TASK-004) adds `updated_at`/`created_by`/`updated_by`/`deleted_at` to every non-exempt table. Masters exempt: `uom`, `hsn`, `item_uom_alt` — these get only `created_at` from their inline DDL declaration.

Other 11 masters tables get the full `TimestampMixin + AuditByMixin + SoftDeleteMixin`. Drift gate verifies.

### 4. `created_by` / `updated_by` overridden on `party`, `item`, `ledger` to add FK

Three masters tables — party (line 316-317), item (line 410-411), ledger (line 508-509) — declare their audit columns *inline* with `REFERENCES app_user(user_id)`. The DO-block-added audit columns on other tables don't have FKs.

`AuditByMixin` declares plain `UUID | None` columns (no FK). For these three, I override with `mapped_column(PG_UUID(as_uuid=True), ForeignKey("app_user.user_id", ondelete="SET NULL"), nullable=True)` to match DDL exactly. Drift gate caught the mismatch on the first push and forced the override — exactly the regression net we built it for.

### 5. Skipped a generic round-trip for every table

5 round-trip tests (party-with-children, item-with-sku, coa-with-ledger, cost-centre, plus the existing identity ones) cover the most representative join + cascade flows. The schema-shape parametrize covers all 14 tables. Round-tripping every table individually would 3x test count for marginal coverage.

### 6. `account_owner_id` on Party kept its FK

Party.account_owner_id declares `REFERENCES app_user(user_id) ON DELETE SET NULL` in DDL. ORM mirrors it explicitly — not via mixin.

### 7. Hsn and Uom keep no FK from `item.hsn_code` / `item.primary_uom`

DDL doesn't enforce these as FKs (item.hsn_code is plain VARCHAR(8), primary_uom is the enum type). ORM matches — no relationship() on Item to Hsn or Uom. Lookup happens in service layer when needed.

## Things the plan got right (no deviation)

- SQLAlchemy 2.0 declarative style with `Mapped[T]` + `mapped_column(...)` — same shape as identity.py.
- Drift gate (TASK-006) caught FK drift on the first push and pointed exactly at the three offending tables. The post-PR-review investment from TASK-006 paid off here.
- Mixins compose correctly — `Party(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin)` gets all 5 audit columns; overriding `created_by` / `updated_by` in the class body adds the FK.
- `enum.StrEnum` from 3.11+ — clean, type-safe, ruff-approved.
- Server defaults (`server_default=text("'UNREGISTERED'::tax_status")`, etc.) match DDL exactly. Drift gate verified.

## Pre-next-task checklist

### 1. TASK-010 (Party CRUD) starts immediately

`Party` + `PartyAddress` + `PartyBank` + `PartyKyc` are all wired with relationships. Service should:
- `create_party(session, *, org_id, firm_id, code, name, …)` — handles the explicit FKs (account_owner_id when provided).
- `update_party(session, *, party_id, fields)`.
- `list_parties(session, *, org_id, firm_id, party_type_filter)` — joins addresses/banks if eager-load needed; otherwise leave for separate endpoints.
- `soft_delete_party` — sets `deleted_at = now()`.
- Encrypted columns (gstin, pan, aadhaar_last_4, phone) — service layer wraps service-level helpers; envelope encryption is a future task. For TASK-010, store as plaintext bytes (encoded UTF-8) — same pattern TASK-007 used for `mfa_secret`.

### 2. TASK-011 (Item + SKU CRUD) drops in next

`Item` + `Sku` + `ItemUomAlt` ready. Service shape mirrors party CRUD. The `tracking_type` enum (NONE/BATCH/LOT/SERIAL) gates lot tracking — TASK-011 should validate that `tracking != NONE` requires lot creation flow.

### 3. TASK-040 (COA seeding) uses CoaGroup + Ledger

COA seed is one-off per org; pattern is similar to RBAC's seed_system_roles — idempotent, runs at signup. Architecture has the standard 100+ Indian COA heads.

### 4. PriceList + PriceListLine are pre-wired for TASK-038

Sales-side wiring (party.price_list_id) needs PriceList already to exist. The FK on `party.price_list_id` is intentionally not declared in DDL (line 311 has plain UUID, no REFERENCES) so the model also leaves it as a bare UUID column. If we later make it a real FK, both DDL and ORM update together.

### 5. CostCentre's firm_id is NOT NULL — different from most

Most masters tables have `firm_id UUID REFERENCES firm` nullable. CostCentre (line 558) requires it: `firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT`. Service layer must enforce — can't create a cost centre at org level. Round-trip test exercises this path.

### 6. Drift gate now covers 25 tables

Identity (11) + Masters (14). Adding any new table without modeling it (e.g. starting TASK-022 stock_ledger) will fail the gate. Either model the new table OR exclude it explicitly via `_include_only_modeled` until that task lands. Easiest: model it.

## Open flags carried over

1. **Encrypted PII columns (gstin, pan, phone, aadhaar_last_4)** — TASK-007 retro item; envelope encryption deferred. Schema columns don't change.
2. **Inventory + Procurement + Sales models** — Wave 3+. The drift gate will gate-keep each new domain.
3. **Async-wrap pattern** — same as TASK-009/007 retros; first router call site decides.
4. **Git identity** — Moiz action.

## Observable state at end of task

- `backend/app/models/masters.py` — 14 models + 6 enum classes + 6 PG_ENUM bindings.
- `backend/app/models/__init__.py` — re-exports all 14 + the 6 enums.
- `backend/tests/test_masters_models.py` — 9 tests (4 schema-shape parametrize + 1 registry + 1 relationship + 4 round-trip).
- ruff + format + mypy strict clean across **43 source files**.
- 121/121 tests pass against fresh `postgres:16-alpine` after `alembic upgrade head`.
- Drift gate passes against the full modeled surface (identity + masters).
- Branch `task/014-masters-scaffold` exists locally; pushed to origin.
