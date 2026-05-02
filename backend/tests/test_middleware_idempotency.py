"""Idempotency middleware (Q7) — strict-presence + Redis-backed dedup.

Behaviors gated here (per ``docs/plans/integration-plan.md`` § T-INT-1):
  - #9  Mutation without ``Idempotency-Key`` → 400 ``IDEMPOTENCY_KEY_REQUIRED``.
  - #10 Duplicate key with same body → cached response replayed.
  - #11 Duplicate key with different body → 409 ``IDEMPOTENCY_KEY_PAYLOAD_MISMATCH``.

Uses ``fakeredis`` so the test doesn't require a live Redis. Real Redis
runs in CI as a workflow service for higher-fidelity coverage there
(adding when the CI workflow grows a Redis service container).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.cors import CORSMiddleware

from app.config import reset_settings
from app.middleware import (
    AuthMiddleware,
    IdempotencyMiddleware,
    LoggingMiddleware,
    RLSMiddleware,
    register_error_handlers,
)


@pytest.fixture
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """In-memory async Redis replacement scoped to one test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def client(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncIterator[AsyncClient]:
    """Build a minimal app with the full middleware chain + a synthetic
    `POST /echo` route that echoes its JSON body. Idempotency middleware's
    redis client is monkey-patched onto the fake instance.
    """
    reset_settings()

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(RLSMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/echo")
    async def _echo(payload: dict[str, object]) -> dict[str, object]:
        return {"received": payload}

    @app.get("/echo")
    async def _echo_get() -> dict[str, str]:
        return {"hello": "world"}

    # Build the middleware stack so the IdempotencyMiddleware instance
    # exists, then walk the chain and inject the fakeredis client.
    app.middleware_stack = app.build_middleware_stack()

    node: object | None = app.middleware_stack
    while node is not None:
        if isinstance(node, IdempotencyMiddleware):
            node._redis_client = fake_redis
            node._redis_url = "redis://fake"  # any non-None unlocks dedup
            break
        node = getattr(node, "app", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ──────────────────────────────────────────────────────────────────────
# Behavior #9 — strict 400 on missing / malformed key
# ──────────────────────────────────────────────────────────────────────


async def test_post_without_idempotency_key_returns_400(client: AsyncClient) -> None:
    resp = await client.post("/echo", json={"x": 1})
    assert resp.status_code == 400

    body = resp.json()
    assert body["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert body["status"] == 400
    assert body["title"] == "Missing Idempotency-Key header"
    assert body["field_errors"] == {}


async def test_post_with_malformed_key_returns_400(client: AsyncClient) -> None:
    resp = await client.post("/echo", json={"x": 1}, headers={"Idempotency-Key": "not-a-uuid"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_get_does_not_require_idempotency_key(client: AsyncClient) -> None:
    """GET / HEAD / OPTIONS bypass idempotency — they don't mutate state."""
    resp = await client.get("/echo")
    assert resp.status_code == 200
    assert resp.json() == {"hello": "world"}


# ──────────────────────────────────────────────────────────────────────
# Behavior #10 — duplicate key + same body → cached replay
# ──────────────────────────────────────────────────────────────────────


async def test_duplicate_key_replays_cached_response(client: AsyncClient) -> None:
    key = str(uuid.uuid4())
    payload = {"customer": "Rajesh", "amount": 1000}

    first = await client.post("/echo", json=payload, headers={"Idempotency-Key": key})
    assert first.status_code == 200
    assert first.json() == {"received": payload}

    second = await client.post("/echo", json=payload, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json() == first.json()


# ──────────────────────────────────────────────────────────────────────
# Behavior #11 — duplicate key + different body → 409
# ──────────────────────────────────────────────────────────────────────


async def test_same_key_different_body_returns_409(client: AsyncClient) -> None:
    key = str(uuid.uuid4())
    first = await client.post("/echo", json={"amount": 1000}, headers={"Idempotency-Key": key})
    assert first.status_code == 200

    second = await client.post("/echo", json={"amount": 9999}, headers={"Idempotency-Key": key})
    assert second.status_code == 409

    body = second.json()
    assert body["code"] == "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"
    assert body["status"] == 409


async def test_different_keys_for_same_body_both_execute(client: AsyncClient) -> None:
    """Different intents (different keys) shouldn't dedup, even with identical bodies."""
    payload = {"x": 1}

    first = await client.post("/echo", json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    second = await client.post(
        "/echo", json=payload, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert first.status_code == 200
    assert second.status_code == 200
