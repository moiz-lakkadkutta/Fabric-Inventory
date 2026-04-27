"""TASK-006: permanent drift gate between ORM models and migrated DDL.

Runs `alembic.autogenerate.compare_metadata` against a fresh migrated
Postgres and asserts there are zero diffs scoped to tables we model.
This catches the entire class of bugs that PR #6's first push had:
missing audit columns, naked DateTime, missing UNIQUE constraints,
default= vs server_default= mismatches.

Drift detection is restricted to tables registered in `Base.metadata`
via an `include_object` filter. Tables that exist in DDL but aren't yet
modeled (sales_invoice, party, etc. — landing in TASK-014+) are
correctly ignored — autogenerate would otherwise want to drop them.

Skipped when no Postgres is reachable. CI's services container makes
this active.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from alembic import command
from app.models import Base


def _alembic_ini_path() -> str:
    """alembic.ini lives next to backend/."""
    from pathlib import Path

    return str(Path(__file__).resolve().parent.parent / "alembic.ini")


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Apply alembic upgrade head, yield a sync engine, leave schema in place."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

    engine = create_engine(sync_url, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        engine.dispose()
        pytest.skip(f"Postgres not reachable at {sync_url!r}: {exc}")

    # Wipe + remigrate so the test is reproducible regardless of leftover state.
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))

    config = Config(_alembic_ini_path())
    command.upgrade(config, "head")

    try:
        yield engine
    finally:
        engine.dispose()


def _modeled_tables() -> set[str]:
    """The set of tables our ORM declares — autogenerate scope."""
    return set(Base.metadata.tables.keys())


def _include_only_modeled(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Restrict autogenerate to schema-correctness drift on modeled tables.

    What this gate checks:
      - tables, columns, foreign-key constraints, unique constraints,
        column types, server_defaults, nullability.
    What it deliberately does NOT check:
      - non-unique indexes. Performance indexes live in DDL and stay
        there; declaring every `idx_*` on the ORM doubles maintenance
        for zero correctness value. Unique constraints (which DO matter
        for correctness) are declared on the ORM and are checked.
      - tables not yet in `Base.metadata` (sales_invoice, party, …).
        autogenerate would want to drop them; we ignore them until the
        owning task models them.
    """
    modeled = _modeled_tables()
    if type_ == "table":
        return name in modeled
    if type_ == "index":
        # Skip indexes entirely. Unique constraints come through type_ == "unique_constraint".
        return False
    # Columns / fks / unique constraints / etc.: keep if their parent table is modeled.
    parent = getattr(object_, "table", None)
    if parent is not None and getattr(parent, "name", None) is not None:
        return parent.name in modeled
    return True


def test_orm_metadata_matches_migrated_db_schema(migrated_engine: Engine) -> None:
    """No diff on modeled tables ↔ migrated DB. Hard gate against drift."""
    with migrated_engine.connect() as conn:
        ctx = MigrationContext.configure(
            connection=conn,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": _include_only_modeled,
            },
        )
        diff = compare_metadata(ctx, Base.metadata)

    if diff:
        # Render a readable failure message; alembic's tuple structure is fine
        # but ugly when many entries trip at once.
        rendered = "\n  - ".join(repr(d) for d in diff)
        pytest.fail(
            f"ORM <-> DDL drift on {len(diff)} item(s) — "
            f"alembic.autogenerate.compare_metadata reports:\n  - {rendered}"
        )
