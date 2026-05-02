"""Test fixtures and env setup.

Sets default env vars BEFORE app imports so pydantic-settings doesn't
fail when a real .env is absent. DB-bound fixtures (`sync_engine`,
`db_session`) live here so any test file can share them.

Local dev without Docker → DB-bound tests skip cleanly.
CI (`CI=true`) → DB-bound fixtures fail loud if Postgres isn't reachable,
so a misconfigured workflow can't silently mask drift.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# Set required env BEFORE the app imports — pydantic-settings validates at import.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-must-be-long-enough-32chars")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("LOG_LEVEL", "INFO")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client over the FastAPI app's ASGI transport."""
    from httpx import ASGITransport

    # Reset settings cache so any test-local env overrides take effect.
    from app.config import reset_settings

    reset_settings()

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ──────────────────────────────────────────────────────────────────────
# IdempotentTestClient + shared http_client fixture
# ──────────────────────────────────────────────────────────────────────
#
# T-INT-1 added IdempotencyMiddleware which strict-rejects mutating
# requests without an `Idempotency-Key` header. To keep existing tests
# focused on what they actually assert, this wrapper auto-injects a UUID
# key on every POST/PATCH/PUT/DELETE unless one is already provided.
# Tests that need to test the missing-key path can pass
# `Idempotency-Key=""` explicitly or use a raw TestClient.


class IdempotentTestClient(TestClient):
    """TestClient that auto-injects an Idempotency-Key on mutating requests."""

    _MUTATING: ClassVar[set[str]] = {"POST", "PATCH", "PUT", "DELETE"}

    def request(self, method: str, url: str, **kwargs: object) -> object:  # type: ignore[override]
        if method.upper() in self._MUTATING:
            headers = dict(kwargs.get("headers") or {})  # type: ignore[arg-type]
            if "Idempotency-Key" not in headers:
                headers["Idempotency-Key"] = str(uuid.uuid4())
                kwargs["headers"] = headers
        return super().request(method, url, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def http_client(sync_engine: Engine) -> Iterator[IdempotentTestClient]:
    """Shared HTTP client for router tests. Hits the real Postgres via
    `sync_engine` (skipped locally without DB; fail-loud in CI).

    Auto-injects Idempotency-Key on mutating requests so individual tests
    don't have to mint UUIDs themselves.
    """
    _ = sync_engine  # keep the fixture's connection check + skip semantics
    from main import create_app

    app = create_app()
    with IdempotentTestClient(app) as c:
        yield c


# ──────────────────────────────────────────────────────────────────────
# DB-bound fixtures (shared by test_identity_models, test_rbac_service, …)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def sync_engine() -> Iterator[Engine]:
    """Sync psycopg2 engine pointing at DATABASE_URL.

    Skips in local dev (no Postgres reachable). Hard-fails in CI so a
    misconfigured workflow can't silently mask DB-bound test drift.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        if os.environ.get("CI") == "true":
            pytest.fail("DATABASE_URL must be set in CI; required for DB-bound tests.")
        pytest.skip("DATABASE_URL not set (set CI=true to fail-loud)")
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    try:
        engine = create_engine(sync_url, future=True)
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if ver is None:
                pytest.skip("alembic schema not migrated; run `make migrate` first")
    except Exception as exc:
        if os.environ.get("CI") == "true":
            pytest.fail(f"Postgres not reachable / unmigrated in CI: {exc}")
        pytest.skip(f"Postgres not reachable / unmigrated: {exc}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(sync_engine: Engine) -> Iterator[OrmSession]:
    """Transactional fixture: each test runs inside a transaction that
    is rolled back on teardown. No row persists across tests; no need
    for cascade-delete cleanup hacks.
    """
    connection = sync_engine.connect()
    transaction = connection.begin()
    session = OrmSession(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def fresh_org_id(db_session: OrmSession) -> uuid.UUID:
    """Create a fresh Organization, set RLS GUC, return its org_id."""
    from app.models import Organization

    org = Organization(
        name=f"test-org-{uuid.uuid4().hex[:10]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    db_session.add(org)
    db_session.flush()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))
    return org.org_id
