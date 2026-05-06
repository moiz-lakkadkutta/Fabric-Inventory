#!/usr/bin/env bash
# scripts/doctor.sh — single source of truth for "is my dev stack working?"
#
# Background: on 2026-05-06 a QA pass found the stack silently broken — the
# api was running but `/ready` returned 503 because env vars from a parent
# shell pointed at docker-internal hostnames the host can't resolve. There
# was no preflight to surface this. This script is that preflight.
#
# Exit codes:
#   0  — all checks green
#   1  — at least one check failed; stderr names what
#
# Configurable via env:
#   FABRIC_API_URL   — base URL to probe (default http://localhost:8000)
#   FABRIC_TIMEOUT   — per-check timeout in seconds (default 3)

set -uo pipefail

API_URL="${FABRIC_API_URL:-http://localhost:8000}"
TIMEOUT="${FABRIC_TIMEOUT:-3}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_ENV="$REPO_ROOT/backend/.env"
FRONTEND_ENV="$REPO_ROOT/frontend/.env"
BACKEND_ENV_EXAMPLE="$REPO_ROOT/backend/.env.example"

ok=0
warn=0
fail=0

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
green() { printf '\033[32m  ok  %s\033[0m\n' "$*"; ok=$((ok+1)); }
yellow() { printf '\033[33m warn %s\033[0m\n' "$*"; warn=$((warn+1)); }
red()   { printf '\033[31m fail %s\033[0m\n' "$*"; fail=$((fail+1)); }

bold "Fabric ERP doctor — probing $API_URL"

# ── /live ─────────────────────────────────────────────────────────────────────
if live_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$API_URL/live" 2>/dev/null); then
  if [ "$live_code" = "200" ]; then
    green "/live → 200"
  else
    red "/live → $live_code (expected 200)"
  fi
else
  red "/live unreachable at $API_URL — connection refused or timeout"
fi

# ── /ready (the check that was missing on 2026-05-06) ─────────────────────────
ready_body=$(curl -s --max-time "$TIMEOUT" "$API_URL/ready" 2>/dev/null || true)
ready_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$API_URL/ready" 2>/dev/null || echo "000")

case "$ready_code" in
  200)
    green "/ready → 200 ($ready_body)"
    ;;
  503)
    red "/ready → 503: $ready_body"
    red "       fix: confirm DATABASE_URL/REDIS_URL resolve from THIS shell, not docker-internal hostnames"
    ;;
  000)
    red "/ready unreachable at $API_URL — connection refused or timeout"
    red "       fix: is uvicorn actually running? \`make dev\` or \`make dev-native\`"
    ;;
  *)
    red "/ready → $ready_code: $ready_body"
    ;;
esac

# ── docker compose state (postgres + redis must be healthy) ───────────────────
if command -v docker >/dev/null 2>&1; then
  ps_out=$(cd "$REPO_ROOT" && docker compose ps --format '{{.Service}} {{.Status}}' 2>/dev/null || true)
  if [ -z "$ps_out" ]; then
    yellow "docker compose ps returned nothing — compose stack not up (ok if running everything natively)"
  else
    for svc in postgres redis; do
      line=$(printf '%s\n' "$ps_out" | grep -E "^$svc " || true)
      if [ -z "$line" ]; then
        yellow "compose service '$svc' not running (ok if running native against external instance)"
      elif printf '%s' "$line" | grep -qi 'healthy'; then
        green "compose '$svc' healthy"
      else
        red "compose '$svc' unhealthy: $line"
      fi
    done
  fi
else
  yellow "docker not on PATH — skipped compose checks"
fi

# ── alembic head matches latest migration on disk ─────────────────────────────
if [ -d "$REPO_ROOT/backend/alembic/versions" ]; then
  newest=$(ls -1 "$REPO_ROOT/backend/alembic/versions"/*.py 2>/dev/null | grep -v __pycache__ | sort | tail -1 || true)
  if [ -n "$newest" ]; then
    rev=$(grep -E "^revision[: ]" "$newest" | head -1 | sed -E 's/.*= *"?([^" ]+)"? *.*/\1/')
    current=$(cd "$REPO_ROOT/backend" && uv run alembic current 2>/dev/null | grep -oE '^[a-z0-9_]+' | tail -1 || true)
    if [ -z "$current" ]; then
      yellow "alembic current returned nothing — DB unreachable or never migrated"
    elif [ "$current" = "$rev" ]; then
      green "alembic at head ($rev)"
    else
      red "alembic head mismatch: DB at $current, latest revision $rev — run \`make migrate\`"
    fi
  fi
fi

# ── env files present ─────────────────────────────────────────────────────────
[ -f "$BACKEND_ENV_EXAMPLE" ] && green "$BACKEND_ENV_EXAMPLE present" || red "$BACKEND_ENV_EXAMPLE missing"
[ -f "$BACKEND_ENV" ] && green "$BACKEND_ENV present" || yellow "$BACKEND_ENV missing — run \`make setup\`"
if [ -f "$FRONTEND_ENV" ]; then
  if grep -q '^VITE_API_MODE=' "$FRONTEND_ENV"; then
    mode=$(grep '^VITE_API_MODE=' "$FRONTEND_ENV" | head -1 | cut -d= -f2)
    green "$FRONTEND_ENV — VITE_API_MODE=$mode"
  else
    yellow "$FRONTEND_ENV missing VITE_API_MODE; UI will silently use mock fixtures"
  fi
else
  yellow "$FRONTEND_ENV missing — UI dev server may default to mock"
fi

# ── effective DATABASE_URL (redacted) ─────────────────────────────────────────
if [ -f "$BACKEND_ENV" ]; then
  url=$(grep -E '^DATABASE_URL=' "$BACKEND_ENV" | head -1 | cut -d= -f2-)
  redacted=$(printf '%s' "$url" | sed -E 's#(://[^:]+):[^@]+@#\1:***@#')
  printf '       effective DATABASE_URL: %s\n' "$redacted"
fi

# ── summary ───────────────────────────────────────────────────────────────────
echo
bold "Summary: $ok ok, $warn warn, $fail fail"
[ "$fail" -gt 0 ] && exit 1
exit 0
