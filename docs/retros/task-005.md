# TASK-005 retro — deviations from plan and pre-next checklist

**Date:** 2026-04-25
**Branch:** task/005-github-actions-ci
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 1)

## Summary

Replaced the TASK-001 stub `ci.yml` (single `lint` job) with four parallel jobs — `backend-lint`, `backend-test`, `frontend-lint`, `frontend-test` — plus a `deploy.yml` stub gated on semver tags. Postgres 16 service container with health-check is wired into `backend-test`; `DATABASE_URL` exposes `postgresql+asyncpg://...` per the `asyncpg` dep in `pyproject.toml`. Both `uv` and `pnpm` caches use the official actions (`astral-sh/setup-uv@v5`, `pnpm/action-setup@v4` + `actions/setup-node@v4` with `cache: pnpm`). `fail-fast: false` at the job level so all four jobs surface their status independently in the PR UI. Triggers cover `push` and `pull_request` on every branch (`'**'`). Concurrency group cancels superseded runs on the same ref. README gets a CI badge with `<owner>/<repo>` placeholders pending the GitHub repo URL.

YAML authored against the GitHub Actions schema; not validated by `actionlint` locally (not installed). No code execution against GitHub — branch is not pushed.

## Deviations from plan

### 1. Wave-1 parallel-agent approach blocked by sandbox; conductor delivered directly

The grand plan §1 calls for Wave 1 to ship via four parallel Tier-2 agents in isolated git worktrees. All four agents (TASK-002/003/004/005) returned blocked: every `Bash` (beyond a small read-only allowlist), `Edit`, and `Write` call hit `Permission has been denied`. Auto-accept mode on the main session did not propagate to background subagent worktrees.

- **Fixed by:** the conductor (main session) executed each Wave-1 task directly in sequence, using the captured research and design artifacts from the blocked agents. TASK-005 was first because the agent had pre-drafted the full file contents.
- **Why not caught in planning:** assumed subagent worktrees inherit user's permission profile. Reality: background subagents auto-deny risky tools because they cannot prompt the user.
- **Impact on later tasks:** TASK-002, 003, 004 are now also delivered directly in the same session. Plan §10 (parallel-merge policy) becomes moot for Wave 1; serial-merge is used. Future waves where parallelism actually pays should either drop `isolation: "worktree"` or add explicit subagent tool grants in `.claude/settings.json`.

### 2. mypy step guarded behind `[ -d app ]`

`backend/app/` lands in TASK-002, which in this session is being delivered AFTER TASK-005. To keep CI green on the TASK-005 commit and on any commit before TASK-002 merges, the `mypy` step prints a skip message rather than failing. Once TASK-002 lands on `main`, the guard becomes a no-op and can be removed in a follow-up cleanup.

- **Fixed by:** shell `if [ -d app ]` wrapper.
- **Impact on later tasks:** zero. Drop the guard whenever convenient post-TASK-002.

### 3. pytest skips gracefully when no tests are collected

`backend/tests/` currently has only a placeholder `test_health.py`. To avoid a red CI on the TASK-005 commit when the test surface is minimal, a two-pass shell snippet (`pytest --collect-only` first; rc=5 → green skip) gates the real run.

- **Fixed by:** `Detect tests, then run pytest` step.
- **Impact on later tasks:** zero. Once tests land, `--collect-only` simply succeeds and the real run executes.

### 4. Playwright deferred to a future workflow

Brief said skip Playwright in CI for now. Noted in the `vitest` step that `e2e.yml` is the future home (likely TASK-068 or a Phase-2 task). Not landed here.

### 5. README badge uses `<owner>/<repo>` placeholders

GitHub repo URL not yet known. HTML comment in README documents the TODO.

## Things the plan got right (no deviation)

- `astral-sh/setup-uv@v5` + `enable-cache: true` is the official Astral pattern; minimal config.
- `pnpm/action-setup@v4` + `actions/setup-node@v4` with `cache: 'pnpm'` is the pnpm-recommended pair.
- Postgres `services:` with `pg_isready` health-check is the canonical GitHub example.
- `fail-fast: false` applies even with no matrix; harmless and self-documenting.
- Concurrency group with `cancel-in-progress: true` is the right default for branch-push CI.

## Pre-next-task checklist

Ordered by what will bite first.

### 1. First push will validate the YAML

YAML correctness is theoretical until a commit lands and the workflow runs. After this branch is pushed (or merged to main), confirm in GitHub Actions UI:
- All four jobs start in parallel.
- `backend-lint` is green (no `app/` yet → mypy skip prints, ruff runs against existing tests/conftest).
- `backend-test` is green (services container starts; pytest skips with "No tests collected").
- `frontend-lint` is green (eslint + prettier + tsc-noEmit on existing scaffold).
- `frontend-test` is green (`vitest run --passWithNoTests`).

### 2. Fix the README badge URL

After first push, replace `<owner>/<repo>` in README.md with the real GitHub path.

### 3. Drop the mypy guard once TASK-002 merges

Two-line edit in `ci.yml`. Remove the `if [ -d app ]` wrapper. Only do it after `backend/app/` is on `main`.

### 4. Decide on branch protection rules

Once green, GitHub → Settings → Branches → require `backend-lint`, `backend-test`, `frontend-lint`, `frontend-test` to pass before merge to `main`. This is the actual gate for Moiz's "no merge without CI green" rule. Not part of TASK-005 (UI setting, not code), but worth a 2-minute step right after the first green run.

### 5. Coordinate with TASK-004 (DDL + Alembic)

TASK-004 will likely need an `alembic upgrade head` step before pytest in `backend-test`. Insert it as a new step between "Install backend deps" and "Detect tests, then run pytest". `DATABASE_URL` is already in scope.

### 6. Subagent permission policy decision

If we want Tier-2/Tier-3 parallelism to work in future waves, decide on one of:
- Add `permissions` block to `.claude/settings.json` allowlisting Bash/Edit/Write for subagents.
- Switch session permission mode such that subagents inherit (e.g., `bypassPermissions` or a richer allowlist).
- Drop `isolation: "worktree"` so agents work in main checkout and inherit user perms.
- Or accept that Wave-shape work is conductor-direct only, and reserve subagents for read-only research / cross-cutting audits.

## Open flags carried over

1. **`actionlint` not installed locally** — first GitHub Actions run is the real validator.
2. **e2e.yml** — Playwright workflow deferred. Separate task or fold into TASK-068.
3. **mypy guard** — TODO post-TASK-002.
4. **Subagent permission profile** — see checklist item 6.
5. **GitHub repo URL** — needed for README badge fix.

## Observable state at end of task

- `.github/workflows/ci.yml` — replaced (4 jobs, services, caches, fail-fast: false, all-branch triggers, concurrency group).
- `.github/workflows/deploy.yml` — new stub (semver-tag trigger; placeholder echos).
- `README.md` — CI badge added with placeholder URL.
- `docs/retros/task-005.md` — this file.
- No new tests added (CI itself is the deliverable; verification happens on first GitHub run).
- Branch `task/005-github-actions-ci` exists locally; not pushed.
