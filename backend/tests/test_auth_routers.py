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

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine


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
            "state_code": "MH",
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

    # System catalog auto-seeded for the new org (TASK-015 wire-in):
    # GET /uoms returns the 10-row UOM catalog without any extra setup.
    uoms_resp = http_client.get(
        "/uoms", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert uoms_resp.status_code == 200
    assert uoms_resp.json()["count"] == 10
    hsn_resp = http_client.get("/hsn", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert hsn_resp.status_code == 200
    assert hsn_resp.json()["count"] == 10


def test_signup_duplicate_org_name_returns_generic_409(http_client: TestClient) -> None:
    """IDM-6: a duplicate org name must return the SAME generic 409 as a
    duplicate email, so an unauthenticated attacker cannot enumerate which
    org names exist by status code / message. (Previously this leaked a
    distinct 422 'organization already exists' response.)
    """
    org_name = _unique_org_name()
    _signup(http_client, email=_unique_email(), password="strong-password-1", org_name=org_name)
    resp = http_client.post(
        "/auth/signup",
        json={
            "email": _unique_email(),
            "password": "strong-password-1",
            "org_name": org_name,
            "firm_name": "Primary Firm",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "USER_EMAIL_TAKEN"
    # Must not leak which field collided (no org name echoed back).
    assert org_name not in resp.text


def test_signup_weak_password_rejected_by_pydantic(http_client: TestClient) -> None:
    resp = http_client.post(
        "/auth/signup",
        json={
            "email": _unique_email(),
            "password": "short",
            "org_name": _unique_org_name(),
            "firm_name": "F",
            "state_code": "MH",
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
            "state_code": "MH",
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
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201


def test_signup_ignores_idempotency_key_per_auth_by_design_exemption(
    http_client: TestClient,
) -> None:
    """Per TASK-CUT-002, /auth/signup is in ``IDEMPOTENT_BY_DESIGN_PATHS``
    so the middleware skips key validation and cache lookup entirely —
    signup always re-executes and issues fresh tokens. A malformed (or
    even missing) key is therefore accepted at the middleware layer.

    Generic key-validation coverage lives in
    ``tests/test_middleware_idempotency.py`` against a synthetic route.
    """
    resp = http_client.post(
        "/auth/signup",
        headers={"Idempotency-Key": "not-a-uuid"},
        json={
            "email": _unique_email(),
            "password": "strong-password-1",
            "org_name": _unique_org_name(),
            "firm_name": "F",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text


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
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


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


def _enable_mfa_for(
    client: TestClient, sync_engine: Engine, user_id: uuid.UUID, org_id: uuid.UUID
) -> str:
    """Use the service directly to enable MFA on a freshly-created user
    (the public 'enable MFA' router lands later)."""
    from sqlalchemy.orm import Session as OrmSession

    from app.service import identity_service

    with OrmSession(sync_engine, expire_on_commit=False) as s:
        # GUC required under fabric_app: enable_mfa SELECTs the user row.
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
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
    _enable_mfa_for(http_client, sync_engine, uuid.UUID(body["user_id"]), uuid.UUID(body["org_id"]))

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
    secret = _enable_mfa_for(
        http_client, sync_engine, uuid.UUID(body["user_id"]), uuid.UUID(body["org_id"])
    )

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
    _enable_mfa_for(http_client, sync_engine, uuid.UUID(body["user_id"]), uuid.UUID(body["org_id"]))

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
    secret = _enable_mfa_for(
        http_client, sync_engine, uuid.UUID(body["user_id"]), uuid.UUID(body["org_id"])
    )
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
    """Sending an access token in the body — with no refresh cookie — must 401."""
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    # Clear the refresh cookie that signup just set, so the body path is
    # exercised in isolation. (Cookie-with-access-token is a different
    # scenario; the cookie carries a valid refresh token here.)
    http_client.cookies.clear()
    resp = http_client.post("/auth/refresh", json={"refresh_token": body["access_token"]})
    assert resp.status_code == 401
    assert resp.json()["code"] == "TOKEN_INVALID"


def test_refresh_replay_returns_401(http_client: TestClient) -> None:
    """Once a refresh token has been rotated, replaying it should fail.

    We clear the cookie between calls so the body-path is exercised in
    isolation — otherwise the cookie (which auto-rotates on each refresh)
    would shadow the stale body and mask the replay.
    """
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    first_refresh = body["refresh_token"]
    http_client.cookies.clear()
    http_client.post("/auth/refresh", json={"refresh_token": first_refresh}).raise_for_status()
    http_client.cookies.clear()
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
        s.execute(text(f"SET LOCAL app.current_org_id = '{body['org_id']}'"))
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


# ──────────────────────────────────────────────────────────────────────
# TS-04 — jti denylist: access token is revoked on logout
# ──────────────────────────────────────────────────────────────────────


def test_TS04_logout_denylists_access_token_so_reuse_returns_401(
    http_client: TestClient,
) -> None:
    """TS-04 (RED): after a logout that sends the access token in the
    Authorization header, any subsequent request using that same access
    token must return 401 (jti denylisted in Redis).

    Before implementation: the access token remains valid for up to 15 min
    after logout because no denylist exists.
    """
    email = _unique_email()
    org_name = _unique_org_name()
    body = _signup(http_client, email=email, password="strong-password-1", org_name=org_name)
    access_token = body["access_token"]
    refresh_token = body["refresh_token"]

    # Sanity: token works before logout.
    pre = http_client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert pre.status_code == 200, f"Expected 200 before logout, got {pre.status_code}"

    # Logout — send access token in Authorization header so the handler
    # can extract its jti and push it to the denylist.
    logout_resp = http_client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refresh_token": refresh_token},
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["revoked"] is True

    # After logout, the same access token must be 401 (jti is denylisted).
    post = http_client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert post.status_code == 401, (
        f"TS-04 FAIL: access token still valid after logout (got {post.status_code}). "
        "Logout must denylist the access token's jti in Redis."
    )


# ──────────────────────────────────────────────────────────────────────
# TS-05 / IDM-5 — permissions_version: stale token rejected after role change
# ──────────────────────────────────────────────────────────────────────


def test_TS05_valid_token_works_when_pv_unchanged(http_client: TestClient) -> None:
    """TS-05 positive: a fresh token with matching pv is accepted normally."""
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert resp.status_code == 200


def test_TS05_stale_access_token_returns_401_after_pv_bump(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """TS-05/IDM-5 (RED): after a role change increments permissions_version,
    any outstanding access token carrying the old pv must return 401.

    Before implementation: the stale token continues to be accepted because
    there is no per-request pv comparison in get_current_user.
    """
    from sqlalchemy.orm import Session as OrmSession

    email = _unique_email()
    org_name = _unique_org_name()
    body = _signup(http_client, email=email, password="strong-password-1", org_name=org_name)
    access_token = body["access_token"]
    org_id = body["org_id"]
    user_id = body["user_id"]

    # Sanity: token works before pv bump.
    pre = http_client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert pre.status_code == 200, f"Expected 200 before pv bump, got {pre.status_code}"

    # Simulate a role change by manually bumping permissions_version in the DB.
    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        s.execute(
            text(
                "UPDATE app_user SET permissions_version = permissions_version + 1 "
                "WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        s.commit()

    # Old access token must now 401 (pv in token < user's current pv).
    post = http_client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert post.status_code == 401, (
        f"TS-05 FAIL: stale token still valid after pv bump (got {post.status_code}). "
        "get_current_user must reject tokens whose pv != user.permissions_version."
    )
