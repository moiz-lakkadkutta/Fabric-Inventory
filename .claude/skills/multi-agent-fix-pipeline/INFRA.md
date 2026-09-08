# Infra recipes — test DBs, env, migrations, CI

## Test-database template (per-agent isolation)

Some tests COMMIT (via `admin_engine` / `org_scoped_session`), so concurrent agents on one DB collide. Give every agent its own DB, cloned from a migrated template:

```bash
export PGPASSWORD=fabric_dev
psql -h localhost -U fabric -d postgres -c "CREATE DATABASE test_template;"
# migrate it (see env recipe), then per agent:
psql -h localhost -U fabric -d postgres -c "CREATE DATABASE test_N TEMPLATE test_template;"   # fast clone
```

- The `fabric_app` role is cluster-global; per-DB grants come from the migrations and are copied by `TEMPLATE`.
- **After each wave's migration merges, `alembic upgrade head` the template** so later clones inherit it.
- Rebuild the template from scratch (`DROP` + `CREATE` + full upgrade) after any migration-chain surgery, so clones match a from-scratch build.
- Drop `test_N`/`test_vN` after each issue integrates. `CREATE … TEMPLATE` fails if anything is connected to the template — `pg_terminate_backend` first.

## The exact test-run env (hand this to every agent)

```bash
env -i HOME="$HOME" PATH="$PATH" bash -c '
  cd <worktree>/backend
  export DATABASE_URL="postgresql+asyncpg://fabric_app:fabric_app_dev@localhost:5432/test_N"        # runtime, RLS ON
  export MIGRATION_DATABASE_URL="postgresql+asyncpg://fabric:fabric_dev@localhost:5432/test_N"      # superuser, migrations only
  export JWT_SECRET="kY7mWq2pR9nB4vX8tL6cJ3hF5dG1sZ0aUeImOoPlQwErTyU" ENVIRONMENT=dev REDIS_URL="redis://localhost:6379/0"
  export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib     # WeasyPrint dlopen — backend will not even BOOT without this on macOS
  uv run pytest <files> -q 2>&1 | grep -vE "\"event\"|request_id|latency" | tail -20
'
```

- `env -i` prevents IDE-injected docker hostnames (`postgres:5432`) from leaking in.
- `LOG_LEVEL` accepts only DEBUG/INFO/WARNING/ERROR — `CRITICAL` crashes pydantic-settings.
- Filter the structured JSON request logs out of pytest output or they bury the summary.
- Worktrees: `uv run` auto-creates a per-worktree `.venv` (cached, fast). Complex nested quoting breaks — write scripts to a file and `bash file.sh`, and **run in background** so the 5-min foreground cap and Mac sleep can't kill them.

## Migration gotchas (all hit for real)

- `alembic/env.py` uses `transaction_per_migration=True` (both online+offline). Without it, an enum `ADD VALUE` in one migration + a *later* migration referencing that value fails from-scratch with `UnsafeNewEnumValueUsage` — incremental upgrades hide this; only a from-scratch run exposes it.
- ADD VALUE **and** use in the SAME migration additionally needs `op.get_context().autocommit_block()` around the ADD VALUE.
- An enum→text cast (`col::text`) is STABLE, not IMMUTABLE — it cannot appear in an index predicate. Enum literals can (they're immutable), which is why the env.py fix is the right one.
- Two migrations in one wave → two heads. Linearize before merging the second: edit its `down_revision` to the first's revision id, then verify `alembic heads` shows exactly one.
- `test_migration_smoke` asserts the head **dynamically** via `ScriptDirectory.get_current_head()` — never hardcode a revision there again.
- Pre-flight data guards inside migrations (e.g. #190's dup check) must fail-closed with an actionable message and never mutate data; the repair lives in `schema/patches/*.sql`.

## Stack + CI facts

- Backend boot: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` or WeasyPrint aborts startup (cookbook §1.3's plain uvicorn command lacks it; `make -C backend run` sets it).
- `/auth/signup` is rate-limited **3/hour/IP** — parallel agents exhaust it instantly; reuse existing orgs (demo: `demo@example.com` / `DemoPass123` / "Demo Co") or stagger signups. Prefix throwaway orgs with `QA ` (cookbook §14 purge).
- CI backend-lint = `ruff check . && ruff format --check . && mypy .` over the WHOLE tree including tests. CI drift job compares the committed `frontend/scripts/openapi-snapshot.json` + `src/types/api.ts` against the live app — run `make openapi-snapshot` after any endpoint/schema change and commit both files.
- Full backend suite ≈ 1700 tests / 10 min locally, 18 min in CI. `test_migration_smoke` and `test_orm_ddl_drift` WIPE the schema of whatever DB they point at — never aim them at a DB another agent is using.
