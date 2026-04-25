"""TASK-002: Sentry init must not crash when DSN is empty/None."""

from __future__ import annotations


def test_sentry_init_skips_when_dsn_none() -> None:
    from app.config import init_sentry

    init_sentry(None, "dev")  # should not raise


def test_sentry_init_skips_when_dsn_empty_string() -> None:
    from app.config import init_sentry

    init_sentry("", "dev")  # should not raise
