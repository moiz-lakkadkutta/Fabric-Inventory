"""Fail-closed guard: the runtime must not connect to Postgres as a
superuser / BYPASSRLS role (that silently disables Row-Level Security and
breaks tenant isolation — INT-9 regression backstop).

The test env exposes two roles:
- DATABASE_URL           → fabric_app  (NOBYPASSRLS, the correct runtime role)
- MIGRATION_DATABASE_URL → fabric      (superuser, migrations only)
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine

from app import db


def _psycopg2(url: str) -> str:
    for prefix in ("postgresql+asyncpg://", "postgresql://"):
        if url.startswith(prefix):
            return url.replace(prefix, "postgresql+psycopg2://", 1)
    return url


class _Settings:
    def __init__(self, environment: str) -> None:
        self.environment = environment


def _run_guard_with(monkeypatch, *, url: str, environment: str) -> None:
    engine = create_engine(_psycopg2(url), future=True)
    monkeypatch.setattr(db, "get_sync_engine", lambda: engine)
    monkeypatch.setattr(db, "get_settings", lambda: _Settings(environment))
    try:
        db.assert_non_privileged_db_role()
    finally:
        engine.dispose()


def test_guard_raises_for_superuser_role_in_prod(monkeypatch) -> None:
    super_url = os.environ["MIGRATION_DATABASE_URL"]  # fabric = superuser
    with pytest.raises(RuntimeError, match="Row-Level Security"):
        _run_guard_with(monkeypatch, url=super_url, environment="prod")


def test_guard_raises_for_superuser_role_in_staging(monkeypatch) -> None:
    super_url = os.environ["MIGRATION_DATABASE_URL"]
    with pytest.raises(RuntimeError, match="fabric_app"):
        _run_guard_with(monkeypatch, url=super_url, environment="staging")


def test_guard_passes_for_fabric_app_role_in_prod(monkeypatch) -> None:
    app_url = os.environ["DATABASE_URL"]  # fabric_app = NOBYPASSRLS
    # No exception → the NOBYPASSRLS runtime role is accepted.
    _run_guard_with(monkeypatch, url=app_url, environment="prod")


def test_guard_only_warns_in_dev_for_superuser(monkeypatch) -> None:
    super_url = os.environ["MIGRATION_DATABASE_URL"]
    # Dev tolerates a privileged role (local convenience) — warns, does not raise.
    _run_guard_with(monkeypatch, url=super_url, environment="dev")
