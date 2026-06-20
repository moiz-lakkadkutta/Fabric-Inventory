"""Tests for idempotency DOS-07 fix: 2xx-only full caching.

After the fix:
  - 2xx responses are cached in full and replayed (existing behaviour kept).
  - 4xx responses (except 401/403) are NOT replayed — only a tiny marker
    (payload_hash + status, no body) is stored so PAYLOAD_MISMATCH still
    fires for same-key/different-body retries.
  - 5xx responses and 401/403 are not cached at all (existing behaviour).

Uses fakeredis to avoid requiring a live Redis instance.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

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
async def idem_client(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncIterator[AsyncClient]:
    """Minimal app with:
      - /maybe-422: returns 422 on first call, 200 on subsequent calls.
      - /always-200: always returns 200 with a call counter.
    IdempotencyMiddleware redis client is patched onto the fake instance.
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

    counter: dict[str, int] = {"n": 0}

    @app.post("/maybe-422")
    async def _maybe_422() -> JSONResponse:
        counter["n"] += 1
        if counter["n"] == 1:
            return JSONResponse(status_code=422, content={"detail": "Validation error"})
        return JSONResponse(status_code=200, content={"ok": True, "call": counter["n"]})

    @app.post("/always-200")
    async def _always_200() -> JSONResponse:
        counter["n"] += 1
        return JSONResponse(status_code=200, content={"count": counter["n"]})

    # Build middleware stack and inject fakeredis.
    app.middleware_stack = app.build_middleware_stack()
    node: object | None = app.middleware_stack
    while node is not None:
        if isinstance(node, IdempotencyMiddleware):
            node._redis_client = fake_redis
            node._redis_url = "redis://fake"
            break
        node = getattr(node, "app", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── DOS-07: 4xx must NOT be replayed ──


async def test_4xx_response_not_replayed_handler_reruns(
    fake_redis: fakeredis.aioredis.FakeRedis,
    idem_client: AsyncClient,
) -> None:
    """After a 422 first call, same key+body must re-execute the handler.

    Pre-fix: the cached 422 would be replayed and the handler would never
    run again — permanently locking the idempotency key on failure.
    Post-fix: only a marker is stored; the retry re-executes and can succeed.
    """
    key = str(uuid.uuid4())
    payload = {"order": "first"}

    first = await idem_client.post("/maybe-422", json=payload, headers={"Idempotency-Key": key})
    assert first.status_code == 422, "First call should return 422"

    # Retry with same key+body: must re-execute (not replay 422).
    second = await idem_client.post("/maybe-422", json=payload, headers={"Idempotency-Key": key})
    assert second.status_code == 200, (
        f"4xx must not be replayed; handler should re-execute and return 200, "
        f"got {second.status_code}: {second.text}"
    )


async def test_2xx_still_cached_handler_not_rerun(
    fake_redis: fakeredis.aioredis.FakeRedis,
    idem_client: AsyncClient,
) -> None:
    """2xx responses must still be cached and replayed — existing behaviour preserved."""
    key = str(uuid.uuid4())
    payload = {"x": 1}

    first = await idem_client.post("/always-200", json=payload, headers={"Idempotency-Key": key})
    assert first.status_code == 200
    first_count = first.json()["count"]

    # Same key + same body → cached replay; counter must NOT increment.
    second = await idem_client.post("/always-200", json=payload, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["count"] == first_count, (
        "Handler must not re-execute for a 2xx cached replay — counter should not change."
    )


async def test_4xx_same_key_different_body_returns_409(
    fake_redis: fakeredis.aioredis.FakeRedis,
    idem_client: AsyncClient,
) -> None:
    """After a 4xx, reusing the same key with a DIFFERENT body → 409 PAYLOAD_MISMATCH.

    Even though the body is not cached, the marker must store the payload_hash
    so conflicting replays can be detected.
    """
    key = str(uuid.uuid4())

    first = await idem_client.post("/maybe-422", json={"x": 1}, headers={"Idempotency-Key": key})
    assert first.status_code == 422

    # Different body + same key → must be a conflict.
    second = await idem_client.post(
        "/maybe-422", json={"x": 9999}, headers={"Idempotency-Key": key}
    )
    assert second.status_code == 409, (
        f"Same key + different body after 4xx must return 409; got {second.status_code}"
    )
    assert second.json()["code"] == "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"
