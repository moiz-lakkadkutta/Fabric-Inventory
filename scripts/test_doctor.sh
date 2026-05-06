#!/usr/bin/env bash
# scripts/test_doctor.sh — INT-7 acceptance check.
#
# `make doctor` is the "is the dev stack actually working?" probe. It must:
#   (a) exit 0 when the stack is healthy
#   (b) exit non-zero with a useful diagnostic when /ready returns 503
#
# This script exercises both paths against a real stack so a regression
# in the `doctor` Makefile target trips CI rather than silently shipping
# a broken safety net.
#
# Conventions:
#   - FABRIC_HEALTHY_API_URL — an API the test KNOWS is healthy (default :8001,
#     because the QA pass on 2026-05-06 brought one up there).
#   - Broken case: point doctor at a port nothing listens on.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HEALTHY_API_URL="${FABRIC_HEALTHY_API_URL:-http://localhost:8001}"
BROKEN_API_URL="http://localhost:1"   # reserved port; nothing listens here

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
note()  { printf '\033[2m%s\033[0m\n' "$*"; }

fail() {
  red "FAIL: $*"
  exit 1
}

# ── Case 1: healthy stack → exit 0 ────────────────────────────────────────────
note "Case 1: doctor against healthy API at $HEALTHY_API_URL"
healthy_log="$(mktemp)"
trap 'rm -f "$healthy_log"' EXIT

if ! FABRIC_API_URL="$HEALTHY_API_URL" make -C "$REPO_ROOT" doctor >"$healthy_log" 2>&1; then
  cat "$healthy_log"
  fail "make doctor exited non-zero against a healthy stack ($HEALTHY_API_URL)"
fi

# Be generous with what we accept as a "healthy" report, but require the
# probe to have actually run — i.e. we want evidence /ready was checked,
# not just an empty success.
grep -qiE '(ready|healthy|ok)' "$healthy_log" \
  || { cat "$healthy_log"; fail "doctor's healthy output has no 'ready/ok' line — did it actually probe?"; }

green "  case 1 ok: doctor passes against healthy stack"

# ── Case 2: broken stack → exit non-zero + diagnostic ─────────────────────────
note "Case 2: doctor against unreachable API at $BROKEN_API_URL"
broken_log="$(mktemp)"
trap 'rm -f "$healthy_log" "$broken_log"' EXIT

set +e
FABRIC_API_URL="$BROKEN_API_URL" make -C "$REPO_ROOT" doctor >"$broken_log" 2>&1
broken_rc=$?
set -e

if [ "$broken_rc" -eq 0 ]; then
  cat "$broken_log"
  fail "make doctor exited 0 against an unreachable API — preflight is asleep at the wheel"
fi

# Diagnostic must name what's wrong. The failure mode that lit up on
# 2026-05-06 was /ready returning 503; doctor must call that out.
grep -qiE '(ready|503|unreachable|connection|refused)' "$broken_log" \
  || { cat "$broken_log"; fail "doctor failed without a useful diagnostic — output should mention /ready, 503, or connection failure"; }

green "  case 2 ok: doctor fails loudly against broken stack (rc=$broken_rc)"

green "ALL CHECKS PASSED"
