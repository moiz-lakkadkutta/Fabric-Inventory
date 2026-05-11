# Backup runbook (TASK-CUT-404)

Last updated: 2026-05-11
Owner: Moiz · On-call: whoever has the prod box SSH key

This runbook covers the daily Postgres backup loop on the prod Hetzner CX22:
provision the bucket, set credentials, run the first backup, verify it, set
up cron, and recover from it.

The scripts live in `ops/`:

- `ops/backup.sh` — pg_dump → gzip → gpg → S3-compatible upload + retention prune
- `ops/restore.sh` — pull from bucket (or local), decrypt, restore
- `ops/.env.backup.example` — credential template

The Makefile thin-wraps both:

```
make backup
make restore date=YYYY-MM-DD [target_db=NAME] [dry_run=1]
make restore-test            # the round-trip integration test
```

---

## 1. Choose the bucket provider

Two cheap S3-compatible options. **Default = Backblaze B2** (cheapest, free
egress to Cloudflare which we already use). Hetzner is the safe fallback if
you want single-vendor (everything in Hetzner: VM + storage).

| Provider | Storage cost (1 TB/mo) | Egress | Notes |
|----------|-----------------------|--------|-------|
| Backblaze B2 (default) | **$6.00** (~₹500) | Free to Cloudflare (10x storage cap), $0.01/GB elsewhere | Cheapest. S3-compatible. |
| Hetzner Object Storage | **€5.99** (~₹540) | 1 TB free / month | Single-vendor with prod box. EU-only locations. |
| AWS S3 (Standard) | $23.00 (~₹1900) | $0.09/GB | Reference price only. Not used. |

Either way the script uses the same env vars (`B2_*`) — only the endpoint URL
and region change.

---

## 2. Provision the bucket (Backblaze B2)

One-time setup, ~5 min.

1. Sign up at https://www.backblaze.com/cloud-storage (no credit card required for first 10 GB).
2. **Create a bucket:** Buckets → Create a Bucket
   - Name: `fabric-erp-backups` (must be globally unique; if taken, prefix with your initials e.g. `mlk-fabric-erp-backups`)
   - Files in bucket are: **Private**
   - Default encryption: **Disable** (we encrypt with gpg locally; double-encrypting wastes CPU)
   - Object Lock: **Disable** (we want to prune)
3. **Lifecycle rule:** in the bucket settings → Lifecycle Settings → "Keep only the last version of the file". This is belt-and-braces; the script also prunes via `aws s3 rm`.
4. **App key:** App Keys → Add a New Application Key
   - Name: `fabric-erp-backup-prod`
   - Allow access to bucket: pick the bucket you just created (do NOT use the master key — least privilege)
   - Type of access: **Read and Write**
   - Save the keyID and applicationKey shown on the next screen — they're shown **once**.
5. **Endpoint URL:** displayed on the bucket page. Looks like
   `https://s3.us-east-005.backblazeb2.com`. The region is the slug after
   `s3.` (e.g. `us-east-005`).

### Alternate: Hetzner Object Storage

1. Hetzner Cloud Console → Object Storage → Create Bucket
   - Name: `fabric-erp-backups`
   - Location: pick the same data centre as the prod box (e.g. `fsn1`)
2. Generate S3 credentials in the project's Security → S3 Credentials tab.
3. Endpoint URL: `https://<location>.your-objectstorage.com` (e.g. `https://fsn1.your-objectstorage.com`).
4. Region = the location slug (`fsn1`).

---

## 3. Configure the prod box

SSH to the prod box. Assumes the repo is checked out under `/opt/fabric`.

```bash
ssh moiz@prod.fabric.app
cd /opt/fabric

# Install dependencies (Ubuntu 24.04):
sudo apt-get update
sudo apt-get install -y postgresql-client-16 awscli gnupg

# Copy + fill in the credential template:
cp ops/.env.backup.example ops/.env.backup
chmod 600 ops/.env.backup
nano ops/.env.backup   # paste the bucket creds + a fresh GPG passphrase
```

### Generating the GPG passphrase

```bash
openssl rand -base64 48
```

