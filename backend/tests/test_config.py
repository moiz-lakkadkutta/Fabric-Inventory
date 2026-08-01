"""TASK-002 follow-up: Settings validator behavior for CORS_ORIGINS.

Wildcard `*` with `allow_credentials=True` is silently broken in browsers,
so we never fall back to `*`. dev gets a localhost default; staging/prod
fail fast at startup.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def isolate_env() -> Iterator[None]:
    """Snapshot/restore env so each test gets a clean Settings load."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _build_settings() -> object:
    """Build a fresh Settings instance bypassing the cached singleton.

    `_env_file=None` disables `.env` loading so the test only sees the
    in-process env this test set up. Without this, a developer's local
    `backend/.env` (which is now created by `make setup` per INT-7) leaks
    values into staging/prod-environment tests and hides real failures.
    """
    from app.config import Settings, reset_settings

    reset_settings()
    return Settings(_env_file=None)  # type: ignore[call-arg]


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
    # Strong, random-looking secret — no placeholder substrings, ≥32 chars.
    os.environ["JWT_SECRET"] = "aB3kR9mXpQ2wLnT7vYdF5hCeGjZuNsOiA8bWqDlPfHy"
    os.environ["ENVIRONMENT"] = env
    os.environ.pop("CORS_ORIGINS", None)

    with pytest.raises(Exception, match="CORS_ORIGINS must be set"):
        _build_settings()


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_cors_origins_non_dev_explicit_succeeds(env: str) -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    # Strong, random-looking secret — no placeholder substrings, ≥32 chars.
    os.environ["JWT_SECRET"] = "aB3kR9mXpQ2wLnT7vYdF5hCeGjZuNsOiA8bWqDlPfHy"
    os.environ["ENVIRONMENT"] = env
    os.environ["CORS_ORIGINS"] = "https://app.fabric.example"
    # TS-04 guard: REDIS_URL is required in non-dev since cycle-2.
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"

    settings = _build_settings()
    assert settings.cors_origins == ["https://app.fabric.example"]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TS-01: JWT secret placeholder / entropy guard
# ---------------------------------------------------------------------------


def test_jwt_placeholder_rejected_in_staging() -> None:
    """Known placeholder secret must be refused in staging (TS-01)."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "change-me-in-prod-must-be-long-enough"
    os.environ["ENVIRONMENT"] = "staging"
    os.environ.pop("CORS_ORIGINS", None)

    with pytest.raises(Exception, match="known placeholder"):
        _build_settings()


def test_jwt_too_short_rejected_in_prod() -> None:
    """A non-placeholder but short (<32 char) secret must be refused in prod (TS-01)."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "only20charlong!!!!!!"  # 20 chars, not a placeholder
    os.environ["ENVIRONMENT"] = "prod"
    os.environ.pop("CORS_ORIGINS", None)

    with pytest.raises(Exception, match="32 characters"):
        _build_settings()


def test_jwt_strong_secret_accepted_in_prod() -> None:
    """A strong (>=32 char, non-placeholder) secret must boot fine in prod (TS-01)."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    # 48 chars, random-looking, not on any denylist
    os.environ["JWT_SECRET"] = "aB3kR9mXpQ2wLnT7vYdF5hCeGjZuNsOiA8bWqDlPfHy"
    os.environ["ENVIRONMENT"] = "prod"
    os.environ["CORS_ORIGINS"] = "https://prod.fabric.example"
    # TS-04 guard: REDIS_URL is required in non-dev since cycle-2.
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"

    settings = _build_settings()
    assert settings.environment == "prod"  # type: ignore[attr-defined]


def test_jwt_short_test_secret_accepted_in_dev() -> None:
    """dev environment must not enforce the entropy floor — no regression (TS-01)."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "test-secret-must-be-long-enough-32chars"
    os.environ["ENVIRONMENT"] = "dev"
    os.environ.pop("CORS_ORIGINS", None)

    settings = _build_settings()
    assert settings.environment == "dev"  # type: ignore[attr-defined]


def test_committed_test_secret_rejected_in_prod() -> None:
    """The committed repo test secret must be refused in prod (TS-01 hole closed)."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    # This is the exact secret committed to the repo and used in conftest.py.
    # After adding "test-secret" to the denylist it must be rejected in prod.
    os.environ["JWT_SECRET"] = "test-secret-must-be-long-enough-32chars"
    os.environ["ENVIRONMENT"] = "prod"
    os.environ["CORS_ORIGINS"] = "https://prod.fabric.example"

    with pytest.raises(Exception, match="known placeholder"):
        _build_settings()


# ---------------------------------------------------------------------------
# TS-04 Redis guard: REDIS_URL required in non-dev environments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_redis_url_required_in_non_dev(env: str) -> None:
    """Redis absent in non-dev must raise at startup — no silent jti denylist bypass."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "aB3kR9mXpQ2wLnT7vYdF5hCeGjZuNsOiA8bWqDlPfHy"
    os.environ["ENVIRONMENT"] = env
    os.environ["CORS_ORIGINS"] = "https://app.fabric.example"
    os.environ.pop("REDIS_URL", None)

    with pytest.raises(Exception, match="REDIS_URL"):
        _build_settings()


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_redis_url_set_in_non_dev_ok(env: str) -> None:
    """REDIS_URL present in non-dev → settings boot fine."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "aB3kR9mXpQ2wLnT7vYdF5hCeGjZuNsOiA8bWqDlPfHy"
    os.environ["ENVIRONMENT"] = env
    os.environ["CORS_ORIGINS"] = "https://app.fabric.example"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"

    settings = _build_settings()
    assert settings.redis_url == "redis://localhost:6379/0"  # type: ignore[attr-defined]


def test_redis_url_optional_in_dev() -> None:
    """Dev mode must not require REDIS_URL — no change to existing behavior."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "test-secret-must-be-long-enough-32chars"
    os.environ["ENVIRONMENT"] = "dev"
    os.environ.pop("REDIS_URL", None)

    settings = _build_settings()
    assert settings.redis_url is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# DOS-01 signup rate-limit guard: the knobs exist for the E2E acceptance
