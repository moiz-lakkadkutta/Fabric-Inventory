#!/usr/bin/env bash
# Wipes and re-seeds the isolated `fabric-video` compose project, then enrols
# MFA for the demo Owner. Every take starts from identical data.
set -euo pipefail
cd "$(dirname "$0")/.."
DC="docker compose -p fabric-video -f docker-compose.yml -f demo-video/docker-compose.video.yml"

$DC down -v --remove-orphans
$DC up -d   # images from the first `make dev`; add --build after backend changes
echo "waiting for API…"
for _ in $(seq 1 60); do
  curl -sf http://localhost:8000/ready >/dev/null && break
  sleep 3
done
curl -sf http://localhost:8000/ready >/dev/null || { echo "API never became ready"; exit 1; }

$DC exec -T api uv run python -m app.cli.seed_demo \
  --email demo@fabric-demo.in --password DemoPass123 \
  --org-name 'Fabric Demo Textiles' --firm-name 'Noor Suits Pvt Ltd' --state-code MH

node demo-video/enroll-mfa.mjs