Paste the output as `BACKUP_GPG_PASSPHRASE`. **Also paste it into your password
manager** (1Password / Bitwarden / paper in a safe). Losing this string =
losing every backup — gpg cannot recover.

---

## 4. First backup (smoke test)

```bash
cd /opt/fabric
make backup
```

Expected output (last few lines):

```
[2026-05-11T...] dump complete: ./ops/backups/fabric_fabric_erp_2026-05-11_*.sql.gz (12M)
[2026-05-11T...] encrypted artefact: ./ops/backups/fabric_fabric_erp_2026-05-11_*.sql.gz.gpg (12M)
[2026-05-11T...] uploading to s3://fabric-erp-backups/fabric_fabric_erp_...sql.gz.gpg
[2026-05-11T...] upload complete
[2026-05-11T...] backup done: ./ops/backups/fabric_fabric_erp_...sql.gz.gpg
```

Verify the bucket has the file (web UI is fastest), or:

```bash
source ops/.env.backup
AWS_ACCESS_KEY_ID="$B2_ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$B2_SECRET_KEY" \
AWS_DEFAULT_REGION="$B2_REGION" \
  aws --endpoint-url "$B2_ENDPOINT_URL" s3 ls "s3://$B2_BUCKET/"
```

---

## 5. Restore test (must do before declaring success)

A backup that has never been restored is not a backup. Run this **the same
day** as your first real backup.

```bash
# Dry-run first to print the plan:
make restore date=$(date -u +%Y-%m-%d) dry_run=1

# Real restore into a sibling DB (does NOT touch the prod DB):
createdb -U fabric fabric_erp_restore_test
make restore date=$(date -u +%Y-%m-%d) target_db=fabric_erp_restore_test

# Spot-check:
psql -U fabric -d fabric_erp_restore_test -c "SELECT count(*) FROM party;"
# Should match prod's count.

# Tear down:
dropdb -U fabric fabric_erp_restore_test
```

The `tests/test_backup.sh` integration test runs this round-trip automatically
in CI on every PR that touches `ops/`, plus weekly via `backup-test.yml`. If
that test ever goes red, treat it as a P1.

---

## 6. Daily cron

Add to root's crontab on the prod box:

```bash
sudo crontab -e
```

```
# Fabric ERP nightly backup — runs daily at 03:00 IST (=21:30 UTC)
# Logs to /var/log/fabric-backup.log; rotated by logrotate (configure separately).
30 21 * * * cd /opt/fabric && /usr/bin/make backup >> /var/log/fabric-backup.log 2>&1
```

Then:

```bash
sudo touch /var/log/fabric-backup.log
sudo chown root:root /var/log/fabric-backup.log

# Smoke-test the cron path (matches what cron will run):
sudo bash -c 'cd /opt/fabric && /usr/bin/make backup' | tail -20
```

### Log rotation (optional but recommended)

```bash
sudo tee /etc/logrotate.d/fabric-backup >/dev/null <<'EOF'
/var/log/fabric-backup.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
EOF
```

---

## 7. Monitoring

Until we wire Sentry/Healthchecks.io into the cron, **eyeball
`/var/log/fabric-backup.log` weekly**. The shape of a healthy line:

```
[2026-05-12T21:30:01+00:00] dump complete: .../fabric_fabric_erp_2026-05-12_*.sql.gz.gpg (12M)
[2026-05-12T21:30:04+00:00] upload complete
[2026-05-12T21:30:05+00:00] pruning bucket objects older than 7 days
[2026-05-12T21:30:06+00:00] backup done: .../fabric_..._.sql.gz.gpg
```

