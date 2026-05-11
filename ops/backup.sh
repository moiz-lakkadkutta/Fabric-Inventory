#!/usr/bin/env bash
# ops/backup.sh — TASK-CUT-404
#
# Dump the Fabric Postgres DB, compress, encrypt, and upload to an
# S3-compatible bucket (Backblaze B2 by default; Hetzner Object Storage
# works with the same flags — both speak the AWS S3 API).
#
# Builds on `task/int-0-staging-bootstrap`'s `ops/staging/pg-backup.sh`,
# which dumped to local disk. This script extends that flow with:
#   - gpg --symmetric encryption (passphrase from $BACKUP_GPG_PASSPHRASE)
#   - aws-cli upload to an S3-compatible endpoint
#   - 7-day retention prune in the bucket (configurable via $BACKUP_RETENTION_DAYS)
#
# Local artefacts in $BACKUP_DIR are kept too — they're the cheapest
# possible recovery target if the bucket is unreachable.
#
# Required env (typically loaded from ops/.env.backup):
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
# Optional env:
#   POSTGRES_HOST        (default: localhost)
#   POSTGRES_PORT        (default: 5432)
#   BACKUP_DIR           (default: ./ops/backups)
#   BACKUP_RETENTION_DAYS (default: 7)
#   BACKUP_GPG_PASSPHRASE  (if absent → encryption skipped + warning)
#   B2_BUCKET, B2_ACCESS_KEY_ID, B2_SECRET_KEY, B2_ENDPOINT_URL
#                          (if any absent → upload skipped + warning,
#                           local artefact still produced — CI runs this way)
#   B2_REGION            (default: us-east-005, matches B2's "auto" region)
#   BACKUP_PG_DUMP_BIN   (default: pg_dump — override to a versioned bin
#                         e.g. /usr/lib/postgresql/16/bin/pg_dump if the
#                         host has multiple postgres-client versions)
#
# Exit codes:
#   0  success (artefact produced; upload may have been skipped with warning)
#   1  unrecoverable failure (pg_dump or gpg failed)
#
# See docs/ops/backup-runbook.md for operator setup.

set -euo pipefail

# ── Setup ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load ops/.env.backup if present. CI / cron will use this; an interactive
# operator can also export the env vars before running.
if [ -f "$SCRIPT_DIR/.env.backup" ]; then
  # shellcheck disable=SC1091
  set -a; . "$SCRIPT_DIR/.env.backup"; set +a
fi

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER is required}"
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB is required}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/ops/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
BACKUP_PG_DUMP_BIN="${BACKUP_PG_DUMP_BIN:-pg_dump}"

mkdir -p "$BACKUP_DIR"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
date_stamp="$(date -u +%Y-%m-%d)"
base_name="fabric_${POSTGRES_DB}_${date_stamp}_${ts}"

dump_path="$BACKUP_DIR/${base_name}.sql.gz"
final_path="$dump_path"  # may become .gpg below

log() { printf '[%s] %s\n' "$(date -u -Iseconds 2>/dev/null || date -u)" "$*"; }
warn() { log "WARN: $*" >&2; }
fail() { log "ERROR: $*" >&2; exit 1; }

# ── Step 1: pg_dump → gzip ───────────────────────────────────────────────────
log "starting pg_dump: ${POSTGRES_USER}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
log "writing: $dump_path"

# Use PGPASSWORD to pass the password without it landing in `ps`.
PGPASSWORD="${POSTGRES_PASSWORD:-}" \
  "$BACKUP_PG_DUMP_BIN" \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --no-owner --clean --if-exists \
  | gzip -9 > "$dump_path"

if [ ! -s "$dump_path" ]; then
  fail "pg_dump produced empty file: $dump_path"
fi

size_h="$(du -h "$dump_path" | cut -f1)"
log "dump complete: $dump_path ($size_h)"

# ── Step 2: encrypt (optional but warned-on-skip) ────────────────────────────
if [ -n "${BACKUP_GPG_PASSPHRASE:-}" ]; then
  encrypted_path="${dump_path}.gpg"
  log "encrypting → $encrypted_path"
  # gpg --batch + --passphrase-fd reads from the passphrase from a file
  # descriptor we control. Avoids leaking the passphrase via `ps`.
  printf '%s' "$BACKUP_GPG_PASSPHRASE" \
    | gpg --batch --yes --quiet \
          --symmetric --cipher-algo AES256 \
          --passphrase-fd 0 \
          --output "$encrypted_path" \
          "$dump_path"

  if [ ! -s "$encrypted_path" ]; then
    fail "gpg produced empty file: $encrypted_path"
  fi

  # Wipe the unencrypted artefact — the .gpg file is the artefact of record.
  rm -f "$dump_path"
  final_path="$encrypted_path"
  log "encrypted artefact: $final_path ($(du -h "$final_path" | cut -f1))"
