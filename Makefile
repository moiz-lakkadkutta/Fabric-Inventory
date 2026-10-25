.PHONY: setup dev dev-native down doctor test test-watch lint lint-fix migrate migrate-create seed seed-demo demo-video demo-videos demo-video-down deploy backup restore restore-test e2e-setup openapi-snapshot cleanup spike-vyapar help

# Prefer "docker compose" (v2 plugin); fall back to legacy "docker-compose" binary.
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

help:
	@echo "Fabric ERP — common targets:"
	@echo "  make setup        Install backend (uv) + frontend (pnpm) deps; create .env files if missing"
	@echo "  make dev          Start docker compose stack (Postgres, Redis, API, Web)"
	@echo "  make dev-native   Bring up Postgres+Redis in compose; run uvicorn+vite natively"
	@echo "  make doctor       Probe the running stack (exit 0 if healthy, 1 with diagnostic)"
	@echo "  make down         Stop docker compose stack"
	@echo "  make test         Run backend + frontend tests"
	@echo "  make lint         Run ruff + mypy + eslint + prettier + tsc"
	@echo "  make lint-fix     Auto-fix ruff + prettier violations"
	@echo "  make e2e-setup    Install Playwright browsers (opt-in, ~400MB)"
	@echo "  make migrate      Run alembic upgrade head (MIGRATION_DATABASE_URL or DATABASE_URL must be set)"
	@echo "  make migrate-create M=\"msg\"  Generate a new alembic revision"
	@echo "  make seed-demo    Load synthetic textile demo dataset (idempotent; TASK-TR-Q04a)"
	@echo "  make openapi-snapshot  Re-dump openapi snapshot + regen FE types (CUT-106)"
	@echo "  make backup       Dump Postgres → gzip → gpg → S3-compatible bucket (CUT-404)"
	@echo "  make restore date=YYYY-MM-DD [target_db=NAME] [dry_run=1]  Restore from a backup (CUT-404)"
	@echo "  make restore-test  Round-trip test: backup → restore → assert sentinel row (CUT-404)"
	@echo "  make cleanup      Prune used/expired password_reset_token rows (CUT-501a; cron daily)"
	@echo "  make spike-vyapar VYAPAR_FILE=<path>  Run the Vyapar real-backup spike runner (TASK-TR-D3-PREP)"

setup:
	@test -f .env || cp .env.example .env
	@test -f backend/.env || cp backend/.env.example backend/.env
	@test -f frontend/.env || cp frontend/.env.example frontend/.env
	cd backend && uv sync
	cd frontend && pnpm install

dev:
	$(COMPOSE) up --build

dev-native:
	@bash scripts/dev-native.sh

doctor:
	@bash scripts/doctor.sh

down:
	$(COMPOSE) down

test:
	cd backend && uv run pytest
	cd frontend && pnpm test

test-watch:
	@echo "Run 'cd backend && uv run pytest -f' and 'cd frontend && pnpm test:watch' in separate terminals."

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .
	cd frontend && pnpm lint && pnpm typecheck

lint-fix:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && pnpm lint:fix

migrate:
	cd backend && uv run alembic upgrade head

migrate-create:
	@if [ -z "$(M)" ]; then \
		echo "usage: make migrate-create M=\"short message\""; exit 1; \
	fi
	cd backend && uv run alembic revision -m "$(M)"

seed:
	@echo "System catalog (UOM/HSN/COA) auto-seeds on /auth/signup; nothing to do here."
	@echo "To re-seed an existing org by id, run:"
	@echo "  cd backend && uv run python -m app.cli.seed --org-id <UUID>"

# Load a synthetic textile-trade demo dataset (parties + items + opening
# stock + ~3 POs + ~5 SIs + 1 JWO) so Moiz can dogfood without waiting on
# the Vyapar adapter migration fix. Idempotent — re-runs are safe.
# Defaults to a demo@example.com / "Demo Co" / "Demo Firm" tenant; pass
# overrides through ARGS, e.g.:
#   make seed-demo ARGS="--email me@example.com --org-name 'Moiz Trading'"
# TASK-TR-C1: prepend ENVIRONMENT=dev so `crypto.get_master_kek()` falls
# back to the public dev KEK instead of raising PIIConfigError on a
# bare-machine `make seed-demo`. Mirrors the same env-prepend pattern
# the `run` target in backend/Makefile uses (PR #104, DYLD helper).
# For a real (demo) instance use `ENVIRONMENT=prod` (the Settings enum is
# dev|staging|prod — "production" fails validation) together with the SAME
# PII_MASTER_KEY, JWT_SECRET (>=32 chars), CORS_ORIGINS and REDIS_URL the
# API runs with, plus `ARGS="--password <strong>"`: the default
# DemoPass123 is public. The Owner must enrol TOTP MFA on first login.
seed-demo:
	cd backend && ENVIRONMENT=$${ENVIRONMENT:-dev} uv run python -m app.cli.seed_demo $(ARGS)

