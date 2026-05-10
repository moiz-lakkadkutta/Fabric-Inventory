"""TASK-CUT-002 — idempotency cookie strip + auth-by-design exemption.

Two regressions documented in `docs/ops/platform-audit-2026-05-10.md` P0-4:

  1. The Redis idempotency cache stored `Set-Cookie: fabric_refresh=<JWT>`
     verbatim. Any replay with the same Idempotency-Key returned the
     original refresh-token cookie for 24 h — the audit verified this with
     `redis-cli get idem:/auth/signup:<key>` and saw the JWT in plaintext.

  2. `/auth/login` and `/auth/signup` were not in
     ``IDEMPOTENT_BY_DESIGN_PATHS``, so a same-key replay would replay the
     cached body (with the original tokens) instead of re-executing the
     handler and issuing a freshly-rotated pair.

Test #1 (cookie strip, defense-in-depth) uses a synthetic ``/echo-cookie``
route to exercise the strip behavior without depending on auth/DB. It
demonstrates that ANY future mutating endpoint that happens to set a
cookie (e.g. /auth/switch-firm) will not leak its credential through the
idempotency cache.

Test #2 (auth-by-design exemption) drives the real `/auth/login`
end-to-end against the migrated Postgres + Redis. Two posts with the
same Idempotency-Key must return *different* tokens (distinct ``jti``
claims) — proof that the handler ran twice rather than the cache being
replayed.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine
from starlette.middleware.cors import CORSMiddleware

from app.config import reset_settings
from app.middleware import (
    AuthMiddleware,
    IdempotencyMiddleware,
    LoggingMiddleware,
    RLSMiddleware,
    register_error_handlers,
)
from app.service import identity_service
from tests.conftest import IdempotentTestClient

_PASSWORD = "PasswordOk123"


# ──────────────────────────────────────────────────────────────────────
# Test #1 — defense-in-depth: cached headers strip Set-Cookie + Authorization
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def cookie_echo_client(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncIterator[AsyncClient]:
    """Minimal app with the full middleware chain + a synthetic
    ``/echo-cookie`` POST route that sets ``Set-Cookie`` and
    ``Authorization`` headers. Idempotency middleware's redis client is
    monkey-patched onto the in-memory fake.
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

    @app.post("/echo-cookie")
    async def _echo_cookie(payload: dict[str, object], response: Response) -> dict[str, object]:
        # Mirrors the auth router's `_set_refresh_cookie`; this is the
        # exact attack surface the strip protects against.
        response.set_cookie(
            key="fabric_refresh",
            value="LEAK-IF-CACHED",
            max_age=1209599,
            httponly=True,
            secure=False,
            samesite="lax",
            path="/auth",
        )
        # Also smuggle an Authorization header (case-mixed on purpose to
        # prove the strip is case-insensitive).
        response.headers["Authorization"] = "Bearer LEAK-IF-CACHED"
        return {"received": payload}

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


async def test_cached_response_has_no_set_cookie_header(
    fake_redis: fakeredis.aioredis.FakeRedis,
    cookie_echo_client: AsyncClient,
) -> None:
    """Reproduce the audit's exact attack vector: post a mutating request
    whose response sets a refresh-token cookie. Inspect the cached
    Redis entry and confirm ``set-cookie`` (any case) is absent from the
    persisted ``headers`` dict.
    """
    key = str(uuid.uuid4())
    resp = await cookie_echo_client.post(
        "/echo-cookie",
        json={"x": 1},
        headers={"Idempotency-Key": key},
    )
    assert resp.status_code == 200, resp.text
    # Sanity: the cookie WAS set on the wire (caller still gets it).
    assert "set-cookie" in {h.lower() for h in resp.headers}

    # The audit reproducer: redis-cli get idem:/echo-cookie:<key>
    cached = await fake_redis.get(f"idem:/echo-cookie:{key}")
    assert cached is not None, "Idempotency middleware should cache 200 responses."

    payload = json.loads(cached)
    cached_header_keys = {k.lower() for k in payload["headers"]}
    assert "set-cookie" not in cached_header_keys, (
        f"Set-Cookie leaked into idempotency cache: {payload['headers']}"
    )
    assert "authorization" not in cached_header_keys, (
        f"Authorization leaked into idempotency cache: {payload['headers']}"
    )

    # And the body of the cookie value must not appear anywhere in the
    # serialized payload (defense in depth — catches any future header
    # rename that re-introduces the leak).
    assert "LEAK-IF-CACHED" not in cached, (
        "Refresh-token sentinel should not appear anywhere in the cached payload."
    )


