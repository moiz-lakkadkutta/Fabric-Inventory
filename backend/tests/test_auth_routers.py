"""TASK-008: auth router integration tests.

End-to-end tests against a migrated Postgres + the FastAPI app. Each
test uses unique org/email names (UUID-suffixed) so successive tests
don't collide on UNIQUE constraints — no transactional rollback in this
file because the app's `get_db_sync` opens its own connections.

Skipped when no Postgres is reachable; CI's services container makes
this active. CI=true → hard fail (consistent with the rest of the
DB-bound test fixtures).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine


@pytest.fixture
def http_client(sync_engine: Engine) -> Iterator[TestClient]:
    """A FastAPI TestClient pointed at the same DATABASE_URL as
    `sync_engine`. The app uses `get_db_sync` internally, which opens
    its own connection — but it shares the same Postgres, so rows the
    handlers create are visible to the test for inspection.
    """
    _ = sync_engine  # keep the fixture's connection check + skip semantics
    from main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


def _unique_email() -> str:
    return f"u-{uuid.uuid4().hex[:10]}@example.com"


def _unique_org_name() -> str:
    return f"Org {uuid.uuid4().hex[:8]}"


def _signup(client: TestClient, *, email: str, password: str, org_name: str) -> dict[str, str]:
    """Returns the parsed JSON body, narrowed to dict[str, str] for callers
    that index into it directly (every value in SignupResponse is a string —
    UUIDs serialize as str, ISO timestamps are str, tokens are str).
    """
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": password,
            "org_name": org_name,
            "firm_name": "Primary Firm",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


# ──────────────────────────────────────────────────────────────────────
# Signup
# ──────────────────────────────────────────────────────────────────────


def test_signup_returns_tokens_and_creates_org_firm_user(http_client: TestClient) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    body = _signup(http_client, email=email, password="strong-password-1", org_name=org_name)

    for key in (
        "user_id",
        "org_id",
        "firm_id",
        "access_token",
        "refresh_token",
        "access_expires_at",
        "refresh_expires_at",
    ):
        assert key in body, f"missing key: {key}"
    # Tokens decode and carry the new user_id + org_id.
    from app.service import identity_service

    payload = identity_service.verify_jwt(body["access_token"])
    assert str(payload.user_id) == body["user_id"]
    assert str(payload.org_id) == body["org_id"]
    assert payload.token_type == "access"
    # Owner perm set on the JWT — proves RBAC seeding worked.
    assert "sales.invoice.finalize" in payload.permissions


def test_signup_duplicate_org_name_returns_422(http_client: TestClient) -> None:
    org_name = _unique_org_name()
    _signup(http_client, email=_unique_email(), password="strong-password-1", org_name=org_name)
    resp = http_client.post(
        "/auth/signup",
        json={
            "email": _unique_email(),
            "password": "strong-password-1",
            "org_name": org_name,
            "firm_name": "Primary Firm",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "validation_error"


def test_signup_weak_password_rejected_by_pydantic(http_client: TestClient) -> None:
    resp = http_client.post(
        "/auth/signup",
        json={
            "email": _unique_email(),
            "password": "short",
            "org_name": _unique_org_name(),
            "firm_name": "F",
        },
    )
    # Pydantic returns 422 for min_length violation.
    assert resp.status_code == 422


def test_signup_invalid_email_rejected_by_pydantic(http_client: TestClient) -> None:
    resp = http_client.post(
        "/auth/signup",
        json={
            "email": "not-an-email",
            "password": "strong-password-1",
            "org_name": _unique_org_name(),
            "firm_name": "F",
        },
    )
    assert resp.status_code == 422


def test_signup_with_idempotency_key_succeeds(http_client: TestClient) -> None:
    """Header validation accepts a UUID; dedupe lands in TASK-017."""
    resp = http_client.post(
        "/auth/signup",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "email": _unique_email(),
            "password": "strong-password-1",
            "org_name": _unique_org_name(),
            "firm_name": "F",
        },
    )
    assert resp.status_code == 201


def test_signup_with_malformed_idempotency_key_rejected(http_client: TestClient) -> None:
    resp = http_client.post(
        "/auth/signup",
        headers={"Idempotency-Key": "not-a-uuid"},
        json={
            "email": _unique_email(),
            "password": "strong-password-1",
            "org_name": _unique_org_name(),
            "firm_name": "F",
        },
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────────────────────────


def test_login_with_correct_creds_returns_tokens(http_client: TestClient) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    password = "strong-password-1"
    _signup(http_client, email=email, password=password, org_name=org_name)

    resp = http_client.post(
        "/auth/login",
        json={"email": email, "password": password, "org_name": org_name},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_mfa"] is False
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_with_wrong_password_returns_401(http_client: TestClient) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    _signup(http_client, email=email, password="strong-password-1", org_name=org_name)

    resp = http_client.post(
        "/auth/login",
        json={"email": email, "password": "wrong-password", "org_name": org_name},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "invalid_credentials"


def test_login_with_unknown_email_returns_401(http_client: TestClient) -> None:
    org_name = _unique_org_name()
    _signup(http_client, email=_unique_email(), password="strong-password-1", org_name=org_name)
    resp = http_client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "any-password", "org_name": org_name},
    )
    assert resp.status_code == 401


def test_login_with_unknown_org_returns_401(http_client: TestClient) -> None:
    """Unknown org name surfaces as the same generic 401 (no leak)."""
    resp = http_client.post(
        "/auth/login",
        json={"email": _unique_email(), "password": "x", "org_name": "Nonexistent Org Name"},
    )
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# MFA verify
# ──────────────────────────────────────────────────────────────────────


def _enable_mfa_for(client: TestClient, sync_engine: Engine, user_id: uuid.UUID) -> str:
    """Use the service directly to enable MFA on a freshly-created user
    (the public 'enable MFA' router lands later)."""
    from sqlalchemy.orm import Session as OrmSession

    from app.service import identity_service

    with OrmSession(sync_engine) as s:
        enrollment = identity_service.enable_mfa(s, user_id=user_id)
        s.commit()
    return enrollment.secret


def test_login_with_mfa_enabled_returns_requires_mfa_true(
    http_client: TestClient, sync_engine: Engine
) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    password = "strong-password-1"
    body = _signup(http_client, email=email, password=password, org_name=org_name)
    _enable_mfa_for(http_client, sync_engine, uuid.UUID(body["user_id"]))

    resp = http_client.post(
        "/auth/login",
        json={"email": email, "password": password, "org_name": org_name},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_mfa"] is True
    assert body["access_token"] is None
    assert body["refresh_token"] is None


def test_mfa_verify_with_valid_totp_returns_tokens(
    http_client: TestClient, sync_engine: Engine
) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    password = "strong-password-1"
    body = _signup(http_client, email=email, password=password, org_name=org_name)
    secret = _enable_mfa_for(http_client, sync_engine, uuid.UUID(body["user_id"]))

    code = pyotp.TOTP(secret).now()
    resp = http_client.post(
        "/auth/mfa-verify",
        json={
            "email": email,
            "password": password,
            "org_name": org_name,
            "totp_code": code,
        },
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["access_token"]
    assert out["refresh_token"]


def test_mfa_verify_with_wrong_code_returns_401(
    http_client: TestClient, sync_engine: Engine
) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    password = "strong-password-1"
    body = _signup(http_client, email=email, password=password, org_name=org_name)
    _enable_mfa_for(http_client, sync_engine, uuid.UUID(body["user_id"]))

    resp = http_client.post(
        "/auth/mfa-verify",
        json={
            "email": email,
            "password": password,
            "org_name": org_name,
            "totp_code": "000000",
        },
    )
    assert resp.status_code == 401


def test_mfa_verify_with_wrong_password_returns_401(
    http_client: TestClient, sync_engine: Engine
) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    body = _signup(http_client, email=email, password="strong-password-1", org_name=org_name)
    secret = _enable_mfa_for(http_client, sync_engine, uuid.UUID(body["user_id"]))
    code = pyotp.TOTP(secret).now()

    resp = http_client.post(
        "/auth/mfa-verify",
        json={
            "email": email,
            "password": "wrong-password",
            "org_name": org_name,
            "totp_code": code,
        },
    )
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# Refresh
# ──────────────────────────────────────────────────────────────────────


def test_refresh_with_valid_token_returns_new_pair(http_client: TestClient) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    password = "strong-password-1"
    body = _signup(http_client, email=email, password=password, org_name=org_name)

    resp = http_client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["access_token"] != body["access_token"]
    assert out["refresh_token"] != body["refresh_token"]


def test_refresh_with_access_token_returns_401(http_client: TestClient) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.post("/auth/refresh", json={"refresh_token": body["access_token"]})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "token_invalid"


def test_refresh_replay_returns_401(http_client: TestClient) -> None:
    """Once a refresh token has been rotated, replaying it should fail."""
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    first_refresh = body["refresh_token"]
    http_client.post("/auth/refresh", json={"refresh_token": first_refresh}).raise_for_status()
    replay = http_client.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# Logout
# ──────────────────────────────────────────────────────────────────────


def test_logout_revokes_session_and_blocks_subsequent_refresh(
    http_client: TestClient, sync_engine: Engine
) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    body = _signup(http_client, email=email, password="strong-password-1", org_name=org_name)

    resp = http_client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True

    # Subsequent refresh of the revoked token returns 401.
    again = http_client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert again.status_code == 401

    # Audit: session row exists and revoked_at is set.
    from sqlalchemy.orm import Session as OrmSession

    from app.models import Session as DbSession
    from app.service import identity_service

    with OrmSession(sync_engine) as s:
        rows = (
            s.execute(
                select(DbSession).where(
                    DbSession.refresh_token_hash
                    == identity_service._hash_token(body["refresh_token"])
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].revoked_at is not None


def test_logout_with_unknown_token_is_idempotent_success(http_client: TestClient) -> None:
    """A logout with a malformed/unknown token returns 200 + revoked=False."""
    resp = http_client.post("/auth/logout", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 200
    assert resp.json()["revoked"] is False


def test_logout_with_access_token_returns_400(http_client: TestClient) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.post("/auth/logout", json={"refresh_token": body["access_token"]})
    assert resp.status_code == 400
    # Suppress unused-arg lint by referencing os.environ check
    _ = os.environ.get("CI")
