#!/usr/bin/env bash
# ops/restore.sh — TASK-CUT-404
#
# Restore a Fabric Postgres backup produced by ops/backup.sh.
#
# Resolution order for the source artefact:
#   1. --file=PATH           explicit local file (takes precedence)
#   2. --date=YYYY-MM-DD     find newest matching local file in $BACKUP_DIR
#   3. --date=YYYY-MM-DD     fall back to fetching from S3 bucket
#
# Modes:
#   --dry-run                print the steps; do not touch the DB or bucket
#   --target-db=NAME         restore into a different DB (default: $POSTGRES_DB)
#                            CREATE DATABASE is NOT run automatically — the
#                            target DB must exist (`createdb` first).
#
# Required env (same as backup.sh, typically from ops/.env.backup):
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
# Optional env:
#   POSTGRES_HOST/PORT       (default: localhost:5432)
#   BACKUP_DIR               (default: ./ops/backups)
#   BACKUP_GPG_PASSPHRASE    (required iff the artefact is .gpg-encrypted)
#   B2_*                     (required iff fetching from the bucket)
#
# Usage examples:
#   ops/restore.sh --date=2026-05-11 --dry-run
#   ops/restore.sh --date=2026-05-11 --target-db=fabric_erp_restore_test
#   ops/restore.sh --file=ops/backups/fabric_fabric_erp_2026-05-11_*.sql.gz.gpg
#
# Exit codes:
#   0 success
#   1 missing artefact / restore failed
#   2 bad arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$SCRIPT_DIR/.env.backup" ]; then
  # shellcheck disable=SC1091
  set -a; . "$SCRIPT_DIR/.env.backup"; set +a
fi

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER is required}"
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB is required}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/ops/backups}"

dry_run=0
src_file=""
src_date=""
target_db="$POSTGRES_DB"

log() { printf '[%s] %s\n' "$(date -u -Iseconds 2>/dev/null || date -u)" "$*"; }
warn() { log "WARN: $*" >&2; }
fail() { log "ERROR: $*" >&2; exit 1; }
plan() { printf '  PLAN: %s\n' "$*"; }

usage() {
  cat <<'EOF'
Usage:
  ops/restore.sh --date=YYYY-MM-DD [--target-db=NAME] [--dry-run]
  ops/restore.sh --file=PATH        [--target-db=NAME] [--dry-run]

Options:
  --date=YYYY-MM-DD   Locate newest artefact for that date (local + bucket).
  --file=PATH         Use a specific local artefact.
  --target-db=NAME    Restore into a different DB (must already exist).
  --dry-run           Print the plan; do not run psql or fetch from bucket.
  -h, --help          Show this.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --date=*) src_date="${arg#--date=}" ;;
    --file=*) src_file="${arg#--file=}" ;;
    --target-db=*) target_db="${arg#--target-db=}" ;;
    -h|--help) usage; exit 0 ;;
    *) usage; fail "unknown argument: $arg" ;;
  esac
done

if [ -z "$src_file" ] && [ -z "$src_date" ]; then
  usage
  exit 2
fi

# ── Resolve source artefact ──────────────────────────────────────────────────
artefact=""
if [ -n "$src_file" ]; then
  if [ ! -f "$src_file" ]; then
    fail "file not found: $src_file"
  fi
  artefact="$src_file"
  log "using explicit file: $artefact"