async def test_replay_does_not_resurrect_stripped_cookie(
    fake_redis: fakeredis.aioredis.FakeRedis,
    cookie_echo_client: AsyncClient,
) -> None:
    """A same-key replay must NOT re-emit the cached cookie. Pre-fix the
    cached headers were copied verbatim onto the replayed Response, so
    the second caller would receive the FIRST caller's refresh-token
    cookie. After the strip, the replay carries no ``Set-Cookie``.
    """
    key = str(uuid.uuid4())
    first = await cookie_echo_client.post(
        "/echo-cookie",
        json={"x": 1},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200

    # Same key, same body → cached replay path.
    second = await cookie_echo_client.post(
        "/echo-cookie",
        json={"x": 1},
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 200
    # Replay must not carry ANYONE's cookie.
    assert "set-cookie" not in {h.lower() for h in second.headers}, (
        f"Replay leaked a Set-Cookie header: {dict(second.headers)}"
    )


# ──────────────────────────────────────────────────────────────────────
# Test #2 — auth-by-design exemption: /auth/login replay re-issues fresh tokens
# ──────────────────────────────────────────────────────────────────────


def _signup(client: TestClient, *, email: str, password: str, org_name: str) -> dict[str, str]:
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": password,
            "org_name": org_name,
            "firm_name": "Primary Firm",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def test_auth_login_replay_with_same_key_issues_fresh_tokens(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    """Two posts to /auth/login with the *same* Idempotency-Key must
    re-execute the handler and return tokens with distinct ``jti`` claims.

    Pre-fix: the second call replayed the cached 200 envelope with the
    first call's tokens — meaning a stale token pair could be served
    indefinitely (until cache TTL).

    Post-fix: ``/auth/login`` is in ``IDEMPOTENT_BY_DESIGN_PATHS`` so the
    middleware short-circuits the cache lookup; tokens rotate per call.
    """
    _ = sync_engine  # ensure DB-bound fixture skip semantics apply
    email = f"cut002-{uuid.uuid4().hex[:8]}@example.com"
    org_name = f"CUT-002 Org {uuid.uuid4().hex[:8]}"
    _signup(http_client, email=email, password=_PASSWORD, org_name=org_name)

    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}
    creds = {"email": email, "password": _PASSWORD, "org_name": org_name}

    first = http_client.post("/auth/login", json=creds, headers=headers)
    assert first.status_code == 200, first.text
    second = http_client.post("/auth/login", json=creds, headers=headers)
    assert second.status_code == 200, second.text

    # Decode the access tokens; ``jti`` is regenerated per token issue.
    jti_first = identity_service.verify_jwt(first.json()["access_token"]).jti
    jti_second = identity_service.verify_jwt(second.json()["access_token"]).jti
    assert jti_first != jti_second, (
        "Login replay returned cached tokens; auth-by-design exemption is not in effect."
    )


def test_auth_signup_replay_with_same_key_issues_fresh_tokens(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    """Same as the login test, but for /auth/signup. Once the org/email
    exists, a same-key replay must re-execute and surface the spec'd
    409 USER_EMAIL_TAKEN — proving the cache was bypassed (otherwise the
    cached 201 with the original tokens would be served).
    """
    _ = sync_engine
    email = f"cut002s-{uuid.uuid4().hex[:8]}@example.com"
    org_name = f"CUT-002 Sig Org {uuid.uuid4().hex[:8]}"
    body = {
        "email": email,
        "password": _PASSWORD,
        "org_name": org_name,
        "firm_name": "Primary Firm",
        "state_code": "MH",
    }
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}

    first = http_client.post("/auth/signup", json=body, headers=headers)
    assert first.status_code == 201, first.text

    # Replay with the same key — pre-fix this returned the cached 201
    # envelope verbatim. Post-fix the handler runs again and the
    # email-already-exists check fires.
    second = http_client.post("/auth/signup", json=body, headers=headers)
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "USER_EMAIL_TAKEN"
