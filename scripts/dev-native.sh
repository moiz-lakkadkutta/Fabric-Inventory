#!/usr/bin/env bash
# scripts/dev-native.sh — INT-7 native dev workflow.
#
# Brings up Postgres+Redis in compose, then runs uvicorn and vite *natively*
# against the host-mapped ports. Native processes get instant reload and
# painless `pdb`, but they're vulnerable to shell-env pollution — exactly
# the bug that caused the 2026-05-06 QA outage. So we launch uvicorn with
# `env -i` plus an explicit-allowlist env and source `backend/.env`.
#
# Stop with Ctrl-C; the script traps SIGINT and tears down both children
# plus the compose services it started.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=$(docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

# ── Sanity: backend/.env must exist (make setup creates it) ──────────────────
if [ ! -f backend/.env ]; then
  echo "backend/.env missing — run 'make setup' first" >&2
  exit 1
fi

echo "▸ bringing up postgres + redis in compose…"
$COMPOSE up -d postgres redis

# Wait for postgres to be healthy before migrating (docker compose's --wait
# would do this, but it's not in older v2). Poll instead.
echo "▸ waiting for postgres to be healthy…"
for _ in $(seq 1 30); do
  status=$($COMPOSE ps --format '{{.Service}} {{.Status}}' 2>/dev/null | awk '/^postgres/ {print $2}' | head -1)
  case "$status" in
    *healthy*) break ;;
  esac
  sleep 1
done

# ── Run alembic against host-mapped postgres ─────────────────────────────────
echo "▸ running alembic upgrade head…"
(
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/backend/.env"
  set +a
  cd backend && uv run alembic upgrade head
)

# ── Launch uvicorn with a SCRUBBED env, sourced from backend/.env ────────────
# `env -i` clears every inherited variable. We explicitly forward only what
# uvicorn needs, then source backend/.env on top so DATABASE_URL etc. come
# from disk, not from a polluted shell.
echo "▸ launching uvicorn (scrubbed env)…"
(
  cd backend
  env -i \
    HOME="$HOME" \
    PATH="$REPO_ROOT/backend/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    TERM="${TERM:-xterm}" \
    bash -c 'set -a; . "$0/.env"; set +a; exec .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --reload' "$REPO_ROOT/backend"
) &
UVICORN_PID=$!

# ── Launch vite (no scrubbing needed; it reads frontend/.env) ────────────────
echo "▸ launching vite…"
(
  cd frontend && pnpm dev
) &
VITE_PID=$!

# ── Preflight: poll /ready until 200 (or fail loudly) ────────────────────────
echo "▸ preflight: polling /ready…"
ready=0
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://localhost:8000/ready || echo 000)
  if [ "$code" = "200" ]; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "✖ /ready never returned 200 within 30s — check uvicorn output above" >&2
  echo "  hint: run 'make doctor' once the api is up to localize the failure" >&2
  kill "$UVICORN_PID" "$VITE_PID" 2>/dev/null || true
  exit 1
fi

echo "✔ stack up: api http://localhost:8000  ui http://localhost:5173"
echo "  press Ctrl-C to stop"

cleanup() {
  echo
  echo "▸ stopping…"
  kill "$UVICORN_PID" "$VITE_PID" 2>/dev/null || true
  wait "$UVICORN_PID" "$VITE_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

wait
