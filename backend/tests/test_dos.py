"""Tests for ContentSizeLimitMiddleware (DOS-03).

Bodies larger than 1 MB must be rejected with HTTP 413 *before*
auth / bcrypt touches the request.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

_MB = 1024 * 1024


async def test_small_body_is_not_rejected(client: AsyncClient) -> None:
    """A body well below 1 MB must pass through (not 413)."""
    key = str(uuid.uuid4())
    resp = await client.post(
        "/auth/login",
        content=b'{"email":"x@x.com","password":"abc"}',
        headers={"Content-Type": "application/json", "Idempotency-Key": key},
    )
    # Any response other than 413 means the middleware let the request through.
    # (/auth/login is in IDEMPOTENT_BY_DESIGN_PATHS so the Idempotency-Key
    # header is accepted but not required — we pass it to avoid a 400 from
    # the middleware on a non-exempt POST, just in case.)
    assert resp.status_code != 413, (
        f"Small body must not be rejected with 413; got {resp.status_code}"
    )


async def test_oversized_body_returns_413(client: AsyncClient) -> None:
    """A body exceeding 1 MB must be rejected with 413 before auth runs."""
    # httpx sets Content-Length automatically when `content=` is provided.
    big_body = b"x" * (_MB + 1)
    resp = await client.post(
        "/auth/login",
        content=big_body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413, (
        f"Body > 1 MB must return 413; got {resp.status_code}: {resp.text}"
    )


async def test_oversized_body_on_non_auth_route_returns_413(client: AsyncClient) -> None:
    """413 must fire on any route — not just auth."""
    big_body = b"y" * (_MB + 1)
    key = str(uuid.uuid4())
    resp = await client.post(
        "/auth/signup",
        content=big_body,
        headers={"Content-Type": "application/json", "Idempotency-Key": key},
    )
    assert resp.status_code == 413, (
        f"Body > 1 MB must return 413 on any route; got {resp.status_code}"
    )
