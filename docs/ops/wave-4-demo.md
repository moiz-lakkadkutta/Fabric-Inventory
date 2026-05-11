# Wave 4 demo — 2026-05-11

**Time to run:** ~25 min in browser + ~5 min terminal.
**Pass criterion:** every step returns the expected outcome with no extra console errors. The wave's headline outcomes are (a) ReportsHub's foundation tabs render real numbers from the live backend, (b) a user can reset a forgotten password, (c) an Owner can invite a teammate and see them in the admin user list, and (d) Job-work BE + MigrationAdapter foundation are in place for Wave 5.
**Amber:** unexpected behavior that doesn't block the wave's goal — file follow-up TASK-CUT-NNN.
**Red:** any step fails outright OR a P0/P1 regresses — wave does not pass; spawn fix-agent.

## What landed in Wave 4

| PR | Title | Closes |
|---|---|---|
| #79 | TASK-CUT-301: Reports FE wired live (5 tabs) | P&L / TB / Daybook / Stock summary pull live; GSTR-1 tab renders a coming-soon panel pending Wave-5 export task |
| #80 | TASK-CUT-302: Reports BE remainder | new `GET /reports/{ledger/{id},ageing,party-statement/{id},gstr1}` — lazy SQL aggregates, no new tables |
| #81 | TASK-CUT-305: MigrationAdapter + Job-work BE | new `backend/app/service/migration/` Protocol + `NoopMigrationAdapter`; new `job_work_order` / `_line` / `job_work_receipt` / `_line` tables + router (`POST /job-work-orders`, `/receive`, `GET /reports/itc04`) |
| #82 | TASK-CUT-304: Admin invites BE+FE | new `user_invite` table; `POST /admin/invites`, `POST /admin/invites/accept`, `GET /admin/users`, `PATCH /admin/users/{id}/role`; AdminHub wired live; `/invite/:token` accept page |
| #83 | TASK-CUT-303: Forgot-password BE+FE | new `password_reset_token` table; `POST /auth/forgot`, `POST /auth/reset`; `EmailAdapter` Protocol with `ConsoleEmailAdapter` dev impl; `/forgot` + `/reset/:token` pages |

Linear Alembic chain after the wave: `task_cut_104 → task_cut_303_pw_reset → task_cut_305_jobwork → task_cut_304_user_invite` (HEAD).

## Pre-flight (do this once)

- [ ] `git pull --ff-only origin main`
- [ ] **macOS WeasyPrint libs** (still required from Wave 3 for PDF render):
  ```bash
  brew install pango cairo harfbuzz fontconfig fonts-noto || true
  export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH
  ```
- [ ] **Run new Alembic migrations** — three migrations landed in Wave 4 (CUT-303, CUT-305, CUT-304):
  ```bash
  cd backend
  env -u DATABASE_URL MIGRATION_DATABASE_URL=postgresql+asyncpg://fabric:fabric_dev@localhost:5432/fabric_erp \
    uv run alembic upgrade head
  # Expect: head ends at task_cut_304_user_invite
  ```
- [ ] **Restart `:8000` uvicorn cleanly** (env-strip per CUT-007 hot-fix):
  ```bash
  cd backend
  env -u DATABASE_URL -u MIGRATION_DATABASE_URL -u REDIS_URL \
    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
    uv run uvicorn main:app --reload --port 8000
  ```
  Confirm: `curl -s http://localhost:8000/admin/users` returns a 401 envelope (proves the new admin router is registered).
- [ ] **Tail the uvicorn log** in a second terminal — the dev `ConsoleEmailAdapter` prints reset + invite links to stdout:
  ```bash
  tail -f /tmp/uvicorn-*.log   # or whichever path you're piping uvicorn output to
  ```
- [ ] Restart Vite dev server: `cd frontend && pnpm dev`
- [ ] Open a fresh **incognito** browser at the running dev port (`:5173` or `:5174`).
- [ ] DevTools → Network + Console open. Clear before each step.
- [ ] **Carry-over data from Wave 3:** sign in to the demo account that already has a finalized invoice + receipt. Most Wave 4 steps need real numbers in the ledger for reports to be non-empty.

## Steps

### 1. Reports FE — P&L / TB / Daybook / Stock summary (CUT-301 + CUT-302)

