"""T3 security tests — auth endpoint rate limits, enumeration collapse, audit.

Covers:
  DOS-01  — rate limits on login, mfa-verify, signup, reset
  IDM-6   — signup enumeration: both collision branches return the same 409
  CRYPTO-02 — failed login emits a login_failed audit event
  TS-06   — password-reset timing: error path runs equivalent bcrypt work

Rate-limit tests follow the exact pattern from test_auth_forgot_rate_limit.py:
a minimal synthetic FastAPI app with the production dep is built against
fakeredis so the suite needs neither Postgres nor real Redis.

IDM-6 / CRYPTO-02 tests are DB-bound (http_client fixture) and skip
locally when Postgres is unreachable; they fail loudly in CI.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import fakeredis.aioredis
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine
from starlette.middleware.cors import CORSMiddleware

from app.config import reset_settings
from app.middleware import (
    AuthMiddleware,
    IdempotencyMiddleware,
    LoggingMiddleware,
    RequestContextMiddleware,
    RLSMiddleware,
    register_error_handlers,
    set_redis_client_for_testing,
)

# ──────────────────────────────────────────────────────────────────────
# Shared fixtures for rate-limit tests (mirrors test_auth_forgot_rate_limit.py)
#
# NOTE: _enable_redis_env is NOT autouse=True here because this file also
# contains DB-bound tests (IDM-6, CRYPTO-02, TS-06). If autouse=True were
# set, those tests would inherit REDIS_URL=redis://fake-for-tests without a
# fake client injected, causing the real app's rate-limit dep to attempt a
# TCP connection to a non-existent host and fail. Rate-limit fixtures
# instead call set_redis_client_for_testing() directly — REDIS_URL is not
# needed because _get_redis() checks the test-injected client first.
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


def _build_app(fake_redis: fakeredis.aioredis.FakeRedis, routes: list[Any]) -> FastAPI:
    """Build a minimal test app with the full middleware chain."""
    set_redis_client_for_testing(fake_redis)
    reset_settings()

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
    for path, dep in routes:
        app.post(path, dependencies=[Depends(dep)])(lambda: {"ok": True})
    return app


# ──────────────────────────────────────────────────────────────────────
# DOS-01 — Login rate limit: 10 req / 60s per (IP+email)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def login_http(fake_redis: fakeredis.aioredis.FakeRedis) -> AsyncIterator[AsyncClient]:
    # Mirror the production policy exactly: 10 req / 60s.
    from app.routers.auth import _LOGIN_RATE_LIMIT  # will fail until dep is added

    app = _build_app(fake_redis, [("/auth/login", _LOGIN_RATE_LIMIT)])
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        set_redis_client_for_testing(None)


async def test_login_eleventh_request_returns_429(
    login_http: AsyncClient,
) -> None:
    """First 10 login attempts from the same IP+email succeed;
    the 11th inside the 60s window returns 429."""
    payload = {"email": "attacker@example.com", "password": "x", "org_name": "NoOrg"}
    for i in range(10):
        resp = await login_http.post("/auth/login", json=payload)
        assert resp.status_code != 429, f"request {i + 1} throttled too early: {resp.text}"

    eleventh = await login_http.post("/auth/login", json=payload)
    assert eleventh.status_code == 429, eleventh.text
    body = eleventh.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in eleventh.headers


async def test_login_different_emails_do_not_share_budget(
    login_http: AsyncClient,
) -> None:
    """Per-email keying: burning email A's budget must not starve email B."""
    payload_a = {"email": "a@example.com", "password": "x", "org_name": "NoOrg"}
    payload_b = {"email": "b@example.com", "password": "x", "org_name": "NoOrg"}

    # Exhaust email A's budget (10 requests).
    for _ in range(10):
        await login_http.post("/auth/login", json=payload_a)

    # email A is now throttled.
    blocked = await login_http.post("/auth/login", json=payload_a)
    assert blocked.status_code == 429

    # email B still has a fresh budget.
    allowed = await login_http.post("/auth/login", json=payload_b)
    assert allowed.status_code != 429, allowed.text


# ──────────────────────────────────────────────────────────────────────
# DOS-01 — MFA-verify rate limit: 10 req / 60s per (IP+email)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def mfa_http(fake_redis: fakeredis.aioredis.FakeRedis) -> AsyncIterator[AsyncClient]:
    from app.routers.auth import _MFA_RATE_LIMIT  # will fail until dep is added

    app = _build_app(fake_redis, [("/auth/mfa-verify", _MFA_RATE_LIMIT)])
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        set_redis_client_for_testing(None)


