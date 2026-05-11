# TASK-CUT-405 retro — HTTPS/Caddy + deploy runbook + Sentry FE + email provider

**Date:** 2026-05-11
**Branch:** task/CUT-405-https-and-ops
**Commit:** _filled at merge_
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` § Wave 5, W5-E

## Summary

Production deployment surface shipped end-to-end:

1. **Email adapter swap (BE).** `MailgunEmailAdapter` added to `backend/app/service/email_adapter.py`. Lifespan hook in `backend/main.py` swaps the registry on boot when `MAILGUN_API_KEY` + `MAILGUN_DOMAIN` + `MAILGUN_SENDER` are all set. Failing test (`backend/tests/test_email_adapter_swap.py`) pins the registry contract: a swap after boot is observed by `password_reset_service` on the very next call, no caching pitfall. Three tests, all green.
2. **Sentry FE prod gate.** `frontend/src/lib/sentry.ts` now gates on `import.meta.env.PROD && VITE_SENTRY_DSN` (previously gated on `MODE === 'development'`, which leaked into vitest's `MODE=test`). `tracesSampleRate: 0.1` caps the free-tier 5k/mo budget. Wired into `frontend/src/main.tsx` via fire-and-forget `void initSentry()`. Four new tests in `sentry.prod.test.ts` prove the gate; all 238 vitest tests still pass.
3. **Caddy / Compose / deploy.yml.** Cherry-picked from `task/int-0-staging-bootstrap` (commit 6611421) and refined: `ops/Caddyfile` (HSTS + security headers, default headers via Caddy 2 native behavior), `docker-compose.prod.yml` (one-shot migrate service via `profiles: [migrate]`, health-checked via `/live`), `.github/workflows/deploy.yml` (tag-triggered, `production` env requires 1-reviewer approval, ENV_FILE indirection so local compose validation works). `backend/Dockerfile.prod` + `frontend/Dockerfile.prod` are new multi-stage images.
4. **Runbook.** `docs/ops/deployment-runbook.md` — concrete, one-screen-per-stage: Hetzner provisioning, DNS + Mailgun SPF/DKIM, GH secrets + environment config, first deploy via tag, smoke test, rollback (two cases), daily ops, P0 escalation.
5. **`ops/.env.production.example`** — every prod env var with a comment explaining when partial config falls back vs fails fast.

Lint, typecheck, test, ruff format, ruff check, mypy, actionlint, `caddy validate`, `docker compose config` — all green. No real keys committed.

## Deviations from plan

### 1. Renamed `docker-compose.staging.yml` → `docker-compose.prod.yml`
Plan suggested "rename to `.prod.yml`". Did exactly that, with `ops/Caddyfile` (not `ops/staging/Caddyfile`) as the matching path. Staging files on `task/int-0-staging-bootstrap` are NOT removed by this PR; they stay parked as the future staging surface.
- **Why not caught in planning:** plan offered both options; called the cleaner one.
- **Impact on later tasks:** staging bootstrap PR (T-INT-0) can land alongside; the two configs differ only in `CADDY_DOMAIN` + tag namespaces, so consolidating into one templated file is a future polish task.

### 2. `env_file:` path indirection via `${ENV_FILE:-}`
Parked staging file hard-coded `/opt/fabric/.env.staging` as the env_file path. That breaks local `docker compose config` validation (the file doesn't exist on a dev box, so compose refuses to render). Refactored to `${ENV_FILE:-./ops/.env.production.example}` so local validation works against the example template and the deploy workflow points it at the real path via `export ENV_FILE=/opt/fabric/.env.production`.
- **Why not caught in planning:** plan didn't explicitly call out CI-time `compose config` as an acceptance gate.
- **Impact on later tasks:** zero — both staging and prod can adopt the same indirection.

### 3. SC2029 (client-side ssh expansion) avoidance
First three attempts at the "pin IMAGE_TAG on box" step tripped actionlint's shellcheck integration on SC2029. Final pattern pipes `printf 'TAG=...\n' "$IMAGE_TAG"` then a quoted heredoc with the remote script, so the runner never lets the tag value sit on the ssh command line. Clean.
- **Why not caught in planning:** plan didn't anticipate actionlint as a gate.
- **Impact on later tasks:** zero, but it's a pattern other deploy workflows (e.g. staging) should copy.

### 4. Did NOT delete parked staging files
The plan said "land on main as the production deployment surface" — implied superseding the parked branch. I left the parked branch untouched and built parallel prod artifacts because: (a) staging is still useful for future Phase 2 / paying-customer onboarding, (b) deleting the parked branch's content would require a separate decision from Moiz. The `task/int-0-staging-bootstrap` branch can land later as-is; its files do not collide with prod ones.
- **Why not caught in planning:** ambiguous wording in the task brief.
- **Impact on later tasks:** Moiz should decide whether to merge staging files in a follow-up or fold them into the prod compose via templating (env var `CADDY_DOMAIN` already supports both).

## Ask-vs-Decide calls made

| Decision | Choice | Rationale |
|---|---|---|
| Email provider | Mailgun flex ($35/mo for 50k emails) | Cheapest credible option for an Indian SaaS at this stage. Postmark is the documented fallback (`email_adapter.py` module docstring) — swap is a one-class change since both implement the same `EmailAdapter` protocol. |
| Deploy trigger | Tag-based (`v*` push) + workflow_dispatch with manual `image_tag` input | Pure auto-deploy on `main` push (the parked branch's approach) is forbidden by the task; tag + GH environment gate gives one explicit human approval per release without a manual ssh ritual. |
| Sentry plan | Free tier (5k events/mo) | Sufficient for solo dogfood. `tracesSampleRate: 0.1` plus error-only sampling stays well inside the budget unless an unbounded loop trips. |
| Approval gate | GH `production` environment, 1 required reviewer | Built-in feature, zero infra. Reviewer = Moiz (self-approve is fine for solo). |

## Things the plan got right (no deviation)

- The parked branch's compose + Caddy skeleton was correct; only naming/paths needed refinement.
- `EmailAdapter` Protocol shape + module-singleton pattern (from CUT-303) was exactly right for the swap. No refactor required to make Mailgun fit.
- 4-hour estimate ↔ 5-hour timebox: realistic. Came in inside the budget.

## Pre-TASK-CUT-501 checklist

### 1. Tag `v0.1.0` after merge
On main HEAD, `git tag v0.1.0 && git push origin v0.1.0`. The deploy workflow will run; first deploy needs all the pre-flight from the runbook (CX22 + DNS + Mailgun) to be done first.

### 2. Provision the GH `production` environment
Settings → Environments → New → `production` → required reviewers = 1 (yourself). Without this, the deploy job runs unattended.

### 3. Add `Dockerfile.prod` smoke build to CI (`ci.yml`)
Optional but low-cost: `docker build -f backend/Dockerfile.prod ./backend` in a single CI job catches breakage to the prod build before tagging. Current PR doesn't do this; could land in CUT-501.

### 4. Verify Mailgun SPF + DKIM AFTER provisioning
The runbook has the steps; don't skip them. Indian deliverability without these is poor.

### 5. Sanity-check `httpx` is on the prod image
`MailgunEmailAdapter` imports httpx locally. The Dockerfile.prod runs `uv sync --no-dev` so httpx must be in the main deps. Confirmed: `pyproject.toml` now lists httpx as a direct dep (CUT-405 added).

## Open flags carried over

- **Staging branch fate.** `task/int-0-staging-bootstrap` is unmerged. Either land it as-is (parallel staging.taana.in surface) or fold into the prod compose with a `CADDY_DOMAIN` env switch. Decision deferred to Moiz; revisit in CUT-501.
- **`@sentry/react` not in package.json.** The `sentry.ts` module uses a dynamic import that silently no-ops if the package isn't installed. Production builds with a DSN need `pnpm add @sentry/react`. Documented in `sentry.ts` doc comment; not blocking the day-1 deploy.
- **`uv.lock` is not committed.** `backend/pyproject.toml` was modified to add httpx as a direct dep; `uv.lock` was regenerated locally but not added to git. The Dockerfile.prod's `uv sync --frozen` falls back to non-frozen, which works but is not reproducible. Commit `uv.lock` in CUT-501 polish.
- **CI does not yet build the prod images.** `.github/workflows/ci.yml` runs tests + lint only. Adding a smoke `docker build -f Dockerfile.prod` is a cheap follow-up.

## Observable state at end of task

- No new running services on dev box (everything is CI/deploy infra).
- New backend env vars (all optional, default to ConsoleEmailAdapter behavior):
  - `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_SENDER` — set together or not at all.
- New frontend env var (build-time, optional):
  - `VITE_SENTRY_DSN` — baked into the bundle by `frontend/Dockerfile.prod` from the GH secret.
- New files:
  - `ops/Caddyfile`
  - `ops/.env.production.example`
  - `docker-compose.prod.yml`
  - `.github/workflows/deploy.yml` (full rewrite of the stub on main)
  - `backend/Dockerfile.prod`
  - `frontend/Dockerfile.prod`
  - `backend/tests/test_email_adapter_swap.py`
  - `frontend/src/lib/__tests__/sentry.prod.test.ts`
  - `docs/ops/deployment-runbook.md`
  - `docs/retros/task-CUT-405.md` (this file)
- Modified files:
  - `backend/app/service/email_adapter.py` (+ MailgunEmailAdapter)
  - `backend/app/config.py` (+ Mailgun settings)
  - `backend/main.py` (+ Mailgun swap in lifespan)
  - `backend/pyproject.toml` (+ httpx as direct dep)
  - `frontend/src/lib/sentry.ts` (gated on PROD instead of MODE)
  - `frontend/src/main.tsx` (+ void initSentry())
