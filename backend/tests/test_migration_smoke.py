"""TASK-004: smoke test for the migration chain.

Wipes the public schema, runs `alembic upgrade head`, asserts the result
has at least 102 tables and that the latest revision is recorded.
Skipped when no real Postgres is reachable so devs without Docker
running locally still get a green test suite — CI's Postgres service
container makes the test a real regression net.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from alembic import command

# Minimum table count for the phase-1 schema. ddl.sql declares 102 BASE TABLE
# entries; add `alembic_version` for >=103. Use >= so future-task migrations
# that add tables don't break this assertion.
_MIN_TABLES = 102


def _alembic_ini_path() -> Path:
    """Locate alembic.ini next to backend/."""
    # tests/ -> backend/ -> alembic.ini
    return Path(__file__).resolve().parent.parent / "alembic.ini"


@pytest.fixture
def sync_postgres_engine() -> Iterator[Engine]:
    """Yield a sync psycopg2 engine pointing at DATABASE_URL.

    Skips the test when Postgres isn't reachable (typical local-dev case
    when Docker isn't running). CI's services container is reachable so
    this fixture activates the assertion path there.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    try:
        engine = create_engine(sync_url, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Postgres not reachable at {sync_url!r}: {exc}")
    try:
        yield engine
    finally:
        engine.dispose()


def _wipe_public_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))


def test_baseline_migration_smoke(sync_postgres_engine: Engine) -> None:
    _wipe_public_schema(sync_postgres_engine)

    # alembic.command.upgrade builds its own engine from alembic.ini + env vars,
    # so we don't pass the test fixture's engine — env.py reads DATABASE_URL.
    config = Config(str(_alembic_ini_path()))
    command.upgrade(config, "head")

    with sync_postgres_engine.connect() as conn:
        table_count = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).scalar_one()
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert table_count >= _MIN_TABLES, f"expected >= {_MIN_TABLES} tables, got {table_count}"
    # Latest forward-only migration head; bump on each new migration.
    assert version == "task_int_1_feature_flag_per_firm", f"unexpected revision: {version!r}"
