"""#208: case-insensitive email login + auto-firm in signup/mfa tokens.

Two onboarding defects fixed here:

  (a) Email was matched byte-for-byte on login / mfa-verify / reset while
      invites stored it lowercased and signup stored it as-typed — so an
      invited user (or a mixed-case signup) got a hard 401 lockout. Fix:
      one `normalize_email` helper applied at every write AND lookup, an
      Alembic backfill, and a `(org_id, lower(email))` unique index.

  (b) The signup token carried `firm_id=None` even though the org's sole
      firm was just created, so firm-scoped endpoints 403'd "No active
      firm". Fix: pass `firm.firm_id` (mirroring login's auto-select);
      mfa-verify gets the same single-firm auto-select.

Real Postgres, app over TestClient (mirrors test_auth_routers.py). Uses
unique org/email per test so rows don't collide across the shared DB.
"""

from __future__ import annotations

import uuid

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, EmailTakenError
from app.models import AppUser, PasswordResetToken, Role
from app.service import identity_service, invite_service, password_reset_service
from tests.conftest import org_scoped_session

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _unique_org_name() -> str:
    return f"CaseOrg {uuid.uuid4().hex[:8]}"


def _signup(
    client: TestClient,
    *,
    email: str,
    password: str,
    org_name: str,
    firm_name: str = "Primary Firm",
) -> dict[str, str]:
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": password,
            "org_name": org_name,
            "firm_name": firm_name,
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _owner_role_id(engine: Engine, org_id: uuid.UUID) -> uuid.UUID:
    with org_scoped_session(engine, org_id) as s:
        role = s.execute(
            select(Role).where(Role.org_id == org_id, Role.code == "OWNER")
        ).scalar_one()
        return role.role_id


