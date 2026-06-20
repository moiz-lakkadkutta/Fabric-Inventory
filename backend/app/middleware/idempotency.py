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

# Mutating endpoints that are intrinsically idempotent at the protocol
# level (replays produce equivalent results because the underlying
# resource rotates on each call). Exempt from the Idempotency-Key
# requirement so the FE silent-refresh-on-401 path doesn't have to
# generate a UUID per attempt.
#
# /auth/login and /auth/signup are also exempt: their security contract
# requires a freshly-rotated token pair on every call. Caching the 200/201
# response and replaying it for 24 h would re-issue the original tokens
# (and the original Set-Cookie header) for any caller with the same
# Idempotency-Key — see `docs/ops/platform-audit-2026-05-10.md` P0-4.
IDEMPOTENT_BY_DESIGN_PATHS = frozenset(
    {
        "/auth/login",
        "/auth/refresh",
        "/auth/signup",
        # CUT-303: forgot/reset are auth-by-design (no JWT) and must
        # not be gated on Idempotency-Key — the FE forms generate one
        # request per user click; cache-replay would either re-issue a
        # stale link to the wrong user or silently swallow a legitimate
        # retry from a different session.
        "/auth/forgot",
        "/auth/reset",
        # CUT-304: invite acceptance is public (no JWT yet) AND single-use
        # by construction — the invite token IS the idempotency key
        # (sha256-hashed in DB, `used_at` stamped atomically on accept).
        # Requiring a UUID Idempotency-Key from a not-yet-authenticated
        # user is friction for zero security benefit.
        "/admin/invites/accept",
    }
)

# Response headers that MUST NOT be persisted in the idempotency cache.
# `set-cookie` is the audit's exact attack vector — the refresh-token
# cookie was being cached verbatim and replayed across callers.
# `authorization` covers the future case of a router echoing a Bearer
# token back in the response. Lower-cased here because we filter on the
# lowercased header key.
_SENSITIVE_RESPONSE_HEADERS = frozenset({"set-cookie", "authorization"})


def _strip_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
    """Drop response headers that may carry credentials before caching.

    Case-insensitive: `dict(starlette_response.headers)` collapses
    multi-value headers (rare but possible for `Set-Cookie`) into a
    single entry, but we filter on the lowercased key so handlers that
    emit `Set-Cookie` / `set-cookie` / `SET-COOKIE` are all covered.
    """
    return {k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_RESPONSE_HEADERS}


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
        if request.url.path in IDEMPOTENT_BY_DESIGN_PATHS:
            # Auth endpoints rotate tokens on every call; replaying a
            # cached response would re-issue stale credentials.
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
                if payload.get("is_marker"):
                    # A non-2xx response was previously returned for this key.
                    # Markers are not replayed — the handler must re-execute so
                    # a transient 4xx (e.g. 422 from bad input) does not
                    # permanently lock the idempotency key. Fall through to
                    # call_next below. (DOS-07 fix)
                    pass
                else:
                    # Full 2xx entry — replay body verbatim.
                    return Response(
                        content=payload["body"].encode(),
                        status_code=payload["status"],
                        headers=payload["headers"],
                        media_type=payload.get("media_type"),
                    )

        response = await call_next(request)

        # DOS-07 fix: cache ONLY 2xx responses with their full body.
        # For non-2xx (except 401/403 which are auth-transient and 5xx which
        # are infra-transient), store a compact marker containing only the
        # payload hash and status so PAYLOAD_MISMATCH detection keeps working
        # on subsequent retries while preventing the 4xx body from being
        # replayed and permanently locking the idempotency key on failure.
        if redis_client is not None:
            if 200 <= response.status_code < 300:
                # Full cache — body, headers, media type.
                response_body = b""
                # Starlette's BaseHTTPMiddleware delivers responses as
                # _StreamingResponse instances, which expose `body_iterator`,
                # but mypy sees the abstract Response type.
                async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                    response_body += chunk

                # Strip credential-carrying headers BEFORE persisting so a
                # replay (or `redis-cli get idem:...`) cannot leak them. The
                # response that goes back to the FIRST caller still carries
                # them — only the cached copy is sanitized.
                cached_headers = _strip_sensitive_headers(dict(response.headers))

                await redis_client.setex(
                    cache_key,
                    CACHE_TTL_SECONDS,
                    json.dumps(
                        {
                            "payload_hash": payload_hash,
                            "status": response.status_code,
                            "headers": cached_headers,
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

            elif response.status_code < 500 and response.status_code not in {401, 403}:
                # Compact marker — hash + status only, NO body.
                # The next retry with the same key+body will re-execute the
                # handler; the next retry with the same key+different body
                # will hit the PAYLOAD_MISMATCH branch above.
                await redis_client.setex(
                    cache_key,
                    CACHE_TTL_SECONDS,
                    json.dumps(
                        {
                            "payload_hash": payload_hash,
                            "status": response.status_code,
                            "is_marker": True,
                        }
                    ),
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
