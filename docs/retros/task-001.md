# TASK-001 retro — deviations from plan and pre-TASK-002 checklist

**Date:** 2026-04-24
**Commit:** `1ddc284` (`main`)
**Plan:** `~/.claude/plans/read-claude-md-and-tasks-md-shiny-harp.md`

## Summary

Repo scaffolding landed end-to-end: `make setup && make dev` produces healthy `postgres:16` + `redis:7` + `fastapi` on `:8000/health` + `vite` on `:5173`. Lint/test/typecheck are green. Five small deviations from the written plan; none changed the contract, all were fixes for real-world gaps.

---

## Deviations from plan

### 1. ESLint 9 requires flat config (not `.eslintrc.cjs`)
Plan specified `.eslintrc.cjs`. ESLint 9 (what we installed, per "^9.0.0") refuses legacy configs with a hard error.
- **Fixed by:** deleting `.eslintrc.cjs`, writing `frontend/eslint.config.js` (flat), adding `globals` devDep.
- **Why not caught in planning:** I researched ESLint flat config broadly but didn't check whether v9 *hard-requires* it. It does.
- **Impact on TASK-002..:** zero (backend doesn't use ESLint). Impact on TASK-003: `pnpm lint` works today; any shadcn-installed components will be linted by the flat config.

### 2. Prettier was scanning `pnpm-lock.yaml`
Plan didn't include a `.prettierignore`. Prettier's default is "check everything prettier knows how to format" which includes YAML, so lockfiles get flagged as unformatted.
- **Fixed by:** `frontend/.prettierignore` covering `pnpm-lock.yaml`, `node_modules`, `dist`, build artifacts.
- **Generalization:** any autoformatter added later (black, biome, etc.) needs an ignore list from day 1.

### 3. `docker compose` vs `docker-compose`
Plan used `docker compose` (two words, Docker Desktop v2 plugin convention). On this Mac only the legacy `docker-compose` hyphenated binary is on `$PATH`; the `docker compose` subcommand wasn't wired.
- **Fixed by:** `Makefile` now does `COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")` and all targets call `$(COMPOSE)`.
- **Portable:** works on modern Docker Desktop, Linux with the plugin, and older hyphenated setups.

### 4. `uv` wasn't installed on the machine
Plan assumed uv was available. Brew install failed on `/opt/homebrew` ownership (pre-existing permissions issue on this machine).
- **Fixed by:** Astral's official installer → `~/.local/bin/uv`.
- **`$PATH` caveat:** `~/.local/bin` is not in the default shell `$PATH`. Every Bash invocation in this session needed `export PATH="$HOME/.local/bin:$PATH"` to find `uv`. **TASK-002 will hit this too** unless (a) the install path is added to your shell rc, or (b) uv is reinstalled via brew after fixing homebrew permissions.

### 5. `.env` must exist before `docker compose up`
`docker-compose.yml` references `env_file: .env`. If `.env` doesn't exist, compose errors out (not just a warning).
- **Fixed by:** `make setup` copies `.env.example → .env` if missing. But running `docker compose up` directly (skipping `make setup`) still fails. The Makefile's `dev` target doesn't pre-seed `.env`.
- **Consider for TASK-002:** either add a `dev: setup` dependency (so `make dev` always runs setup first) or make the `env_file` entry optional by using only shell `environment:` declarations. I'd vote for the first — `make setup` is idempotent and fast when deps are already synced.

### 6. `globals` package not transitively available
`eslint.config.js` imports from `globals` (a tiny standard package listing browser/node globals). It's not a transitive dep of any direct dep, so `pnpm add -D globals` was explicit.
- **Now pinned:** `globals@^17.5.0` in `package.json` devDependencies.

### 7. Unexpected `design/` folder in working tree
`design/claude-design-prompt.md` (~20KB) appeared mid-session. Not something I wrote, not on the plan's manifest, so **excluded from the commit**. Still untracked on disk.
- **Decide before TASK-002:** commit it (where? `docs/design-prompt.md`?), move it to `docs/`, or `rm` it. If you keep it at root `design/`, consider updating CLAUDE.md's repo tree so it's not a surprise next session.

---

## Things the plan got right (no deviation)

- **uv PEP 621 layout** with `[project]` + `[dependency-groups].dev` worked on first `uv sync`.
- **Strict mypy from day 1** — zero type errors in the scaffold, no ratcheting needed.
- **Ruff rule set** `E, F, W, I, B, UP, N, S, SIM, RUF` — clean. `S101` ignored globally, `S` ignored in tests. No false positives.
- **Anonymous volume trick** for `frontend/node_modules` prevented host/container `node_modules` collisions; HMR verified.
- **uv binary pinned to `ghcr.io/astral-sh/uv:0.5`** in `backend/Dockerfile.dev` — deterministic builds.
- **CLAUDE.md tree reshuffle** (`docs/` for non-root docs) → all cross-refs updated; no broken links.

---

## Pre-TASK-002 checklist

Order is rough priority (most likely to bite first).

### 1. `$PATH` fix for `uv`
Every new terminal that runs `make` targets needs `uv`. Either:
```zsh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```
…or fix Homebrew permissions and `brew install uv` (then `brew uninstall` the Astral-installed one in `~/.local/bin/`). Pick one; don't run both.

### 2. Git identity
The TASK-001 commit is authored as `Moiz P <moizp@Abduls-MacBook-Pro.local>` (auto-guessed by git). Set your real identity once:
```
git config --global user.name "Moiz …"
git config --global user.email "moiz@…"
```
Past commits won't be rewritten (no `git rebase --reset-author` unless you explicitly want that).

### 3. `make dev` requires Docker Desktop running
No way around this — Docker Desktop is a user app, not a background service. Launch it (`open -a Docker` works) before `make dev`. First build after `make setup` pulls `postgres:16-alpine` + `redis:7-alpine` + builds two images → ~2–4 min. Subsequent starts are fast.

### 4. Health endpoints need to split
Currently `backend/main.py` has one `/health`. Best practice (folded into the plan, deferred to TASK-002):
- `/live` — zero external calls. Kubernetes restarts on fail.
- `/ready` — checks DB + Redis via `asyncio.gather(...)`. Kubernetes routes traffic away on fail.
TASK-002 should land these once `db.py` (async SQLAlchemy engine) and the redis client exist.

### 5. TASK-002 scope reminder
Per `TASKS.md` + `docs/architecture.md`:
- `backend/app/config.py` — pydantic-settings; all env vars typed and validated at startup.
- `backend/app/db.py` — `async_sessionmaker` + engine factory. Do **not** call `create_all()`; migrations own schema (TASK-004).
- `backend/app/middleware/*` — CORS, logging, RLS (`SET LOCAL app.current_org_id`), error handler.
- `backend/app/exceptions.py` — custom exception classes (`InvoiceStateError`, `InsufficientStockError`, etc.).
- `backend/app/dependencies.py` — `get_current_user` + permission check helpers (stubs OK; real auth is TASK-007).
- Update `/health` → `/live` + `/ready`.

Write one integration test per middleware behavior. mypy-strict applies.

### 6. Tailwind v3 / React 18.3 still the literal pin
CLAUDE.md pins "Tailwind 3.4+" and "React 18.3+". Current install: Tailwind 3.4.19, React 18.3.1. shadcn/ui's newer components assume Tailwind v4 + React 19. **If you want to jump before TASK-003**, do it *now* (it's a ~5-minute diff) — not after shadcn components are scattered through the codebase.