else
  warn "BACKUP_GPG_PASSPHRASE not set — backup is UNENCRYPTED. Do not ship this to prod without setting it."
fi

# ── Step 3: upload to S3-compatible bucket (optional) ────────────────────────
upload_done=0
if [ -n "${B2_BUCKET:-}" ] \
   && [ -n "${B2_ACCESS_KEY_ID:-}" ] \
   && [ -n "${B2_SECRET_KEY:-}" ] \
   && [ -n "${B2_ENDPOINT_URL:-}" ]; then
  if ! command -v aws >/dev/null 2>&1; then
    warn "aws CLI not on PATH — skipping upload. Install awscli (apt: awscli, brew: awscli)."
  else
    log "uploading to s3://${B2_BUCKET}/$(basename "$final_path")"
    AWS_ACCESS_KEY_ID="$B2_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$B2_SECRET_KEY" \
    AWS_DEFAULT_REGION="${B2_REGION:-us-east-005}" \
      aws --endpoint-url "$B2_ENDPOINT_URL" \
          s3 cp "$final_path" "s3://${B2_BUCKET}/$(basename "$final_path")"
    upload_done=1
    log "upload complete"
  fi
else
  warn "B2 credentials incomplete — skipping upload (local artefact at $final_path is the only copy)."
  warn "  needed: B2_BUCKET, B2_ACCESS_KEY_ID, B2_SECRET_KEY, B2_ENDPOINT_URL"
fi

# ── Step 4: retention prune (local + bucket) ─────────────────────────────────
log "pruning local backups older than ${BACKUP_RETENTION_DAYS} days under $BACKUP_DIR"
find "$BACKUP_DIR" -type f \( -name 'fabric_*.sql.gz' -o -name 'fabric_*.sql.gz.gpg' \) \
     -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete || true

if [ "$upload_done" = "1" ]; then
  log "pruning bucket objects older than ${BACKUP_RETENTION_DAYS} days"
  # List objects, parse "LastModified Size Key" lines, compare against cutoff,
  # delete anything older. We deliberately do NOT rely on lifecycle policies —
  # different S3-compatible providers honour them differently (B2 does, but
  # MinIO local tests don't).
  cutoff_epoch="$(( $(date -u +%s) - BACKUP_RETENTION_DAYS * 86400 ))"
  AWS_ACCESS_KEY_ID="$B2_ACCESS_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$B2_SECRET_KEY" \
  AWS_DEFAULT_REGION="${B2_REGION:-us-east-005}" \
    aws --endpoint-url "$B2_ENDPOINT_URL" \
        s3api list-objects-v2 --bucket "$B2_BUCKET" --prefix "fabric_" \
        --query 'Contents[].[Key,LastModified]' --output text 2>/dev/null \
  | while read -r key last_modified; do
      [ -z "$key" ] && continue
      # LastModified is ISO8601 like 2026-05-04T03:00:00.000Z
      obj_epoch="$(date -u -d "$last_modified" +%s 2>/dev/null \
                   || python3 -c "from datetime import datetime; print(int(datetime.fromisoformat('${last_modified%Z}+00:00').timestamp()))" 2>/dev/null \
                   || echo 0)"
      if [ "$obj_epoch" -gt 0 ] && [ "$obj_epoch" -lt "$cutoff_epoch" ]; then
        log "  deleting expired: $key (last_modified=$last_modified)"
        AWS_ACCESS_KEY_ID="$B2_ACCESS_KEY_ID" \
        AWS_SECRET_ACCESS_KEY="$B2_SECRET_KEY" \
        AWS_DEFAULT_REGION="${B2_REGION:-us-east-005}" \
          aws --endpoint-url "$B2_ENDPOINT_URL" \
              s3 rm "s3://${B2_BUCKET}/${key}" >/dev/null
      fi
    done
fi

log "backup done: $final_path"
exit 0