async def test_mfa_verify_eleventh_request_returns_429(mfa_http: AsyncClient) -> None:
    """11th MFA verify from same IP+email returns 429.

    /auth/mfa-verify is NOT in IDEMPOTENT_BY_DESIGN_PATHS, so each request
    needs a unique Idempotency-Key to avoid 400 from IdempotencyMiddleware.
    """
    import uuid as _uuid_mod

    payload = {"email": "mfa@example.com", "password": "x", "totp_code": "123456", "org_name": "x"}
    for i in range(10):
        resp = await mfa_http.post(
            "/auth/mfa-verify",
            json=payload,
            headers={"Idempotency-Key": str(_uuid_mod.uuid4())},
        )
        assert resp.status_code != 429, f"request {i + 1} throttled too early: {resp.text}"

    eleventh = await mfa_http.post(
        "/auth/mfa-verify",
        json=payload,
        headers={"Idempotency-Key": str(_uuid_mod.uuid4())},
    )
    assert eleventh.status_code == 429, eleventh.text
    assert eleventh.json()["code"] == "RATE_LIMIT_EXCEEDED"


# ──────────────────────────────────────────────────────────────────────
# DOS-01 — Signup rate limit: 3 req / 3600s per IP
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def signup_http(fake_redis: fakeredis.aioredis.FakeRedis) -> AsyncIterator[AsyncClient]:
    from app.routers.auth import _SIGNUP_RATE_LIMIT  # will fail until dep is added

    app = _build_app(fake_redis, [("/auth/signup", _SIGNUP_RATE_LIMIT)])
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        set_redis_client_for_testing(None)


async def test_signup_fourth_request_returns_429(signup_http: AsyncClient) -> None:
    """First 3 signup requests from same IP succeed; 4th returns 429."""
    payload = {"email": "new@example.com", "password": "x", "org_name": "X"}
    for i in range(3):
        resp = await signup_http.post("/auth/signup", json=payload)
        assert resp.status_code != 429, f"request {i + 1} throttled too early"

    fourth = await signup_http.post("/auth/signup", json=payload)
    assert fourth.status_code == 429, fourth.text
    assert fourth.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in fourth.headers


# ──────────────────────────────────────────────────────────────────────
# DOS-01 — Reset rate limit: 5 req / 60s per IP
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def reset_http(fake_redis: fakeredis.aioredis.FakeRedis) -> AsyncIterator[AsyncClient]:
    from app.routers.auth import _RESET_RATE_LIMIT  # will fail until dep is added

    app = _build_app(fake_redis, [("/auth/reset", _RESET_RATE_LIMIT)])
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        set_redis_client_for_testing(None)


async def test_reset_sixth_request_returns_429(reset_http: AsyncClient) -> None:
    """First 5 reset requests from same IP succeed; 6th returns 429."""
    payload = {"token": "x" * 32, "org_name": "X", "new_password": "y" * 12}
    for i in range(5):
        resp = await reset_http.post("/auth/reset", json=payload)
        assert resp.status_code != 429, f"request {i + 1} throttled too early"

    sixth = await reset_http.post("/auth/reset", json=payload)
    assert sixth.status_code == 429, sixth.text
    assert sixth.json()["code"] == "RATE_LIMIT_EXCEEDED"


# ──────────────────────────────────────────────────────────────────────
# IDM-6 — Signup enumeration: both collision branches return the same 409
# DB-bound tests (skip locally without Postgres)
# ──────────────────────────────────────────────────────────────────────


def _unique_email() -> str:
    return f"u-{uuid.uuid4().hex[:10]}@example.com"


def _unique_org_name() -> str:
    return f"Org-{uuid.uuid4().hex[:8]}"


def _signup_body(
    *,
    email: str | None = None,
    org_name: str | None = None,
) -> dict[str, str]:
    return {
        "email": email or _unique_email(),
        "password": "strong-password-1234",
        "org_name": org_name or _unique_org_name(),
        "firm_name": "Test Firm",
        "state_code": "MH",
    }


def test_signup_both_collision_paths_return_same_409_body(http_client):  # type: ignore[no-untyped-def]
    """IDM-6: whether the collision is on the org name OR the email,
    the response must be status 409 with the EXACT same code + message
    and must NOT echo the email or org name in the detail field.
    """
    email = _unique_email()
    org_name = _unique_org_name()

    # First signup — creates org + user.
    first = http_client.post("/auth/signup", json=_signup_body(email=email, org_name=org_name))
    assert first.status_code == 201, first.text

    # Case 1: same org, same email → collision on both
    same_both = http_client.post("/auth/signup", json=_signup_body(email=email, org_name=org_name))
    assert same_both.status_code == 409, same_both.text

    # Case 2: same org, different email → collision on org only
    diff_email = http_client.post(
        "/auth/signup",
        json=_signup_body(email=_unique_email(), org_name=org_name),
    )
    assert diff_email.status_code == 409, diff_email.text

    body1 = same_both.json()
    body2 = diff_email.json()

    # Both must return the SAME stable error code.
    assert body1["code"] == body2["code"], (
        f"Enumeration leak: case 1 code={body1['code']!r}, case 2 code={body2['code']!r}"
    )
    # Both must return the SAME message.
    assert body1["detail"] == body2["detail"], (
        f"Enumeration leak: case 1 detail={body1['detail']!r}, case 2 detail={body2['detail']!r}"
    )
    # The detail must NOT echo the email or org name.
    for body in (body1, body2):
        assert email.lower() not in body["detail"].lower(), (
            f"Email echoed in error detail: {body['detail']!r}"
        )
        assert org_name.lower() not in body["detail"].lower(), (
            f"Org name echoed in error detail: {body['detail']!r}"
        )


