#!/usr/bin/env bash
# tests/test_backup.sh — TASK-CUT-404 integration test
#
# Exercises ops/backup.sh + ops/restore.sh end-to-end against a real
# Postgres. Confirms:
#   1. `make backup` (==`ops/backup.sh`) produces a .sql.gz.gpg artefact
#      with non-zero size.
#   2. `make restore --dry-run` lists the plan without touching the DB.
#   3. `make restore` round-trips a sentinel row: we insert "marker" into
#      a `cut404_sanity` table, run backup, DROP the row, restore into a
#      sibling DB, and assert the marker is back.
#
# Connection: this script reads POSTGRES_HOST/PORT/USER/PASSWORD/DB from
# env (CI sets them via the workflow `env:` block). For local runs against
# docker-compose:
#   export POSTGRES_HOST=localhost POSTGRES_PORT=5432
#   export POSTGRES_USER=fabric POSTGRES_PASSWORD=fabric_dev POSTGRES_DB=fabric_erp
#   bash tests/test_backup.sh
#
# The test is hermetic: it creates a throw-away DB (fabric_cut404_src), a
# throw-away restore target (fabric_cut404_dst), and tears them down on exit.
# It does NOT touch the configured POSTGRES_DB.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
note()  { printf '\033[2m[test] %s\033[0m\n' "$*"; }
fail()  { red "FAIL: $*"; exit 1; }

# ── Required toolchain ───────────────────────────────────────────────────────
for bin in pg_dump psql createdb dropdb gpg gunzip gzip; do
  command -v "$bin" >/dev/null 2>&1 || fail "missing required binary: $bin"
done

# ── Source DB credentials (must be set in env) ───────────────────────────────
: "${POSTGRES_HOST:?POSTGRES_HOST must be set (e.g. localhost)}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"

SRC_DB="fabric_cut404_src_$$"
DST_DB="fabric_cut404_dst_$$"
BACKUP_DIR="$(mktemp -d)/backups"
mkdir -p "$BACKUP_DIR"

cleanup() {
  note "cleanup: dropping $SRC_DB + $DST_DB + $BACKUP_DIR"
  PGPASSWORD="$POSTGRES_PASSWORD" dropdb \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
    --if-exists "$SRC_DB" >/dev/null 2>&1 || true
  PGPASSWORD="$POSTGRES_PASSWORD" dropdb \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
    --if-exists "$DST_DB" >/dev/null 2>&1 || true
  rm -rf "$(dirname "$BACKUP_DIR")"
}
trap cleanup EXIT

note "creating source DB: $SRC_DB"
PGPASSWORD="$POSTGRES_PASSWORD" createdb \
  -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$SRC_DB"

note "creating destination DB: $DST_DB"
PGPASSWORD="$POSTGRES_PASSWORD" createdb \
  -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$DST_DB"

# ── Insert sentinel row ──────────────────────────────────────────────────────
note "seeding sentinel row in $SRC_DB"
PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 \
  -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$SRC_DB" \
  -c "CREATE TABLE cut404_sanity (id int primary key, marker text);" \
  -c "INSERT INTO cut404_sanity VALUES (1, 'hello-from-cut-404');"

# ── Step 1: make backup ──────────────────────────────────────────────────────
note "STEP 1: ops/backup.sh against $SRC_DB"
export POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_PASSWORD
export POSTGRES_DB="$SRC_DB"
export BACKUP_DIR
export BACKUP_GPG_PASSPHRASE="test-passphrase-do-not-use-in-prod"
# Deliberately do NOT set B2_* — script must skip upload with a warning,
# not fail. That's the CI behaviour.
unset B2_BUCKET B2_ACCESS_KEY_ID B2_SECRET_KEY B2_ENDPOINT_URL || true

bash "$REPO_ROOT/ops/backup.sh"

artefact="$(ls -1t "$BACKUP_DIR"/fabric_"${SRC_DB}"_*.sql.gz.gpg 2>/dev/null | head -n1 || true)"
[ -n "$artefact" ] || fail "no .sql.gz.gpg artefact produced under $BACKUP_DIR"
[ -s "$artefact" ] || fail "artefact is zero-size: $artefact"
note "  artefact: $artefact ($(du -h "$artefact" | cut -f1))"
green "  step 1 ok: encrypted dump exists and is non-empty"

# ── Step 2: make restore --dry-run ───────────────────────────────────────────
note "STEP 2: restore --dry-run (should not touch the DB)"
dry_log="$(mktemp)"

# Use --file to pin to the artefact we just produced (date-based discovery
# would also work but pinning makes the test deterministic).
bash "$REPO_ROOT/ops/restore.sh" --file="$artefact" --target-db="$DST_DB" --dry-run >"$dry_log" 2>&1 \
  || { cat "$dry_log"; fail "restore --dry-run exited non-zero"; }

grep -q "PLAN:" "$dry_log" || { cat "$dry_log"; fail "dry-run output should contain a PLAN: section"; }
grep -q "not executing" "$dry_log" \
  || grep -q "dry-run" "$dry_log" \
  || { cat "$dry_log"; fail "dry-run output should explicitly say it isn't executing"; }

