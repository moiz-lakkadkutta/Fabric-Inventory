# Production Deployment Runbook — `app.taana.in`

Single Hetzner CX22 (~₹800/month). Stack: Postgres 16, Redis 7, FastAPI, web (Vite bundle behind nginx), Caddy fronting TLS. Compose file: `docker-compose.prod.yml`. On-box env: `/opt/fabric/.env.production` (template: `ops/.env.production.example`).

> First user is Moiz. v1 acceptance is 7 consecutive days of operating Fabric without falling back to Vyapar. If prod dies during the soak, fall back to Vyapar and triage; no customer data is at risk during dogfood.

---

## Pre-flight checklist

Run BEFORE pushing the `v0.1.0` tag. Each item is single-decision; do not skip.

- [ ] CI green on `main` HEAD (the commit you intend to tag).
- [ ] CHANGELOG entry for the tag exists (or accept "untracked release notes" for v0.1.0 only).
- [ ] Hetzner CX22 provisioned (steps below).
- [ ] DNS A record `app.taana.in` → CX22 IPv4 (≥10 min propagation; `dig app.taana.in +short` returns the IP).
- [ ] GitHub repo secrets populated (table below).
- [ ] GitHub environment `production` configured with 1 required reviewer.
- [ ] Mailgun domain verified (SPF + DKIM live; sender test mail received).
- [ ] Sentry project `fabric-prod` exists; DSN saved in repo secrets.
- [ ] On-box `/opt/fabric/.env.production` populated from `ops/.env.production.example` and verified read-only to the deploy user.
- [ ] Read **PII encryption status** below — no env var is required for v0.1.0, but you should know what the stub means before you ship.

### PII encryption status (v0.1.0)

`backend/app/utils/crypto.py` is a **deliberate stub** for the MVP.
`encrypt_pii` / `decrypt_pii` UTF-8 encode/decode only — there is no
AES-GCM, no per-org data key, no master key. PII columns (`party.gstin`,
`party.pan`, `party.phone`, `bank_account.account_number`,
`mfa_secret`, …) are `BYTEA` so the column shape is final, and every
service-layer read/write already routes through these helpers (grep
`encrypt_pii\|decrypt_pii` to verify). When the real implementation
lands (TASK-Phase-2 per `app/utils/crypto.py` docstring), no callers
need to change — the swap is internal to `crypto.py`.

What this means for ops:

- **No env var to set for v0.1.0.** There is no `PII_MASTER_KEY` /
  `KMS_KEY_ID` / etc. in `ops/.env.production.example` because the
  stub doesn't read one. Adding a placeholder env var now would be
  misleading.
- **At-rest protection comes from Postgres + the encrypted off-box
  backup, not from this code path** in v0.1.0. The `pgdata` volume
  lives on the CX22's encrypted disk, the daily dump
  (`ops/backup.sh`) is `gpg --symmetric AES256`-encrypted before
  upload to B2 (CUT-501c hardening enforces this in prod via
  `BACKUP_FAIL_PLAINTEXT=1`), and Postgres-to-app traffic stays on
  the docker bridge network.
- **When Phase-2 lands**, `ops/.env.production.example` will gain a
  `PII_MASTER_KEY` (or similar) line and this runbook section grows
  a "rotate the key" entry. Until then, treat any claim that
  "field-level PII encryption is on" as aspirational, not factual.

---

## 1. Provision the Hetzner CX22