# stack (ENVIRONMENT=dev) only. staging/prod must never run a looser policy.
#
# These tests are the tripwire: if someone later "just bumps the default" or
# drops the non-dev guard so a red CI job goes green, this file fails.
# ---------------------------------------------------------------------------


def _dev_base_env() -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "test-secret-must-be-long-enough-32chars"
    os.environ["ENVIRONMENT"] = "dev"
    os.environ.pop("CORS_ORIGINS", None)
    os.environ.pop("SIGNUP_RATE_LIMIT_MAX_REQUESTS", None)
    os.environ.pop("SIGNUP_RATE_LIMIT_WINDOW_SECONDS", None)


def _non_dev_base_env(env: str) -> None:
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:y@h:5432/z"
    os.environ["JWT_SECRET"] = "aB3kR9mXpQ2wLnT7vYdF5hCeGjZuNsOiA8bWqDlPfHy"
    os.environ["ENVIRONMENT"] = env
    os.environ["CORS_ORIGINS"] = "https://app.fabric.example"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ.pop("SIGNUP_RATE_LIMIT_MAX_REQUESTS", None)
    os.environ.pop("SIGNUP_RATE_LIMIT_WINDOW_SECONDS", None)


def test_signup_rate_limit_defaults_are_secure() -> None:
    """Unset env → the strict DOS-01 policy: 3 signups per 3600s per IP."""
    from app.config import (
        SECURE_SIGNUP_RATE_LIMIT_MAX_REQUESTS,
        SECURE_SIGNUP_RATE_LIMIT_WINDOW_SECONDS,
    )

    assert SECURE_SIGNUP_RATE_LIMIT_MAX_REQUESTS == 3
    assert SECURE_SIGNUP_RATE_LIMIT_WINDOW_SECONDS == 3600

    _dev_base_env()
    settings = _build_settings()
    assert settings.signup_rate_limit_max_requests == 3  # type: ignore[attr-defined]
    assert settings.signup_rate_limit_window_seconds == 3600  # type: ignore[attr-defined]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_signup_rate_limit_defaults_are_secure_in_non_dev(env: str) -> None:
    """staging/prod with nothing set boots on the strict policy."""
    _non_dev_base_env(env)
    settings = _build_settings()
    assert settings.signup_rate_limit_max_requests == 3  # type: ignore[attr-defined]
    assert settings.signup_rate_limit_window_seconds == 3600  # type: ignore[attr-defined]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_signup_rate_limit_loose_max_rejected_in_non_dev(env: str) -> None:
    """A raised max (the E2E override value) must refuse to boot in prod."""
    _non_dev_base_env(env)
    os.environ["SIGNUP_RATE_LIMIT_MAX_REQUESTS"] = "200"

    with pytest.raises(Exception, match="Signup rate limit may not be loosened"):
        _build_settings()


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_signup_rate_limit_short_window_rejected_in_non_dev(env: str) -> None:
    """Shrinking the window is loosening too — same boot refusal."""
    _non_dev_base_env(env)
    os.environ["SIGNUP_RATE_LIMIT_WINDOW_SECONDS"] = "60"

    with pytest.raises(Exception, match="Signup rate limit may not be loosened"):
        _build_settings()


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_signup_rate_limit_tightening_allowed_in_non_dev(env: str) -> None:
    """Stricter-than-default is always allowed (fewer signups, longer window)."""
    _non_dev_base_env(env)
    os.environ["SIGNUP_RATE_LIMIT_MAX_REQUESTS"] = "1"
    os.environ["SIGNUP_RATE_LIMIT_WINDOW_SECONDS"] = "7200"

    settings = _build_settings()
    assert settings.signup_rate_limit_max_requests == 1  # type: ignore[attr-defined]
    assert settings.signup_rate_limit_window_seconds == 7200  # type: ignore[attr-defined]


def test_signup_rate_limit_override_allowed_in_dev() -> None:
    """The E2E stack (ENVIRONMENT=dev) may raise the ceiling — that is the
    single sanctioned consumer of these knobs."""
    _dev_base_env()
    os.environ["SIGNUP_RATE_LIMIT_MAX_REQUESTS"] = "200"

    settings = _build_settings()
    assert settings.signup_rate_limit_max_requests == 200  # type: ignore[attr-defined]


def test_signup_rate_limit_max_must_be_positive() -> None:
    """0 / negative would disable the limiter outright — rejected everywhere."""
    _dev_base_env()
    os.environ["SIGNUP_RATE_LIMIT_MAX_REQUESTS"] = "0"

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        _build_settings()
