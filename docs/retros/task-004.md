# TASK-004 retro — DDL + Alembic baseline + P0/P1 fold-ins

**Date:** 2026-04-25
**Branch:** task/004-ddl-alembic
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 1)

## Summary

Alembic baseline migration loads `schema/ddl.sql` (2400+ lines, 102 CREATE TABLE statements) and applies the remaining P1-3 fix (`mo_operation.firm_id` NOT NULL — possible immediately on a greenfield install). Three real DDL bugs surfaced and were fixed mid-task: two `UNIQUE (..., COALESCE(...))` inline constraints (Postgres disallows expressions in `UNIQUE`; converted to `UNIQUE INDEX`) and the audit-sweep DO block needed `alembic_version` in its exempt list. Migration runs end-to-end, round-trips downgrade→upgrade cleanly, idempotent on re-run. Final state: 103 tables (102 schema + 1 alembic_version). ruff + mypy strict clean.

## Deviations from plan

### 1. Switched migration engine from asyncpg → psycopg2 (sync)

Original env.py used the async engine matching `DATABASE_URL=postgresql+asyncpg://...`. asyncpg refuses to `prepare` multi-statement DDL files, so loading `ddl.sql` via async engine fails immediately. The standard Alembic pattern (even when the app is async at runtime) is to use a sync driver for migrations.

- **Fixed by:** rewrote env.py to use `engine_from_config` (sync) + `psycopg2-binary`. URL transform happens inline: `postgresql+asyncpg://` → `postgresql+psycopg2://` before the engine is built.
- **Why not caught in planning:** the blocked TASK-004 agent's draft used async engine; followed that draft initially before testing surfaced the issue.
- **Impact on later tasks:** zero. App runtime keeps using asyncpg. `psycopg2-binary` is now in deps.

### 2. Used `cursor.execute()` directly instead of `op.execute()` / `bind.exec_driver_sql()`

SQLAlchemy 2.0's `op.execute()` parses `:colon` patterns as bind params; `exec_driver_sql()` still routes through immutabledict default params that psycopg2 chokes on; explicit `(,)` empty tuple triggers a different psycopg2 format-string error because the DDL contains literal `%` characters.

- **Fixed by:** `op.get_bind().connection.cursor()` returns the raw psycopg2 cursor. `cursor.execute(sql)` with no parameters bypasses the entire format/parameter layer. Wrapped in a `_raw_cursor()` helper for both upgrade and downgrade.
- **Why not caught in planning:** SQLAlchemy 2.0 + psycopg2 + multi-statement DDL is a niche combination; the agent's draft assumed `op.execute(sql)` would just work.
- **Impact on later tasks:** future migrations that touch model-defined tables can use `op.execute()` normally — only multi-statement DDL loads need the raw-cursor pattern.

### 3. Three real DDL bugs found and fixed in `schema/ddl.sql` (NOT in review.md)

These were not flagged by the original P0/P1 audit; they surfaced when `psql` actually parsed the schema:

- **`user_role` (line 195):** `UNIQUE (user_id, role_id, COALESCE(firm_id, '00...0'))` — Postgres disallows expressions inside inline `UNIQUE`. Removed inline constraint; added `CREATE UNIQUE INDEX uq_user_role_user_role_firm` with the COALESCE expression (legal in indexes).
- **`stock_position` (line 661):** Same pattern. Same fix → `uq_stock_position_org_firm_item_lot_location`.
- **`budget` (line 1975):** Same pattern. Same fix → `uq_budget_firm_fy_cc_ledger_month`.
- **`alembic_version` not exempt from PATCH 1 audit_sweep:** the DO block iterates over all public tables to add `updated_at`/`created_by`/`updated_by`/`deleted_at` plus a partial index on `(org_id) WHERE deleted_at IS NULL`. `alembic_version` doesn't have `org_id` and shouldn't have audit columns anyway. Added `'alembic_version'` to the exempt array.

These fixes should be flagged in `docs/review.md` as "P0-DDL-load: schema didn't actually load before TASK-004" — fix landed in this PR.

### 4. P1-2 (audit FKs ON DELETE policy) **deferred** to a follow-up migration

The grand plan §3 Wave 1 listed P1-2 as a fold-in. The blocked agent's analysis identified 41 audit-style FK columns (`created_by`, `updated_by`, `actor_*`, etc.) defaulting to NO ACTION. The right policy is `SET NULL` (preserve audit history when the referenced user/party is deleted), but this is genuinely a Moiz design decision — and it's a substantial 41-FK rewrite that risks ballooning Wave 1 cost.

- **Fixed by:** documented the deferral in the migration's docstring and this retro. Will land as a follow-up migration when the design call is confirmed (probably alongside TASK-006 or TASK-007 when audit columns get their first real data).
- **Impact on later tasks:** none until something tries to delete an `app_user` or `party` row. Until then, NO ACTION is functionally identical to RESTRICT.

### 5. P1-9 cosmetic (section-6 header marker) **skipped**

The end-of-file P1-9 comment in `schema/ddl.sql` already documents which tables are Phase-3 manufacturing. Adding a duplicate marker before line 1030 is doc polish, not behavior.

- **Impact on later tasks:** zero. Manufacturing feature flag (`mfg.enabled` defaults FALSE) is the actual gate.

