"""Per-IP sliding-window rate limiter (CUT-501a).

Small Redis-only helper. No external rate-limit library; the algorithm
is a sorted-set sliding window:

    ZREMRANGEBYSCORE  key  -inf  (now - window)        # drop expired
    ZCARD             key                              # current count
    if count >= max: 429 RATE_LIMIT_EXCEEDED + Retry-After
    ZADD              key  now  <unique-member>        # record this hit
    EXPIRE            key  window                      # auto-clean idle keys

The Redis primitive operations are atomic individually; the gap between
ZCARD and ZADD is small enough that the worst-case burst exceeds the
window by O(workers), which is acceptable for "5 forgot-password
requests per minute" — the threshold is generous compared to legitimate
usage and the failure mode of over-counting is the conservative one.

`rate_limit` returns a FastAPI dependency callable so a router can
declare it inline. Tests inject a `redis_client` to avoid touching
the real Redis (uses ``fakeredis.aioredis.FakeRedis``).

Why not just a middleware?
    Rate limiting is per-endpoint: `/auth/forgot` ≠ `/auth/login` ≠
    everything-else. A middleware would either need an endpoint
    allow-list (re-introducing the "don't forget to gate the new
    route" footgun the audit caught with `IDEMPOTENT_BY_DESIGN_PATHS`)
    or wrap every route. Per-router `Depends(...)` keeps the policy
    visible at the endpoint declaration.

Why per-IP and not per-(IP, email)?
    Per-IP gates the email-pump attack (an attacker who learns one
    address spamming the adapter). Per-(IP, email) would let an
    attacker rotate emails from the same IP to bypass. The forgot
    endpoint already no-ops on unknown emails, so the only side
    effect we actually rate-limit is the adapter call + DB row mint
    on KNOWN emails — and that's what per-IP catches.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis
import structlog
from fastapi import Request

from ..config import get_settings
from ..exceptions import RateLimitedError

logger = structlog.get_logger()


# Test-injected client. In production we build a fresh client per
# request from settings — caching across requests breaks under pytest
# because the asyncio client binds to the event loop in scope when it
# was constructed, and pytest creates a fresh loop per test.
# `aioredis.from_url` internally uses a connection pool, so the
# per-request overhead is one pool-lookup, not a fresh TCP handshake.
_test_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis | None:
    """Return the Redis client to use for rate limiting. Tests inject
    via ``set_redis_client_for_testing``; otherwise we build fresh from
    settings (or return None when ``REDIS_URL`` is unset → dev fallback).
    """
    if _test_redis_client is not None:
        return _test_redis_client
    url = get_settings().redis_url
    if url is None:
        return None
    # Build per call — aioredis.from_url uses a connection pool under
    # the hood so this is cheap. See module docstring for why module-
    # level caching is the wrong shape here.
    return aioredis.from_url(url, decode_responses=True)


def set_redis_client_for_testing(client: aioredis.Redis | None) -> None:
    """Inject a (fake)redis client for tests. Pass ``None`` to reset."""
    global _test_redis_client
    _test_redis_client = client


def _client_ip(request: Request) -> str:
    """Best-effort client IP. Honours ``X-Forwarded-For`` (left-most
    entry — the original client per RFC 7239 convention) since prod
    sits behind Caddy. Falls back to the socket peer for local dev.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Left-most entry is the originating client per the convention
        # the reverse proxy uses; strip whitespace and only keep one hop.
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit(
    *,
    bucket: str,
    max_requests: int,
    window_seconds: int,
) -> Callable[[Request], Awaitable[None]]:
    """Return a FastAPI dependency that enforces the sliding window.

    Args:
        bucket: short stable string identifying the endpoint (e.g.
            ``"auth.forgot"``). Used as the Redis key prefix so two
            endpoints with the same threshold don't collide.
        max_requests: maximum requests allowed inside the window.
        window_seconds: window size in seconds.

    Returns:
        An async callable suitable for ``Depends(...)``.

    Raises:
        RateLimitedError (429) with ``Retry-After`` header when the
        caller's IP has already used the budget. No-op when Redis is
        unconfigured (dev fallback — the endpoint still works, just
        unprotected).
    """

    async def _dep(request: Request) -> None:
        redis_client = _get_redis()
        if redis_client is None:
            return  # No Redis -> no rate limiting (dev fallback).

        ip = _client_ip(request)
        key = f"ratelimit:{bucket}:{ip}"
        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        cutoff_ms = now_ms - window_ms

        # Drop expired entries first so ZCARD reflects the current window.
        await redis_client.zremrangebyscore(key, "-inf", cutoff_ms)
        current = await redis_client.zcard(key)
        if current >= max_requests:
            # Compute Retry-After from the OLDEST surviving entry — when
            # that one ages out, the caller has at least one slot back.
            oldest = await redis_client.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_score_ms = int(oldest[0][1])
                retry_ms = (oldest_score_ms + window_ms) - now_ms
                retry_after = max(1, (retry_ms + 999) // 1000)
            else:
                retry_after = window_seconds
            raise RateLimitedError(
                f"Rate limit exceeded for {bucket}: {max_requests} requests per {window_seconds}s.",
                retry_after_seconds=retry_after,
            )

        # Record this hit. Member is a unique token so a re-tried request
        # within the same ms doesn't collapse to a single sorted-set entry.
        await redis_client.zadd(key, {f"{now_ms}-{uuid.uuid4().hex}": now_ms})
        # Cap key lifetime so idle IPs don't accumulate forever.
        await redis_client.expire(key, window_seconds)

    return _dep


__all__ = ["rate_limit", "set_redis_client_for_testing"]
