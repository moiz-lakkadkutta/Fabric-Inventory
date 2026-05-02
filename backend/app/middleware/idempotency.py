"""Idempotency middleware (Q7).

Per the integration plan (Q7b): mutating endpoints (POST/PATCH/DELETE/PUT)
require an `Idempotency-Key` header. Missing or malformed → 400
``IDEMPOTENCY_KEY_REQUIRED``. Duplicate key with the same request body →
the cached response (matching status + body) is replayed. Duplicate key
with a different body → 409 ``IDEMPOTENCY_KEY_PAYLOAD_MISMATCH``.

Cache lives in Redis with a 24-hour TTL. When ``REDIS_URL`` is not
configured, the middleware enforces presence-of-key only and skips the
cache (local dev without Redis still works; CI runs Redis as a service).

Errors here are returned directly because middleware sits upstream of the
global exception handler — raising would bypass the Q8a envelope.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import redis.asyncio as aioredis
import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from ..config import get_settings
from ..exceptions import (
    AppError,
    IdempotencyConflictError,
    IdempotencyKeyRequiredError,
)

logger = structlog.get_logger()

MUTATING_METHODS = {"POST", "PATCH", "DELETE", "PUT"}
CACHE_TTL_SECONDS = 24 * 60 * 60


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Strict-presence + Redis-backed dedup for mutating requests."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._redis_client: aioredis.Redis | None = None
        self._redis_url = get_settings().redis_url

    async def _redis(self) -> aioredis.Redis | None:
        if self._redis_url is None:
            return None
        if self._redis_client is None:
            self._redis_client = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis_client

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in MUTATING_METHODS:
            return await call_next(request)

        key = request.headers.get("Idempotency-Key")
        if not key:
            return _envelope(
                IdempotencyKeyRequiredError(
                    "Mutating endpoints require an Idempotency-Key header (UUID v4)."
                )
            )
        try:
            uuid.UUID(key)
        except ValueError:
            return _envelope(IdempotencyKeyRequiredError("Idempotency-Key must be a valid UUID."))

        # Read body once; we hash it for mismatch detection AND must put it
        # back so the downstream handler can read it.
        body_bytes = await request.body()
        _restore_request_body(request, body_bytes)

        payload_hash = hashlib.sha256(body_bytes).hexdigest()
        cache_key = f"idem:{request.url.path}:{key}"

        redis_client = await self._redis()
        if redis_client is not None:
            cached = await redis_client.get(cache_key)
            if cached is not None:
                payload = json.loads(cached)
                if payload["payload_hash"] != payload_hash:
                    return _envelope(
                        IdempotencyConflictError(
                            "Idempotency-Key was reused with a different request body."
                        )
                    )
                return Response(
                    content=payload["body"].encode(),
                    status_code=payload["status"],
                    headers=payload["headers"],
                    media_type=payload.get("media_type"),
                )

        response = await call_next(request)

        # Cache deterministic outcomes only. 4xx like 422 (validation) and
        # 409 (conflict) are intent-deterministic — same payload, same
        # outcome, replay is correct. 401/403 are TRANSIENT auth state — a
        # token refresh + retry must hit the handler again, not the cache.
        # 5xx is also skipped (transient infra). See T-INT-1 hard review
        # CRIT-1 for the failure mode this protects against.
        cacheable = response.status_code < 500 and response.status_code not in {401, 403}
        if redis_client is not None and cacheable:
            response_body = b""
            # Starlette's BaseHTTPMiddleware delivers responses as
            # _StreamingResponse instances, which expose `body_iterator`,
            # but mypy sees the abstract Response type.
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                response_body += chunk

            await redis_client.setex(
                cache_key,
                CACHE_TTL_SECONDS,
                json.dumps(
                    {
                        "payload_hash": payload_hash,
                        "status": response.status_code,
                        "headers": dict(response.headers),
                        "body": response_body.decode(errors="replace"),
                        "media_type": response.media_type,
                    }
                ),
            )

            # body_iterator is consumed; rebuild a fresh response.
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response


def _restore_request_body(request: Request, body: bytes) -> None:
    """Re-attach a consumed request body so the downstream handler can read it."""

    async def _receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    # Documented Starlette pattern for body re-reading after consumption.
    request._receive = _receive


def _envelope(exc: AppError) -> JSONResponse:
    """Render an AppError as the Q8a envelope without going through the handler."""
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "code": str(exc.code),
            "title": exc.title,
            "detail": exc.message,
            "status": exc.http_status,
            "field_errors": exc.field_errors,
        },
    )