# Narrated product films (see demo-video/README.md). `make demo-video` records
# one film (default the explainer → demo-video/out/fabric-explainer.mp4);
# `make demo-video FILM=<id>` picks demo-video/films/<id>.mjs, and
# `make demo-videos` records every film, re-seeding before each.
# Uses its own compose project; stop `make dev` first.
FILM ?= explainer
demo-video:
	demo-video/prepare.sh
	node demo-video/record.mjs --film=$(FILM)

demo-videos:
	@set -e; for f in demo-video/films/*.mjs; do \
	  id=$$(basename $$f .mjs); echo "── film: $$id"; \
	  demo-video/prepare.sh; node demo-video/record.mjs --film=$$id; \
	done

demo-video-down:
	docker compose -p fabric-video -f docker-compose.yml -f demo-video/docker-compose.video.yml down -v

deploy:
	@echo "Implement in TASK-005 (GitHub Actions deploy workflow)."

backup:
	@bash ops/backup.sh

# `make restore` shells out to ops/restore.sh. Two ways to pass arguments:
#   make restore date=2026-05-11 dry_run=1
#   make restore date=2026-05-11 target_db=fabric_erp_restore_test
#   make restore file=ops/backups/fabric_fabric_erp_2026-05-11_*.sql.gz.gpg
# Variables map to the script flags via the Makefile's lazy expansion.
restore:
	@bash ops/restore.sh \
		$(if $(date),--date=$(date),) \
		$(if $(file),--file=$(file),) \
		$(if $(target_db),--target-db=$(target_db),) \
		$(if $(dry_run),--dry-run,)

# Convenience alias for the round-trip test (TASK-CUT-404).
# Requires the docker-compose Postgres to be reachable + the same env
# tests/test_backup.sh expects (see header of that file).
restore-test:
	@bash tests/test_backup.sh

e2e-setup:
	cd frontend && pnpm exec playwright install --with-deps

# Refresh frontend/scripts/openapi-snapshot.json from the in-process
# FastAPI app, then regenerate frontend/src/types/api.ts. Run after
# any BE schema change (new endpoint, new pydantic field, etc.) and
# commit both files. CI's `openapi-drift` job blocks PRs that skip
# this step.
openapi-snapshot:
	cd backend && uv run python ../frontend/scripts/dump-openapi.py
	cd frontend && pnpm gen:types

# Prune used/expired password_reset_token rows (CUT-501a). Wire to cron
# in prod (see docs/ops/deployment-runbook.md § Scheduled jobs); calling
# this in dev is a safe no-op.
cleanup:
	cd backend && uv run python -m app.cli.cleanup_tokens

# TASK-TR-D3-PREP: Vyapar real-backup spike runner. Reads a Vyapar
# Excel export and prints a coverage report against the in-tree
# VyaparExcelAdapter. Usage:
#   make spike-vyapar VYAPAR_FILE=docs/spikes/vyapar-sample-export.xlsx
# The VYAPAR_FILE path is interpreted relative to the repo root. If
# unset, the target prints a helpful pointer and exits 0 — it's a
# no-op, not an error, because the file is operator-supplied.
spike-vyapar:
	@if [ -z "$(VYAPAR_FILE)" ]; then \
		echo "Set VYAPAR_FILE=<path> (typically docs/spikes/vyapar-sample-export.xlsx)."; \
		echo "See docs/spikes/vyapar-real-backup-protocol.md for how to produce one."; \
	else \
		REPO_ROOT="$$(pwd)"; \
		case "$(VYAPAR_FILE)" in /*) ABS_PATH="$(VYAPAR_FILE)";; *) ABS_PATH="$$REPO_ROOT/$(VYAPAR_FILE)";; esac; \
		cd backend && ENVIRONMENT=dev uv run python -m scripts.spike_vyapar "$$ABS_PATH"; \
	fi
