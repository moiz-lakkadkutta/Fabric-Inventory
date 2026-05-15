"""Startup fail-fast for the WeasyPrint native-library dependency.

Bug B7 (E2E QA 2026-05-12): when uvicorn was launched without
``DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`` on macOS, WeasyPrint
couldn't ``dlopen()`` ``libgobject-2.0-0`` and every call to
``GET /v1/invoices/{id}/pdf`` 500'd at request time. The user only
found out by clicking Print.

The fix is a tiny 1-byte WeasyPrint render at app boot. If the dlopen
chain is broken, the lifespan re-raises a ``RuntimeError`` whose
message names ``DYLD_FALLBACK_LIBRARY_PATH`` and ``WeasyPrint`` so the
operator sees the right knob to twist — instead of a silent 500
per-request hours later.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_startup_fails_fast_when_weasyprint_broken() -> None:
    """If WeasyPrint can't dlopen its native deps, the app must NOT start.

    We patch ``weasyprint.HTML.write_pdf`` to raise the OSError WeasyPrint
    itself raises when ``libgobject`` is missing. Then we drive the
    lifespan via ``TestClient.__enter__`` (Starlette runs the lifespan
    on context entry, raising any startup error to the caller).

    The error must:
    - propagate as a RuntimeError (operators see a clear stacktrace,
      not a per-request 500 hours later)
    - mention ``DYLD_FALLBACK_LIBRARY_PATH`` so the macOS dev knows the
      exact env var to set
    - mention ``WeasyPrint`` so the linux deployer searches for the
      right keyword in docs
    """
    from main import create_app

    with patch(
        "weasyprint.HTML.write_pdf",
        side_effect=OSError("cannot load library 'gobject-2.0-0': dlopen failed"),
    ):
        app = create_app()
        with pytest.raises(RuntimeError) as exc_info, TestClient(app):
            pass  # pragma: no cover — lifespan should raise before yield

    msg = str(exc_info.value)
    assert "DYLD_FALLBACK_LIBRARY_PATH" in msg, (
        f"Startup error must name the env var DYLD_FALLBACK_LIBRARY_PATH; got: {msg!r}"
    )
    assert "WeasyPrint" in msg, (
        f"Startup error must name WeasyPrint so operators search the right docs; got: {msg!r}"
    )


def test_app_starts_normally_when_weasyprint_works() -> None:
    """Regression guard for slice 4b.

    With a working WeasyPrint dlopen chain (real libs on the host, or a
    patched-to-succeed ``write_pdf``), the lifespan must complete cleanly
    and the app must serve ``/live``. If the probe over-catches and
    swallows unrelated exceptions, or if it short-circuits the rest of
    the lifespan, this test will fail.
    """
    from main import create_app

    # Patch with a stub that returns a tiny valid PDF byte string so the
    # test does not require the actual native libs to be installed on the
    # test host. If the probe is correctly scoped, the lifespan returns
    # normally and ``/live`` is reachable.
    with patch("weasyprint.HTML.write_pdf", return_value=b"%PDF-1.4\n%%EOF\n"):
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/live")
            assert resp.status_code == 200
            assert resp.json() == {"status": "live"}


# ──────────────────────────────────────────────────────────────────────
# M5 — fail-fast for PII_MASTER_KEY at boot
# ──────────────────────────────────────────────────────────────────────
#
# `config.py` accepts an unset `pii_master_key` but `main.py` never
# eagerly calls `get_master_kek`. With B3's stricter check, a deploy
# that forgets the env var boots healthy and only fails when the first
# user signs up. Pulling the resolve into the lifespan means a
# misconfigured prod box never accepts traffic — the container crashes
# at boot with a clear error.


def test_app_startup_fails_when_kek_missing_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In a non-dev/test environment without `PII_MASTER_KEY`, the
    lifespan must raise `PIIConfigError` (subclass of `RuntimeError`)
    BEFORE serving any request. Container restarts on crash; the
    operator sees the failure in 1 boot, not 6 hours later.
    """
    from app.utils import crypto
    from main import create_app

    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    crypto._reset_caches_for_tests()

    # Keep WeasyPrint happy so its probe doesn't mask the KEK failure.
    with patch("weasyprint.HTML.write_pdf", return_value=b"%PDF-1.4\n%%EOF\n"):
        app = create_app()
        with pytest.raises(crypto.PIIConfigError) as exc_info, TestClient(app):
            pass  # pragma: no cover — lifespan should raise before yield

    msg = str(exc_info.value)
    assert "PII_MASTER_KEY" in msg, (
        f"Startup error must name PII_MASTER_KEY so operators know which env "
        f"var to set; got: {msg!r}"
    )


def test_app_startup_fails_when_kek_missing_in_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Staging is treated identically — anything outside the {dev, test}
    allowlist must refuse to boot without a real KEK."""
    from app.utils import crypto
    from main import create_app

    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    crypto._reset_caches_for_tests()

    with patch("weasyprint.HTML.write_pdf", return_value=b"%PDF-1.4\n%%EOF\n"):
        app = create_app()
        with pytest.raises(crypto.PIIConfigError), TestClient(app):
            pass  # pragma: no cover


def test_app_startup_succeeds_in_dev_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ENVIRONMENT=dev with no KEK → the lifespan resolves the public
    dev fallback and the app boots. The fallback fires a WARNING log
    (B3 behaviour) — but boot still succeeds, otherwise the dev loop
    would be impossible.
    """
    from app.utils import crypto
    from main import create_app

    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    crypto._reset_caches_for_tests()

    with patch("weasyprint.HTML.write_pdf", return_value=b"%PDF-1.4\n%%EOF\n"):
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/live")
            assert resp.status_code == 200
            assert resp.json() == {"status": "live"}
