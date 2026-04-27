"""SQLAlchemy engine and session factories — both async and sync.

Migrations own the schema (Alembic, TASK-004). This module never calls
`create_all`. Per-request sessions yielded via:

- `get_session()` (async) — for async handlers / future async services.
- `get_sync_session()` — for sync route handlers + sync services
  (`rbac_service`, `identity_service`). FastAPI runs sync handlers in a
  threadpool so blocking sync calls don't stall the event loop.

Both share the same `DATABASE_URL`; the sync engine rewrites the
asyncpg-shaped URL to psycopg2 (same trick alembic env.py uses).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_async_engine: AsyncEngine | None = None
_async_sessionmaker: async_sessionmaker[AsyncSession] | None = None

_sync_engine: Engine | None = None
_sync_sessionmaker: sessionmaker[Session] | None = None


def _sync_url(database_url: str) -> str:
    """Rewrite asyncpg URL to psycopg2 for the sync engine."""
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return database_url


def get_engine() -> AsyncEngine:
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        _async_engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
    return _async_engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _async_sessionmaker
    if _async_sessionmaker is None:
        _async_sessionmaker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async session for one request, close after."""
    async with get_sessionmaker()() as session:
        yield session


def get_sync_engine() -> Engine:
    global _sync_engine
    if _sync_engine is None:
        settings = get_settings()
        _sync_engine = create_engine(
            _sync_url(settings.database_url),
            echo=False,
            pool_pre_ping=True,
            future=True,
        )
    return _sync_engine


def get_sync_sessionmaker() -> sessionmaker[Session]:
    global _sync_sessionmaker
    if _sync_sessionmaker is None:
        _sync_sessionmaker = sessionmaker(
            get_sync_engine(),
            class_=Session,
            expire_on_commit=False,
            future=True,
        )
    return _sync_sessionmaker


def get_sync_session() -> Iterator[Session]:
    """Yield a sync session for one request. Used by sync FastAPI route
    handlers + the sync service layer (`rbac_service`, `identity_service`).
    """
    with get_sync_sessionmaker()() as session:
        yield session


async def check_db_health() -> bool:
    """Run `SELECT 1`; return True if it succeeds, False otherwise."""
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose_engine() -> None:
    """Tear down both engines. Call on app shutdown."""
    global _async_engine, _async_sessionmaker, _sync_engine, _sync_sessionmaker
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_sessionmaker = None
    if _sync_engine is not None:
        _sync_engine.dispose()
        _sync_engine = None
        _sync_sessionmaker = None