1. Visit `/reports`. Click each tab in turn.
2. **P&L tab**: pick a date range that includes your Wave-2 invoice + receipt. Numbers should be real — non-zero revenue, non-zero net result. Network: `GET /reports/pnl?from=&to=` returns 200.
3. **Trial balance tab**: pick an as-of date covering today. Numbers populate. The footer row `total debit == total credit` (Postgres aggregate, not a UI calc).
4. **Daybook tab**: pick today's date. See the vouchers from the wave's setup (sales invoice GL voucher, receipt GL voucher, etc.).
5. **Stock summary tab**: see Cotton Suit row with current SOH (after Wave-3 step 5's `+50 -10 = 40` adjustment, assuming nothing else moved).
6. **GSTR-1 tab**: in `IS_LIVE` mode, this tab now renders a `<Gstr1ComingSoon>` panel pointing forward to a future export task. That's expected — the CUT-301 prompt left GSTR-1 live-wiring optional and the agent chose the safer ship-without-it path. Wave 5 wires the buckets onto a downloadable CSV.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 2. Reports BE — ledger / ageing / party-statement / gstr1 (CUT-302)

Curl directly (the FE doesn't surface these yet — they're staged for Wave 5 export):

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen | tr A-Z a-z)" \
  -d '{"email":"YOUR@EMAIL","password":"YOUR_PASSWORD","org_name":"YOUR_ORG"}' \
  | jq -r '.access_token')

# Ageing: per-party AR buckets (current / 1-30 / 31-60 / 61-90 / >90).
# Invariant: per-party bucket sum == outstanding.
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/reports/ageing?as_of=$(date -u +%Y-%m-%d)" | jq '.parties[0]'

# Party statement: voucher list + running balance for one party.
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/reports/party-statement/<party-id>?from=2026-04-01&to=$(date -u +%Y-%m-%d)" | jq '.summary'

# Ledger: per-ledger journal lines in period + walking balance.
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/reports/ledger/<ledger-id>?from=2026-04-01&to=$(date -u +%Y-%m-%d)" | jq '.closing_balance'

# GSTR-1: B2B/B2C(L)/B2C(S)/Export/HSN buckets for a month.
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/reports/gstr1?period=$(date -u +%Y-%m)" | jq 'keys'
# Expect: ["b2b","b2cl","b2cs","export","hsn","period"] (key order may vary)
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 3. Forgot-password loop (CUT-303) — the headline auth-UX win

1. Sign out. Visit `/login` — confirm "Forgot password?" link is present. Click it.
2. On `/forgot`: enter your demo account's email + org name. Submit. UI shows "If that email exists, a reset link was sent…" (same copy whether the email exists or not — no enumeration).
3. Watch the `tail -f` terminal. A console-log line prints the reset link of the form `http://localhost:5173/reset/<token>?org=<org-name>`.
4. **Negative path**: post to `/auth/forgot` with a non-existent email and confirm the response is byte-identical to step 2 (no enumeration). Confirm NO console line is printed for unknown emails.
5. Open the reset link from step 3 (paste into the same incognito window). On `/reset/:token`: set a new password. Submit. Redirect to `/login`.
6. Log in with the new password. Successful.
7. Re-open the same reset link — submit a different new password. Expect: 400 `INVALID_RESET_TOKEN`. (Single-use token; second consume fails.)

✅ pass / ❌ fail / ⚠️ amber: ___________

### 4. Admin invites flow (CUT-304) — the headline team-onboard win