When a paying customer lands, swap in
[Healthchecks.io](https://healthchecks.io/) (free tier) by appending a curl
to the cron line:

```
30 21 * * * cd /opt/fabric && /usr/bin/make backup >> /var/log/fabric-backup.log 2>&1 && curl -fsS -m 10 --retry 3 https://hc-ping.com/<UUID>
```

That pings on success only; the dashboard alerts you when a ping is missed.

---

## 8. Disaster recovery

**Scenario: prod box dies, you have only the bucket.**

1. Spin up a fresh Hetzner CX22, install Docker + Postgres 16 client + gpg + awscli.
2. Clone the repo: `git clone <repo> /opt/fabric && cd /opt/fabric`.
3. Restore `ops/.env.backup` from your password manager (the GPG passphrase + B2 creds are the only secrets needed).
4. Bring up Postgres locally (e.g. `docker compose up postgres -d`).
5. Create the prod DB: `createdb -U fabric fabric_erp`.
6. Restore the newest backup:

   ```bash
   make restore date=$(date -u +%Y-%m-%d) target_db=fabric_erp
   ```

7. Bring up the rest of the stack: `docker compose up -d`.
8. Spot-check: hit `/dashboard` in the UI; reconcile a trial balance.

**Scenario: a single row went bad — point-in-time recovery.**

We don't have WAL-based PITR yet (it's overkill for the daily-pg_dump model).
The recovery granularity is **daily**. Pick the backup from before the bad
write happened:

```bash
make restore date=2026-05-09 target_db=fabric_erp_yesterday
# Then handwrite an UPDATE/INSERT in the prod DB to copy the good row back.
```

If we end up wanting sub-daily recovery, the upgrade path is:
1. Enable `archive_mode = on` + `archive_command` shipping WAL segments to B2.
2. Use `pg_basebackup` + WAL replay instead of `pg_dump`.

That's a Phase-2+ exercise; the current model is fine until we have >10
paying customers or >50 GB of data.

---

## 9. Credentials handoff

| Credential | Where to store | Who knows it |
|-----------|----------------|--------------|
| `BACKUP_GPG_PASSPHRASE` | Password manager + paper in a safe | Moiz only (until co-founder) |
| `B2_ACCESS_KEY_ID` / `B2_SECRET_KEY` | Password manager | Moiz only |
| `ops/.env.backup` on the prod box | `chmod 600` on the box | root + moiz |
| GitHub Actions secret (for backup-test.yml) | **Not needed** — the CI test uses ephemeral creds inside the workflow and a fresh GPG passphrase. No real bucket creds in CI. | — |

When (if) you hand off operations:
1. Share the password-manager vault item.
2. Rotate the B2 app key (revoke old one, mint new one).
3. Rotate the GPG passphrase: see §10.

---

## 10. Rotating the GPG passphrase

Decrypt-then-reencrypt every artefact, then update `.env.backup`.

```bash
cd /opt/fabric/ops/backups
OLD_PASS='<old>'
NEW_PASS='<new>'
for f in fabric_*.sql.gz.gpg; do
  printf '%s' "$OLD_PASS" | gpg --batch --yes --passphrase-fd 0 --decrypt -o "${f%.gpg}" "$f"
  printf '%s' "$NEW_PASS" | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-fd 0 -o "${f}.new" "${f%.gpg}"
  mv "${f}.new" "$f"
  rm "${f%.gpg}"
done
# Then re-upload each rewrapped file to the bucket and update .env.backup.
```

Schedule the rotation yearly, or whenever a person who knew the old
passphrase leaves the project.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `pg_dump: server version mismatch` | Host `pg_dump` is older than server (e.g. PG 14 client vs 16 server) | `sudo apt-get install postgresql-client-16` and re-export `BACKUP_PG_DUMP_BIN=/usr/lib/postgresql/16/bin/pg_dump` in `ops/.env.backup` |
| `aws: command not found` | awscli missing | `sudo apt-get install awscli` (Ubuntu) or `brew install awscli` (mac) |
| `WARN: B2 credentials incomplete — skipping upload` | One of `B2_BUCKET / B2_ACCESS_KEY_ID / B2_SECRET_KEY / B2_ENDPOINT_URL` not set | Check `ops/.env.backup`; the warning is harmless on dev/CI but a P1 on prod |
| `WARN: BACKUP_GPG_PASSPHRASE not set — backup is UNENCRYPTED` | passphrase env empty | Set it in `ops/.env.backup` before the next cron run |
| gpg `decrypt failed: Bad session key` | wrong passphrase | Use the one from the password manager. There is no recovery. |
| `make restore` says "no bucket object matches date=YYYY-MM-DD" | The cron didn't run that day, or the date format is wrong (must be `YYYY-MM-DD`) | Pick the nearest available date; check the cron log |