1. Hetzner Cloud Console → Add Server.
   - Location: Nuremberg or Helsinki (latency to Indian users is comparable; pick by Hetzner pricing day-of).
   - Image: Ubuntu 24.04 LTS.
   - Type: CX22 (2 vCPU, 4 GB RAM, 40 GB SSD).
   - SSH key: add your ed25519 public key (`ssh-keygen -t ed25519 -C "fabric-deploy@taana.in"` if you don't have one).
   - Name: `fabric-prod-1`.
2. Note the IPv4. Everything downstream uses it.
3. SSH in: `ssh root@<IPv4>`.
4. Create a non-root deploy user:
   ```bash
   adduser --disabled-password --gecos "" moiz
   usermod -aG sudo moiz
   mkdir -p /home/moiz/.ssh
   cp ~/.ssh/authorized_keys /home/moiz/.ssh/
   chown -R moiz:moiz /home/moiz/.ssh
   chmod 700 /home/moiz/.ssh && chmod 600 /home/moiz/.ssh/authorized_keys
   echo "moiz ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/moiz
   ```
5. Disable root SSH + password auth in `/etc/ssh/sshd_config.d/99-fabric.conf`:
   ```
   PermitRootLogin no
   PasswordAuthentication no
   ```
   Then `systemctl reload sshd`.
6. UFW firewall: open 22, 80, 443:
   ```bash
   ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
   ```

---

## 2. DNS

In your DNS provider:

- A record: `app.taana.in` → `<CX22 IPv4>` (TTL 300).
- TXT record (Mailgun): see `ops/.env.production.example` for the values your domain dashboard surfaces.
- DKIM CNAME (Mailgun): same.
- MX records (Mailgun bounces): optional but improves deliverability.

Wait until `dig app.taana.in +short` returns the box IP (5–15 min on most registrars). Caddy's ACME HTTP-01 challenge fails if DNS is not live.

---

## 3. GitHub repo secrets + environment

Settings → Secrets and variables → Actions:

| Secret name | Value |
|---|---|
| `PROD_SSH_KEY` | The PRIVATE ed25519 key for the `moiz` user. Paste the PEM-encoded private key (multi-line). |
| `PROD_SSH_HOST` | `app.taana.in` or the CX22 IPv4. |
| `PROD_SSH_USER` | `moiz`. |
| `SENTRY_DSN_PROD` | Sentry frontend DSN — baked into the web bundle at build time. |

Variables tab:

| Var name | Value |
|---|---|
| `PROD_DOMAIN` | `app.taana.in`. Used as the smoke-test target. |

Environments → New environment → `production`:

- Required reviewers: 1 (yourself; you'll click "approve" before each deploy).
- Wait timer: 0 minutes.
- Deployment branches: `main` and tag pattern `v*` only.

---

## 4. First-time provisioning on the box

SSH in as `moiz`. Run each step deliberately; do not script-glob.

1. Install Docker + compose plugin:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER && newgrp docker
   ```
2. Create `/opt/fabric`:
   ```bash
   sudo mkdir -p /opt/fabric/repo
   sudo chown -R $USER:$USER /opt/fabric
   ```
3. Bootstrap the repo on the box. The deploy workflow rsyncs the compose + ops files on every deploy, so you only need the very first copy by hand:
   ```bash
   cd /opt/fabric/repo
   curl -fsSL https://raw.githubusercontent.com/moiz-lakkadkutta/Fabric-Inventory/main/docker-compose.prod.yml -o docker-compose.prod.yml
   mkdir -p ops
   curl -fsSL https://raw.githubusercontent.com/moiz-lakkadkutta/Fabric-Inventory/main/ops/Caddyfile -o ops/Caddyfile
   curl -fsSL https://raw.githubusercontent.com/moiz-lakkadkutta/Fabric-Inventory/main/ops/.env.production.example -o ops/.env.production.example
   ```
4. Populate `/opt/fabric/.env.production`:
   ```bash
   sudo cp /opt/fabric/repo/ops/.env.production.example /opt/fabric/.env.production
   sudo chown $USER:$USER /opt/fabric/.env.production
   chmod 600 /opt/fabric/.env.production
   # Edit /opt/fabric/.env.production — set:
   #   - POSTGRES_PASSWORD: openssl rand -base64 32
   #   - JWT_SECRET:        openssl rand -base64 32
   #   - MAILGUN_API_KEY:   from Mailgun dashboard (key-...)
   #   - MAILGUN_DOMAIN:    mg.taana.in (or whatever you set up)
   #   - SENTRY_DSN:        from Sentry dashboard
   nano /opt/fabric/.env.production
   ```
5. **The first deploy MUST come from GitHub Actions, not from this box.** The `docker compose pull` step below depends on `ghcr.io/<owner>/fabric-api:<tag>` and `fabric-web:<tag>` already existing in GHCR, which only happens after the `Deploy` workflow's `build-api` + `build-web` jobs run. On a brand-new box those tags don't exist yet, so a manual `pull` here fails with `manifest unknown`.

   Cold-start sequence:
   1. Push the `v0.1.0` tag from your dev box (Section 6) — this triggers the workflow, which builds both images and pushes them to GHCR. The same workflow will then deploy them onto this box automatically. **Stop here for the cold start.** Skip the manual commands below — they're documented for re-bootstrap scenarios (DR / re-imaging the box) only, when the images already exist in GHCR.
   2. Re-bootstrap path (images already in GHCR — e.g. recovering a wiped CX22):
      ```bash
      cd /opt/fabric/repo
      export ENV_FILE=/opt/fabric/.env.production
      # Optionally pin to a known-good tag instead of `latest` before pulling:
      #   sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=v0.1.0/' /opt/fabric/.env.production
      docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production pull
      docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production --profile migrate run --rm migrate
      docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production up -d
      ```
6. After the workflow finishes (cold-start path) or after the manual `up -d` (re-bootstrap path), watch Caddy provision the LE cert (~30s):
   ```bash
   docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production logs -f caddy
   # Look for: "certificate obtained successfully"
   ```
7. Smoke test:
   ```bash
   curl -sS https://app.taana.in/live    # {"status":"live"}
   curl -sS https://app.taana.in/ready   # {"status":"ready","db":true,"redis":true}
   curl -sI https://app.taana.in/         # 200 + HTML
   ```

---

## 5. Mailgun — SPF + DKIM

Indian deliverability without these is poor (Gmail / Outlook drop unauthenticated mail to spam). Skipping this step means the password-reset flow silently fails.

1. Mailgun dashboard → Sending → Domains → Add new domain → `mg.taana.in`.
2. DNS records Mailgun gives you (paste into your DNS provider verbatim):
   - SPF: `v=spf1 include:mailgun.org ~all` as TXT on `mg.taana.in`.
   - DKIM: `k1._domainkey.mg.taana.in` TXT with the long key Mailgun provides.
   - MX (optional): `mxa.mailgun.org` and `mxb.mailgun.org`, priority 10.
3. Wait for Mailgun to flip to "verified" (5–60 min depending on TTL).
4. Test the password-reset flow end-to-end (Section 7 below) once `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_SENDER` are populated in the on-box env file and fastapi has been restarted.

---

## 6. First deploy via GH Actions

After all the above is green:

1. On your dev box: `git tag v0.1.0 && git push origin v0.1.0`.
2. GitHub Actions kicks off `Deploy`. The `build-api` + `build-web` jobs build and push to GHCR.
3. `deploy` job pauses at "Waiting for review". Click "Review deployments" → check "production" → "Approve and deploy".
4. The job rsyncs compose/ops, pins `IMAGE_TAG` on-box, runs migrations, restarts the stack, smoke-tests `/live` + `/ready`. ~4 min total.
5. Verify in the browser: `https://app.taana.in/`. Padlock green; FE loads.

---

## 7. Post-deploy smoke test

Hit these by hand the first time; CI's automated smoke test (last step of the deploy job) handles them on every release after.

- `curl https://app.taana.in/live` — `200 {"status":"live"}`.
- `curl https://app.taana.in/ready` — `200 {"status":"ready","db":true,"redis":true}`.
- Browser: `https://app.taana.in/` → padlock green; React app renders.
- Sign up a throwaway org (`/onboarding`). Try forgot-password:
  - Visit `/forgot`, enter that email + org name.
  - Mailgun delivers the reset link to your inbox within ~30 seconds (NOT in spam — that confirms SPF+DKIM).
  - Click the link, set a new password, sign in. PASS.
- Sentry: from the browser console, throw `throw new Error('CUT-405 smoke test')`. Sentry dashboard shows the event within ~1 min (with PII redacted — no `moiz@...` in the message).

---

## 8. Rollback

Two cases.

### Case A: bad release, want to ship a hotfix forward.

1. Branch off `main`, fix, PR, merge.
2. `git tag v0.1.1 && git push origin v0.1.1`.
3. Approve the new deploy. Same flow as Section 6.

### Case B: bad release, want to revert to the previous version (faster than fixing forward).

1. On your dev box: find the previous green tag (`git tag --sort=-creatordate | head`).
2. Trigger `Deploy` via workflow_dispatch:
   - GitHub → Actions → Deploy → Run workflow.
   - Branch: `main`.
   - Input `image_tag`: e.g. `v0.0.9`.
3. Approve the deploy. GHCR already has the previous image, so build steps are cache-hits; deploy proceeds in ~90s.
4. If the previous release had backward-incompatible migrations (rare; should never happen on this project per CLAUDE.md), you'll need to restore from `pg_dump` first — see TASK-CUT-404's backup runbook.

---

## 9. Daily ops

| Action | Command |
|---|---|
| SSH | `ssh moiz@app.taana.in && cd /opt/fabric/repo` |
| Tail API logs | `docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production logs -f --tail=200 fastapi` |
| Tail Caddy logs | `docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production logs -f --tail=200 caddy` |
| Restart API | `docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production restart fastapi` |
| Re-run migrations | `docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production --profile migrate run --rm migrate` |
| Check disk | `df -h && docker system df` |
| Prune old images | `docker image prune -f` |

---

## 9a. Scheduled jobs (cron)

The MVP runs sync FastAPI only — no Celery, no scheduler daemon. Two
recurring chores:

1. **`make cleanup`** — prunes `password_reset_token` rows
   (`used > 7d` or `expires < now - 1d`) so the table doesn't grow
   unbounded. CUT-501a.
2. **`ops/backup.sh`** — encrypted Postgres dump → local + B2 (CUT-404).
   Requires the host→container connectivity choice in §9b below
   (option (a) is the documented default — the cron line uses
   `docker compose exec`).

Install on the box as a system crontab line for the deploying user:

```cron
# m h dom mon dow  command

# 04:30 IST — token cleanup
30 4 * * * cd /opt/fabric/repo && make cleanup >> /var/log/fabric-cleanup.log 2>&1

# 03:00 IST — encrypted Postgres dump + B2 upload (option (a), see §9b).
# Requires ops/.env.backup to exist on the box (chmod 600) and the
# postgres service in docker-compose.prod.yml to be up.
0 3 * * * cd /opt/fabric/repo && ./ops/backup.sh >> /var/log/fabric-backup.log 2>&1
```

`make cleanup` runs at 04:30 IST (off-peak). Idempotent — re-running
deletes nothing on the second invocation. The log line carries the
deleted-row count so a `tail -n 20 /var/log/fabric-cleanup.log` shows
the trend at a glance.

`ops/backup.sh` runs at 03:00 IST so the artefact is on the box BEFORE
the morning's first user activity. It's gated on
`BACKUP_GPG_PASSPHRASE` (refuses to write plaintext when
`BACKUP_FAIL_PLAINTEXT=1` per `ops/.env.production.example` — CUT-501c).

To add a job here later (e.g. an e-way bill cancellation reaper when
that feature lands): add a new `make <thing>` target + a crontab line
+ a doc entry in this section. Resist adding Celery until the first
job has fan-out / retry needs the Makefile can't model — see CLAUDE.md
"Manufacturing / mobile / WhatsApp" deferral note.

---

## 9b. Backup host→container connectivity (CUT-404 follow-up)

`ops/backup.sh` shells out to `pg_dump`, which needs a route to the
Postgres server. The `postgres` service in `docker-compose.prod.yml`
deliberately does NOT publish a host port (line 34: "No host port
published — only fastapi reaches it on the docker network"), so the
default `POSTGRES_HOST=localhost` in `ops/.env.backup.example` cannot
reach the DB from the host.

Two viable fixes were considered; **the runbook uses option (a)**:

**(a) Run pg_dump inside the docker network via `compose exec` — CHOSEN.**

Keep Postgres unpublished (no attack surface on the host's loopback
either, which matters once monitoring agents like node_exporter run as
non-root with localhost binds). The cron line invokes `pg_dump`
through `docker compose exec -T postgres`, which talks over the docker
bridge network. The `ops/backup.sh` script keeps working as written —
the only adjustment is to wrap the cron invocation so the script's
`pg_dump` shells out via `docker compose exec` instead of running on
the host. The simplest expression of this is the cron line in §9a:
the script runs from inside `/opt/fabric/repo`, where it can see
`docker-compose.prod.yml`; if you swap the `pg_dump` invocation for
`docker compose exec -T postgres pg_dump …` in a thin wrapper (a
follow-up task), no host-side `postgresql-client` install is needed
either.

**(b) Publish `127.0.0.1:5432:5432` on the postgres service. NOT USED.**

Would mean adding `ports: ["127.0.0.1:5432:5432"]` to the `postgres`
service in `docker-compose.prod.yml`. Localhost-only (no public
exposure) — but it adds a redundant network path purely for one cron
job. Rejected because it muddies the "DB is internal" invariant for
no measurable gain over option (a).

### Operator action for fix-up

Until the thin `ops/backup-in-container.sh` wrapper lands (small
follow-up), invoke `pg_dump` over the docker network manually if
running `ops/backup.sh` end-to-end on the host fails with
`could not connect to server: Connection refused`. The simplest test:

```bash
cd /opt/fabric/repo
docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production \
  exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip -9 > /opt/fabric/backups/manual_$(date -u +%Y%m%dT%H%M%SZ).sql.gz
```

This proves the in-network path works before the cron line takes
over.

---

## 10. P0 escalation

**P0 = Moiz can't bill a customer right now.** Anything else can wait.

1. If `/live` or `/ready` is failing and a quick restart (`docker compose restart fastapi`) doesn't fix it, fall back to Vyapar for billing immediately. Triage at leisure.
2. If Caddy cannot renew its cert (LE rate-limit, DNS misconfigured): `docker compose logs caddy` — search for "ACME"/"obtain"/"challenge". Last-resort fix is `caddy reload` after the underlying issue is corrected.
3. If `pg` won't start: check `docker compose logs postgres` for FS-level errors. Restore from yesterday's backup (TASK-CUT-404 runbook).
4. After every P0: write a one-paragraph incident note at `docs/retros/incidents/<date>.md`. No need to be elaborate; pattern emerges only if we record them.

---

## 11. User invite flow

Operators (Owners) invite the rest of the org from `/admin`. There's
no self-signup once an org exists — the only way to add a user is via
an invite. Documenting the exact post-accept UX here so nobody is
surprised when they walk a new user through it.

### How an Owner sends an invite

1. Sign in as Owner, visit `/admin`. The page is `AdminHub`
   (`frontend/src/pages/admin/AdminHub.tsx`), gated by
   `admin.user.manage`.
2. Click **+ Invite user** → fill email, pick a role from the
   dropdown (sourced from `GET /admin/roles`), optionally pick a
   firm. Submit. The FE calls `POST /admin/invites`.
3. The response (`InviteCreateResponse`) carries the invite link.
   The Owner sees a toast with the link; the same link is also
   `print()`-ed to the backend stdout (dev console-log adapter) and
   sent via Mailgun in prod once `EMAIL_PROVIDER=mailgun` is set
   (see §5).
4. The new row appears in the AdminHub users table only AFTER the
   invitee accepts. Until then the invite is in `user_invite` table
   with `used_at = NULL`. Owners with the `admin.user.manage`
   permission could query that table directly; the FE doesn't
   surface pending invites in v1 (filed follow-up).

### What the invitee sees after clicking the link

The invite link is `${FRONTEND_URL}/invite/<32-byte-hex-token>` (see
`backend/app/service/invite_service.py::_frontend_invite_url`). The
public page `AcceptInvite` (no auth required, outside `<RequireAuth>`)
renders a tiny form: **Your name** + **Password**. On submit the FE
calls `POST /admin/invites/accept` with `{ token, name, password }`
and gets back this shape:

```jsonc
// 201 Created — AcceptInviteResponse
{
  "user_id":  "<uuid>",
  "org_id":   "<uuid>",
  "email":    "naseem@example.com",
  "org_name": "Audit Co"
}
```

**Note: no tokens are issued.** The accept endpoint deliberately
returns 201 + identity (not a session). The FE then redirects to
`/login` with `prefillEmail` + `prefillOrgName` + a flash message
("Invite accepted. Sign in to continue."). The invitee types the
password they just set and goes through the standard login flow.

### Why no auto-login? (the decision)

Two paths were on the table; v1 picked option B.

| | A — Auto-login on accept | B — Redirect to `/login` after accept (CURRENT) |
|---|---|---|
| Server returns | Access + refresh tokens | 201 + identity envelope, no tokens |
| Invitee experience | Lands signed-in on `/` | Types password they just set; one extra click |
| MFA enrollment | Bypassed on first session (worse, if the org turns MFA on later) | Exercised on first login like every other user |
| bcrypt verify path | Not exercised at first session | Exercised — proves the password the user just set actually unlocks the account |
| Code surface | Need to mint tokens at accept-time, plumb refresh, special-case session-without-login | One redirect; standard `/login` flow works as-is |
| Trade-off | One-fewer click for the invitee | Invitee types the password twice in ~5 seconds |

**v1 picked B** for the dogfood phase. The trade-off — typing the
password twice — is acceptable because (a) the redirect arrives with
email + org name pre-filled so only the password field is empty,
(b) MFA-enrollment will need this path anyway when we turn MFA on
(per CLAUDE.md "MFA mandatory for Admin"), and (c) it halves the
auth-related code surface for the same dogfood outcome. Documented
in `docs/retros/task-CUT-304.md` § "Accept-endpoint returns 201 +
redirect-to-/login".

If feedback from a friendly customer's trial pushes us to switch to
auto-login (option A) post-v1, the change is:

1. Service-layer: have `accept_invite()` mint an
   `access_token` + `refresh_token` pair from `identity_service` and
   include them in `AcceptInviteResponse`.
2. FE-layer: `AcceptInvite.tsx::onSuccess` does
   `authStore.set({ accessToken, refreshToken, ... })` and navigates
   to `/` instead of `/login`.
3. Tests: `tests/test_admin_invites.py` adds a happy-path that
   asserts the response carries tokens; the FE test asserts the
   landing is `/` not `/login`.

That's a ~1-day task. Not on the v1 critical path.

### What the Owner sees on `/admin/users` after accept

The accept handler:

1. Creates an `app_user` row (`email`, `legal_name=body.name`,
   bcrypt'd password hash).
2. Creates a `user_role` row mapping that user to the invited
   role + (optional) firm.
3. Stamps `user_invite.used_at = now()` and clears the token.
4. Emits audit-log entries: `invite.accept` + `user_role.create`.

The next `GET /admin/users` shows the new row with:

- `status: "ACTIVE"`
- `last_login_at: null` (they haven't completed the `/login` step yet)
- `role: "<the role display name>"`
- `created_at` is the accept moment, not the invite moment

After the invitee logs in successfully for the first time,
`last_login_at` populates and the per-row `<select>` for role-change
appears (Owner can promote/demote via `PATCH /admin/users/{id}/role`,
gated by `admin.user.manage`, with last-Owner-demotion protection at
the service layer).

### Idempotency notes

- `POST /admin/invites` is **idempotent by email-within-org**: if an
  Owner clicks Invite twice for the same email, the same `invite_id`
  is returned but the token is rotated. This stops row sprawl when
  the Owner thinks the first invite didn't go through.
- `POST /admin/invites/accept` is in
  `app/middleware/idempotency.py::IDEMPOTENT_BY_DESIGN_PATHS`, so the
  invitee doesn't need to mint a UUID. The single-use invite token is
  the idempotency key by construction (sha256-hashed in DB, `used_at`
  stamped atomically; replays return `TOKEN_INVALID`).

### Operational checklist

- [ ] When `EMAIL_PROVIDER=console`, the invite link prints to backend
      stdout. `docker compose logs fastapi | grep invite` finds it.
- [ ] When `EMAIL_PROVIDER=mailgun`, double-check SPF + DKIM in
      `app.taana.in` DNS (see §5 of this runbook).
- [ ] Tokens expire after 7 days. Invitees who miss the window get
      `TOKEN_INVALID`; the Owner re-clicks Invite to mint a fresh
      one.
- [ ] If an Owner ever deletes themselves: the service refuses
      (`last_owner` 422). Add a second Owner first via this flow.

---

## What's deliberately deferred (post-v0.1.0)

- Hot standby / multi-region. Single CX22 only until paying customer #1.
- Sentry Replay. Free-tier errors + tracing only until paying customer.
- Blue/green deploys. Compose `up -d` does a rolling restart per service; ~5s downtime per deploy is acceptable for dogfood.
- Celery worker + Redis-backed e-invoice async submission. Phase 1 stays sync.
