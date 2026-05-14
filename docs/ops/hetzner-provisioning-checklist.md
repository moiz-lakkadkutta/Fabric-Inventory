# Hetzner Provisioning Checklist — first production deploy

**Created:** 2026-05-14 (TASK-TR-E01, Wave 0)
**Status of deploy infra:** artifacts are written and mostly **READY** — but the stack has **never been run**. This doc is the audited, corrected path to a first deploy. It supersedes the sequencing in `docs/ops/deployment-runbook.md` where they conflict (see "Runbook bugs" below).

---

## TL;DR

`backend/Dockerfile.prod`, `frontend/Dockerfile.prod`, `docker-compose.prod.yml`, `.github/workflows/deploy.yml`, `ops/Caddyfile`, `ops/backup.sh`, `ops/restore.sh` are all production-grade and coherent. The migration ordering in `deploy.yml` is correct (migrate one-shot runs before `fastapi` flips). **Nothing is fundamentally broken** — but there are 9 cold-start sequencing/config blockers that will fail a naive first deploy, plus a handful of small repo fixes (tracked as TASK-TR-E01a).

---

## Critical blockers — resolve before / during provisioning

1. **Deploy artifacts must be on `main`.** `deploy.yml` rsyncs the compose + ops files, but the runbook's box-bootstrap `curl`s raw GitHub URLs. Confirm `docker-compose.prod.yml` + `ops/*` + both `Dockerfile.prod` are committed to `main`. Decide repo visibility (private → needs GHCR auth on the box; see #3).
2. **GHCR images don't exist until the first tag is pushed.** Correct cold-start order: provision box → push `v0.1.0` tag → CI builds + pushes images → *then* the box can pull. Do **not** run the runbook's §4.5 manual `docker compose pull` before any image exists.
3. **GHCR packages are private by default on first push.** Either make `fabric-api` + `fabric-web` packages public after the first push, **or** `docker login ghcr.io` on the box with a PAT (`read:packages`). Without one, `compose pull` fails with `denied`.
4. **`backup.sh` cannot reach Postgres from the host** — `docker-compose.prod.yml` publishes no host port for postgres. Run backups via `docker compose exec postgres pg_dump`, or publish `127.0.0.1:5432:5432`. **No backup cron is wired at all** — only `make cleanup` is croned. Add a backup cron line (step F26).
5. **`ops/.env.backup.example` DB-name mismatch** — ships `fabric_erp`, prod DB is `fabric_prod`. Fix when creating `ops/.env.backup` on the box.
6. **DNS must resolve before stack bring-up** — Caddy's ACME HTTP-01 challenge fails and backs off if `app.taana.in` A record isn't live when Caddy first starts.
7. **GitHub `production` environment + secrets don't exist yet** — `PROD_SSH_KEY`, `PROD_SSH_HOST`, `PROD_SSH_USER`, `SENTRY_DSN_PROD`, var `PROD_DOMAIN`, and the `production` environment with a required reviewer all need to be created.
8. **Mailgun unconfigured = silent auth-mail failure** — blank `MAILGUN_API_KEY` falls back to a console adapter; password-reset/invite emails won't send, with no error.
9. **No `backend/.dockerignore`** — a committed `backend/.env` could be baked into the image. Low risk; fixed in TASK-TR-E01a.

---

## Secrets to generate up front (store in a password manager)

| Secret | Generate with | Goes where |
|--------|---------------|-----------|
| `POSTGRES_PASSWORD` | `openssl rand -base64 32` | `/opt/fabric/.env.production` + `ops/.env.backup` |
| `JWT_SECRET` | `openssl rand -base64 32` (min 16 chars) | `/opt/fabric/.env.production` |
| `BACKUP_GPG_PASSPHRASE` | `openssl rand -base64 48` | `ops/.env.backup` |
| Deploy SSH keypair | `ssh-keygen -t ed25519 -C fabric-deploy -f ~/.ssh/fabric_deploy` | private → GH secret `PROD_SSH_KEY`; public → box |
| Sentry backend DSN | Sentry project `fabric-prod` | `/opt/fabric/.env.production` `SENTRY_DSN` |
| Sentry frontend DSN | same project | GH secret `SENTRY_DSN_PROD` (baked into web bundle) |
| Mailgun API key | Mailgun, domain `mg.taana.in` | `/opt/fabric/.env.production` |
| B2 keys | Backblaze B2 bucket `fabric-erp-backups` | `ops/.env.backup` (`B2_ACCESS_KEY_ID`, `B2_SECRET_KEY`) |

`CORS_ORIGINS` and `FRONTEND_URL` must be `https://app.taana.in` (non-empty `CORS_ORIGINS` or the backend refuses to start).

---

## Provisioning checklist

