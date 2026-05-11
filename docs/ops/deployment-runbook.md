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
5. Bring up the stack manually for the first time (the deploy workflow takes over from the next push):
   ```bash
   cd /opt/fabric/repo
   export ENV_FILE=/opt/fabric/.env.production
   docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production pull
   docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production --profile migrate run --rm migrate
   docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production up -d
   ```
6. Watch Caddy provision the LE cert (~30s):
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

## 10. P0 escalation

**P0 = Moiz can't bill a customer right now.** Anything else can wait.

1. If `/live` or `/ready` is failing and a quick restart (`docker compose restart fastapi`) doesn't fix it, fall back to Vyapar for billing immediately. Triage at leisure.
2. If Caddy cannot renew its cert (LE rate-limit, DNS misconfigured): `docker compose logs caddy` — search for "ACME"/"obtain"/"challenge". Last-resort fix is `caddy reload` after the underlying issue is corrected.
3. If `pg` won't start: check `docker compose logs postgres` for FS-level errors. Restore from yesterday's backup (TASK-CUT-404 runbook).
4. After every P0: write a one-paragraph incident note at `docs/retros/incidents/<date>.md`. No need to be elaborate; pattern emerges only if we record them.

---

## What's deliberately deferred (post-v0.1.0)

- S3 / B2 off-box backup. CUT-404 lands local-disk `pg_dump`; off-box upload is a v2 task.
- Hot standby / multi-region. Single CX22 only until paying customer #1.
- Sentry Replay. Free-tier errors + tracing only until paying customer.
- Blue/green deploys. Compose `up -d` does a rolling restart per service; ~5s downtime per deploy is acceptable for dogfood.
- Celery worker + Redis-backed e-invoice async submission. Phase 1 stays sync.
