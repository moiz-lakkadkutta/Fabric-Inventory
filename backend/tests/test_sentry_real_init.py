"""TASK-066: init_sentry calls sentry_sdk.init with correct kwargs when DSN is set."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_sentry_real_init_calls_sdk() -> None:
    """init_sentry with a non-empty DSN must call sentry_sdk.init."""
    fake_dsn = "https://fake@sentry.example.com/1"

    with patch("sentry_sdk.init") as mock_init:
        from app.config import init_sentry

        init_sentry(fake_dsn, "prod")

    mock_init.assert_called_once()
    call_kwargs = mock_init.call_args.kwargs
    assert call_kwargs["dsn"] == fake_dsn
    assert call_kwargs["environment"] == "prod"
    assert call_kwargs["traces_sample_rate"] == 0.1
    assert call_kwargs["send_default_pii"] is False


def test_sentry_real_init_includes_fastapi_integration() -> None:
    """init_sentry must wire up FastApiIntegration so routes are captured."""
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    fake_dsn = "https://fake@sentry.example.com/1"
    captured: list[MagicMock] = []

    def capture_init(**kwargs: object) -> None:
        integrations = kwargs.get("integrations", [])
        captured.extend(integrations)  # type: ignore[arg-type]

    with patch("sentry_sdk.init", side_effect=capture_init):
        from app.config import init_sentry

        init_sentry(fake_dsn, "staging")

    assert any(isinstance(i, FastApiIntegration) for i in captured), (
        "FastApiIntegration must be in the integrations list"
    )


def test_sentry_real_init_no_op_for_none() -> None:
    """init_sentry must not call sentry_sdk.init when DSN is None (regression guard)."""
    with patch("sentry_sdk.init") as mock_init:
        from app.config import init_sentry

        init_sentry(None, "prod")

    mock_init.assert_not_called()


def test_sentry_real_init_no_op_for_empty_string() -> None:
    """init_sentry must not call sentry_sdk.init when DSN is empty (regression guard)."""
    with patch("sentry_sdk.init") as mock_init:
        from app.config import init_sentry

        init_sentry("", "prod")

    mock_init.assert_not_called()