### Phase A — Prerequisites (before touching the box)
1. Push deploy artifacts to `main`; decide repo visibility.
2. (TASK-TR-E01a) Add `backend/.dockerignore` + `frontend/.dockerignore`.
3. Generate all secrets above.
4. Create the deploy SSH keypair.
5. Create Sentry project `fabric-prod`; note backend + frontend DSNs.
6. Sign up for Mailgun; add domain `mg.taana.in`.
7. Sign up for Backblaze B2; create bucket + application key.

### Phase B — Box + DNS
8. Hetzner → Add Server: Ubuntu 24.04 LTS, **CX22**, add `fabric_deploy.pub`, name `fabric-prod-1`. Note the IPv4.
9. DNS A record: `app.taana.in` → `<IPv4>`, TTL 300. Wait until `dig app.taana.in +short` returns the IP.
10. Add Mailgun DNS records (SPF, DKIM, optional MX); wait for "verified".
11. SSH as root: create `moiz` deploy user, copy `authorized_keys`, passwordless sudo, disable root SSH + password auth, UFW 22/80/443. (runbook §1.4–6)

### Phase C — GitHub config
12. Repo → Settings → Secrets → Actions: `PROD_SSH_KEY` (private key), `PROD_SSH_HOST` = `app.taana.in`, `PROD_SSH_USER` = `moiz`, `SENTRY_DSN_PROD` = frontend DSN.
13. → Variables: `PROD_DOMAIN` = `app.taana.in`.
14. → Environments → new `production`: 1 required reviewer (yourself), branches = `main` + tag `v*`.

### Phase D — On-box first-time setup
15. SSH as `moiz`. Install Docker: `curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER && newgrp docker`.
16. `sudo mkdir -p /opt/fabric/repo && sudo chown -R $USER:$USER /opt/fabric`.
17. Resolve GHCR auth: make packages public after first push, **or** `docker login ghcr.io` with a `read:packages` PAT.
18. Get compose + ops files onto the box (`scp` from dev box, or `git clone`).
19. `cp ops/.env.production.example /opt/fabric/.env.production`, `chmod 600`, fill `POSTGRES_PASSWORD`, `JWT_SECRET`, `MAILGUN_API_KEY`, `SENTRY_DSN` (backend). Keep `CORS_ORIGINS`/`FRONTEND_URL` = `https://app.taana.in`.
20. `cp ops/.env.backup.example ops/.env.backup`, `chmod 600`, set `POSTGRES_DB=fabric_prod` (**not** the template's `fabric_erp`), `POSTGRES_PASSWORD`, `BACKUP_GPG_PASSPHRASE`, `B2_*`. Decide host→container Postgres path.

### Phase E — First deploy
21. From dev box, CI green on `main` → `git tag v0.1.0 && git push origin v0.1.0`. Triggers image build + push.
22. GitHub → Actions → Deploy run → "Review deployments" → approve `production`. Job rsyncs, pins `IMAGE_TAG`, migrates, `up -d`, smoke-tests.
23. Watch Caddy get its cert: `docker compose -f docker-compose.prod.yml --env-file /opt/fabric/.env.production logs -f caddy` → "certificate obtained successfully".

### Phase F — Verify & harden
24. Smoke test: `curl https://app.taana.in/live` → `{"status":"live"}`; `/ready` → `{"status":"ready","db":true,"redis":true}`; browser → green padlock, app renders.
25. Test mail: sign up a throwaway org, run forgot-password, confirm the Mailgun email arrives (not spam).
26. Cron (`crontab -e` as `moiz`):
    - `30 4 * * * cd /opt/fabric && make cleanup >> /var/log/fabric-cleanup.log 2>&1`
    - **`0 3 * * * cd /opt/fabric/repo && ./ops/backup.sh >> /var/log/fabric-backup.log 2>&1`** — first run it by hand and confirm a `.gpg` lands in B2.
27. Verify restore round-trips once: `./ops/restore.sh --date=<today> --target-db=fabric_restore_test --dry-run`, then for real into a scratch DB.

---

## Runbook bugs found (also tracked in TASK-TR-E01a)
- `docs/ops/deployment-runbook.md` §4 (manual bring-up) is sequenced before any GHCR image exists — reorder or add a "push tag first" note.
- Runbook "deferred: S3/B2 backup is v2" contradicts the already-implemented B2 upload in `ops/backup.sh`.
- `ops/.env.backup.example`: `POSTGRES_DB` should be `fabric_prod`.
- Missing `backend/.dockerignore` + `frontend/.dockerignore`.
- Confirm whether field-level PII encryption needs an env var (none in `ops/.env.production.example` or `config.py` — likely not wired yet; verify before go-live).

---

**Note:** This is the *verification* deliverable of TASK-TR-E01. Actually provisioning the box is Moiz's gated action (real infra, costs money). When the box exists, the remaining E01 work — running the deploy and confirming Phase F — can be closed out.