## Things the plan got right (no deviation)

- Single baseline migration loading `ddl.sql` verbatim is the cleanest pattern.
- Alembic revision ID format constraint (no `-` allowed) — caught early; renamed `TASK-004-baseline` → `task_004_baseline`.
- `Path(__file__).resolve().parents[3]` correctly resolves to repo root from `backend/alembic/versions/<file>.py`.
- Transient Postgres on port 5499 (`docker run --name task004-pg -p 5499:5432 ...`) — clean isolation from user's main dev DB.
- `target_metadata = None` for the baseline — autogenerate is OFF until SQLAlchemy models exist (TASK-006+), exactly as the agent's draft proposed.

## Pre-next-task checklist

### 1. Drop the audit_sweep `alembic_version` exemption when models land

When TASK-006 introduces SQLAlchemy models, the audit_sweep DO block in `ddl.sql` lines 2278-2346 becomes redundant — models will declare `updated_at`/`created_at`/`deleted_at` directly. The exempt list will then be moot. Plan to remove the entire `DO $audit_sweep$` block in a TASK-006 follow-up migration; document the migration explicitly so reviewers know it's a refactor, not a behavior change.

### 2. P1-2 audit FK SET NULL — separate migration

Land as `task_xxx_audit_fks_set_null.py` once Moiz confirms `SET NULL` is the right policy. The DO block to apply it iterates over `pg_constraint` looking for FKs with `confdeltype='a'` and audit-named columns. Sketch in this retro's "deferred" section above.

### 3. Postgres extensions are pinned

`pgcrypto` is the only extension declared in ddl.sql. `gen_random_uuid()` works out of the box on Postgres 13+ (it's now in the core); but the explicit `CREATE EXTENSION IF NOT EXISTS pgcrypto` keeps compatibility with older Postgres if someone runs against 12. We ship 16 in docker-compose, so this is forward-compatible.

### 4. The `migrate` Makefile target needs DATABASE_URL

`make migrate` runs `cd backend && uv run alembic upgrade head`. It reads `DATABASE_URL` from env (or `.env` via uv's automatic loading). For dev, the loaded `.env` from `make setup` has `DATABASE_URL=postgresql+asyncpg://fabric:fabric_dev@localhost:5432/fabric_erp` which env.py rewrites to `psycopg2://`. For CI, the GHA workflow already sets `DATABASE_URL` for the Postgres service container (TASK-005).

### 5. CI integration — add `make migrate` step

TASK-005's CI workflow doesn't yet run migrations before tests. After TASK-004 merges, add a step in `backend-test` between "Install backend deps" and "Detect tests, then run pytest":
```yaml
- name: Run migrations
  working-directory: backend
  run: uv run alembic upgrade head
```

### 6. RLS enabled on every tenant table — verify spot-check

`ddl.sql` declares `ALTER TABLE x ENABLE ROW LEVEL SECURITY` + `CREATE POLICY x_rls` for every tenant-scoped table inline. PATCH 1 didn't add this loop because tables that should have RLS already have it. Worth a spot-check after TASK-006 lands real models: query `pg_policies` for any tenant-scoped table missing a policy.

### 7. Git identity still auto-guessed (carryover from TASK-001)

Every commit on this branch authored as `Moiz P <moizp@Abduls-MacBook-Pro.local>`. Run `git config --global user.name "Moiz …"` and `git config --global user.email "…"` at first opportunity.

## Open flags carried over

1. **P1-2 audit FK ON DELETE policy** — deferred to a follow-up migration (Moiz design call).
2. **P1-9 section-6 header marker** — skipped (already documented at EOF).
3. **`make dev` end-to-end validation** — not done this session (carried from TASK-002).
4. **`make dev: setup` Makefile dependency** — still unresolved (TASK-001 retro item 5).
5. **Audit-sweep DO block removal** — slated for TASK-006 follow-up after models land.
6. **CI doesn't run migrations** — fold into TASK-005 cleanup or do as part of TASK-006 prep.
7. **Git identity** — Moiz action.

## Observable state at end of task

- `schema/ddl.sql` — 3 inline UNIQUE-with-expression constraints converted to UNIQUE INDEXes; `alembic_version` added to audit_sweep exempt list.
- `backend/alembic.ini` — new (sync engine config; sqlalchemy.url comes from env).
- `backend/alembic/env.py` — new (sync engine, asyncpg→psycopg2 URL rewrite).
- `backend/alembic/script.py.mako` — new (standard alembic template).
- `backend/alembic/versions/2026042500001_task_004_baseline.py` — new (loads ddl.sql, applies P1-3).
- `backend/pyproject.toml` — added `sqlalchemy[asyncio]>=2.0` (was `sqlalchemy>=2.0`), `psycopg2-binary>=2.9`, `greenlet>=3.0`.
- `backend/uv.lock` — regenerated.
- `Makefile` — `migrate` and `migrate-create` targets are no longer stubs.
- `docs/retros/task-004.md` — this file.
- Branch `task/004-ddl-alembic` exists locally; not pushed.
- Migration verified end-to-end against transient Postgres 16 on port 5499 (container `task004-pg` cleaned up).
- Round-trip: 103 tables → downgrade base → 0 → upgrade head → 103 tables. Idempotent on re-run.