else
  # Find newest local match for the date. Prefer .gpg over .sql.gz.
  log "searching for backup matching date=$src_date in $BACKUP_DIR"
  local_match=""
  if [ -d "$BACKUP_DIR" ]; then
    # shellcheck disable=SC2012
    local_match="$(ls -1t "$BACKUP_DIR"/fabric_*_"${src_date}"_*.sql.gz.gpg 2>/dev/null | head -n1 || true)"
    if [ -z "$local_match" ]; then
      local_match="$(ls -1t "$BACKUP_DIR"/fabric_*_"${src_date}"_*.sql.gz 2>/dev/null | head -n1 || true)"
    fi
  fi

  if [ -n "$local_match" ]; then
    artefact="$local_match"
    log "found local: $artefact"
  else
    # Try the bucket.
    if [ -z "${B2_BUCKET:-}" ] || [ -z "${B2_ACCESS_KEY_ID:-}" ] \
       || [ -z "${B2_SECRET_KEY:-}" ] || [ -z "${B2_ENDPOINT_URL:-}" ]; then
      fail "no local backup for $src_date and B2 credentials are incomplete — cannot fetch from bucket"
    fi

    log "searching bucket s3://${B2_BUCKET} for date=$src_date"
    if [ "$dry_run" = "1" ]; then
      plan "list bucket and pick newest matching fabric_*_${src_date}_*.sql.gz[.gpg]"
      plan "download to $BACKUP_DIR/"
      # Pretend we found one for plan-print symmetry below.
      artefact="$BACKUP_DIR/<from-bucket>_${src_date}.sql.gz.gpg"
    else
      keys="$(AWS_ACCESS_KEY_ID="$B2_ACCESS_KEY_ID" \
              AWS_SECRET_ACCESS_KEY="$B2_SECRET_KEY" \
              AWS_DEFAULT_REGION="${B2_REGION:-us-east-005}" \
              aws --endpoint-url "$B2_ENDPOINT_URL" \
                  s3api list-objects-v2 --bucket "$B2_BUCKET" \
                  --prefix "fabric_" \
                  --query "Contents[?contains(Key, \`${src_date}\`)].Key" \
                  --output text 2>/dev/null || true)"
      # aws --output text emits tab-separated; convert to newline-separated.
      keys_nl="$(printf '%s' "$keys" | tr '\t' '\n')"
      # Prefer .gpg
      key="$(printf '%s\n' "$keys_nl" | grep -E '\.sql\.gz\.gpg$' | sort -r | head -n1 || true)"
      if [ -z "$key" ]; then
        key="$(printf '%s\n' "$keys_nl" | grep -E '\.sql\.gz$' | sort -r | head -n1 || true)"
      fi
      if [ -z "$key" ]; then
        fail "no bucket object matches date=$src_date"
      fi
      mkdir -p "$BACKUP_DIR"
      artefact="$BACKUP_DIR/$(basename "$key")"
      log "downloading s3://${B2_BUCKET}/${key} → $artefact"
      AWS_ACCESS_KEY_ID="$B2_ACCESS_KEY_ID" \
      AWS_SECRET_ACCESS_KEY="$B2_SECRET_KEY" \
      AWS_DEFAULT_REGION="${B2_REGION:-us-east-005}" \
        aws --endpoint-url "$B2_ENDPOINT_URL" \
            s3 cp "s3://${B2_BUCKET}/${key}" "$artefact"
    fi
  fi
fi

# ── Print the plan ───────────────────────────────────────────────────────────
log "restore plan:"
plan "source artefact     = $artefact"
plan "target DB           = ${target_db} (host=${POSTGRES_HOST}:${POSTGRES_PORT}, user=${POSTGRES_USER})"
if [[ "$artefact" == *.gpg ]]; then
  plan "decrypt step        = gpg --decrypt (needs BACKUP_GPG_PASSPHRASE)"
fi
plan "decompress step     = gunzip"
plan "load step           = psql -d $target_db < <dump>"
plan "WARNING: this OVERWRITES tables in $target_db (--clean --if-exists from pg_dump)."

if [ "$dry_run" = "1" ]; then
  log "--dry-run: not executing. Re-run without --dry-run to actually restore."
  exit 0
fi

# ── Sanity: target DB must exist and not be a critical prod DB unless asked ──
if [ "$target_db" = "$POSTGRES_DB" ]; then
  warn "target DB == POSTGRES_DB ($target_db). This will OVERWRITE the configured prod/dev DB."
  warn "If this is unintended, abort within 5 seconds (Ctrl-C)."
  sleep 5 || true
fi

# ── Decrypt + decompress + load ──────────────────────────────────────────────
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

stream_source="$artefact"
if [[ "$artefact" == *.gpg ]]; then
  if [ -z "${BACKUP_GPG_PASSPHRASE:-}" ]; then
    fail "artefact is encrypted (.gpg) but BACKUP_GPG_PASSPHRASE is not set"
  fi
  decrypted="$work_dir/$(basename "${artefact%.gpg}")"
  log "decrypting → $decrypted"
  printf '%s' "$BACKUP_GPG_PASSPHRASE" \
    | gpg --batch --yes --quiet \
          --decrypt --passphrase-fd 0 \
          --output "$decrypted" \
          "$artefact"
  stream_source="$decrypted"
fi

log "loading $stream_source into ${target_db}"
PGPASSWORD="${POSTGRES_PASSWORD:-}" \
  gunzip -c "$stream_source" \
  | PGPASSWORD="${POSTGRES_PASSWORD:-}" \
    psql -v ON_ERROR_STOP=1 \
         -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
         -d "$target_db"

log "restore complete: $target_db ← $artefact"
exit 0
