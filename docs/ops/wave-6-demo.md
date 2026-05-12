# Wave 6 demo — 2026-05-12

**This is the v1 ship gate.** Unlike Waves 1-5 where "demo" meant a ~30-min walk Moiz ran to gate the next wave, **Wave 6's demo IS the cutover itself**, executed for real against Moiz's live Vyapar data. The detailed step-by-step lives in `docs/ops/cutover-runbook.md` (CUT-502, 562 lines). This doc is the cover sheet: what landed in Wave 6, how to confirm it's ready, and the criterion for v1 sign-off.

## What landed in Wave 6

| PR | Title | Closes |
|---|---|---|
| #91 | TASK-CUT-502: cutover runbook | `docs/ops/cutover-runbook.md` — T-7/T-1 pre-flight + H-Hour timed sequence + 7-day soak monitor + rollback decision tree + sign-off block |
| #92 | TASK-CUT-501c: ops + docs hygiene closeout | `@sentry/react`+`@sentry/tracing` installed; CI prod-Dockerfile smoke build job; backup hard-fail flag (`BACKUP_FAIL_PLAINTEXT=1` defaulted on in `.env.production.example`); TASKS.md full Wave-1-through-5 sync; agent-prompt-template gained 3 coordination memos |
| #93 | TASK-CUT-501b: banking exports + invite UX doc | AccountingHub bank-accounts + cheques tabs gained CSV/Excel Export buttons (PII decrypted before export, Indian-style number formatting); deployment-runbook gained §11 documenting the v1 redirect-to-/login choice over auto-login |
| #94 | TASK-CUT-503: acceptance Playwright suite | `frontend/__tests__/e2e/cutover.spec.ts` — single continuous Playwright spec running the Wave-1-through-5 demos end-to-end against a real docker-compose stack; new CI `e2e-acceptance` job |
| #95 | TASK-CUT-501a: rate-limit /auth/forgot + token cleanup | Redis sliding-window rate-limit (5 req/60s/IP) on `/auth/forgot` with `Retry-After` header; `make cleanup` Make target + cron line in deployment-runbook for daily `password_reset_token` cleanup |

## Pre-cutover readiness check

Run these BEFORE the first H-Hour to confirm the surface is intact. Each item should be one or two commands, not minutes of investigation.

1. **`origin/main` HEAD** matches `98cf17f` (the merge commit for #94) or newer.
2. **Alembic chain** is linear; head = `task_cut_402_user_migration` (no new migrations after Wave 5):
   ```bash
   cd backend && uv run alembic heads
   # Expect single line: task_cut_402_user_migration (head)
   ```
3. **BE + FE tests green** locally:
   ```bash
   cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
   # Expect: 153 passed, 667 skipped (skipped require live DB env)
   cd frontend && pnpm exec vitest run && pnpm tsc --noEmit && pnpm check:types
   # Expect: 252 tests passed, 0 fail, no type/codegen drift
   ```
4. **CI is green** on `main`'s latest commit (every job, including the new `e2e-acceptance` + `prod-docker-smoke`):
   ```bash
   gh run list --branch main --limit 1
   # Expect: latest run is "completed" with all jobs green
   ```
5. **Acceptance Playwright suite** runs end-to-end against your local stack:
   ```bash
   docker compose up -d --build
   # Wait for /ready
   curl -sf http://localhost:8000/ready
   curl -sf http://localhost:5173/
   cd frontend && E2E_RUN_CUTOVER=1 pnpm exec playwright test cutover.spec.ts
   # Expect: 1 test passed (Wave 1-5 cutover scenario)
   ```
6. **Rate-limit smoke**:
   ```bash
   for i in $(seq 1 6); do
     curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/auth/forgot \
       -H 'Content-Type: application/json' \
       -d '{"email":"smoke@example.com"}'
   done
   # Expect: 200 200 200 200 200 429 (6th is rate-limited)
   ```
7. **Backup script hard-fails** when `BACKUP_FAIL_PLAINTEXT=1` and no passphrase:
   ```bash
   BACKUP_FAIL_PLAINTEXT=1 BACKUP_GPG_PASSPHRASE= bash ops/backup.sh ; echo "exit=$?"
   # Expect: non-zero exit, no plaintext .sql.gz left in ops/backups/
   ```
8. **All deployment artifacts validate**:
   ```bash
   docker compose -f docker-compose.prod.yml config > /dev/null && echo "compose OK"
   caddy validate --config ops/Caddyfile || echo "(install caddy to run)"
   actionlint .github/workflows/ci.yml .github/workflows/deploy.yml || echo "(install actionlint)"
   shellcheck ops/backup.sh ops/restore.sh
   ```

If every item passes: the surface is ready. Open `docs/ops/cutover-runbook.md` and start the T-7 checklist.

## Known carry-overs from Wave-5 (NOT blockers for cutover)

These came out of the CUT-502 runbook write-up and are documented in the runbook's "Operational gotchas" section. They're operator-manual workarounds, not v1 blockers:

- **Vyapar adapter imports parties + AR/AP opening balances only.** Cash-on-hand, bank balances, and capital openings are NOT imported — the operator posts those as manual opening-balance vouchers on cutover day. The runbook §3 walks this.
- **GSTR-1 tab in `/reports` renders a coming-soon panel** in live mode. The Wave-5 CUT-403 exporter ships the data (multi-sheet xlsx via `/reports/gstr1?format=xlsx`); the FE tab itself is the gap. Filing as a polish follow-up.
- **`/inventory` SOH refresh lags after stock-adjust** — operator reads from `/reports/stock-summary` (CUT-403 wired) instead. Filed in the CUT-204 retro.
- **No automated TB-vs-Vyapar diff during soak** — operator does the comparison by hand from the two systems' TB reports. Manual but not high-friction at v1 scale.
- **No `make rollback-to-morning` shortcut** — six stress-time operator commands documented in the runbook §7. Acceptable for v1; bundle into a follow-up if cutover stress reveals demand.
- **No backend error capture independent of Sentry FE** — acceptable for v1 (no async workers yet to error out independently); revisit when Celery lands.
- **`task/int-0-staging-bootstrap` parked branch** — content superseded by CUT-405's prod artifacts; safe to delete after cutover. Requires Moiz confirmation per repo policy.

## v1 ship criterion

From CLAUDE.md and the cutover plan:

> **v1 done = Moiz has been operating Fabric for 7 consecutive days without falling back to Vyapar.**
>
> Acceptance: 7 consecutive days, real data, zero P0/P1 bugs filed.

If the soak passes: tag `v0.1.0`, run the GH-environment-approved deploy, monitor day 8. If a P0 lands during soak: file it, fix it, the soak clock resets (per the cutover plan's risk register).

## Sign-off

- Cutover date: ____________
- Day-7 sign-off (Moiz): ⬜ pass / ⬜ rolled back / ⬜ rescheduled
- v1 tagged at: ____________
- Friendly-customer-trial milestone (per cutover plan §"deferred"): revisit after Day-7 pass.