def _enable_mfa_for(engine: Engine, user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    with OrmSession(engine, expire_on_commit=False) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        enrollment = identity_service.enable_mfa(s, user_id=user_id)
        s.commit()
    return enrollment.secret


# ──────────────────────────────────────────────────────────────────────
# (a) Case-insensitive email
# ──────────────────────────────────────────────────────────────────────


def test_login_with_mixed_case_email_succeeds(http_client: TestClient) -> None:
    """Signup with a mixed-case email; login with any casing → 200."""
    org_name = _unique_org_name()
    password = "strong-password-1"
    _signup(http_client, email="Owner-208@Example.COM", password=password, org_name=org_name)

    for typed in ("owner-208@example.com", "OWNER-208@EXAMPLE.COM"):
        resp = http_client.post(
            "/auth/login",
            json={"email": typed, "password": password, "org_name": org_name},
        )
        assert resp.status_code == 200, f"{typed}: {resp.text}"
        body = resp.json()
        assert body["requires_mfa"] is False
        assert body["access_token"]


def test_invited_user_can_login_with_mixed_case_email(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """The literal QA lockout: invite stores lowercase, user logs in with
    the mixed-case original → must succeed."""
    org_name = _unique_org_name()
    owner = _signup(
        http_client,
        email="owner-inv-208@example.com",
        password="strong-password-1",
        org_name=org_name,
    )
    org_id = uuid.UUID(owner["org_id"])
    owner_id = uuid.UUID(owner["user_id"])
    role_id = _owner_role_id(sync_engine, org_id)

    invited_email = "QA-Lowpriv-208@X.com"
    invited_password = "invited-password-9"
    with org_scoped_session(sync_engine, org_id) as s:
        result = invite_service.create_invite(
            s,
            org_id=org_id,
            invited_by=owner_id,
            email=invited_email,
            role_id=role_id,
            firm_id=None,
        )
        raw_token = result.raw_token
    with org_scoped_session(sync_engine, org_id) as s:
        invite_service.accept_invite(
            s, token=raw_token, name="QA Lowpriv", password=invited_password
        )

    resp = http_client.post(
        "/auth/login",
        json={"email": invited_email, "password": invited_password, "org_name": org_name},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


def test_signup_stores_email_lowercased(http_client: TestClient, sync_engine: Engine) -> None:
    org_name = _unique_org_name()
    body = _signup(
        http_client,
        email="Mixed-Case-208@Example.COM",
        password="strong-password-1",
        org_name=org_name,
    )
    org_id = uuid.UUID(body["org_id"])
    with org_scoped_session(sync_engine, org_id) as s:
        stored_email = s.execute(
            select(AppUser.email).where(AppUser.user_id == uuid.UUID(body["user_id"]))
        ).scalar_one()
        admin_email = s.execute(
            text("SELECT admin_email FROM organization WHERE org_id = :o"),
            {"o": str(org_id)},
        ).scalar_one()
    assert stored_email == "mixed-case-208@example.com"
    assert admin_email == "mixed-case-208@example.com"


def test_duplicate_email_differing_only_by_case_rejected(
    http_client: TestClient, sync_engine: Engine
) -> None:
    org_name = _unique_org_name()
    body = _signup(
        http_client, email="dup-208@x.com", password="strong-password-1", org_name=org_name
    )
    org_id = uuid.UUID(body["org_id"])
    owner_id = uuid.UUID(body["user_id"])
    role_id = _owner_role_id(sync_engine, org_id)

    with org_scoped_session(sync_engine, org_id) as s, pytest.raises(AppValidationError):
        identity_service.register_user(
            s, email="DUP-208@X.COM", password="strong-password-1", org_id=org_id
        )
    with org_scoped_session(sync_engine, org_id) as s, pytest.raises(EmailTakenError):
        invite_service.create_invite(
            s,
            org_id=org_id,
            invited_by=owner_id,
            email="Dup-208@X.Com",
            role_id=role_id,
            firm_id=None,
        )


def test_db_unique_index_blocks_mixed_case_duplicate(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A raw INSERT of a case-variant email in the same org must trip the
    new `uq_app_user_org_lower_email` index (the plain constraint is
    case-sensitive and would let it through)."""
    org_name = _unique_org_name()
    body = _signup(
        http_client, email="idx-208@x.com", password="strong-password-1", org_name=org_name
    )
    org_id = uuid.UUID(body["org_id"])
    with pytest.raises(IntegrityError) as exc, org_scoped_session(sync_engine, org_id) as s:
        s.execute(
            text(
                "INSERT INTO app_user (org_id, email, password_hash, is_active) "
                "VALUES (:o, :e, :h, true)"
            ),
            {"o": str(org_id), "e": "IDX-208@X.COM", "h": "x"},
        )
    assert "uq_app_user_org_lower_email" in str(exc.value)


def test_forgot_password_mixed_case_email_creates_token(
    http_client: TestClient, sync_engine: Engine
) -> None:
    org_name = _unique_org_name()
    body = _signup(
        http_client, email="forgot-208@x.com", password="strong-password-1", org_name=org_name
    )
    org_id = uuid.UUID(body["org_id"])
    user_id = uuid.UUID(body["user_id"])

    with org_scoped_session(sync_engine, org_id) as s:
        password_reset_service.request_reset(s, email="Forgot-208@X.COM", org_name=org_name)
    with org_scoped_session(sync_engine, org_id) as s:
        rows = (
            s.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
            .scalars()
            .all()
        )
    assert len(rows) == 1


def test_mfa_verify_mixed_case_email(http_client: TestClient, sync_engine: Engine) -> None:
    org_name = _unique_org_name()
    password = "strong-password-1"
    body = _signup(http_client, email="mfa-208@x.com", password=password, org_name=org_name)
    secret = _enable_mfa_for(sync_engine, uuid.UUID(body["user_id"]), uuid.UUID(body["org_id"]))

    resp = http_client.post(
        "/auth/mfa-verify",
        json={
            "email": "MFA-208@X.COM",
            "password": password,
            "org_name": org_name,
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


# ──────────────────────────────────────────────────────────────────────
# (b) Auto-firm in signup / mfa tokens
# ──────────────────────────────────────────────────────────────────────


def test_signup_token_carries_sole_firm_id(http_client: TestClient) -> None:
    org_name = _unique_org_name()
    body = _signup(
        http_client, email="firm-208@x.com", password="strong-password-1", org_name=org_name
    )
    payload = identity_service.verify_jwt(body["access_token"])
    assert payload.firm_id is not None
    assert str(payload.firm_id) == body["firm_id"]
    assert len(payload.permissions) > 0  # Owner permission snapshot present


def test_signup_token_reaches_firm_scoped_endpoint(http_client: TestClient) -> None:
    """The exact QA repro (b): the raw signup token hits /reports/tb with
    no 'No active firm' 403."""
    org_name = _unique_org_name()
    body = _signup(
        http_client, email="scoped-208@x.com", password="strong-password-1", org_name=org_name
    )
    resp = http_client.get(
        "/reports/tb", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert resp.status_code == 200, resp.text


def test_mfa_verify_token_autofills_single_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    org_name = _unique_org_name()
    password = "strong-password-1"
    body = _signup(http_client, email="mfa-firm-208@x.com", password=password, org_name=org_name)
    secret = _enable_mfa_for(sync_engine, uuid.UUID(body["user_id"]), uuid.UUID(body["org_id"]))

    resp = http_client.post(
        "/auth/mfa-verify",
        json={
            "email": "mfa-firm-208@x.com",
            "password": password,
            "org_name": org_name,
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )
    assert resp.status_code == 200, resp.text
    payload = identity_service.verify_jwt(resp.json()["access_token"])
    assert payload.firm_id is not None
    assert str(payload.firm_id) == body["firm_id"]


# ──────────────────────────────────────────────────────────────────────
# Regression guards
# ──────────────────────────────────────────────────────────────────────


def test_login_multi_firm_still_returns_null_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Multi-firm org: login must keep firm_id None and list both firms
    (protects login's auto-select semantics)."""
    org_name = _unique_org_name()
    password = "strong-password-1"
    body = _signup(http_client, email="multi-208@x.com", password=password, org_name=org_name)
    org_id = uuid.UUID(body["org_id"])
    # Add a second firm so the org has two live firms.
    with org_scoped_session(sync_engine, org_id) as s:
        s.execute(
            text("INSERT INTO firm (org_id, code, name, has_gst) VALUES (:o, :c, :n, false)"),
            {"o": str(org_id), "c": f"F2-{uuid.uuid4().hex[:6]}", "n": "Second Firm"},
        )

    resp = http_client.post(
        "/auth/login",
        json={"email": "multi-208@x.com", "password": password, "org_name": org_name},
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["firm_id"] is None
    assert len(out["available_firms"]) == 2
    payload = identity_service.verify_jwt(out["access_token"])
    assert payload.firm_id is None


def test_same_email_different_orgs_still_allowed(http_client: TestClient) -> None:
    """Per-org email scoping: the same (differently-cased) email can own
    two distinct orgs."""
    email_a = "shared-208@x.com"
    email_b = "SHARED-208@X.COM"
    b1 = _signup(
        http_client, email=email_a, password="strong-password-1", org_name=_unique_org_name()
    )
    b2 = _signup(
        http_client, email=email_b, password="strong-password-1", org_name=_unique_org_name()
    )
    assert b1["org_id"] != b2["org_id"]