1. Sign in as the Owner of your demo firm.
2. Visit `/admin`. The Users tab shows you (Owner) — confirm this is the live `GET /admin/users` response (network: row count matches FE count).
3. Click `+ Invite user`. Pick role = Sales (or another non-Owner role). Enter `teammate@example.com`. Submit.
4. Network: `POST /admin/invites` returns 201 with `{invite_id, expires_at}`. Toast/banner: "Invite link logged to server console" (dev guidance).
5. Watch the `tail -f` terminal. A console-log prints the invite link of the form `http://localhost:5173/invite/<token>`.
6. Open the invite link in a **second** incognito window (or another browser). On `/invite/:token`: fill name + password. Submit.
7. Network: `POST /admin/invites/accept` returns 201 (or returns a login bundle — verify per CUT-304's retro for the exact UX). Sign in as `teammate@example.com` in that window.
8. Switch back to the Owner window. Refresh `/admin`. User list now shows two rows. The new user's role column reads "Sales".
9. Change the new user's role to "Accountant" via the row dropdown. Network: `PATCH /admin/users/<id>/role` 200. UI updates.
10. **Negative path (last-owner protection)**: try to demote yourself (the only Owner) to "Sales". Expect: 400 with a clear "cannot demote last owner" message; UI surfaces the envelope.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 5. Job-work BE smoke (CUT-305)

The FE is W5-A (TASK-CUT-401), so this is BE-only for now.

```bash
TOKEN=… # from step 2

# Empty list (proves router registered + auth gate works):
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/job-work-orders | jq
# Expect: {"items":[],"count":0} or similar empty-envelope shape per CUT-305's response schema.

# Create a JWO (send-out) — requires items + a karigar party + a JOBWORK location;
# the service should auto-provision JOBWORK if missing.
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen | tr A-Z a-z)" \
  -d '{
    "firm_id": "<firm-uuid>",
    "party_id": "<karigar-party-uuid>",
    "lines": [{"item_id":"<cotton-suit-id>","qty":"100","uom":"METER"}],
    "operation": "Embroidery"
  }' \
  http://localhost:8000/job-work-orders | jq
# Expect: 201 with new jwo_id.

# ITC-04 prep:
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/reports/itc04?period=$(date -u +%Y-%m)" | jq 'keys'
# Expect: a structured envelope per CUT-305's schema.
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 6. MigrationAdapter Protocol foundation (CUT-305) — read-only sanity

```bash
cd backend
uv run pytest tests/test_migration_protocol.py -q
# Expect: green, with the Protocol-conformance test for NoopMigrationAdapter passing.

# Confirm the package shape Wave 5 expects:
ls app/service/migration/
# Expect: protocol.py, intermediate.py, noop_adapter.py, __init__.py
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 7. Codegen + no-mock check

```bash
cd frontend
pnpm check:types
# Expect: green; FE types match the BE OpenAPI snapshot.

grep -rn "fakeFetch\|@/lib/mock/identity" src/pages/reports/ src/pages/admin/ src/pages/auth/ 2>&1 \
  | grep -v __tests__ | grep -v ".test."
# Expect: zero hits in non-test source files.
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 8. Post-merge integration verification (already executed)

For the record, after the wave's last merge (PR #82), on a fresh checkout of `origin/main`:

- `cd backend && uv run ruff check . && uv run ruff format --check .` — clean.
- `cd frontend && pnpm exec vitest run` — 52 files / 234 tests pass.
- `cd frontend && pnpm tsc --noEmit && pnpm exec eslint . && pnpm exec prettier --check .` — clean.
- `cd frontend && pnpm check:types` — no OpenAPI drift.
- Alembic chain: linear, head = `task_cut_304_user_invite`.

## Follow-ups (amber)

- [ ] _CUT-301 retro: GSTR-1 tab is a coming-soon panel in live mode pending the Wave-5 export task; tab is functional in mock mode for click-dummy continuity._
- [ ] _CUT-303 retro: rate-limit `/auth/forgot` to 5 req/min/IP. Needs a Redis sliding-window primitive that doesn't exist yet — file under Wave 5 ops hardening if not already in CUT-405._
- [ ] _CUT-303 retro: daily cleanup job for expired/used `password_reset_token` rows — schedule alongside CUT-404 (backups + cron)._
- [ ] _CUT-303 retro: add a Playwright E2E for the full reset loop in CUT-503 (Wave 6 acceptance suite)._
- [ ] _CUT-304 retro: invite-accept UX choice between auto-login vs "go log in" — document the chosen branch in the retro, revisit if user feedback flags it._
- [ ] _CUT-305 retro: `period=YYYY-Qn` quarterly aggregation for ITC-04 not exercised by tests; Wave 5 export task validates._
- [ ] _Wave-3 carry: CUT-204 SOH refresh after stock-adjustment depends on `/reports/stock-summary` which CUT-301 wires — re-verify on `/inventory` after this wave._

## Sign-off

- Moiz: ⬜ pass / ⬜ fail / ⬜ amber-with-followups
- Date: ____________
- If pass → next session: spawn Wave 5 (TASK-CUT-401…405 — Job-work FE + Vyapar import + CSV/Excel export + Backups + HTTPS/Sentry/email-provider).
