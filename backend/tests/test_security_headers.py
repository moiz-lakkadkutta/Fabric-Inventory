"""Tests for SecurityHeadersMiddleware (API-7-01 / FE-01/FE-02 backend half).

Verifies that:
  - Every response carries the required security headers.
  - /auth/* responses additionally carry Cache-Control: no-store.
  - /docs, /redoc, /openapi.json are unavailable when ENVIRONMENT != 'dev'.
"""

from __future__ import annotations

import base64
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

# ── Required security headers on every response ──


async def test_x_content_type_options_nosniff(client: AsyncClient) -> None:
    resp = await client.get("/live")
    assert resp.headers.get("x-content-type-options") == "nosniff", (
        "X-Content-Type-Options: nosniff missing from response"
    )


async def test_x_frame_options_deny(client: AsyncClient) -> None:
    resp = await client.get("/live")
    assert resp.headers.get("x-frame-options") == "DENY", (
        "X-Frame-Options: DENY missing from response"
    )


async def test_referrer_policy_no_referrer(client: AsyncClient) -> None:
    resp = await client.get("/live")
    assert resp.headers.get("referrer-policy") == "no-referrer", (
        "Referrer-Policy: no-referrer missing from response"
    )


async def test_csp_contains_frame_ancestors_none(client: AsyncClient) -> None:
    resp = await client.get("/live")
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp, f"CSP must contain frame-ancestors 'none'; got: {csp!r}"


async def test_permissions_policy_header_present(client: AsyncClient) -> None:
    resp = await client.get("/live")
    assert "permissions-policy" in resp.headers, "Permissions-Policy header missing from response"


# ── Cache-Control: no-store on /auth/* ──


async def test_auth_path_has_cache_control_no_store(client: AsyncClient) -> None:
    """/auth/login (even if it 422s) must carry Cache-Control: no-store."""
    # /auth/login is in IDEMPOTENT_BY_DESIGN_PATHS — no idempotency key needed.
    resp = await client.post("/auth/login", json={})
    cc = resp.headers.get("cache-control", "")
    assert "no-store" in cc, f"Cache-Control: no-store missing on /auth/* response; got: {cc!r}"


async def test_non_auth_path_no_forced_cache_control_no_store(client: AsyncClient) -> None:
    """/live should NOT have a forced Cache-Control: no-store."""
    resp = await client.get("/live")
    cc = resp.headers.get("cache-control", "")
    assert "no-store" not in cc, f"/live must not carry Cache-Control: no-store; got: {cc!r}"


# ── /docs disabled outside dev ──


def test_docs_disabled_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAPI UI endpoints must return 404 when ENVIRONMENT != 'dev'."""
    from app.config import reset_settings
    from app.utils import crypto as _crypto

    # A 32-byte key base64-encoded — meets the KEK requirement for prod.
    valid_kek = base64.b64encode(bytes(range(32))).decode()

    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("PII_MASTER_KEY", valid_kek)
    reset_settings()
    _crypto._reset_caches_for_tests()

    try:
        with patch("weasyprint.HTML.write_pdf", return_value=b"%PDF-1.4\n%%EOF\n"):
            from main import create_app

            app = create_app()
            with TestClient(app) as http:
                assert http.get("/docs").status_code == 404, "/docs must be 404 in prod"
                assert http.get("/redoc").status_code == 404, "/redoc must be 404 in prod"
                assert http.get("/openapi.json").status_code == 404, (
                    "/openapi.json must be 404 in prod"
                )
    finally:
        reset_settings()
        _crypto._reset_caches_for_tests()
