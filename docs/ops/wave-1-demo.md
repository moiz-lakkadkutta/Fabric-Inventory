# Wave 1 demo — 2026-05-10

**Time to run:** ~10 min in browser + ~2 min terminal.
**Pass criterion:** every step returns the expected outcome with no extra console errors.
**Amber:** unexpected behavior that doesn't block the wave's goal — file follow-up TASK-CUT-NNN, link below.
**Red:** any step fails outright OR a P0/P1 regresses — wave does not pass; spawn fix-agent.

## What landed in Wave 1

| PR | Title | Closes |
|---|---|---|
| #55 | TASK-CUT-002: idempotency cookie strip + auth-by-design exemption | P0-4 |
| #56 | TASK-CUT-005: Wave-1 spike combo (Vyapar / Reports BE / PDF) | spikes for waves 3/4/5 |
| #57 | TASK-CUT-004: Real identity via useMe + RequireAuth route gate | P0-5, P1-4 |
| #58 | TASK-CUT-003: Onboarding wizard wire to /auth/signup | P0-3 |
| #59 | TASK-CUT-001: CORS via Vite proxy + error copy + login pre-fill cleanup | P0-2, P1-1, P1-5 |
| #60 | TASK-CUT-006 (hot-fix): restore frontend tests on main | post-merge integration regression |

## Pre-flight (do this once before steps below)

- [ ] `git pull --ff-only origin main` on your fabric checkout
- [ ] **Restart `:8000` uvicorn** — the running dev backend was 500'ing for hours; the actual root cause (uncovered post-Wave-1, see TASK-CUT-007 in the cutover plan) is shell-leaked docker-compose env vars (`DATABASE_URL=...@postgres:5432/...`, `REDIS_URL=redis://redis:6379/...`) overriding `.env`. Restart cleanly with the leaked vars unset:
  ```bash
  # In your tty running uvicorn: Ctrl-C, then:
  cd backend
  env -u DATABASE_URL -u MIGRATION_DATABASE_URL -u REDIS_URL uv run uvicorn main:app --reload --port 8000
  ```
  Confirm: `curl -s http://localhost:8000/auth/me` returns `{"code":"TOKEN_INVALID",...}` (NOT a 500). That envelope means the DB connection works.
- [ ] **Restart Vite dev server.** It was on `:5174` per the audit; with CUT-001's `vite.config.ts` proxy change you need to restart so the new proxy block takes effect:
  ```bash
  cd frontend && pnpm dev
  ```
  Confirm: navigate `http://localhost:<port>` and the app shell renders.
- [ ] Open a fresh **incognito** browser window pointing at the running dev port (likely `:5173` or `:5174`).
- [ ] Open DevTools → Network tab and Console tab. Clear both before each step below.

## Steps

### 1. CORS via same-origin proxy (P0-2 — closes via CUT-001)

Open `/` in incognito.

Expect:
- Network tab: requests go to `/api/dashboard/kpis`, `/api/activity?limit=5`, `/api/auth/refresh` — same-origin (no different host:port).
- Each request returns 200 OR an envelope error (e.g. 401 with `request_id`); NO CORS preflight rejection.
- Console: no "Access to fetch at … blocked by CORS policy" lines.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 2. Invoice list error copy (P1-1 — closes via CUT-001)

Sign out (clear authStore — easiest: open a new incognito tab) and visit `/sales/invoices` directly.

Expect (because not authenticated → 401 from `/api/invoices`):
- An error card. The copy is something like `"<code>: <detail> · request_id: <uuid>"` or `"Network error — couldn't reach the server"`.
- The string `"mock layer hiccupped"` MUST NOT appear anywhere on the page.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 3. Login form not pre-filled (P1-5 — closes via CUT-001)

