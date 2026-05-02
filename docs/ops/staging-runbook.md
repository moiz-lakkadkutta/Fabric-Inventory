# Staging runbook — `staging.taana.in`

Single Hetzner CX22, single box. Stack: Postgres 16, Redis 7, FastAPI, web (built Vite bundle behind nginx), Caddy fronting TLS at `staging.taana.in`. Compose file: `docker-compose.staging.yml`. Env file (not in git): `/opt/fabric/.env.staging`.

> No customer data is in staging. Vyapar remains source-of-truth during dogfood. If staging dies, the worst case is rebuild + restore from yesterday's `pg_dump` and double-enter the day's invoices.

---

## First-time provisioning (one box, one shot)

These are the steps Moiz runs once to bring `staging.taana.in` online. They are deliberately bash-runnable; no scripted automation yet.

1. **Provision Hetzner CX22.** Ubuntu 24.04 LTS. Add SSH key. Note IPv4.
2. **DNS.** Point `staging.taana.in` A record to the CX22 IPv4. Wait for propagation (`dig staging.taana.in +short` returns the box IP).
3. **Install Docker + compose plugin** on the box:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER && newgrp docker
   ```
4. **Clone repo + populate env file.** As `moiz` (or whatever non-root user owns deploys):
   ```bash
   sudo mkdir -p /opt/fabric && sudo chown $USER:$USER /opt/fabric
   git clone https://github.com/moiz-l/fabric /opt/fabric/repo
   ln -s /opt/fabric/repo/docker-compose.staging.yml /opt/fabric/docker-compose.staging.yml
   ln -s /opt/fabric/repo/ops /opt/fabric/ops
   cp /opt/fabric/repo/ops/staging/.env.staging.example /opt/fabric/.env.staging
   # Edit /opt/fabric/.env.staging — set strong POSTGRES_PASSWORD and JWT_SECRET.
   chmod 600 /opt/fabric/.env.staging
   ```
5. **Bring up the stack.** First start of Caddy provisions the LE cert (DNS must be live):
   ```bash
   cd /opt/fabric
   docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging up -d
   ```
6. **Run alembic migrations once:**
   ```bash
   docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging \
     run --rm fastapi uv run alembic upgrade head
   ```
7. **Seed.** A signup-on-first-org flow is the canonical seeder; for staging dogfood, use the dev seed CLI to populate Rajesh Textiles + 25 invoices:
   ```bash
   docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging \
     run --rm fastapi uv run python -m app.cli.seed --org-slug rajesh-textiles --full
   ```
   *(If `--full` flag does not exist yet, use whatever seeding entry-point exists; this is the pre-T-INT-1 placeholder.)*
8. **Wire nightly backup.** From the repo on the box:
   ```bash
   sudo cp /opt/fabric/repo/ops/staging/pg-backup.sh /usr/local/bin/fabric-pg-backup
   sudo chmod +x /usr/local/bin/fabric-pg-backup
   ( sudo crontab -l 2>/dev/null; echo "0 3 * * * /usr/local/bin/fabric-pg-backup >> /var/log/fabric-pg-backup.log 2>&1" ) | sudo crontab -
   ```
9. **Smoke test:**
   ```bash
   curl -s https://staging.taana.in/api/v1/health    # → {"ok": true}
   curl -sI https://staging.taana.in/                # → 200 with HTML
   ```
10. **Sentry.** Drop the staging DSN into `/opt/fabric/.env.staging` (`SENTRY_DSN=`), then `docker compose ... restart fastapi`. Throw a test error from the API to confirm events arrive.

---

## Daily operations

### SSH in
```bash
ssh moiz@staging.taana.in
cd /opt/fabric
```

### Tail logs
```bash
docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging logs -f --tail=200 fastapi
```

### Restart a service
```bash
docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging restart fastapi
docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging restart caddy
```
Restarts are zero-data-loss; Postgres is unaffected unless explicitly touched.

### Apply migrations after a deploy
The deploy workflow runs migrations automatically. To re-run by hand:
```bash
docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging \
  run --rm fastapi uv run alembic upgrade head
```

### Pull a new image manually (if Actions is broken)
```bash
docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging pull
docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging up -d
```

---

## Restore from snapshot

Backups are gzipped pg_dump in `/opt/fabric/ops/staging/pg-backups/fabric_staging_<ts>.sql.gz`. 7-day retention.

```bash
# 1. Stop the API so nothing writes during restore
docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging stop fastapi

# 2. Pipe the gzipped dump into psql
gunzip -c /opt/fabric/ops/staging/pg-backups/fabric_staging_<ts>.sql.gz | \
  docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging \
  exec -T postgres psql -U "$POSTGRES_USER" "$POSTGRES_DB"

# 3. Bring API back up
docker compose -f docker-compose.staging.yml --env-file /opt/fabric/.env.staging start fastapi
```

Expected restore time on a CX22 with the dogfood-sized DB: < 5 minutes.

---

## P0 escalation

**P0 = Moiz can't bill a customer right now.** Anything else can wait.

1. Page Moiz directly (he's the only oncall during dogfood).
2. If staging is down for > 2h, switch back to Vyapar-only and triage at leisure. **There is no data loss** because Vyapar is the source-of-truth during the dogfood window.
3. After resolution: post a one-paragraph incident note in `docs/retros/incidents/<date>.md` even if no code changed. Pattern emerges that way.

---

## Out of scope (post-T-INT-5)

- Production (`app.taana.in`). Stands up after PR-INT-5 + 1-week soak (per `integration-plan.md` Q10a).
- S3 / B2 off-box backup. Currently local-disk only.
- Hot standby / multi-region. Single CX22 only until paying customer #1.
- Sentry Replay. Free-tier errors + tracing only until paying customer.
