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

import asyncio
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
    IdempotencyInProgressError,
    IdempotencyKeyRequiredError,
    TokenInvalidError,
)
from ..service.identity_service import verify_jwt
from .rate_limit import _get_redis as _get_denylist_redis
from .rate_limit import _is_test_redis_injected as is_test_redis_injected

logger = structlog.get_logger()

MUTATING_METHODS = {"POST", "PATCH", "DELETE", "PUT"}
CACHE_TTL_SECONDS = 24 * 60 * 60

# Q01-01 in-flight reservation. The lock is SET NX with this TTL and a
# heartbeat re-extends it every INFLIGHT_HEARTBEAT_SECONDS while the handler
# runs, so (a) a slow request (e.g. a large Vyapar import) is never
# overtaken by its own retry, and (b) a crashed / killed worker stops
# beating and the key frees itself within INFLIGHT_TTL_SECONDS.
INFLIGHT_TTL_SECONDS = 30
INFLIGHT_HEARTBEAT_SECONDS = 10
IN_PROGRESS_RETRY_AFTER_SECONDS = 1

# Q01-04: v2 keys are principal + method scoped:
#   idem:v2:{org_id}:{user_id}:{method}:{path}:{key}
# Pre-deploy `idem:{path}:{key}` entries simply never match and age out.
RESULT_KEY_PREFIX = "idem:v2:"
LOCK_KEY_PREFIX = "idem-lock:v2:"

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

# Q01-04: authenticated mutating routes whose 2xx body carries credentials
# or secret material. They keep the Idempotency-Key requirement and the
# in-flight reservation (so a double-submit is still serialised), but the
# response is NEVER written to Redis; a sequential retry re-executes, which
# is safe for each of them:
#   /auth/switch-firm  — fresh access + refresh token pair in the body
#   /auth/mfa-verify   — fresh token pair (public; challenge-token auth)
#   /auth/mfa/setup    — TOTP secret + otpauth provisioning URI
#   /auth/mfa/confirm  — completes enrolment; a retry is refused by TOTP
#                        replay protection, never silently "succeeds"
#   /auth/logout       — revocation; re-running it is the correct retry
# These are NOT added to IDEMPOTENT_BY_DESIGN_PATHS: that set also drops the
# key requirement, which these routes have always enforced.
NEVER_CACHE_PATHS = frozenset(
    {
        "/auth/switch-firm",
        "/auth/mfa-verify",
        "/auth/mfa/setup",
        "/auth/mfa/confirm",
        "/auth/logout",
    }
)

