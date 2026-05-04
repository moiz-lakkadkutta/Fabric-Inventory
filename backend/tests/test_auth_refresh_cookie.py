"""Refresh-cookie path (T-INT-1, Q2 hybrid token storage).

Login / signup / mfa-verify set the refresh token in an httpOnly Secure
SameSite=Lax cookie scoped to /auth. Refresh reads from the cookie OR
falls back to the request body. Logout clears the cookie.
"""

from __future__ import annotations

import uuid

from tests.conftest import IdempotentTestClient


def _signup(client: IdempotentTestClient) -> dict[str, str]:
    body: dict[str, str] = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org {uuid.uuid4().hex[:8]}",
            "firm_name": "Primary Firm",
            "state_code": "MH",
        },
    ).json()
    return body


def test_signup_sets_refresh_cookie(http_client: IdempotentTestClient) -> None:
    """Cookie attributes per Q2: HttpOnly, SameSite=Lax, scoped to /auth.

    Signup, login, and mfa-verify all share the same `_set_refresh_cookie`
    helper, so this test covers the cookie shape for all three paths.
    """
    resp = http_client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org {uuid.uuid4().hex[:8]}",
            "firm_name": "Primary Firm",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201

    set_cookie = resp.headers.get("set-cookie", "")
    assert "fabric_refresh=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "Path=/auth" in set_cookie


def test_refresh_with_cookie_only_succeeds(http_client: IdempotentTestClient) -> None:
    """Frontend sends the cookie automatically; body.refresh_token may be omitted."""
    _signup(http_client)
    # Cookie is in http_client.cookies after signup.
    assert http_client.cookies.get("fabric_refresh")

    resp = http_client.post("/auth/refresh", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]


def test_refresh_with_body_only_still_works(http_client: IdempotentTestClient) -> None:
    """Legacy CLI / tests can still send the token in the body."""
    body = _signup(http_client)
    # Drop the cookie so we test the body fallback in isolation.
    http_client.cookies.clear()

    resp = http_client.post(
        "/auth/refresh",
        json={"refresh_token": body["refresh_token"]},
    )
    assert resp.status_code == 200, resp.text


def test_refresh_without_cookie_or_body_returns_401(
    http_client: IdempotentTestClient,
) -> None:
    """No cookie + empty body → uniform 401 (TOKEN_INVALID), no information leak."""
    resp = http_client.post("/auth/refresh", json={})
    assert resp.status_code == 401
    assert resp.json()["code"] == "TOKEN_INVALID"


def test_logout_clears_refresh_cookie(http_client: IdempotentTestClient) -> None:
    body = _signup(http_client)

    resp = http_client.post(
        "/auth/logout",
        json={"refresh_token": body["refresh_token"]},
    )
    assert resp.status_code == 200

    # The Set-Cookie on logout is the deletion form: empty value + expiry
    # in the past (httpx sees this and removes the cookie).
    set_cookie = resp.headers.get("set-cookie", "")
    assert "fabric_refresh=" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()