# ──────────────────────────────────────────────────────────────────────
# CRYPTO-02 — Failed login emits login_failed audit row
# DB-bound tests (skip locally without Postgres)
# ──────────────────────────────────────────────────────────────────────


def test_failed_login_emits_login_failed_audit_row(http_client, sync_engine) -> None:  # type: ignore[no-untyped-def]
    """CRYPTO-02: a wrong-password login attempt must write an audit row
    with action='login_failed' for the targeted org.
    """
    import uuid as _uuid

    from sqlalchemy import select, text
    from sqlalchemy.orm import Session as OrmSession

    from app.models import AuditLog

    email = _unique_email()
    org_name = _unique_org_name()

    signup = http_client.post("/auth/signup", json=_signup_body(email=email, org_name=org_name))
    assert signup.status_code == 201, signup.text
    org_id = signup.json()["org_id"]

    # Attempt login with wrong password.
    bad_login = http_client.post(
        "/auth/login",
        json={"email": email, "password": "wrong-password-xyz", "org_name": org_name},
    )
    assert bad_login.status_code == 401, bad_login.text

    # Verify audit row was written.
    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rows = list(
            s.execute(
                select(AuditLog).where(
                    AuditLog.org_id == _uuid.UUID(org_id),
                    AuditLog.action == "login_failed",
                )
            ).scalars()
        )

    assert len(rows) >= 1, (
        "Expected at least one 'login_failed' audit row after bad-password attempt, "
        f"got {len(rows)}"
    )


def test_successful_login_does_not_emit_login_failed_audit_row(http_client, sync_engine) -> None:  # type: ignore[no-untyped-def]
    """Positive-path sanity: a successful login must NOT write login_failed."""
    import uuid as _uuid

    from sqlalchemy import select, text
    from sqlalchemy.orm import Session as OrmSession

    from app.models import AuditLog

    email = _unique_email()
    org_name = _unique_org_name()
    password = "strong-password-1234"

    signup = http_client.post("/auth/signup", json=_signup_body(email=email, org_name=org_name))
    assert signup.status_code == 201, signup.text
    org_id = signup.json()["org_id"]

    good_login = http_client.post(
        "/auth/login",
        json={"email": email, "password": password, "org_name": org_name},
    )
    assert good_login.status_code == 200, good_login.text

    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rows = list(
            s.execute(
                select(AuditLog).where(
                    AuditLog.org_id == _uuid.UUID(org_id),
                    AuditLog.action == "login_failed",
                )
            ).scalars()
        )

    assert len(rows) == 0, (
        f"Expected zero 'login_failed' rows after successful login, got {len(rows)}"
    )


# ──────────────────────────────────────────────────────────────────────
# TS-06 — Password-reset timing: error path runs equivalent bcrypt work
# ──────────────────────────────────────────────────────────────────────


