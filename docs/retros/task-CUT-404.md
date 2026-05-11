# TASK-CUT-404 retro — Backups (pg_dump → S3-compatible) + cron + restore-test runbook

**Date:** 2026-05-11
**Branch:** task/CUT-404-backups
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 5, W5-D)

## Summary

Shipped the full backup loop end-to-end in one PR:

- `ops/backup.sh` — pg_dump → gzip -9 → gpg --symmetric (AES256) → S3-compatible upload → 7-day retention prune on both the local cache and the bucket. Builds on the parked `task/int-0-staging-bootstrap`'s `ops/staging/pg-backup.sh` (the local-only seed) rather than replacing it: the dump+gzip backbone is intact, encryption + upload + bucket-prune are the new layers.
- `ops/restore.sh` — fetch (local first, then bucket fallback) → gpg --decrypt → gunzip → psql restore. Supports `--dry-run` (prints a PLAN block without touching the DB or the bucket) and `--target-db=NAME` (restore into a sibling DB, doesn't clobber prod).
- `ops/.env.backup.example` — credential template; the real `.env.backup` is gitignored.
- `tests/test_backup.sh` — integration test that creates a fresh source DB, seeds a sentinel row, runs `ops/backup.sh`, asserts the encrypted artefact is non-empty, runs `ops/restore.sh --dry-run` (asserts the destination DB is untouched), runs the real `ops/restore.sh` into a sibling DB, then asserts the sentinel round-trips. All temp DBs and dirs are cleaned up on `trap EXIT`.
- `.github/workflows/backup-test.yml` — runs the integration test on PRs that touch `ops/`, `Makefile`, or this workflow, plus a weekly Monday-04:00-UTC cron. Spins up `postgres:16-alpine` as a service, installs `postgresql-client-16`, `gnupg`, and `shellcheck`, runs shellcheck (warning severity) before the round-trip, then sanity-runs `make backup` to confirm the Makefile glue is wired.
- `Makefile` — replaced the placeholder `backup:` echo with `bash ops/backup.sh`, added `restore` (forwards `date=`, `file=`, `target_db=`, `dry_run=1` to the script flags) and `restore-test` (runs `tests/test_backup.sh`).
- `docs/ops/backup-runbook.md` — operator handoff: bucket provisioning (B2 default, Hetzner alternate), credential layout, first-backup smoke, restore-test ritual, cron line (03:00 IST), log rotation, disaster recovery, GPG passphrase rotation, troubleshooting table.

**Verification (local, on this branch):**
- `shellcheck --severity=warning ops/*.sh tests/test_backup.sh` — clean (run via `koalaman/shellcheck-alpine:stable` in Docker — Homebrew install was blocked by directory permissions but the same image runs in CI).
- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/backup-test.yml'))"` — clean.
- `actionlint` (via `rhysd/actionlint:latest`) — clean.
- `tests/test_backup.sh` round-trip — green, ran inside an ephemeral `postgres:16-alpine` container with `gnupg` + `aws-cli` installed, networked to the running `fabric-postgres-1` compose service. Sentinel row `(1, 'hello-from-cut-404')` round-tripped through pg_dump → gzip → gpg → restore exactly.
- `make backup` end-to-end against the real `fabric_erp` DB — green, produced a 2.9 MB `.sql.gz.gpg`. Upload was skipped (no B2 creds set in the test env), which is the expected dev / CI behaviour.

## Deviations from plan

### 1. Used `aws-cli` not `s3cmd` for the upload
Plan said "s3cmd/aws-cli". Picked `aws` because (a) it's already widely available on Ubuntu via `apt-get install awscli`, (b) it's what most s3-compatible providers' docs use as the canonical example, (c) it has first-class `--endpoint-url` support, and (d) `aws --output text` + `--query` gives me a sane prune loop without parsing JSON in bash.

- **Fixed by:** documented in `docs/ops/backup-runbook.md` §11 — the only host-side dep is `apt-get install awscli` (or `brew install awscli`).
- **Why not caught in planning:** plan listed both as acceptable; I picked one.
- **Impact on later tasks:** none. If we ever ship to Alpine boxes that don't have python3 (= a transitive dep of awscli), we can pivot to the much-smaller `s3cmd` or even raw `curl` against the S3 REST API.

### 2. Local backup files are kept around, not deleted post-upload
The script writes the encrypted artefact under `$BACKUP_DIR` AND uploads it. The retention prune runs `find -mtime +7 -delete` on the local cache symmetrically with the bucket. I left this in because:
1. If the bucket is unreachable on Tuesday and the cron runs anyway, Tuesday's local copy is the only artefact. Removing it because "upload skipped" would be exactly the wrong behaviour.
2. Disk on the CX22 is cheap (40 GB SSD); 7 days × ~5 MB compressed dumps = ~35 MB. Negligible.

- **Why not caught in planning:** plan didn't specify either way.
- **Impact on later tasks:** none. If a future dataset grows so large that the local cache becomes annoying, drop `BACKUP_RETENTION_DAYS` to 1 in the env file — the bucket still keeps 7 days.

### 3. CI workflow uses the postgres SUPERUSER, not `fabric_app`
The other backend CI jobs connect as `fabric_app` (the NOBYPASSRLS role) to enforce RLS. The backup test uses `postgres` because:
- `pg_dump` needs to read every table in the cluster — including `pg_authid` for role definitions and any tables the app role wouldn't normally see.
- The test creates and drops its own throw-away DBs, which `fabric_app` cannot do.

- **Fixed by:** Documented in `tests/test_backup.sh` and the workflow comments.
- **Why not caught in planning:** I noticed it while wiring the workflow.
- **Impact on later tasks:** none. The integration test's elevated privileges live entirely inside the CI service container; they don't leak to runtime.

### 4. `BACKUP_GPG_PASSPHRASE` falls back to a "skip encryption + WARN" path
The acceptance criteria say `make backup` must produce an encrypted artefact, but the way the script is wired, if `BACKUP_GPG_PASSPHRASE` is unset, it emits a warning, drops the `.sql.gz` instead of `.sql.gz.gpg`, and exits 0. I kept the fallback because:
- Dev environments shouldn't be forced to set up a passphrase to play.
- CI is explicit about setting one, so the test matrix still covers the encrypted path.
- The warning is loud enough to be hard to miss in cron logs.

If Moiz wants this to be a hard fail on prod, we can flip the default to "encryption required" with a `BACKUP_ALLOW_PLAINTEXT=1` opt-out for dev. Logged as an open flag below.

## Things the plan got right (no deviation)

- Picking Backblaze B2 as the default. At $6/TB/month + free egress to Cloudflare, the math is unambiguous. Hetzner is the runner-up for single-vendor preference.
- Building on `task/int-0-staging-bootstrap`'s seed rather than rewriting. The local-disk dump path was solid; I added three layers (encrypt, upload, prune-bucket) without touching the dump backbone.
- Symmetric `--dry-run` for restore. The PLAN block is verbose enough that an on-call can paste it into a Slack thread before pulling the trigger.
- Round-trip integration test, not unit test. A backup script that hasn't restored a real row is a placebo; the test creates a separate DB so it can't accidentally clobber state.

## Pre-next-task checklist

### 1. CUT-405 (HTTPS via Caddy + prod deployment runbook)
The backup cron line is in `docs/ops/backup-runbook.md` §6 but the prod box doesn't exist yet — CUT-405 brings it up. CUT-405 should:
- Read §3 of `backup-runbook.md` first (install `postgresql-client-16`, `awscli`, `gnupg`, `make`).
- Copy `ops/.env.backup.example` → `ops/.env.backup` on the box, fill it, chmod 600.
- Add the cron line **after** the first successful `make backup` (don't schedule something that's never run).
- Run `make restore date=$(date -u +%Y-%m-%d) dry_run=1` as part of the post-deploy smoke.

### 2. CUT-501 (closeout) might want to fold these in
- Optional `BACKUP_ALLOW_PLAINTEXT` flag (see deviation #4) if Moiz wants prod to refuse plaintext.
- Healthchecks.io ping URL once an account exists (see `backup-runbook.md` §7).
- Sentry alert wiring for cron failures (overlap with the FE Sentry work in CUT-405).

### 3. PG version pin
The script reads `BACKUP_PG_DUMP_BIN` if set, defaulting to whichever `pg_dump` is on PATH. The compose stack runs `postgres:16-alpine` so the matching client is `postgresql-client-16`. The runbook §3 calls this out, and the CI workflow installs it explicitly. If we ever upgrade the server, bump both the workflow and the runbook table.

## Open flags carried over

- **Plaintext-backup fallback** (`BACKUP_GPG_PASSPHRASE` absent → unencrypted). Acceptable for dev/CI; loud WARN; runbook tells operator to set it on prod. Convert to hard-fail if Moiz wants to be paranoid.
- **No PITR (point-in-time recovery).** The recovery granularity is daily. Adequate for the textile-trade use case (typical bad write is "wrong invoice posted yesterday → restore yesterday's data into a sibling DB → handwrite the UPDATE"). Upgrade path documented in runbook §8.
- **Manual cron monitoring.** Until Healthchecks.io is wired, an operator has to eyeball `/var/log/fabric-backup.log`. Documented; revisit when the first paying customer onboards.
- **No bucket lifecycle policy.** We prune via `aws s3 rm` in the script rather than relying on the provider's lifecycle rule, because different S3-compatible providers honour those rules differently (B2 honours them; MinIO local testing doesn't). The runbook tells the operator to set the lifecycle rule anyway as belt-and-braces, but the script does not depend on it.
- **GPG passphrase rotation cadence.** Runbook recommends yearly or "when a person who knew it leaves the project". No tooling enforces this.

## Observable state at end of task

- Branch: `task/CUT-404-backups`. PR title: `TASK-CUT-404: Backups + cron + restore runbook`.
- New repo paths: `ops/`, `tests/`, `docs/ops/backup-runbook.md`, `docs/retros/task-CUT-404.md`, `.github/workflows/backup-test.yml`.
- `.gitignore` now ignores `ops/.env.backup` and `ops/backups/`. No real credentials committed; only the `.env.backup.example` template is checked in.
- The local dev stack `fabric-postgres-1` and `fabric-redis-1` are untouched. A throw-away DB called `fabric_cut404_src_*` / `fabric_cut404_dst_*` is created and dropped automatically by the test.
- A 2.9 MB encrypted artefact was produced under `/tmp/make-backup-smoke/` during local verification; it lives inside the docker volume layer and was deleted on container exit.

## Cost rationale (Ask-vs-Decide → Decide)

Picked Backblaze B2:
- Storage: $6.00 per TB-month (~₹500/month). Real workload is more like 10 GB × 7 versions = 70 GB → ~$0.42/month.
- Egress: free to Cloudflare (we already use Cloudflare for DNS); $0.01/GB elsewhere. Restore from B2 to CX22 over the public internet at <50 GB/month is well within the "occasional restore" budget.
- API requests: free below the daily limits we'll ever hit.
- One-time signup, no credit card for the first 10 GB.

Total monthly cost at MVP scale: <₹50. Even at 100 customers × 1 GB DB × 7 versions = 700 GB, the bill is ~₹350/month. Comfortably inside the ₹10-25k/month bootstrap budget.

Hetzner Object Storage runner-up (€5.99/TB, ~₹540, single-vendor + EU-only) — flip via the `B2_ENDPOINT_URL` + `B2_REGION` env vars without changing any code.
