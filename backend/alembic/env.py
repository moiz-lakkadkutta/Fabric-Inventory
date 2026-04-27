"""Alembic env.py — sync (psycopg2) engine for migrations.

The app uses async (asyncpg) at runtime, but migrations use sync (psycopg2).
This is the standard Alembic pattern: asyncpg can't `prepare` multi-statement
DDL files, while psycopg2 happily executes them via `cursor.execute()`.

`DATABASE_URL` (env) is the source of truth. If it's asyncpg-shaped
(`postgresql+asyncpg://...` per backend/.env.example), we rewrite it to
`postgresql+psycopg2://...` here. `target_metadata` stays None until
SQLAlchemy models exist (TASK-006+); autogenerate is OFF until then.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# DATABASE_URL is asyncpg-shaped per backend/.env.example. Transform for migrations.
db_url = os.environ.get("DATABASE_URL", "")
if not db_url:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Run `make dev` first (boots Postgres + populates env), "
        "or export DATABASE_URL=postgresql+asyncpg://user:pw@host:port/db."
    )
if db_url.startswith("postgresql+asyncpg://"):
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
config.set_main_option("sqlalchemy.url", db_url)


target_metadata = None  # No models yet; autogenerate is OFF until TASK-006.


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