Visit `/login` in production-like build OR with `__FABRIC_TEST_NO_PREFILL__` set. (For dev mode, the pre-fill stays — that's intentional for dogfood ergonomics.)

Expect:
- In dev: form is pre-filled with "Rajesh Textiles" / your email / password (acceptable in dev).
- In a `pnpm build && pnpm preview` run: form is empty.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 4. Onboarding signup wires to backend (P0-3 — closes via CUT-003)

Navigate `/onboarding`.
- Step 1: org name "Wave1 Demo Co" + your contact email + **password** (new field).
- Step 2: firm name "Demo HQ" + GSTIN like "24ABCDE1234F1Z5" + **state code** "MH" (auto-derived from GSTIN's first 2 chars; you can override).
- Step 3: pick "I'm new to the trade" — note the Vyapar option is labelled "(coming soon — TASK-CUT-402)".
- Click "Commit & finish".

Expect:
- Network tab: a `POST /api/auth/signup` with the payload `{email, password, org_name, firm_name, state_code, gstin?}` returns 201.
- Token cookie `fabric_refresh` set.
- Browser navigates to `/`.
- Topbar firm chip shows "Demo HQ" (not "Rajesh Textiles").
- `/admin` shows your user as Owner.

If signup returns 500: that's audit P0-1 (running uvicorn wedged). Restart it per pre-flight and retry.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 5. Real identity drives the chrome (P0-5 — closes via CUT-004)

While signed in from step 4:
- Topbar firm chip = your firm name from `/auth/me` (NOT "Rajesh Textiles · 24AAACR5055K1Z5").
- Click the user-menu avatar — initials and email reflect YOUR signed-in account (NOT "moiz@rajeshtextiles.in", NOT "Moiz Lakkadkutta").
- Dashboard subtitle reflects today's date in `en-IN` format (NOT "Wednesday, 30 Apr 2026").

✅ pass / ❌ fail / ⚠️ amber: ___________

### 6. RequireAuth gate (P1-4 — closes via CUT-004)

Open a fresh incognito window and visit `/admin` directly.

Expect:
- Browser redirects to `/login` (URL changes); the post-redirect router state preserves the original `from: '/admin'` so a future "redirect-on-success-login" feature can land seamlessly.
- The mock topbar / firm chip / user menu are NOT visible during the redirect.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 7. Idempotency cookie strip (P0-4 — closes via CUT-002)

After step 4's signup, in a terminal:

```bash
docker exec fabric-redis-1 redis-cli keys 'idem:/auth/signup:*' | head -1
# Pick one of the keys, e.g. idem:/auth/signup:abc-...
docker exec fabric-redis-1 redis-cli get '<paste-the-key-here>' | jq '.headers'
```

Expect:
- The cached `headers` object does NOT contain `set-cookie` (case-insensitive).
- The cached `headers` object does NOT contain `authorization`.

Also: replay `/auth/login` with the same Idempotency-Key:

```bash
KEY=$(uuidgen | tr A-Z a-z)
for i in 1 2; do
  curl -s -X POST http://localhost:8000/auth/login \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: $KEY" \
    -d "{\"email\":\"<your-signup-email>\",\"password\":\"<password>\",\"org_name\":\"Wave1 Demo Co\"}" \
    | jq '.access_token' | cut -c1-50
done
```

Expect: the two access tokens differ in their `jti` claim. (Decode with `jwt.io` or `cut -c1-50` then compare characters around position 30 onward — the `jti` is part of the payload.) Receipts of fresh tokens prove the handler re-executed; no cached replay.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 8. Spike docs ready for review (CUT-005)

Open and skim:
- `docs/spikes/vyapar-source-format.md` — recommends Excel-export adapter over `.vyp` binary
- `docs/spikes/reports-be-schema.md` — recommends lazy SQL aggregate, lists the 7 endpoints, calls out 2 small migrations for Wave 2
- `docs/spikes/pdf-rendering-tech.md` — recommends WeasyPrint
- `docs/spikes/invoice-template-wireframe.html` — open in a browser; verify all 12 mandatory GST fields render with placeholder values

Each doc has a "Decision needed from Moiz" section. Either approve in writing on this demo doc OR override and re-spike. Without a decision here, Wave 4/5 work cannot start.

✅ pass / ❌ fail / ⚠️ amber: ___________

## Follow-ups (amber)

(Add new TASK-CUT-NNN entries here as you walk the demo and find non-blocking issues.)

- [ ] _none yet — fill in as you walk_

## Sign-off

- Moiz: ⬜ pass / ⬜ fail / ⬜ amber-with-followups
- Date: ____________
- If pass → next session: spawn Wave 2 (TASK-CUT-101…106).
