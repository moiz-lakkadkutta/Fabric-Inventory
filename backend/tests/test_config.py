"""TASK-002 follow-up: Settings validator behavior for CORS_ORIGINS.

Wildcard `*` with `allow_credentials=True` is silently broken in browsers,
so we never fall back to `*`. dev gets a localhost default; staging/prod
fail fast at startup.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolate_env() -> Iterator[None]:
    """Snapshot/restore env so each test gets a clean Settings load."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _build_settings() -> object:
    """Build a fresh Settings instance bypassing the cached singleton."""
    from app.config import Settings, reset_settings

    reset_settings()
    return Settings()  # type: ignore[call-arg]


def test_cors_origins_dev_empty_defaults_to_localhost() -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "test-secret-must-be-long-enough-32chars"
    os.environ["ENVIRONMENT"] = "dev"
    os.environ.pop("CORS_ORIGINS", None)

    settings = _build_settings()
    assert settings.cors_origins == ["http://localhost:5173"]  # type: ignore[attr-defined]


def test_cors_origins_dev_explicit_wins_over_default() -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "test-secret-must-be-long-enough-32chars"
    os.environ["ENVIRONMENT"] = "dev"
    os.environ["CORS_ORIGINS"] = "http://app.fabric.local,http://staging.fabric.local"

    settings = _build_settings()
    assert settings.cors_origins == [  # type: ignore[attr-defined]
        "http://app.fabric.local",
        "http://staging.fabric.local",
    ]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_cors_origins_non_dev_empty_raises(env: str) -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "test-secret-must-be-long-enough-32chars"
    os.environ["ENVIRONMENT"] = env
    os.environ.pop("CORS_ORIGINS", None)

    with pytest.raises(Exception, match="CORS_ORIGINS must be set"):
        _build_settings()


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_cors_origins_non_dev_explicit_succeeds(env: str) -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "test-secret-must-be-long-enough-32chars"
    os.environ["ENVIRONMENT"] = env
    os.environ["CORS_ORIGINS"] = "https://app.fabric.example"

    settings = _build_settings()
    assert settings.cors_origins == ["https://app.fabric.example"]  # type: ignore[attr-defined]
