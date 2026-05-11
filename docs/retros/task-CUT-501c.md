# TASK-CUT-501c retro — Ops + docs hygiene closeout

**Date:** 2026-05-11
**Branch:** task/CUT-501c-ops-docs-hygiene
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` § Wave 5 spawn rationale + post-Wave-5 follow-ups
**Parent tasks closed out:** CUT-404 (backup plaintext-fallback open flag), CUT-405 (Sentry React dep + prod-Docker CI smoke open flags)

## Summary

Five small fixes captured in one PR, each addressing a specific open flag from the Wave 4-5 retros:

1. **`@sentry/react` + `@sentry/tracing` added to `frontend/package.json` + `pnpm-lock.yaml`.** `frontend/src/lib/sentry.ts` had a dynamic import behind a string variable specifically so the dep could be missing during dev. The PR-405 retro carried that as an open flag against day-1 prod deploy. Resolved: `pnpm install` now resolves both deps; the existing dynamic-import + `PROD && VITE_SENTRY_DSN` gate is untouched. No prod-runtime behavior change in dev/CI builds (gate still off).

2. **CI prod-Dockerfile smoke build job.** New `prod-docker-smoke` job in `.github/workflows/ci.yml` builds `backend/Dockerfile.prod` and `frontend/Dockerfile.prod` on every PR. Uses `docker/build-push-action@v6` with the GHA cache backend so subsequent runs are ~30s. Catches regressions like a missing apt dep or a `tsc --noEmit` break in the frontend build before they reach a tag-triggered deploy. PR-405's retro filed this as a "low-cost follow-up"; now it's load-bearing.

3. **Backup hard-fail on missing `BACKUP_GPG_PASSPHRASE` when `BACKUP_FAIL_PLAINTEXT=1`.** `ops/backup.sh` previously warned + shipped plaintext when no passphrase was set. Prod can't tolerate that. New flag-gated branch exits 1 with a clear error message; `ops/.env.production.example` defaults the flag to `1` so the prod box is hard-fail by default. Dev/CI leave the flag unset → warn-and-continue stays the path of least resistance for local testing. `tests/test_backup.sh` gained two new steps: step 6 verifies the hard-fail (exit code non-zero, error message names the flag, no plaintext artefact leaks under `$BACKUP_DIR`); step 7 verifies the warn-and-continue path still produces a plaintext `.sql.gz` when the flag is unset. Both run under the existing CI postgres service container.

4. **TASKS.md full sync.** Wave 1 through Wave 5 tables all show every merged TASK-CUT-NNN as Done with its PR number. Hot-fixes (CUT-107, CUT-108, CUT-206) now appear in their wave's table instead of living only in the cutover-plan status board. Demo gate notes for each wave were also updated (Wave 1 closed via Wave 2 demo; Wave 2/3/4 demos passed; Wave 5 demo pending Moiz walk). Re-classification matrix at the top of TASKS.md is unchanged — it was already current. The new CUT-501c row sits at the top of the Wave 6 table.

5. **Agent prompt template gained three sections.** Appended to `docs/ops/agent-prompt-template.md`:
   - **Worktree hygiene** — absolute paths inside the worktree on every `Bash` call; first call is `pwd`. Surfaces the drift bug seen in Wave 4 + Wave 5.
   - **Migration chain coordination** — what the second-to-merge agent must do when two parallel agents both added migrations off the same parent. Includes the `Revises:` + `down_revision` + smoke-test head-assertion update sequence.
   - **Codegen-drift resolution** — when rebase surfaces conflicts in `openapi-snapshot.json` + `src/types/api.ts`, take main's version, regenerate from BE via `dump-openapi.py`, re-run `pnpm gen:types`. Never hand-edit.

## Deviations from plan

### 1. CUT-007 (`make dev-restart`) was NOT folded into this PR
The task brief offered it as an optional fold-in. I chose not to — CUT-007 touches the dev loop (a real ergonomic fix), not Wave 4-5 closeout. Mixing it in would make this PR harder to revert if any one of the five fixes turned out controversial. Filed as still-Ready in TASKS.md under its existing entry; it can pick up as a standalone PR.

### 2. Did NOT update `frontend/src/lib/sentry.ts` to swap dynamic import for static
The retro for CUT-405 hinted at this as a follow-up. I deliberately left the dynamic import in place because:
- The PROD gate guards against accidental dev/CI invocation; the dynamic import was the second line of defence.
- Swapping to a static import would change the bundle size profile and could surface a transitive-deps issue with `@sentry/tracing` (which is in maintenance mode upstream).
- The task brief says "the existing dynamic import + prod-gate stays" — explicit.

### 3. Added two test steps (step 6 + step 7) rather than one
The brief says "verify the hard-fail path with a test case." A single test of the hard-fail path leaves a gap: a future refactor could break the warn-and-continue default and the test would still pass. Step 7 pins the warn behavior so the default stays the default. Two short test steps, one assertion focus each.

## Ask-vs-Decide calls made

| Decision | Choice | Rationale |
|---|---|---|
| Delete `task/int-0-staging-bootstrap`? | STOPPED — filed as follow-up below | Destructive; requires Moiz confirmation per the task brief. |
| Sentry-tracing version | `^7.120.4` (whatever `pnpm add` resolved) | Newer `@sentry/react` 10.x already bundles tracing; adding the legacy `@sentry/tracing` package keeps the dynamic-import path's API expectations stable. Future cleanup can drop it when `lib/sentry.ts` static-imports. |
| `prod-docker-smoke` should run on every PR or only on touched paths? | Every PR | Cost is ~30s with cache; the regression risk it protects is a tag-triggered deploy failure that costs hours. Cheap insurance. |
| Backup hard-fail flag default in dev | Unset (warn-and-continue) | Matches CI's expectations; matches the test scaffolding. Prod opts in via `ops/.env.production.example`. |
| Wave 1 demo gate copy in TASKS.md | "Superseded by Wave 2 demo" | Truthful — Moiz never ran the Wave 1 demo separately; Wave 2 absorbed it. The plan's status board already says this; TASKS.md was lagging. |

## Pre-next-task checklist

### 1. Tag `v0.1.0` after this PR merges
Same as CUT-405's checklist — still pending. The deploy workflow's prod-Docker smoke is now gated by CI green on this PR. Tag after that.

### 2. CUT-007 (`make dev-restart`) is unblocked
Pick it up next or fold into CUT-501 polish. The shell-leaked-env foot-gun is documented but not fixed.

### 3. CUT-501 (the "real" closeout) is still open
This PR is CUT-501c — the **c** subset (Sentry deps + Docker CI smoke + backup hard-fail + TASKS sync + agent-prompt memos). The full CUT-501 closeout covers all Wave 1-5 demo follow-ups (the amber items in each `wave-N-demo.md`). Hold until Wave 5 demo walk completes; some Wave 5 ambers may merge into CUT-501.

## Open flags carried over

- **`task/int-0-staging-bootstrap` branch fate.** Inherited from CUT-405's open flags; still unresolved. Either land as parallel staging surface, fold into prod compose via `CADDY_DOMAIN` env switch, or delete. Decision deferred to Moiz. This PR adds NO new dependency on that branch — it neither cherry-picks nor deletes.
- **`uv.lock` commit hygiene.** Inherited from CUT-405; not in scope for this PR. The prod-Docker smoke build will catch a `uv.lock` drift via `uv sync --frozen` if one ever sneaks in.
- **CI prod-Docker smoke caching strategy.** Used `type=gha` for now; if cache eviction becomes annoying we can swap to `type=registry,ref=...` against a GHCR cache image. No action needed unless cache miss rate becomes a CI-time pain point.
- **Sentry source-map upload.** Not configured. Stack traces in prod will show minified line numbers. A `sentry-cli sourcemaps upload` step in `deploy.yml` is the right home; out of scope for CUT-501c.
- **`@sentry/tracing` legacy package.** Sentry 8+ migrated tracing into `@sentry/react` directly. The legacy package is on `^7.120.4` and will eventually be archived. When `lib/sentry.ts` switches to static imports, drop `@sentry/tracing` and use `@sentry/react`'s built-in tracing instead.

## Observable state at end of task

- Branch: `task/CUT-501c-ops-docs-hygiene`. PR title: `TASK-CUT-501c: ops + docs hygiene closeout`.
- New files: `docs/retros/task-CUT-501c.md` (this one).
- Modified files:
  - `.github/workflows/ci.yml` (+ `prod-docker-smoke` job)
  - `frontend/package.json` (+ `@sentry/react`, `@sentry/tracing` deps)
  - `frontend/pnpm-lock.yaml` (regenerated; +346 transitive lines)
  - `ops/backup.sh` (+ `BACKUP_FAIL_PLAINTEXT=1` hard-fail branch + docstring entry)
  - `ops/.env.production.example` (+ `BACKUP_FAIL_PLAINTEXT=1` with explanatory comment)
  - `tests/test_backup.sh` (+ step 6 hard-fail test, + step 7 warn-and-continue test, renamed final banner)
  - `TASKS.md` (full Wave 1-5 sync; Wave 6 row for CUT-501c)
  - `docs/ops/agent-prompt-template.md` (+ Worktree hygiene, + Migration chain coordination, + Codegen-drift resolution sections)
- No new running services. No DB schema changes. No new env vars to wire up on dev.
- Prod box reading `ops/.env.production.example` will pick up `BACKUP_FAIL_PLAINTEXT=1` only when it's copied to `.env.production` and re-sourced; existing `.env.backup` on the box is untouched.

## Time-box

3 hours allotted; came in inside the budget (closer to 90 min of focused work + verification). Most of the time was reading retros + cutover plan + TASKS.md to scope the sync correctly. Implementation was small per fix; the test-scaffold extension was the most subtle piece (env-i isolation to confirm the hard-fail path doesn't read stray passphrases from the test's outer env).
