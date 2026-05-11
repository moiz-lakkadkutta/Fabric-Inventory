"""TASK-CUT-501a: per-IP rate limit on /auth/forgot.

CUT-303 retro follow-up #1: the forgot endpoint accepts unauthenticated
requests, so without a throttle a single IP can mint reset rows + spam
the email adapter at line rate. This test fixes the policy: 5 reqs in
60s per IP; 6th returns 429 with a ``Retry-After`` header.

We test the rate-limit dependency in isolation against a synthetic
``/auth/forgot`` route so the suite doesn't depend on Postgres being
reachable (the limiter runs as a FastAPI dependency BEFORE the body
handler executes against the DB; the prod wiring in
``app/routers/auth.py`` applies the same dep to the same path). The
DB-bound integration coverage already lives in
``test_password_reset.py``.

Uses fakeredis so the suite runs without a Redis service container.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import fakeredis.aioredis
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.cors import CORSMiddleware

from app.config import reset_settings
from app.middleware import (
    AuthMiddleware,
    IdempotencyMiddleware,
    LoggingMiddleware,
    RequestContextMiddleware,
    RLSMiddleware,
    rate_limit,
    register_error_handlers,
    set_redis_client_for_testing,
)


@pytest.fixture(autouse=True)
def _enable_redis_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The rate-limit helper short-circuits to a no-op when
    ``REDIS_URL`` is unset (dev fallback). Force it on so the
    middleware path runs even on a developer's laptop without
    docker-compose up.

    Reset the settings cache on BOTH sides so a later test in the
    same suite session doesn't inherit our fake URL (the global
    ``IdempotencyMiddleware`` lazily resolves it from settings and
    would then try to dial ``fake-for-tests:6379``)."""
    monkeypatch.setenv("REDIS_URL", "redis://fake-for-tests")
    reset_settings()
    try:
        yield
    finally:
        monkeypatch.undo()
        reset_settings()


@pytest.fixture
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def http(fake_redis: fakeredis.aioredis.FakeRedis) -> AsyncIterator[AsyncClient]:
    """Build a tiny app with the full middleware chain + the same
    rate-limit dep that ``app/routers/auth.py`` applies on
    ``POST /auth/forgot``. Swap the dep's redis client for fakeredis
    so the suite needs neither Postgres nor real Redis.
    """
    set_redis_client_for_testing(fake_redis)
    reset_settings()

    # Mirror the production policy exactly: 5 reqs / 60s / per-IP.
    forgot_dep = rate_limit(bucket="auth.forgot", max_requests=5, window_seconds=60)

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(RLSMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/auth/forgot", dependencies=[Depends(forgot_dep)])
    async def _forgot() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        set_redis_client_for_testing(None)


# ──────────────────────────────────────────────────────────────────────
# Behavior: 5 hits succeed, 6th is throttled
# ──────────────────────────────────────────────────────────────────────


async def test_sixth_request_within_window_returns_429(http: AsyncClient) -> None:
    """First 5 forgot requests from the same IP succeed (200, regardless
    of whether the email matches — no-enumeration shape preserved);
    the 6th inside the 60s window returns 429 + Retry-After."""
    payload = {"email": "stranger@example.com", "org_name": "no-such-org"}

    for i in range(5):
        resp = await http.post("/auth/forgot", json=payload)
        assert resp.status_code == 200, f"request {i + 1}: {resp.text}"
        assert resp.json() == {"ok": True}

    sixth = await http.post("/auth/forgot", json=payload)
    assert sixth.status_code == 429, sixth.text
    body = sixth.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["status"] == 429
    assert "Retry-After" in sixth.headers
    # Retry-After is whole seconds; with a 60s window and ~5 instant
    # hits, the wait must be in (0, 60].
    retry_after = int(sixth.headers["Retry-After"])
    assert 1 <= retry_after <= 60


async def test_different_ips_do_not_share_budget(http: AsyncClient) -> None:
    """An attacker IP burning through their 5/min budget must not
    starve a legitimate user on a different IP. The limiter keys by
    client IP — proven here by sending the 6th request with a
    different ``X-Forwarded-For`` left-most entry."""
    payload = {"email": "stranger@example.com", "org_name": "no-such-org"}

    # Burn through IP A's 5 hits.
    for i in range(5):
        resp = await http.post(
            "/auth/forgot",
            json=payload,
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert resp.status_code == 200, f"A request {i + 1}: {resp.text}"

    # IP A's 6th is throttled.
    blocked = await http.post("/auth/forgot", json=payload, headers={"X-Forwarded-For": "10.0.0.1"})
    assert blocked.status_code == 429

    # IP B is untouched.
    allowed = await http.post("/auth/forgot", json=payload, headers={"X-Forwarded-For": "10.0.0.2"})
    assert allowed.status_code == 200, allowed.text


async def test_envelope_carries_request_id_and_retry_after(
    http: AsyncClient,
) -> None:
    """The 429 path must still return the standard envelope (so the FE
    handles it through the same error pipeline) AND must surface the
    Retry-After header to the caller (so polite clients back off)."""
    payload = {"email": "stranger@example.com", "org_name": "no-such-org"}

    for _ in range(5):
        await http.post("/auth/forgot", json=payload)

    throttled = await http.post("/auth/forgot", json=payload)
    assert throttled.status_code == 429
    body = throttled.json()
    # Envelope shape — same as every other AppError-mapped response.
    assert set(body.keys()) >= {
        "code",
        "title",
        "detail",
        "status",
        "field_errors",
        "request_id",
    }
    assert body["title"] == "Too many requests"
    assert int(throttled.headers["Retry-After"]) >= 1
