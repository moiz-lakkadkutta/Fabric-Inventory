#!/usr/bin/env bash
# Nightly Postgres dump for staging — local disk only (no S3 yet, per plan).
#
# Wire-up on the box (one-time):
#   sudo cp /opt/fabric/ops/staging/pg-backup.sh /usr/local/bin/fabric-pg-backup
#   sudo chmod +x /usr/local/bin/fabric-pg-backup
#   sudo crontab -e
#   # Add: 0 3 * * * /usr/local/bin/fabric-pg-backup >> /var/log/fabric-pg-backup.log 2>&1
#
# Restore:
#   docker compose -f /opt/fabric/docker-compose.staging.yml exec -T postgres \
#     psql -U "$POSTGRES_USER" "$POSTGRES_DB" < /opt/fabric/ops/staging/pg-backups/<file>.sql

set -euo pipefail

BACKUP_DIR="/opt/fabric/ops/staging/pg-backups"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
COMPOSE_FILE="/opt/fabric/docker-compose.staging.yml"
ENV_FILE="/opt/fabric/.env.staging"

# shellcheck disable=SC1090
source "$ENV_FILE"

mkdir -p "$BACKUP_DIR"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/fabric_staging_${ts}.sql.gz"

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
	pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists \
	| gzip -9 > "$out"

# Prune backups older than RETENTION_DAYS days.
find "$BACKUP_DIR" -name 'fabric_staging_*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "[$(date -u -Iseconds)] backup complete: $out ($(du -h "$out" | cut -f1))"