# Sanity: confirm $DST_DB was NOT modified.
row_count_dst="$(PGPASSWORD="$POSTGRES_PASSWORD" psql -tA \
  -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$DST_DB" \
  -c "SELECT count(*) FROM pg_tables WHERE tablename = 'cut404_sanity';" 2>/dev/null || echo "0")"
[ "$row_count_dst" = "0" ] \
  || fail "dry-run actually touched $DST_DB — cut404_sanity exists"
rm -f "$dry_log"
green "  step 2 ok: dry-run printed plan + did not touch DB"

# ── Step 3: real restore into DST_DB ─────────────────────────────────────────
note "STEP 3: real restore into $DST_DB (separate from source)"
bash "$REPO_ROOT/ops/restore.sh" --file="$artefact" --target-db="$DST_DB"

# ── Step 4: assert the row round-trips ───────────────────────────────────────
note "STEP 4: assert sentinel row in $DST_DB"
marker="$(PGPASSWORD="$POSTGRES_PASSWORD" psql -tA \
  -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$DST_DB" \
  -c "SELECT marker FROM cut404_sanity WHERE id = 1;")"

if [ "$marker" != "hello-from-cut-404" ]; then
  fail "round-trip broke: expected 'hello-from-cut-404', got '$marker'"
fi
green "  step 4 ok: round-trip succeeded — marker='$marker'"

# ── Step 5: retention prune is non-destructive on fresh artefacts ────────────
note "STEP 5: retention prune leaves today's artefact alone"
[ -f "$artefact" ] \
  || fail "today's artefact got pruned (retention should be 7 days by default)"
green "  step 5 ok: fresh artefact survives retention prune"

# ── Step 6: CUT-501c hard-fail path (BACKUP_FAIL_PLAINTEXT=1 + no passphrase) ─
note "STEP 6: BACKUP_FAIL_PLAINTEXT=1 must exit 1 when passphrase is empty"
fail_log="$(mktemp)"
fail_dir="$(mktemp -d)/fail-backups"
mkdir -p "$fail_dir"

# Run backup.sh in a fresh env: no passphrase, but the prod policy flag is on.
set +e
env -i PATH="$PATH" HOME="$HOME" \
  POSTGRES_HOST="$POSTGRES_HOST" \
  POSTGRES_PORT="$POSTGRES_PORT" \
  POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  POSTGRES_DB="$SRC_DB" \
  BACKUP_DIR="$fail_dir" \
  BACKUP_FAIL_PLAINTEXT=1 \
  bash "$REPO_ROOT/ops/backup.sh" >"$fail_log" 2>&1
fail_rc=$?
set -e

if [ "$fail_rc" -eq 0 ]; then
  cat "$fail_log"
  fail "backup.sh exited 0 with BACKUP_FAIL_PLAINTEXT=1 and no passphrase — expected non-zero"
fi
grep -qE "BACKUP_FAIL_PLAINTEXT|refusing to produce an unencrypted" "$fail_log" \
  || { cat "$fail_log"; fail "expected hard-fail error message naming BACKUP_FAIL_PLAINTEXT"; }

# And the script must NOT leave a plaintext .sql.gz lying around in $fail_dir.
leaked="$(ls -1 "$fail_dir"/fabric_*.sql.gz 2>/dev/null | head -n1 || true)"
[ -z "$leaked" ] \
  || fail "hard-fail path leaked a plaintext artefact: $leaked"

rm -f "$fail_log"
rm -rf "$(dirname "$fail_dir")"
green "  step 6 ok: BACKUP_FAIL_PLAINTEXT=1 hard-fails and leaves no plaintext"

# ── Step 7: warn-and-continue path stays the default (no flag set) ───────────
note "STEP 7: unset BACKUP_FAIL_PLAINTEXT + no passphrase → warn + plaintext"
warn_log="$(mktemp)"
warn_dir="$(mktemp -d)/warn-backups"
mkdir -p "$warn_dir"

set +e
env -i PATH="$PATH" HOME="$HOME" \
  POSTGRES_HOST="$POSTGRES_HOST" \
  POSTGRES_PORT="$POSTGRES_PORT" \
  POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  POSTGRES_DB="$SRC_DB" \
  BACKUP_DIR="$warn_dir" \
  bash "$REPO_ROOT/ops/backup.sh" >"$warn_log" 2>&1
warn_rc=$?
set -e

if [ "$warn_rc" -ne 0 ]; then
  cat "$warn_log"
  fail "backup.sh exited $warn_rc with no flag set — expected 0 (warn-and-continue)"
fi
grep -qE "BACKUP_GPG_PASSPHRASE not set" "$warn_log" \
  || { cat "$warn_log"; fail "expected warning about missing passphrase"; }

warn_artefact="$(ls -1 "$warn_dir"/fabric_*.sql.gz 2>/dev/null | head -n1 || true)"
[ -n "$warn_artefact" ] \
  || { cat "$warn_log"; fail "expected a plaintext .sql.gz under $warn_dir"; }
[ -s "$warn_artefact" ] || fail "warn-path artefact is zero-size: $warn_artefact"

rm -f "$warn_log"
rm -rf "$(dirname "$warn_dir")"
green "  step 7 ok: warn-and-continue still works without the flag"

green "ALL CUT-404 + CUT-501c BACKUP TESTS PASSED"
