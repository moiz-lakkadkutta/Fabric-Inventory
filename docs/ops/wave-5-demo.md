# Wave 5 demo — 2026-05-11

**Time to run:** ~30 min in browser + ~10 min terminal.
**Pass criterion:** every step returns the expected outcome with no extra console errors. The wave's headline outcomes are (a) the textile-specific job-work tracker is live, (b) Moiz can import his Vyapar export and reconcile against TB, (c) every list/report has CSV+Excel export, (d) `make backup` round-trips through a bucket, and (e) production deployment artifacts (Caddy/HTTPS, deploy.yml, Sentry FE, Mailgun email adapter) are ready.
**Amber:** unexpected behavior that doesn't block the wave's goal — file follow-up TASK-CUT-NNN.
**Red:** any step fails outright OR a P0/P1 regresses — wave does not pass; spawn fix-agent.

## What landed in Wave 5

| PR | Title | Closes |
|---|---|---|
| #85 | TASK-CUT-401: Job-work FE wired live | `/jobwork` (textile send-out / receive-back / karigar cards) |
| #86 | TASK-CUT-404: Backups + cron + restore runbook | `make backup` + `make restore` + B2 cloud target + 7-day retention + weekly CI round-trip |
| #87 | TASK-CUT-405: HTTPS/Caddy + deploy runbook + Sentry FE + email provider | `ops/Caddyfile`, `docker-compose.prod.yml`, `.github/workflows/deploy.yml` (tag-triggered, GH-environment manual approval), `MailgunEmailAdapter`, Sentry FE prod-gate |
| #88 | TASK-CUT-403: CSV/Excel export per list | `?format=csv\|xlsx` on every list endpoint + multi-sheet GSTR-1 xlsx; FE Export buttons wired |
| #89 | TASK-CUT-402: Vyapar adapter + migration upload | `/admin/migrations` upload + reconciliation + Owner-approval flow; opening-balance posting; `user_migration` table |

Linear Alembic chain after the wave: `task_cut_105 → task_cut_104 → task_cut_303_pw_reset → task_cut_305_jobwork → task_cut_304_user_invite → task_cut_402_user_migration` (HEAD).

## Pre-flight (do this once)

- [ ] `git pull --ff-only origin main` — land at `2c44eeb`.
- [ ] **Run new Alembic migration** (CUT-402 added `user_migration` table):
  ```bash
  cd backend
  env -u DATABASE_URL MIGRATION_DATABASE_URL=postgresql+asyncpg://fabric:fabric_dev@localhost:5432/fabric_erp \
    uv run alembic upgrade head
  # Expect: head = task_cut_402_user_migration
  ```
- [ ] **macOS WeasyPrint libs** (still required from Wave 3 for PDF render):
  ```bash
  brew install pango cairo harfbuzz fontconfig fonts-noto || true
  export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH
  ```
- [ ] **Restart `:8000` uvicorn cleanly** (env-strip per CUT-007 hot-fix):
  ```bash
  cd backend
  env -u DATABASE_URL -u MIGRATION_DATABASE_URL -u REDIS_URL \
    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
    uv run uvicorn main:app --reload --port 8000
  ```
  Confirm: `curl -s http://localhost:8000/admin/migrations` returns a 401 envelope (proves the new migrations router is registered).
- [ ] **Tail uvicorn log** for the dev `ConsoleEmailAdapter` lines (still the default; Mailgun swaps in only when prod env is set):
  ```bash
  tail -f /tmp/uvicorn-*.log
  ```
- [ ] Restart Vite dev server: `cd frontend && pnpm dev`.
- [ ] Open a fresh **incognito** browser at the running dev port.
- [ ] DevTools → Network + Console open. Clear before each step.
- [ ] **Carry-over data:** sign in to the demo account that has parties + items + a finalized invoice + a receipt. Wave-5 doesn't require Wave-3 PO/GRN chain but uses inventory data for job-work send-outs.

## Steps

### 1. Job-work send-out → receive-back (CUT-401) — textile headline

1. Visit `/jobwork`. Page renders the active jobs table (live list from `GET /job-work-orders`) + karigar cards. With zero data, both render empty states, not Coming-soon modals.
2. Click `+ Send out`. Pick the Cotton Suit item, qty 100, uom METER, karigar party (any party with `is_supplier=true` works), operation = "Embroidery". Save.
3. Network: `POST /job-work-orders` returns 201 with new `jwo_id`. Active jobs table refetches; new row visible.
4. Click `Receive back` on the new row. Enter finished 95, wastage 5. Save.
5. Network: `POST /job-work-orders/{id}/receive` returns 201. Row updates / moves to "Completed" view.
6. Karigar cards now group by `party_id` and show "0 pending" against that karigar (100 sent − 95 finished − 5 wastage = 0).
7. **Negative path:** open Receive back again; try to receive 110 (more than the open qty). UI blocks with the client-side `received + wastage ≤ open qty` invariant.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 2. ITC-04 BE smoke (CUT-401 + CUT-305 follow-on)

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen | tr A-Z a-z)" \
  -d '{"email":"YOUR@EMAIL","password":"YOUR_PASSWORD","org_name":"YOUR_ORG"}' \
  | jq -r '.access_token')

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/reports/itc04?period=$(date -u +%Y-%m)" | jq 'keys'
# Expect: ["challan_summary", "outward", "inward", "period", ...] per CUT-305's schema.
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 3. Vyapar import — the migration headline (CUT-402)

