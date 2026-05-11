# Cutover runbook — Vyapar → Fabric, one day

**Task:** TASK-CUT-502
**Plan reference:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 6)
**North star:** Moiz stops using Vyapar and runs his textile firm on Fabric exclusively. v1 ship gate = 7 consecutive days operating Fabric without falling back to Vyapar, on Moiz's real data, with zero P0/P1 bugs filed.
**Audience:** the operator on cutover day (Moiz). Written so a junior on-call could execute it if Moiz were unavailable.

This runbook covers the single day Moiz flips from Vyapar to Fabric for live billing. It assumes production has already been deployed via `docs/ops/deployment-runbook.md`, backups are proven via `docs/ops/backup-runbook.md`, and Waves 1–5 demos all passed.

---

## Document conventions

- All times are **IST (Asia/Kolkata)**. Postgres stores UTC; the UI displays Asia/Kolkata. When in doubt, trust what the UI shows.
- **Production URL:** `https://app.taana.in`.
- **Production box:** Hetzner CX22, SSH as `moiz@app.taana.in`. Repo lives at `/opt/fabric/repo`; env at `/opt/fabric/.env.production`.
- **Money:** Indian rupees, `NUMERIC(18,2)`. Reconciliation tolerance against Vyapar is **±₹1** (per cutover plan locked decision #5).
- **Two ledger systems exist on cutover day:** Vyapar (source of truth for pre-cutover history) and Fabric (empty until Approve is clicked). After Approve, Fabric is the system of record going forward.
- Every step is single-decision. If a step fails, jump straight to **Section 9 — Rollback** before doing anything else.

---

## 0. Roles and contacts

| Role | Person | Reachable via |
|---|---|---|
| Operator (you) | Moiz | (running the runbook) |
| P0 escalation | Moiz | (this is a solo project — escalation is "stop, breathe, fall back to Vyapar, triage offline") |
| Accountant (post-cutover spot-check on Day 1 books) | Moiz's CA | WhatsApp / email — coordinate beforehand |

P0 = "I cannot issue an invoice to a customer right now." Anything else can wait until tomorrow.

---

## 1. Pre-flight checklist — T-7 days

Run this exactly **7 days before cutover day**. Each item is a hard gate; do not skip. Tick the boxes in this file (or a printed copy) and sign at the bottom.

### 1.1 Production is deployed and live

- [ ] `docs/ops/deployment-runbook.md` Sections 1–6 are complete on the Hetzner CX22.
- [ ] `curl -sS https://app.taana.in/live` returns `{"status":"live"}` (HTTP 200).
- [ ] `curl -sS https://app.taana.in/ready` returns `{"status":"ready","db":true,"redis":true}` (HTTP 200).
- [ ] Browser: `https://app.taana.in/` loads with a green padlock. The React app renders the login screen.
- [ ] `dig app.taana.in +short` returns the CX22 IPv4 (DNS propagation complete).

### 1.2 TLS / SSL

- [ ] Browser padlock is green on `https://app.taana.in/` — Caddy obtained a valid Let's Encrypt cert.
- [ ] Run `echo | openssl s_client -servername app.taana.in -connect app.taana.in:443 2>/dev/null | openssl x509 -noout -dates`. The `notAfter=` date is **at least 30 days away**. (Caddy auto-renews at 30 days; you want at least one auto-renew window of comfort before cutover.)

### 1.3 Backup loop is proven

- [ ] `docs/ops/backup-runbook.md` Section 4 ran successfully at least once on prod. Today's `*.sql.gz.gpg` is in the B2 bucket: `b2 ls "$B2_BUCKET" | head -3` (run from the prod box after sourcing `ops/.env.backup`).
- [ ] **Restore test on a sibling DB has been completed end-to-end** — `docs/ops/backup-runbook.md` Section 5. Spot-check (`SELECT count(*) FROM party WHERE deleted_at IS NULL`) matched prod. This is non-negotiable: a backup that has never been restored is not a backup.
- [ ] Cron is installed: `sudo crontab -l | grep 'make backup'` returns the line `30 21 * * * cd /opt/fabric && /usr/bin/make backup >> /var/log/fabric-backup.log 2>&1`.
- [ ] `/var/log/fabric-backup.log` has at least one successful `[YYYY-MM-DDTHH:MM:SS] backup done:` line from a cron run (not just the manual smoke test).
- [ ] **GPG passphrase is in your password manager AND on paper in a safe.** Losing it means losing every encrypted backup; gpg has no recovery. Confirm both copies exist physically.

### 1.4 Sentry FE is capturing

- [ ] In an incognito tab, open `https://app.taana.in/garbage-test-route`. Wait 60 seconds.
- [ ] Sentry dashboard for project `fabric-prod` → Issues → confirm a "Route not found" or equivalent FE error event appeared, with PII redacted (no email addresses, no GSTINs in the message).
- [ ] If nothing shows up, check `frontend/dist/assets/*.js | xargs grep -l sentry` on the prod box — confirm `@sentry/react` actually bundled (see Wave-5 demo step 7).

### 1.5 Email deliverability is proven

- [ ] Mailgun dashboard shows `mg.taana.in` as **Verified** (SPF + DKIM both green).
- [ ] Sign up a throwaway org on prod via `https://app.taana.in/onboarding`. Sign out, visit `/forgot`, enter that throwaway email + org name.
- [ ] The reset email lands in your **inbox** within ~30 seconds — NOT in spam. Open it, click the link, set a new password, sign in successfully.
- [ ] Delete the throwaway org afterwards: `ssh moiz@app.taana.in`, then `docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production exec postgres psql -U fabric -d fabric_erp -c "UPDATE organization SET deleted_at = now() WHERE name = 'Throwaway Test Co';"` (substitute the org name you used).

### 1.6 User accounts are provisioned

- [ ] Moiz's prod account exists (signed up via `/onboarding` already; firm + org rows live).
- [ ] **Two-firm sanity check (skip if single-firm):** if Moiz runs more than one textile firm, both firms exist under one org, and `/auth/me` returns `available_firms` with both entries.
- [ ] Any teammate (accountant, staff) who needs prod access has been invited via `/admin` → `+ Invite user` and has accepted (`/admin` user list shows them).
- [ ] Owner role assignment is correct: Moiz is Owner. Accountant role is the CA only. Sales role for anyone else.
- [ ] **Last-owner protection test:** attempt to demote yourself from Owner via the `/admin` row dropdown. Expect a 400 error: "cannot demote last owner". Confirm Moiz cannot accidentally orphan the org.

### 1.7 Dress rehearsal — full Vyapar import on a fresh test firm

This is the dry run. It surfaces every footgun before cutover day.

- [ ] Sign up a **fresh test org** on prod: org name `Cutover Rehearsal Co`, separate email alias (e.g. `moiz+rehearsal@taana.in`).
- [ ] Export Moiz's actual Vyapar data: in Vyapar desktop app → Utilities → Export → Excel. Save as `vyapar-rehearsal-YYYY-MM-DD.xlsx`.
- [ ] Sign in as Owner of the rehearsal org. Visit `/admin/migrations`. Click `Choose file` → pick the rehearsal xlsx. Click **`Upload and preview`**.
- [ ] Reconciliation report appears below the upload form. Walk every counter:
  - `Parties` = expected number of party rows from Vyapar.
  - `Opening balances` = expected number of party-scoped openings.
  - `Errors` = 0.
  - `Warnings` = note any (typically: ambiguous duplicate names, missing GSTINs — these are non-blocking but should be reviewed).
  - `Opening TB diff` ≤ ₹1 (target per cutover plan). If higher, **stop and investigate** — likely a Vyapar export column mis-mapped or a manual Vyapar adjustment that didn't make it into the export.
- [ ] Click **`Approve and commit`**. Status pill flips to `APPROVED`. Footer message: "Migration applied. Parties + opening balances are now in your books."
- [ ] Visit `/masters/parties`. The Vyapar parties are present. Spot-check 5 random parties for: correct name spelling, correct GSTIN, correct state code, correct opening balance (DR for customers, CR for suppliers).
- [ ] Visit `/accounting` → Vouchers tab. Exactly **one** voucher of type `OPENING_BAL` exists, dated yesterday (1 day before the import), labeled "Opening Balances - imported from Vyapar". DR total == CR total.
- [ ] Visit `/reports` → Trial balance tab, as-of today. Numbers match the Vyapar TB snapshot you exported alongside the data (±₹1). **Print or screenshot both** for your records.
- [ ] **Walk every Wave 1–5 demo** against the rehearsal firm:
  - Wave 2: create a draft invoice using a freshly-imported customer. Finalize. Record a partial cash receipt. Verify invoice flips to PARTIALLY_PAID.
  - Wave 3: create a PO against a freshly-imported supplier. Approve → Confirm. Build a GRN. Build a Purchase Invoice. Post. Print one finalized sales invoice as PDF — confirm the 12 mandatory GST fields render and ₹ shows as ₹ (not a tofu box).
  - Wave 4: trigger a forgot-password loop end-to-end on the rehearsal account.
  - Wave 5: post one job-work send-out + one receive-back to a karigar. Click `Export CSV` on `/sales/invoices`, `/masters/parties`, `/reports` → P&L. All three CSVs open cleanly in Excel.
- [ ] At the end of the rehearsal, **soft-delete the rehearsal org**: `ssh moiz@app.taana.in`, then run `docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production exec postgres psql -U fabric -d fabric_erp -c "UPDATE organization SET deleted_at = now() WHERE name = 'Cutover Rehearsal Co';"`. (Soft-delete is intentional — preserve the audit trail per CLAUDE.md.)
- [ ] If any step above failed: **the cutover is not ready.** File a hot-fix task (`TASK-CUT-NNN`) and reschedule cutover day. Do not proceed.

### 1.8 T-7 sign-off

- [ ] Every box above is ticked.
- [ ] Cutover day and start time are on the calendar.
- Moiz: ⬜ ready / ⬜ not ready (specify blockers)
- Date: _____________

---

## 2. Pre-flight checklist — T-1 day

Run this **the day before cutover day**, in the evening. Each item is a single decision; do not skip.

### 2.1 Lock in the production Vyapar export

- [ ] In Vyapar desktop app, decide the **final Vyapar invoice date** you will accept. Plan: today (T-1). Anything dated T-1 or earlier lives in Vyapar; anything dated cutover-day (T+0) or later lives in Fabric.
- [ ] **Stop issuing Vyapar invoices effective end of day T-1.** Tell any staff who might issue invoices.
- [ ] Print or screenshot Vyapar's Trial Balance as-of end-of-T-1. Save as `cutover-tb-vyapar-YYYY-MM-DD.pdf`. This is your reconciliation reference for tomorrow.
- [ ] Print or screenshot Vyapar's P&L for the current FY-to-date. Save alongside.
- [ ] Export Vyapar data: Utilities → Export → Excel. Save as `vyapar-cutover-YYYY-MM-DD.xlsx`. **Do not edit this file.**
- [ ] Verify the file is readable: open it in Excel. Walk the sheets — Parties, Opening Balances. Spot-check 5 random rows for sanity (no obvious corruption, no `#REF!` errors).
- [ ] Copy the file to a **second physical location** — external SSD, second laptop, or your own email. The file is the source of truth for pre-cutover history; losing it means losing your books.

### 2.2 Verify production health

- [ ] `curl -sS https://app.taana.in/live` returns `{"status":"live"}`.
- [ ] `curl -sS https://app.taana.in/ready` returns `{"status":"ready","db":true,"redis":true}`.
- [ ] Browser: `https://app.taana.in/` loads, padlock green. Sign in as Owner.
- [ ] `/admin` shows the user list as expected (no surprise extra accounts).
- [ ] `/masters/parties` and `/masters/items` are empty (you have not staged any data on the prod owner org — the migration brings it in tomorrow).
- [ ] Visit `https://app.taana.in/admin/migrations`. The list is empty (no leftover migrations from the rehearsal — that was a different org).

### 2.3 Verify backup ran today

- [ ] `ssh moiz@app.taana.in`, then `tail -20 /var/log/fabric-backup.log`. The latest line should be from tonight at 21:30 UTC (which is 03:00 IST tomorrow morning — if you're running this checklist before 03:00 IST, the latest line is from last night).
- [ ] `b2 ls "$B2_BUCKET" | tail -3` lists today's encrypted dump.

### 2.4 Laptop-side prep

- [ ] Charge your laptop. Plug in a charger.
- [ ] Confirm strong internet. Switch to a wired connection if possible.
- [ ] Open your password manager. Confirm you have:
  - Production Owner login (email + password).
  - GPG backup passphrase.
  - B2 access keys (only needed if a restore is required).
  - SSH access to `moiz@app.taana.in`.
- [ ] Confirm browser is up-to-date (Chrome 120+ or Firefox 121+). Old browser versions have surprised us with broken CSS variable resolution on the design system.
- [ ] Disable browser extensions that intercept network traffic (uBlock Origin is fine; Privacy Badger and similar can cause CORS-shaped failures).

### 2.5 Lay out tomorrow's schedule

Print or copy into a Notes app:

| Time (IST) | Step | Expected duration | Allowed slack |
|---|---|---|---|
| 09:00 | Pause Vyapar writes (no new invoices in Vyapar) | instant | 0 |
| 09:00 – 09:15 | Final Vyapar verification (TB snapshot already taken yesterday) | 15 min | +15 min |
| 09:15 – 09:30 | Re-export Vyapar data (in case anything snuck in overnight) | 15 min | +15 min |
| 09:30 – 09:45 | Upload to `/admin/migrations`, watch reconciliation | 15 min | +30 min if reconciliation fails first time |
| 09:45 | Click `Approve and commit` (POINT OF NO RETURN) | instant | 0 |
| 09:45 – 10:00 | Spot-check imported data | 15 min | +15 min |
| 10:00 | Issue first real Fabric invoice + receipt against it | 15 min | +15 min |
| 10:15 | Sign-off step (Section 8) | 5 min | 0 |

Total expected: ~1h15m. Hard stop at 12:00 — if you have not signed off by noon, invoke Section 9 (Rollback) and reschedule.

### 2.6 T-1 sign-off

- [ ] Every box above is ticked.
- [ ] Vyapar export file is safely stored in two locations.
- [ ] Schedule is on the calendar.
- Moiz: ⬜ go for tomorrow / ⬜ defer (specify reason)
- Date: _____________

---

## 3. Cutover day — H-Hour sequence

This is the live ops sequence. **Follow the times. Do not skip ahead. Do not improvise.**

### 3.1 — 09:00 IST: Pause Vyapar writes

Action:
1. Walk to whoever else uses Vyapar (if anyone — for a solo firm, this is just you). Tell them: "No new invoices in Vyapar from this moment. Everything goes into Fabric starting at 10:00."
2. Close the Vyapar desktop app. (Leave the laptop running — you may need to look up history later, but no writes.)

Verification:
- [ ] Vyapar desktop app is closed on every device that has it installed.

Time check: should be **09:00–09:05 IST**.

### 3.2 — 09:15 IST: Final Vyapar export

Action:
1. Re-open Vyapar desktop app **read-only** — do not click `+ New invoice` or any save button.
2. Verify the Trial Balance is identical to last night's snapshot. If a row drifted: someone made a write after T-1. **Stop, reconcile, then continue.**
3. Re-export: Utilities → Export → Excel. Save as `vyapar-cutover-final-YYYY-MM-DD.xlsx`.
4. Close Vyapar again.

Verification:
- [ ] `vyapar-cutover-final-YYYY-MM-DD.xlsx` exists on disk.
- [ ] File size is non-zero (`ls -lh vyapar-cutover-final-*.xlsx`).
- [ ] Open the file. Spot-check Parties sheet has the same row count as last night's export.

Time check: should be **09:15–09:30 IST**.

### 3.3 — 09:30 IST: Upload to /admin/migrations

Action:
1. Open `https://app.taana.in/` in a fresh **incognito** browser window. Sign in as Owner.
2. Navigate to `https://app.taana.in/admin/migrations`. Confirm the migration history table is empty.
3. Click `Choose file`. Pick `vyapar-cutover-final-YYYY-MM-DD.xlsx`.
4. Click **`Upload and preview`**.
5. Wait for the reconciliation report to render below the upload form. Typically <5 seconds; <30 seconds for a large Vyapar shop.

Verification — walk the reconciliation report top to bottom:
- [ ] Status pill reads `RECONCILED`.
- [ ] `Parties` counter matches your expected party count from Vyapar (±0 — every Vyapar party should be picked up).
- [ ] `Opening balances` counter matches expected.
- [ ] `Errors` = 0. (If non-zero: do not Approve. Read each error in the per-row list below the counters. Common causes: missing required column in Vyapar export, mis-mapped state code. Re-export from Vyapar with the column fixed, or invoke Section 9 rollback.)
- [ ] `Warnings` = whatever you noted at T-7 rehearsal time, ±1–2. Review each warning briefly; warnings are non-blocking by design.
- [ ] **`Opening TB diff` ≤ ₹1 AND the pill says `tb_reconciles: true`.** This is the hard gate. If the diff is > ₹1, do not Approve.

If any verification fails: **DO NOT click `Approve and commit`. Skip to Section 9.**

Time check: should be **09:30–09:45 IST**. Allow +30 min slack if reconciliation must be re-run (you can re-upload the same file or a fresh re-export — each upload mints a new migration row; only the Approved one matters).

### 3.4 — 09:45 IST: Click Approve and commit (POINT OF NO RETURN)

**Read this carefully before clicking:**

Approve is irreversible inside Fabric. It:
- Creates the parties in `party` table (RLS-scoped to your org).
- Posts a single compound journal voucher of type `OPENING_BAL`, dated 1 day before today (yesterday IST), labeled "Opening Balances - imported from Vyapar". DR == CR.
- Cannot be undone via UI. Reversal requires either (a) restoring from this morning's backup, or (b) manually posting a reversal voucher (and accepting that the migration row stays as `APPROVED` in history).

Up until you click Approve, **the only state in Fabric is the migration row itself in `user_migration`** — no parties, no vouchers, nothing on the ledger. Rollback before Approve is trivial (just don't approve; the migration row is informational).

Action:
1. Re-confirm the reconciliation report is green (Errors = 0, TB diff ≤ ₹1).
2. Re-confirm the file you uploaded is the one you intend to commit (filename shown in the migration row).
3. Click **`Approve and commit`**.
4. The Approve button re-uploads the same file bytes (per CUT-402 retro design). If the page was reloaded between Upload and Approve, you'll need to re-upload first.
5. Wait for the request to complete. Typically <10 seconds for a small textile shop.

Verification:
- [ ] Status pill flips from `RECONCILED` to `APPROVED`.
- [ ] Footer message renders: "Migration applied. Parties + opening balances are now in your books."
- [ ] **No error envelope appears.** If you see "Commit failed: ..." in red, the migration is in `FAILED` state. Investigate the failure_reason text. The pre-Approve state is preserved (no partial commit thanks to the all-or-nothing service-layer DB transaction); you can re-upload and retry.

Time check: should land exactly **09:45 IST**. From this moment, Fabric is the system of record.

### 3.5 — 09:45–10:00 IST: Spot-check imported data

Action — walk these screens, in this order, in the same window:

1. Visit `/masters/parties`.
   - [ ] Row count = the `Parties` number from the reconciliation report.
   - [ ] Open 3 random customer parties: check name, GSTIN, state code, opening balance match Vyapar.
   - [ ] Open 3 random supplier parties: same checks (opening balance should be CR for suppliers, DR for customers).
2. Visit `/accounting` → Vouchers tab.
   - [ ] Filter to find vouchers dated yesterday (Asia/Kolkata).
   - [ ] Exactly **one** voucher of type `OPENING_BAL` exists, labeled "Opening Balances - imported from Vyapar".
   - [ ] DR total == CR total (footer of the voucher detail).
3. Visit `/reports` → Trial balance tab.
   - [ ] Pick as-of date = today.
   - [ ] Footer: `total debit == total credit` (the Postgres aggregate invariant — not a UI calc).
   - [ ] Compare against your `cutover-tb-vyapar-YYYY-MM-DD.pdf` printout from T-1. Sundry Debtors and Sundry Creditors balances should match within ±₹1.
4. Visit `/reports` → P&L tab.
   - [ ] Pick date range = current FY-to-date.
   - [ ] **Expected:** zero revenue, zero COGS, zero expenses. Opening balances do not flow into P&L — they're balance-sheet only.

Verification:
- [ ] All four screens look right. Numbers reconcile against Vyapar within ±₹1.

If anything looks wrong: **do not issue a customer invoice yet.** Pause, investigate. Worst case, invoke Section 9 rollback within the same hour — the morning's backup is still pristine.

Time check: should be **09:45–10:00 IST**.

### 3.6 — 10:00 IST: Issue the first real Fabric invoice

Action:
1. Visit `/sales/invoices`. Confirm the list is empty (or shows only what the rehearsal added — but rehearsal was on a different org, so this should be empty for the prod owner org).
2. Click `+ New invoice`. The customer dropdown is populated with the imported parties.
3. Build a real invoice for a real customer:
   - Pick a real customer party (one of the parties imported from Vyapar).
   - Pick item(s) — you'll need to create at least one Item via `/masters/items` first if Vyapar's export didn't include item master data (per the CUT-402 spec, only Parties + Opening Balances import; Items are entered fresh).
   - Quantities, rates, GST rate per line as appropriate.
4. Click `Save draft`. Invoice lands at `/sales/invoices/<id>` showing `DRAFT` pill.
5. Click `Finalize`. Pill flips to `FINALIZED`.
6. Click `Print` to generate the PDF. Open the PDF — confirm:
   - Seller name + GSTIN + state are yours.
   - Buyer name + GSTIN + state are the customer's.
   - Place of supply is correct.
   - IGST (inter-state) or CGST+SGST split (intra-state) per the place-of-supply rule.
   - ₹ renders cleanly (not a tofu box — Noto fonts installed per Wave-3 demo).

Verification:
- [ ] One finalized invoice exists for the current FY in Fabric.
- [ ] PDF prints cleanly.

### 3.7 — 10:10 IST: Receipt against the first invoice

Action:
1. While on the FINALIZED invoice's detail page, click `Record payment`.
2. Pick mode (Cash / UPI / Cheque / NEFT as appropriate). Enter the amount (full or partial).
3. Save. Network: `POST /receipts` returns 201.
4. The invoice pill flips to `PAID` (full payment) or `PARTIALLY_PAID` (partial).
5. Visit `/accounting` → Receipts tab. Confirm the receipt is listed.
6. Visit `/accounting` → Vouchers tab. Confirm a `RECEIPT` voucher exists with DR == CR.

Verification:
- [ ] Receipt is posted. Invoice state is `PAID` or `PARTIALLY_PAID`.
- [ ] Bank / Cash ledger reflects the inflow on Trial Balance refresh.

Time check: should be **10:00–10:15 IST**.

---

## 4. Sign-off step

Once Sections 3.1 through 3.7 are all green, complete the sign-off block at **Section 8** below. Then:

- [ ] Tell anyone else who needs to know (CA, staff): "Cutover complete. Fabric is the system of record from now on. Vyapar is read-only history."
- [ ] Close the Vyapar desktop app on every device and **do not reopen it for writes**.

---

## 5. First-week monitoring — daily check sheet

Run this checklist **every weekday morning for the 7-day soak**. Stop running it once the soak completes successfully (Section 7). Each check is <2 minutes.

### Daily checklist — Day N (1 through 7)

- [ ] **Sentry FE dashboard** — visit https://sentry.io and select project `fabric-prod`. Walk the Issues tab. Zero new P0/P1 events overnight = green. Any new error event = open it, decide if it's user-impacting. File a task if so.
- [ ] **Backup landed** — on the prod box:
  ```bash
  ssh moiz@app.taana.in
  tail -5 /var/log/fabric-backup.log
  # Expect: one [YYYY-MM-DDTHH:MM:SS+00:00] backup done: line from the 21:30 UTC cron (~03:00 IST today)
  ```
- [ ] **Backup landed in bucket** — same SSH session:
  ```bash
  cd /opt/fabric && source ops/.env.backup
  AWS_ACCESS_KEY_ID="$B2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$B2_SECRET_KEY" \
    AWS_DEFAULT_REGION="$B2_REGION" \
    aws --endpoint-url "$B2_ENDPOINT_URL" s3 ls "s3://$B2_BUCKET/" | tail -3
  # Expect: today's *.sql.gz.gpg listed.
  ```
- [ ] **Trial balance still balances** — `https://app.taana.in/reports` → Trial balance tab → as-of today. Footer: `total debit == total credit`. Any drift = P0 (someone posted an unbalanced voucher, which the service layer should make impossible — file immediately).
- [ ] **No surprise voucher diffs vs Vyapar snapshot** — pull up your `cutover-tb-vyapar-YYYY-MM-DD.pdf` from T-1. The Sundry Debtors / Sundry Creditors totals on Fabric's TB should equal:
  - (Vyapar TB Sundry Debtors at cutover) + (sum of new Fabric sales since cutover) − (sum of new Fabric receipts since cutover) = Fabric TB Sundry Debtors today.
  - If the math doesn't work out: a voucher posted incorrectly OR a receipt was double-applied. Open `/accounting` → Vouchers tab; sort by created_at desc; review recent vouchers for the affected ledger.
- [ ] **Health checks green** —
  ```bash
  curl -sS https://app.taana.in/live   # {"status":"live"}
  curl -sS https://app.taana.in/ready  # {"status":"ready","db":true,"redis":true}
  ```
- [ ] **No new P0/P1 bug filed** in the issue tracker. Soak success requires zero.

If all 7 checks pass on Day N, that day counts toward the soak. If any check fails on Day N, file a task, fix it, and **reset the soak counter to 0** (per CLAUDE.md cutover plan locked decision: "7 consecutive days").

---

## 6. Operational gotchas (known foot-guns)

These are things that have surprised us during Waves 1–5 demos. Read once before cutover day; refer back if you hit something weird.

1. **Shell-leaked env vars wedge the dev backend.** If you `source` an env file in a shell that also runs `uvicorn`, `DATABASE_URL=...@postgres:5432/...` overrides `.env` and every request 500s with `psycopg2.OperationalError: could not translate host name "postgres" to address`. Prod is unaffected (Docker Compose owns the env). But if you ever fall back to running uvicorn manually on the prod box, use the env-strip pattern: `env -u DATABASE_URL -u MIGRATION_DATABASE_URL -u REDIS_URL uv run uvicorn main:app --reload --port 8000`.

2. **Each upload mints a fresh migration row.** The upload endpoint deliberately does not dedupe by file body — if you click `Upload and preview` twice with the same file, you get two `RECONCILED` rows. Only the one you `Approve` commits to ledgers. The others sit harmlessly in history. If you accidentally Approve the wrong one (impossible if errors=0 and you reviewed it, but defense in depth): rollback per Section 9.

3. **Approve re-uploads the file.** If you reload the browser between `Upload and preview` and `Approve and commit`, you lose the in-memory file handle. The Approve form is rendered with a re-upload field — pick the same file again and submit. The service re-runs the adapter and re-validates the TB invariant before committing. (CUT-402 retro #1 covers this design.)

4. **Cash / capital / bank firm-level openings are NOT imported.** Vyapar's Parties export covers party-scoped openings only. If you have an opening cash balance, opening bank balance, or opening capital account, **post it manually via `/accounting` → New voucher** after the migration but before issuing your first Fabric invoice. The TB diff from the reconciliation report explicitly excludes these; if your Vyapar TB had non-zero Cash / Bank / Capital opening rows, your Fabric TB will be short by exactly that amount until you manually post them. (CUT-402 retro "Open flags carried over" item.)

5. **Stock SOH refresh on `/inventory` was deferred to a future task.** The Stock summary report (`/reports` → Stock summary) is the source of truth for current SOH. If a stock adjustment isn't reflected on `/inventory` rows immediately, that's a UI refresh gap, not a data-correctness issue.

6. **GSTR-1 tab is currently a coming-soon panel.** The four foundation report tabs (P&L, TB, Daybook, Stock summary) are live; GSTR-1 is staged for a future export task. For your first month's GSTR-1 filing, use the BE endpoint directly: `curl -H "Authorization: Bearer $TOKEN" "https://app.taana.in/reports/gstr1?period=YYYY-MM" -o gstr1.json`. (Wave-4 demo step 2.)

7. **Idempotency-Key cookie strip is in place.** Mutating endpoints (POST/PATCH/DELETE) accept `Idempotency-Key: <uuid>` for safe replay. Cached responses do NOT echo `Set-Cookie` or `Authorization` (CUT-002). Safe to retry any 5xx from the UI.

8. **Last-Owner protection.** Fabric refuses to demote the only Owner. If you need to hand off Owner role, first invite a new user, accept the invite, promote them to Owner, then demote yourself to Sales / Accountant. Otherwise the API returns 400 "cannot demote last owner" and the UI surfaces the envelope.

---

## 7. 7-day soak success criterion

**v1 ship test (from CLAUDE.md / `docs/ops/cutover-plan-2026-05-10.md` North star):**

> 7 consecutive days of operating Fabric without falling back to Vyapar, on Moiz's real data, with zero P0/P1 bugs filed.

Concrete pass conditions:
- Days 1 through 7 of the soak each completed the daily monitor checklist (Section 5) with every box green.
- Every invoice issued during the soak was issued in Fabric. Zero Vyapar writes happened during the soak.
- Every receipt collected during the soak was recorded in Fabric.
- Zero P0 bugs filed (P0 = "Moiz cannot bill a customer right now").
- Zero P1 bugs filed (P1 = "a money / tax / ledger field is wrong, or a workflow is broken in a way that requires a code fix").
- Trial balance balanced (DR == CR) at end of every soak day.
- At least one backup landed in the B2 bucket on every soak day.

If any condition fails on Day N, the soak counter resets to 0 once the underlying issue is fixed. The soak is intentionally strict — the entire point of the v1 gate is to prove Fabric is reliable enough that Moiz can run his actual business on it.

When all 7 days pass: **v1 ships.** Update `docs/ops/cutover-plan-2026-05-10.md` status board (Wave 6 row) to `Demo passed`. Tag the prod release as `v0.1.0-soaked` for the record.

---

## 8. Sign-off block

### Cutover day sign-off

Each step below is initialled + dated by Moiz once the step is verified complete.

| Step | Time (IST) | Verified | Initials | Date |
|---|---|---|---|---|
| 3.1 — Vyapar writes paused | 09:00 | ⬜ | _______ | _______ |
| 3.2 — Final Vyapar export saved (2 locations) | 09:15 | ⬜ | _______ | _______ |
| 3.3 — Upload + reconciliation green (Errors=0, TB diff≤₹1) | 09:30 | ⬜ | _______ | _______ |
| 3.4 — Approve and commit clicked, status=APPROVED | 09:45 | ⬜ | _______ | _______ |
| 3.5 — Spot-check parties / vouchers / TB / P&L all match Vyapar (±₹1) | 09:55 | ⬜ | _______ | _______ |
| 3.6 — First real Fabric invoice issued + PDF prints cleanly | 10:05 | ⬜ | _______ | _______ |
| 3.7 — First real Fabric receipt recorded against that invoice | 10:10 | ⬜ | _______ | _______ |
| 4 — Cutover declared complete; Vyapar is now read-only history | 10:15 | ⬜ | _______ | _______ |

### 7-day soak sign-off

Tick each day once the daily monitor checklist (Section 5) was completed green. If any day failed: reset to 0, fix, restart.

| Day | Date | Daily checks green | Initials |
|---|---|---|---|
| 1 | _______ | ⬜ | _______ |
| 2 | _______ | ⬜ | _______ |
| 3 | _______ | ⬜ | _______ |
| 4 | _______ | ⬜ | _______ |
| 5 | _______ | ⬜ | _______ |
| 6 | _______ | ⬜ | _______ |
| 7 | _______ | ⬜ | _______ |

### v1 ship sign-off

- [ ] All 7 soak days passed in sequence with zero P0/P1 bugs filed.
- [ ] TB balanced on every soak day.
- [ ] At least one backup landed in the B2 bucket on every soak day.
- [ ] Update `docs/ops/cutover-plan-2026-05-10.md` Wave-6 status board to `Demo passed`.

**v1 SHIPPED.**
- Moiz: ⬜ shipped / ⬜ not yet (reset reason: _____________)
- Date: _____________

---

## 9. Rollback procedure

Rollback decisions are **time-bound**. Different cutover-day failures need different responses. Read the whole section once before cutover day so you know which path applies if you hit one of these.

### 9.0 Decision tree

- **Failure occurred BEFORE clicking `Approve and commit` (any time in Section 3.1 – 3.3):** rollback is trivial. Vyapar is untouched; Fabric has only an informational migration row. **Go to 9.1.**
- **Failure occurred AFTER `Approve and commit` but on cutover day, within the first hour (Section 3.4 – 3.7):** the morning's pre-cutover backup is still on disk and in the bucket. **Go to 9.2.**
- **Failure occurred during the 7-day soak (Section 5):** depends on severity. Most issues are forward-fixes (file a task, ship a hotfix). Only a corrupt-books scenario triggers a full Vyapar restore. **Go to 9.3.**

Who decides? Moiz, alone. There is no committee. The decision is fast (<10 minutes) because the alternative — sitting in a half-cutover state — is worse than picking either direction.

### 9.1 Before Approve — abort cleanly

The migration row at this point is just a `RECONCILED` status with a reconciliation report. It has zero ledger or party effect.

1. Do NOT click `Approve and commit`.
2. Click `Reject` on the migration row (this is the safer path — marks status=`REJECTED` and writes an audit log entry).
3. Tell anyone who knows about the cutover attempt: "Held back. Cutover did not happen today. Continue using Vyapar."
4. Re-open Vyapar desktop app. Resume normal operation.
5. File a task with the specific failure cause: reconciliation error messages, screenshots of the report, the Vyapar export file. Schedule a new cutover day.

What to keep: the Vyapar export file (for the next attempt), the failed migration row in Fabric (for audit trail).
What to discard: nothing.

### 9.2 After Approve, same day — restore from morning backup

The pre-cutover Postgres state is in this morning's encrypted backup. If you Approved at 09:45 IST today, the backup from `21:30 UTC yesterday = 03:00 IST today` predates the migration.

**Decision point:** is the issue a real corruption (e.g., parties imported with wrong opening balances and you already issued an invoice against one) OR a recoverable bug (e.g., one party's GSTIN is wrong)?

- **Recoverable bug:** edit the affected row manually via the UI. Do not roll back the whole import.
- **Real corruption:** continue below.

Steps:
1. **Stop the production stack** to prevent further writes:
   ```bash
   ssh moiz@app.taana.in
   cd /opt/fabric/repo
   docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production down fastapi
   ```
   (Leave Postgres and Redis up so restore can run.)
2. **Restore the pre-cutover backup** into a sibling DB first (do not overwrite prod yet):
   ```bash
   cd /opt/fabric
   make restore date=$(date -u +%Y-%m-%d) target_db=fabric_erp_predcutover dry_run=1
   make restore date=$(date -u +%Y-%m-%d) target_db=fabric_erp_predcutover
   psql postgresql://fabric:$POSTGRES_PASSWORD@localhost:5432/fabric_erp_predcutover \
     -c "SELECT count(*) FROM party WHERE deleted_at IS NULL;"
   # Expect: zero (or whatever your owner-org's party count was BEFORE the migration — ideally 0).
   ```
3. **Confirm the sibling DB is clean.** Spot-check that no migration row exists:
   ```bash
   psql postgresql://fabric:$POSTGRES_PASSWORD@localhost:5432/fabric_erp_predcutover \
     -c "SELECT migration_id, status, source_filename FROM user_migration;"
   # Expect: zero rows (this is the pre-migration state).
   ```
4. **Cut the swap.** Rename prod → broken; sibling → prod:
   ```bash
   psql postgresql://fabric:$POSTGRES_PASSWORD@localhost:5432/postgres -c "ALTER DATABASE fabric_erp RENAME TO fabric_erp_broken_$(date -u +%Y%m%d);"
   psql postgresql://fabric:$POSTGRES_PASSWORD@localhost:5432/postgres -c "ALTER DATABASE fabric_erp_predcutover RENAME TO fabric_erp;"
   ```
5. **Bring the stack back up:**
   ```bash
   cd /opt/fabric/repo
   docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production up -d fastapi
   ```
6. **Smoke test:**
   ```bash
   curl -sS https://app.taana.in/ready
   # Expect: {"status":"ready","db":true,"redis":true}
   ```
7. **Re-open Vyapar.** Vyapar's data was never touched — it remains the source of truth for all pre-cutover history. The first Fabric invoice you issued at 10:00 has been wiped (along with the migration). Continue on Vyapar until the underlying bug is fixed.
8. File a task with the failure cause. Reschedule cutover.

What to keep: the Vyapar export file, the `fabric_erp_broken_<date>` database (for forensics — drop it after the task is closed).
What to discard: the failed Fabric writes from 09:45 – 10:15. Yes, this includes the first invoice — but you have Vyapar history and you can re-issue it after the next successful cutover.

### 9.3 During soak — fall back per severity

Day-N of the soak. Fabric has been running cleanly until something broke today.

**Severity decision:**
- **P0 (cannot bill):** fall back to Vyapar for billing **right now** to keep the business operating. Triage Fabric offline. After fix, decide whether to re-cutover (re-import the days Vyapar held the writes) or forward-fix (export the Vyapar-only days into Fabric manually). Reset the soak counter to 0.
- **P1 (a money / tax / ledger field is wrong):** keep Fabric running, but issue a stop-the-line for the affected workflow until fixed (e.g., "don't post receipts until the FIFO bug is patched"). Do not fall back to Vyapar unless P0. Reset the soak counter to 0.
- **P2 (something annoying but not money-affecting):** continue. File a task. Soak counter does not reset (per CLAUDE.md cutover plan: only P0/P1 reset it).

There is no automated "restore from backup" path during the soak — by the time you discover a multi-day issue, the morning's backup is more recent than the bug onset. Forward-fix is the standard play. Use `make restore date=YYYY-MM-DD target_db=fabric_erp_<day>` (per `docs/ops/backup-runbook.md` Section 5) to spot-check a previous day's state if forensics requires it.

---

## 10. Post-cutover housekeeping (run within 30 days)

These are not blockers for v1 ship, but get them done while the cutover is fresh.

- [ ] **Archive the Vyapar laptop.** Vyapar desktop app stays installed as a read-only history reference. Do not write to it again. Consider taking a final `.vyp` file backup and putting it on the external SSD.
- [ ] **Update CA's process.** Send your accountant the Fabric URL + their login. Walk them through `/reports` → P&L, TB, Daybook on a quick screen-share. Their next monthly closing happens in Fabric.
- [ ] **Update WhatsApp / email signatures and customer-facing comms** to reflect any new invoice numbering scheme.
- [ ] **Schedule the friendly-customer trial conversation** for ~30 days post-soak (per CLAUDE.md cutover plan "Open questions" #6).
- [ ] **Update `docs/ops/cutover-plan-2026-05-10.md` status board** Wave 6 row from `Blocked` → `Demo passed` once the 7-day soak completes.

---

**End of runbook.**

If you're reading this on cutover day and something is unclear: STOP, do not improvise, fall back to Vyapar, and triage offline. The cost of one delayed cutover day is days; the cost of a corrupt-books day is weeks.