# Defense in depth for any other route: a 2xx JSON body with one of these
# (non-empty) fields at any depth is not cached. Catches e.g. the dev-mode
# `invite_link` echo on POST /admin/invites and any future token-returning
# endpoint that forgets to join NEVER_CACHE_PATHS.
_SECRET_BODY_FIELDS = frozenset(
    {
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "provisioning_uri",
        "invite_link",
        "password",
        "totp_secret",
        "backup_codes",
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
    """Strict-presence + Redis-backed, principal-scoped dedup for mutating requests."""

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

        redis_client = await self._redis()
        if redis_client is None:
            return await call_next(request)

        # Q01-04: the cache is scoped to a VERIFIED principal. No principal
        # (no / invalid / expired / revoked / non-access token) → never
        # served from, or written to, the cache; the handler runs and its
        # own auth dependency answers (401 for authenticated routes).
        principal = await _resolve_principal(request, redis_client)
        if principal is None:
            return await call_next(request)
        org_id, user_id = principal

        # Read body once; we hash it for mismatch detection AND must put it
        # back so the downstream handler can read it.
        body_bytes = await request.body()
        _restore_request_body(request, body_bytes)
        payload_hash = hashlib.sha256(body_bytes).hexdigest()

        scope = f"{org_id}:{user_id}:{request.method}:{request.url.path}:{key}"
        result_key = f"{RESULT_KEY_PREFIX}{scope}"
        lock_key = f"{LOCK_KEY_PREFIX}{scope}"

        early = await _check_result(redis_client, result_key, payload_hash)
        if early is not None:
            return early

        # Q01-01: atomically reserve the key BEFORE running the handler.
        owner = uuid.uuid4().hex
        acquired = await redis_client.set(
            lock_key,
            json.dumps({"payload_hash": payload_hash, "owner": owner}),
            nx=True,
            ex=INFLIGHT_TTL_SECONDS,
        )
        if not acquired:
            return await _reject_concurrent(redis_client, lock_key, result_key, payload_hash)

        heartbeat: asyncio.Task[None] | None = None
        try:
            # Double-check: a concurrent request may have completed (stored
            # its result and released the lock) between our GET and SET NX.
            early = await _check_result(redis_client, result_key, payload_hash)
            if early is not None:
                return early

            heartbeat = asyncio.create_task(_heartbeat(redis_client, lock_key, owner))
            response = await call_next(request)
            return await _store_outcome(
                redis_client,
                result_key,
                payload_hash,
                response,
                cacheable=request.url.path not in NEVER_CACHE_PATHS,
            )
        finally:
            # Release on every exit path: success (result already stored),
            # handler exception / cancellation (nothing stored → a retry
            # re-executes), and the early-replay branch above.
            if heartbeat is not None:
                heartbeat.cancel()
            await _release(redis_client, lock_key, owner)


async def _resolve_principal(
    request: Request, redis_client: aioredis.Redis
) -> tuple[str, str] | None:
    """Return ``(org_id, user_id)`` from a verified ACCESS token, else None.

    Uses the same verifier as ``dependencies.get_current_user``
    (``identity_service.verify_jwt``: HS256 signature + expiry + payload
    shape), the same access-type check, and the same TS-04 ``jti`` denylist.
    The DB-backed checks (``permissions_version``, suspended / inactive)
    still run in the handler on every executed request; a replay only ever
    returns this same principal's own earlier 2xx.

    Keyed on the principal, not the raw token, so a retry after a silent
    refresh (new access token, same user) still dedupes.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = verify_jwt(token)
    except TokenInvalidError:
        return None
    if payload.token_type != "access":  # noqa: S105 — JWT type discriminator
        return None
    denylist = _get_denylist_redis() if is_test_redis_injected() else redis_client
    if denylist is not None and await denylist.exists(f"jti:{payload.jti}"):
        return None
    return str(payload.org_id), str(payload.user_id)


async def _check_result(
    redis_client: aioredis.Redis, result_key: str, payload_hash: str
) -> Response | None:
    """Replay a completed 2xx, reject a payload mismatch, else None (execute)."""
    cached = await redis_client.get(result_key)
    if cached is None:
        return None
    payload = json.loads(cached)
    if payload["payload_hash"] != payload_hash:
        return _envelope(
            IdempotencyConflictError("Idempotency-Key was reused with a different request body.")
        )
    if payload.get("is_marker"):
        # A non-2xx response was previously returned for this key.
        # Markers are not replayed — the handler must re-execute so a
        # transient 4xx (e.g. 422 from bad input) does not permanently
        # lock the idempotency key. (DOS-07 fix)
        return None
    return Response(
        content=payload["body"].encode(),
        status_code=payload["status"],
        headers=payload["headers"],
        media_type=payload.get("media_type"),
    )


async def _reject_concurrent(
    redis_client: aioredis.Redis, lock_key: str, result_key: str, payload_hash: str
) -> Response:
    """Another request holds the reservation (or just released it)."""
    held = await redis_client.get(lock_key)
    if held is not None:
        if json.loads(held).get("payload_hash") != payload_hash:
            return _envelope(
                IdempotencyConflictError(
                    "Idempotency-Key was reused with a different request body."
                )
            )
        return _in_progress()
    # The holder finished between our SET NX and GET: replay if it stored a 2xx.
    early = await _check_result(redis_client, result_key, payload_hash)
    return early if early is not None else _in_progress()


def _in_progress() -> JSONResponse:
    resp = _envelope(
        IdempotencyInProgressError(
            "A request with this Idempotency-Key is still being processed; retry shortly."
        )
    )
    resp.headers["Retry-After"] = str(IN_PROGRESS_RETRY_AFTER_SECONDS)
    return resp


async def _heartbeat(redis_client: aioredis.Redis, lock_key: str, owner: str) -> None:
    """Keep the reservation alive while the handler runs, so a slow request
    is never overtaken; a crashed worker stops beating and the key frees
    itself within ``INFLIGHT_TTL_SECONDS``."""
    try:
        while True:
            await asyncio.sleep(INFLIGHT_HEARTBEAT_SECONDS)
            held = await redis_client.get(lock_key)
            if held is None or json.loads(held).get("owner") != owner:
                return
            await redis_client.expire(lock_key, INFLIGHT_TTL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("idempotency_heartbeat_failed", exc_info=True)


async def _release(redis_client: aioredis.Redis, lock_key: str, owner: str) -> None:
    """Delete the reservation if (and only if) we still own it."""
    try:
        held = await redis_client.get(lock_key)
        if held is not None and json.loads(held).get("owner") == owner:
            await redis_client.delete(lock_key)
    except Exception:
        # The TTL frees the key on its own; log and move on.
        logger.warning("idempotency_release_failed", exc_info=True)


async def _store_outcome(
    redis_client: aioredis.Redis,
    result_key: str,
    payload_hash: str,
    response: Response,
    *,
    cacheable: bool,
) -> Response:
    """Persist the handler's outcome per the DOS-07 / Q01-04 rules."""
    if 200 <= response.status_code < 300:
        if not cacheable:
            # Secret-bearing route (tokens / TOTP secret): never persisted.
            # The reservation is released, so a sequential retry re-executes.
            return response
        # Starlette's BaseHTTPMiddleware delivers responses as
        # _StreamingResponse instances, which expose `body_iterator`,
        # but mypy sees the abstract Response type.
        response_body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            response_body += chunk
        rebuilt = Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
        if _body_carries_secret(response_body):
            logger.warning("idempotency_skip_cache_secret_body")
            return rebuilt

        # Strip credential-carrying headers BEFORE persisting so a replay
        # (or `redis-cli get idem:...`) cannot leak them. The response that
        # goes back to the FIRST caller still carries them.
        cached_headers = _strip_sensitive_headers(dict(response.headers))
        await redis_client.setex(
            result_key,
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
        return rebuilt

    if response.status_code < 500 and response.status_code not in {401, 403}:
        # DOS-07: compact marker — hash + status only, NO body. The next
        # retry with the same key+body re-executes; a different body hits
        # PAYLOAD_MISMATCH. 401/403 (auth-transient) and 5xx (infra-
        # transient, incl. a failed COMMIT — Q01-11) store nothing.
        await redis_client.setex(
            result_key,
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


def _body_carries_secret(body: bytes) -> bool:
    """True when a JSON body has a credential-named field (any depth)."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False
    stack: list[object] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and k.lower() in _SECRET_BODY_FIELDS and v:
                    return True
                stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
    return False


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
