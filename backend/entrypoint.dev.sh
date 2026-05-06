#!/usr/bin/env bash
# entrypoint.dev.sh — runs in the compose `api` container.
#
# Two responsibilities, in order:
#   1. wait for postgres to accept connections (compose healthcheck handles
#      readiness, but `--wait` isn't universal; this is a belt-and-suspenders)
#   2. run `alembic upgrade head` against the runtime DB — closes P0-2
#      so a fresh clone via `make dev` boots into a migrated schema instead
#      of a 500-on-everything backend.
#
# Then exec the CMD (uvicorn) so signals propagate.

set -euo pipefail

echo "[entrypoint] alembic upgrade head…"
# Use MIGRATION_DATABASE_URL if set, else fall back to DATABASE_URL.
# (INT-9 will split these apart; today they're equal.)
if [ -n "${MIGRATION_DATABASE_URL:-}" ]; then
  export DATABASE_URL_FOR_ALEMBIC="$MIGRATION_DATABASE_URL"
else
  export DATABASE_URL_FOR_ALEMBIC="$DATABASE_URL"
fi

# Retry alembic a few times — postgres healthcheck normally gates this,
# but on slow CI workers the first attempt sometimes races the listener.
for attempt in 1 2 3 4 5; do
  if uv run alembic upgrade head; then
    break
  fi
  echo "[entrypoint] alembic attempt $attempt failed; retrying in 2s…"
  sleep 2
done

echo "[entrypoint] handing off to: $*"
exec "$@"