### 7. Full CI is still stubbed
`.github/workflows/ci.yml` runs `make lint` only. TASK-005 adds pytest + vitest + Postgres service + deploy. Until then, don't assume CI green == code tested — `make test` locally before merging.

### 8. The `design/` folder question
Decide what to do with `design/claude-design-prompt.md` before it becomes background noise. Three options:
1. `git add design/ && git commit` (keep at root).
2. `git mv design/claude-design-prompt.md docs/` (consolidate with other docs).
3. `rm -rf design/` (if it was a one-off reference).

### 9. Untracked artifacts you'll see locally
- `.env` (gitignored, dev-only; copy of `.env.example`).
- `backend/.venv/` (uv-managed virtualenv).
- `frontend/node_modules/` (pnpm store).
- `__pycache__/`, `.ruff_cache/`, `.mypy_cache/` after first test/lint run.
All covered by root `.gitignore`.

---

## Open flags carried over to next task

1. **Tailwind v4 vs v3.4** decision (deferred from TASK-001 plan).
2. **React 19 vs 18.3** decision (deferred from TASK-001 plan).
3. **shadcn/ui install time** — Tailwind/React decisions above dictate which components work cleanly. TASK-003 work.
4. **`design/` folder disposition** — see checklist item 8.
5. **`dev: setup`** dependency in Makefile — see deviation 5.