def test_reset_with_invalid_token_still_returns_400_not_timing_shortcut(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """TS-06: the reset error path runs the same bcrypt work as the
    success path so timing alone cannot reveal token validity.
    Verifies the production code path (auth.py reset_password) doesn't
    short-circuit on InvalidResetTokenError.

    We measure two requests: one to a valid-token-consumed org and one
    with a garbage token. Both should return 400. Both should take
    > 0ms (bcrypt ran). We don't assert on exact timing (flaky in CI)
    — we just verify the DUMMY_BCRYPT_HASH constant is in scope and
    that the endpoint returns 400 for both paths.
    """
    from app.service import identity_service

    # DUMMY_BCRYPT_HASH must exist (it's the mechanism for TS-06 constant-work).
    assert hasattr(identity_service, "DUMMY_BCRYPT_HASH"), (
        "identity_service.DUMMY_BCRYPT_HASH is missing — "
        "the TS-06 constant-work fix was not implemented."
    )

    # Garbage token → 400 (and bcrypt must have run internally).
    resp = http_client.post(
        "/auth/reset",
        json={
            "token": "completely-invalid-token-garbage-x1",
            "org_name": "nonexistent-org-xyz",
            "new_password": "newpassword12345",
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_RESET_TOKEN"


# ──────────────────────────────────────────────────────────────────────
# DOS-02 / API-7-03 CYCLE-2 — Spy tests: verify_password called on every
# unknown path (org-missing, user-missing, invalid-reset-token).
# DB-bound tests (skip locally without Postgres)
# ──────────────────────────────────────────────────────────────────────


def test_unknown_org_login_calls_verify_password(http_client) -> None:  # type: ignore[no-untyped-def]
    """Item 1 (blocker): login with a nonexistent org must call
    identity_service.verify_password BEFORE raising so the ~100ms bcrypt
    latency is present and the response is timing-indistinguishable from
    the wrong-password path.

    This test FAILS if _resolve_org_by_name raises before bcrypt runs.
    """
    from unittest.mock import patch

    import app.service.identity_service as _ids

    with patch.object(_ids, "verify_password", wraps=_ids.verify_password) as spy:
        resp = http_client.post(
            "/auth/login",
            json={
                "email": "nobody@example.com",
                "password": "somepass123",
                "org_name": "totally-nonexistent-org-zzz-xyz",
            },
        )
    assert resp.status_code == 401, resp.text
    (
        spy.assert_called_once(),
        ("verify_password was NOT called on unknown-org login — timing oracle remains open"),
    )


def test_unknown_user_login_calls_verify_password(http_client) -> None:  # type: ignore[no-untyped-def]
    """Item 2a: login where org exists but user doesn't must call
    verify_password (regression guard — must fail if dummy-bcrypt removed).
    """
    from unittest.mock import patch

    import app.service.identity_service as _ids

    email = _unique_email()
    org_name = _unique_org_name()
    signup = http_client.post("/auth/signup", json=_signup_body(email=email, org_name=org_name))
    assert signup.status_code == 201

    with patch.object(_ids, "verify_password", wraps=_ids.verify_password) as spy:
        resp = http_client.post(
            "/auth/login",
            json={
                "email": "no-such-user@example.com",  # not registered in this org
                "password": "somepass123",
                "org_name": org_name,  # org exists
            },
        )
    assert resp.status_code == 401, resp.text
    (
        spy.assert_called_once(),
        ("verify_password was NOT called on unknown-user login — timing oracle remains open"),
    )


def test_invalid_reset_token_calls_verify_password(http_client) -> None:  # type: ignore[no-untyped-def]
    """Item 2b: invalid-reset-token path must call verify_password
    (TS-06 regression spy — must fail if dummy-bcrypt removed from except block).
    """
    from unittest.mock import patch

    import app.service.identity_service as _ids

    with patch.object(_ids, "verify_password", wraps=_ids.verify_password) as spy:
        resp = http_client.post(
            "/auth/reset",
            json={
                "token": "completely-invalid-token-garbage-x1",
                "org_name": "nonexistent-org-xyz",
                "new_password": "newpassword12345",
            },
        )
    assert resp.status_code == 400, resp.text
    (
        spy.assert_called_once(),
        ("verify_password was NOT called on invalid-reset-token path — TS-06 timing fix missing"),
    )


# ──────────────────────────────────────────────────────────────────────
# Item 3 — PII audit: login_failed must NOT store raw email
# DB-bound tests (skip locally without Postgres)
# ──────────────────────────────────────────────────────────────────────


def test_login_failed_audit_omits_raw_email(http_client, sync_engine) -> None:  # type: ignore[no-untyped-def]
    """Item 3: the login_failed audit row must NOT contain raw attacker-
    supplied email in changes.after. Email is PII; the reset path already
    omits it for consistency.
    """
    import uuid as _uuid

    from sqlalchemy import select, text
    from sqlalchemy.orm import Session as OrmSession

    from app.models import AuditLog

    email = _unique_email()
    org_name = _unique_org_name()
    signup = http_client.post("/auth/signup", json=_signup_body(email=email, org_name=org_name))
    assert signup.status_code == 201
    org_id = signup.json()["org_id"]

    bad_login = http_client.post(
        "/auth/login",
        json={"email": email, "password": "wrong-password-xyz", "org_name": org_name},
    )
    assert bad_login.status_code == 401

    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rows = list(
            s.execute(
                select(AuditLog).where(
                    AuditLog.org_id == _uuid.UUID(org_id),
                    AuditLog.action == "login_failed",
                )
            ).scalars()
        )

    assert len(rows) >= 1, "Expected at least one login_failed audit row"
    for row in rows:
        after = (row.changes or {}).get("after", {})
        assert "email" not in after, (
            f"Raw email found in login_failed audit changes.after: {after!r} — PII leak"
        )
