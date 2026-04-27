.PHONY: setup dev down test test-watch lint lint-fix migrate migrate-create seed deploy backup e2e-setup help

# Prefer "docker compose" (v2 plugin); fall back to legacy "docker-compose" binary.
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

help:
	@echo "Fabric ERP — common targets:"
	@echo "  make setup        Install backend (uv) + frontend (pnpm) deps; create .env if missing"
	@echo "  make dev          Start docker compose stack (Postgres, Redis, API, Web)"
	@echo "  make down         Stop docker compose stack"
	@echo "  make test         Run backend + frontend tests"
	@echo "  make lint         Run ruff + mypy + eslint + prettier + tsc"
	@echo "  make lint-fix     Auto-fix ruff + prettier violations"
	@echo "  make e2e-setup    Install Playwright browsers (opt-in, ~400MB)"
	@echo "  make migrate      Run alembic upgrade head (DATABASE_URL must be set)"
	@echo "  make migrate-create M=\"msg\"  Generate a new alembic revision"

setup:
	@test -f .env || cp .env.example .env
	cd backend && uv sync
	cd frontend && pnpm install

dev:
	$(COMPOSE) up --build

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
	@echo "Implement in TASK-006+ (seed fixtures)."

deploy:
	@echo "Implement in TASK-005 (GitHub Actions deploy workflow)."

backup:
	@echo "Implement post-deploy (pg_dump + S3 upload)."

e2e-setup:
	cd frontend && pnpm exec playwright install --with-deps