The test fixture `backend/tests/fixtures/vyapar-sample.xlsx` is synthetic — re-use it (or upload your real Vyapar export, encrypted via Fabric's TLS).

1. As Owner, visit `/admin/migrations` (new in Wave 5). See empty list.
2. Click `+ Upload migration`. Pick the fixture xlsx. Submit.
3. Network: `POST /admin/migrations` (multipart) returns 201 with `migration_id` + a reconciliation report payload. UI renders the reconciliation summary:
   - X parties found (Y matched against existing, Z new).
   - Opening-TB DR == CR (balanced invariant).
   - Pre-import TB vs post-import-TB diff (target ≤ ₹1).
4. Click `Approve`. Network: `POST /admin/migrations/{id}/approve` returns 200. Status flips to APPROVED.
5. Visit `/masters/parties`. The new parties from the fixture appear with their opening balances reflected in their AR/AP rows.
6. Visit `/accounting` → Vouchers tab. One compound journal voucher exists, dated 1 day before the migration, labeled "Opening Balances - imported from Vyapar". DR == CR.
7. **Negative path:** upload again with the same fixture. Reconciliation reports "0 new parties; all already imported". Approve is a no-op (idempotent) OR returns a clear error — verify which path the CUT-402 retro documents.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 4. CSV + Excel exports across every list (CUT-403) — the operator headline

Walk each list / report:

1. **Invoices** (`/sales/invoices`): click `Export CSV`. Download triggers. Open in Excel — ₹ renders cleanly (UTF-8 BOM honored). Re-click `Export Excel` — `.xlsx` downloads. Cells use real number/date types (not strings).
2. **Parties** (`/masters/parties`): both formats download.
3. **Items** (`/masters/items`): both formats.
4. **Receipts** (`/accounting` → Receipts tab): both formats.
5. **Vouchers** (`/accounting` → Vouchers tab): both formats.
6. **Reports** (`/reports`):
   - P&L tab: both formats.
   - TB tab: both formats.
   - Daybook tab: both formats.
   - Stock summary tab: both formats.
   - **GSTR-1 tab**: CSV button is disabled (canonical filing is multi-sheet xlsx); xlsx download has 5 sheets — B2B, B2CL, B2CS, Export, HSN.
7. **Negative path:** sign out + re-login as a user without `accounting.report.view`. Export buttons on Reports return 403 envelopes.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 5. Backup → bucket → restore round-trip (CUT-404)

Skip if your dev box doesn't have B2 (or another S3-compatible) credentials wired — the script falls back to local-only with a loud warning.

```bash
cd /Users/moizp/fabric

# One-shot backup (uses ops/.env.backup if present):
make backup
ls -lh ops/backups/ | tail -3
# Expect: today's *.sql.gz.gpg with non-zero size

# Dry-run restore (lists steps without executing):
make restore date=$(date -u +%Y-%m-%d) dry_run=1

# Real restore into a sibling DB to prove round-trip:
make restore date=$(date -u +%Y-%m-%d) target_db=fabric_erp_restore_test

# Confirm a sentinel row survived:
psql postgresql://fabric:fabric_dev@localhost:5432/fabric_erp_restore_test \
  -c "SELECT count(*) FROM party WHERE deleted_at IS NULL"
# Expect: matches the count in fabric_erp.

# Cleanup the sibling DB:
psql postgresql://fabric:fabric_dev@localhost:5432/postgres \
  -c "DROP DATABASE fabric_erp_restore_test"
```

If B2 is configured (`ops/.env.backup` populated with `B2_BUCKET` + creds):

```bash
# Confirm today's encrypted dump landed in the bucket:
b2 ls "$B2_BUCKET" | grep $(date -u +%Y%m%d) | head -3
# Expect: one *.sql.gz.gpg of today's date.
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 6. Deployment artifacts validate (CUT-405)

```bash
cd /Users/moizp/fabric

# Caddyfile syntax:
caddy validate --config ops/Caddyfile || echo "(install caddy locally to run this)"

# Compose syntax:
docker compose -f docker-compose.prod.yml config > /dev/null && echo "compose ok"

# Deploy workflow lint:
actionlint .github/workflows/deploy.yml || echo "(install actionlint to run this)"

# Verify the workflow has the manual-approval gate:
grep -A2 "environment:" .github/workflows/deploy.yml | head -5
# Expect: environment: production
#         (which on GH has 1 required-reviewer set per the runbook)
```

Read `docs/ops/deployment-runbook.md` end-to-end — sanity-check that:
- Hetzner CX22 provisioning steps are concrete (not "see Hetzner docs").
- DNS + SPF + DKIM steps for Mailgun are spelled out.
- GH-secrets list is exhaustive.
- Rollback procedure has TWO documented flows (re-deploy previous tag; manual ssh + compose-down + image-revert).

✅ pass / ❌ fail / ⚠️ amber: ___________

### 7. Sentry FE prod-gate (CUT-405)

```bash
# Vitest proves the gate in test mode (Sentry must NOT initialize):
cd frontend
pnpm exec vitest run src/lib/__tests__/sentry.prod.test.ts
# Expect: 4 tests pass.
```

Manually verify in dev that Sentry does NOT fire:
1. Open DevTools Network tab on the running `pnpm dev` build.
2. Trigger a frontend error (e.g., visit a non-existent route — `/garbage`).
3. Confirm NO `POST` to `*.sentry.io` or similar. (The gate `import.meta.env.PROD && VITE_SENTRY_DSN` keeps Sentry quiet in dev/test.)

To prove the gate the OTHER direction, build prod locally:

```bash
cd frontend
VITE_SENTRY_DSN="https://fake-dsn@example.ingest.sentry.io/0" pnpm run build
grep -l "sentry" dist/assets/*.js | head -2
# Expect: at least one bundle mentions sentry (proves the gate compiled it in).
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 8. Email adapter swap (CUT-405 + CUT-303 follow-on)

```bash
cd /Users/moizp/fabric/backend

# Unit test pins the swap registry semantics:
uv run pytest tests/test_email_adapter_swap.py -v
# Expect: 3 tests pass.

# Confirm dev still uses ConsoleEmailAdapter (no MAILGUN_API_KEY env):
unset MAILGUN_API_KEY MAILGUN_DOMAIN MAILGUN_SENDER
uv run python -c "
from app.service.email_adapter import get_email_adapter
print(type(get_email_adapter()).__name__)
"
# Expect: ConsoleEmailAdapter

# Confirm Mailgun adapter loads when all three env vars are set:
MAILGUN_API_KEY=fake MAILGUN_DOMAIN=fake.com MAILGUN_SENDER=ops@fake.com \
uv run python -c "
from app.main import _swap_email_adapter_from_env
from app.service.email_adapter import get_email_adapter
_swap_email_adapter_from_env()
print(type(get_email_adapter()).__name__)
"
# Expect: MailgunEmailAdapter
```

(The actual Mailgun POST is NOT exercised in dev — that requires real creds. The runbook step `Initial Mailgun smoke test` is the one Moiz runs on the production box.)

✅ pass / ❌ fail / ⚠️ amber: ___________

### 9. Post-merge integration verification (already executed)

For the record, after the wave's last merge (PR #89), on a fresh checkout of `origin/main`:

- `cd backend && uv run ruff check . && uv run ruff format --check .` — clean.
- `cd backend && uv run pytest -q` — 150 passed (655 skipped require live DB env vars).
- `cd frontend && pnpm exec vitest run` — 56 files / 250 tests pass.
- `cd frontend && pnpm tsc --noEmit && pnpm exec eslint . && pnpm exec prettier --check .` — clean.
- `cd frontend && pnpm check:types` — no OpenAPI drift.
- Alembic chain: linear, head = `task_cut_402_user_migration`.

Wave 5 grew the BE pytest count from 128 → 150 (+22; the rest are integration tests gated on the CI Postgres service) and the FE vitest count from 234 → 250 (+16 across 4 new test files).

## Follow-ups (amber)

- [ ] _CUT-401 retro: receive-back is per-row (not a header CTA); revisit if the karigar workflow grows multi-line._
- [ ] _CUT-401 retro: send-out form is single-line (one fabric item + one operation); multi-line is a pure FE addition if Moiz needs it._
- [ ] _CUT-402 retro: re-upload idempotency semantics — document the chosen path in the retro (idempotent no-op vs explicit error)._
- [ ] _CUT-403 retro: AccountingHub bank-accounts / cheques tabs have no export buttons (no list endpoint to export from yet); file under polish wave._
- [ ] _CUT-404 retro: prod hard-fail on missing `BACKUP_GPG_PASSPHRASE` (dev currently warns + ships plaintext); flag if Moiz wants a stricter prod posture._
- [ ] _CUT-405 retro: `@sentry/react` is not in `package.json` — dynamic import currently no-ops; run `pnpm add @sentry/react` before first prod deploy._
- [ ] _CUT-405 retro: CI doesn't smoke-build the prod Dockerfiles yet; cheap CUT-501 follow-up._
- [ ] _CUT-405 retro: `task/int-0-staging-bootstrap` parked branch is now superseded by CUT-405's prod artifacts. Drop it during Wave 6 polish (or now if you prefer)._

## Sign-off

- Moiz: ⬜ pass / ⬜ fail / ⬜ amber-with-followups
- Date: ____________
- If pass → next session: spawn Wave 6 (TASK-CUT-501 closeout + CUT-502 cutover runbook + CUT-503 acceptance Playwright suite), then the 7-day dogfood soak.
