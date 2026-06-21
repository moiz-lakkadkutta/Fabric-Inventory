"""Test fixtures and env setup.

Sets default env vars BEFORE app imports so pydantic-settings doesn't
fail when a real .env is absent. DB-bound fixtures (`sync_engine`,
`db_session`) live here so any test file can share them.

Local dev without Docker → DB-bound tests skip cleanly.
CI (`CI=true`) → DB-bound fixtures fail loud if Postgres isn't reachable,
so a misconfigured workflow can't silently mask drift.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# Set required env BEFORE the app imports — pydantic-settings validates at import.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
# TS-01 (C2): the boot-time guard rejects placeholder / "test-secret" / <32-char
# JWT secrets when ENVIRONMENT != "dev". Tests that boot the app in staging/prod
# mode (docs-disabled, KEK checks, security headers, …) must use a strong,
# non-placeholder secret or they'd trip that guard. Use a strong default here;
# the dedicated TS-01 tests in test_config.py set their own secret to exercise
# the rejection paths.
os.environ.setdefault("JWT_SECRET", "kY7mWq2pR9nB4vX8tL6cJ3hF5dG1sZ0aUeImOoPlQwErTyU")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("LOG_LEVEL", "INFO")

# CUT-205: WeasyPrint dlopen()s pango/cairo/gobject. On macOS-arm64 those
# libraries live in /opt/homebrew/lib. Set the fallback path for tests so
# `uv run pytest` finds them even with a scrubbed shell env. No-op on Linux.
import platform as _platform

if _platform.system() == "Darwin":
    for _candidate in ("/opt/homebrew/lib", "/usr/local/lib"):
        if os.path.isdir(_candidate):
            existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
            if _candidate not in existing.split(":"):
                os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                    f"{_candidate}:{existing}" if existing else _candidate
                )
            break


# TASK-TR-SEC1 follow-up: `organization.encrypted_dek` is NOT NULL post-migration,
# but ~20 existing test fixtures construct `Organization(...)` directly without
# setting it (the real signup path does, see routers/auth.py:184-189). Rather
# than sweeping every fixture, register a `before_insert` hook that auto-mints a
# wrapped DEK when one isn't provided. Production code is unaffected — auth and
# the seed-demo CLI pass an explicit `encrypted_dek=` so this branch is dead in
# prod. Test-only safety net.
from sqlalchemy import event as _sa_event

from app.models import Organization as _Organization
from app.utils.crypto import generate_dek as _generate_dek
from app.utils.crypto import wrap_dek as _wrap_dek


@_sa_event.listens_for(_Organization, "before_insert")
def _autofill_encrypted_dek(_mapper: object, _connection: object, target: _Organization) -> None:
    if target.encrypted_dek is not None:
        return
    if target.org_id is None:
        target.org_id = uuid.uuid4()
    target.encrypted_dek = _wrap_dek(_generate_dek(), org_id=target.org_id)


@pytest.fixture(autouse=True)
def _isolate_rate_limit() -> Iterator[None]:
    """Give every test a private, empty rate-limit store.

    DOS-01 added IP-keyed limits to login/signup/mfa/reset (e.g. signup is
    3/3600s). The whole suite shares one client IP, so without per-test
    isolation the 4th signup *anywhere* in the session trips 429 and breaks
    every later test that authenticates. Inject a fresh in-memory fakeredis
    per test (and reset after) so limits are hermetic: dedicated rate-limit
    tests still drive their own fresh store to the threshold, while ordinary
    tests get a clean budget and never hit the real Redis.
    """
    from app.middleware.rate_limit import set_redis_client_for_testing

    try:
        import fakeredis.aioredis as _fakeredis
    except ModuleNotFoundError:  # pragma: no cover - fakeredis is a test dep
        yield
        return
    fake = _fakeredis.FakeRedis(decode_responses=True)
    set_redis_client_for_testing(fake)
    try:
        yield
    finally:
        set_redis_client_for_testing(None)


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

    def request(self, method: str, url: str, **kwargs: Any) -> Any:  # type: ignore[override]
        if method.upper() in self._MUTATING:
            headers = dict(kwargs.get("headers") or {})
            if "Idempotency-Key" not in headers:
                headers["Idempotency-Key"] = str(uuid.uuid4())
                kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


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
def admin_engine() -> Iterator[Engine]:
    """Sync engine connected as the migration role (BYPASSRLS / superuser).

    Per TASK-INT-16, the runtime DATABASE_URL connects as `fabric_app`
    (NOBYPASSRLS) so RLS is enforced. Tests that need to seed cross-tenant
    fixtures, drop test data, or read system catalogs use this fixture
    to bypass RLS deliberately. Falls back to DATABASE_URL when
    MIGRATION_DATABASE_URL is unset (single-role local setups).
    """
    db_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not db_url:
        if os.environ.get("CI") == "true":
            pytest.fail("MIGRATION_DATABASE_URL or DATABASE_URL must be set in CI")
        pytest.skip("MIGRATION_DATABASE_URL/DATABASE_URL not set")
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    try:
        engine = create_engine(sync_url, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        if os.environ.get("CI") == "true":
            pytest.fail(f"Migration DB unreachable in CI: {exc}")
        pytest.skip(f"Migration DB unreachable: {exc}")
    try:
        yield engine
    finally:
        engine.dispose()


@contextlib.contextmanager
def org_scoped_session(engine: Engine, org_id: uuid.UUID) -> Iterator[OrmSession]:
    """Yield an ORM session pre-set with `app.current_org_id` = org_id.

    Use this when a test needs to inspect / seed rows under fabric_app
    (NOBYPASSRLS): without the GUC, every SELECT returns zero rows and
    every INSERT fails the WITH CHECK clause. `expire_on_commit=False`
    avoids the post-commit refresh that would re-issue a SELECT outside
    the SET LOCAL scope.
    """
    with OrmSession(engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        yield session
        session.commit()


@pytest.fixture
def fresh_org_id(db_session: OrmSession) -> uuid.UUID:
    """Create a fresh Organization, set RLS GUC, return its org_id.

    Order matters under INT-9: when the runtime DB role is `fabric_app`
    (NOBYPASSRLS), the WITH CHECK clause on `organization_rls` evaluates
    `current_setting('app.current_org_id')` at INSERT time. The GUC must
    be SET to the new org_id BEFORE the INSERT or psql raises
    `unrecognized configuration parameter`. We pre-mint the UUID,
    set the GUC, then insert with the same id.

    TASK-TR-SEC1: also mint and wrap a Data Encryption Key so the
    `encrypted_dek NOT NULL` column is satisfied. Tests using the
    crypto path then hit the same code path as production signup.
    """
    from app.models import Organization
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"test-org-{uuid.uuid4().hex[:10]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    db_session.add(org)
    db_session.flush()
    return org_id
