"""TASK-007: auth service — registration, login, JWT, refresh, MFA."""

from __future__ import annotations

import datetime
import time
import uuid

import jwt as pyjwt
import pyotp
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.config import get_settings
from app.exceptions import (
    AppValidationError,
    InvalidCredentialsError,
    TokenInvalidError,
)
from app.models import AppUser, Role
from app.models import Session as DbSession
from app.service import identity_service, rbac_service

# ──────────────────────────────────────────────────────────────────────
# Pure-Python: password hashing (no DB)
# ──────────────────────────────────────────────────────────────────────


def test_hash_and_verify_password_round_trip() -> None:
    hashed = identity_service.hash_password("hunter2-correct-horse")
    assert identity_service.verify_password("hunter2-correct-horse", hashed)
    assert not identity_service.verify_password("wrong-password", hashed)


def test_hash_password_rejects_empty() -> None:
    with pytest.raises(AppValidationError, match="empty"):
        identity_service.hash_password("")


def test_hash_password_rejects_too_short() -> None:
    with pytest.raises(AppValidationError, match="at least"):
        identity_service.hash_password("short")


def test_verify_password_rejects_garbage_hash() -> None:
    assert not identity_service.verify_password("anything", "not-a-valid-bcrypt-hash")


# ──────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────


def test_register_user_creates_row_with_hashed_password(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    user = identity_service.register_user(
        db_session,
        email="alice@example.com",
        password="alice-password-1234",
        org_id=fresh_org_id,
    )
    assert user.user_id is not None
    assert user.email == "alice@example.com"
    assert user.password_hash is not None
    assert user.password_hash != "alice-password-1234"
    assert identity_service.verify_password("alice-password-1234", user.password_hash)
    assert user.is_active is True


def test_register_user_duplicate_email_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    identity_service.register_user(
        db_session,
        email="dupe@example.com",
        password="some-password",
        org_id=fresh_org_id,
    )
    with pytest.raises(AppValidationError, match="already exists"):
        identity_service.register_user(
            db_session,
            email="dupe@example.com",
            password="other-password",
            org_id=fresh_org_id,
        )


def test_register_user_rejects_empty_email(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="email"):
        identity_service.register_user(
            db_session, email="", password="strong-password-1", org_id=fresh_org_id
        )


# ──────────────────────────────────────────────────────────────────────
# Login + JWT verify
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def signed_up_user(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> tuple[AppUser, uuid.UUID, str]:
    """Seed RBAC + create a user + assign Owner. Returns (user, org_id, plaintext_password)."""
    rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)
    roles = {
        r.code: r
        for r in db_session.execute(select(Role).where(Role.org_id == fresh_org_id)).scalars()
    }
    plaintext = "very-strong-password-2026"
    user = identity_service.register_user(
        db_session, email="owner@example.com", password=plaintext, org_id=fresh_org_id
    )
    rbac_service.assign_role(
        db_session,
        user_id=user.user_id,
        role_id=roles["OWNER"].role_id,
        firm_id=None,
        org_id=fresh_org_id,
    )
    return user, fresh_org_id, plaintext


def test_login_returns_distinct_access_and_refresh_tokens(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    _, org_id, password = signed_up_user
    pair = identity_service.login(
        db_session,
        email="owner@example.com",
        password=password,
        org_id=org_id,
    )
    assert pair.access_token != pair.refresh_token
    assert pair.access_expires_at < pair.refresh_expires_at
    # Session row was persisted with both hashes.
    rows = (
        db_session.execute(
            select(DbSession).where(
                DbSession.access_token_hash == identity_service._hash_token(pair.access_token)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


def test_login_wrong_password_raises_generic_error(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    _, org_id, _ = signed_up_user
    with pytest.raises(InvalidCredentialsError):
        identity_service.login(
            db_session,
            email="owner@example.com",
            password="wrong-password",
            org_id=org_id,
        )


def test_login_unknown_email_raises(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    _, org_id, _ = signed_up_user
    with pytest.raises(InvalidCredentialsError):
        identity_service.login(
            db_session,
            email="nobody@example.com",
            password="any-password",
            org_id=org_id,
        )


def test_login_inactive_user_raises(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    user, org_id, password = signed_up_user
    user.is_active = False
    db_session.flush()
    with pytest.raises(InvalidCredentialsError):
        identity_service.login(
            db_session, email="owner@example.com", password=password, org_id=org_id
        )


def test_login_updates_last_login_at(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    user, org_id, password = signed_up_user
    assert user.last_login_at is None
    identity_service.login(db_session, email="owner@example.com", password=password, org_id=org_id)
    db_session.refresh(user)
    assert user.last_login_at is not None


def test_verify_jwt_decodes_payload(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    user, org_id, password = signed_up_user
    pair = identity_service.login(
        db_session, email="owner@example.com", password=password, org_id=org_id
    )
    payload = identity_service.verify_jwt(pair.access_token)
    assert payload.user_id == user.user_id
    assert payload.org_id == org_id
    assert payload.firm_id is None
    assert payload.token_type == "access"
    # Owner role → all 38 system permissions.
    assert "sales.invoice.finalize" in payload.permissions
    assert "accounting.voucher.post" in payload.permissions
    refresh_payload = identity_service.verify_jwt(pair.refresh_token)
    assert refresh_payload.token_type == "refresh"


def test_verify_jwt_bad_signature_raises() -> None:
    settings = get_settings()
    bogus = pyjwt.encode({"sub": "x"}, settings.jwt_secret + "x", algorithm="HS256")
    with pytest.raises(TokenInvalidError):
        identity_service.verify_jwt(bogus)


def test_verify_jwt_expired_raises() -> None:
    settings = get_settings()
    payload: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "org_id": str(uuid.uuid4()),
        "firm_id": None,
        "permissions": [],
        "jti": "x",
        "iat": int(time.time()) - 3600,
        "exp": int(time.time()) - 1,
        "token_type": "access",
    }
    expired = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(TokenInvalidError, match="expired"):
        identity_service.verify_jwt(expired)


def test_verify_jwt_malformed_payload_raises() -> None:
    settings = get_settings()
    # Missing required keys.
    bad = pyjwt.encode(
        {"iat": int(time.time()), "exp": int(time.time()) + 60},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(TokenInvalidError, match="malformed"):
        identity_service.verify_jwt(bad)


# ──────────────────────────────────────────────────────────────────────
# Refresh
# ──────────────────────────────────────────────────────────────────────


def test_refresh_token_issues_new_pair_and_revokes_old(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    user, org_id, password = signed_up_user
    first = identity_service.login(
        db_session, email="owner@example.com", password=password, org_id=org_id
    )
    second = identity_service.refresh_token(db_session, refresh_token=first.refresh_token)

    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token

    # First session row revoked; new session row not revoked.
    rows = (
        db_session.execute(select(DbSession).where(DbSession.user_id == user.user_id))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    revoked = [r for r in rows if r.revoked_at is not None]
    assert len(revoked) == 1
    assert revoked[0].refresh_token_hash == identity_service._hash_token(first.refresh_token)


def test_refresh_token_with_access_token_raises(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    _, org_id, password = signed_up_user
    pair = identity_service.login(
        db_session, email="owner@example.com", password=password, org_id=org_id
    )
    with pytest.raises(TokenInvalidError, match="refresh token"):
        identity_service.refresh_token(db_session, refresh_token=pair.access_token)


def test_refresh_token_already_revoked_raises(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    _, org_id, password = signed_up_user
    pair = identity_service.login(
        db_session, email="owner@example.com", password=password, org_id=org_id
    )
    identity_service.refresh_token(db_session, refresh_token=pair.refresh_token)
    with pytest.raises(TokenInvalidError, match=r"not found|revoked"):
        identity_service.refresh_token(db_session, refresh_token=pair.refresh_token)


def test_refresh_token_unknown_token_raises(db_session: OrmSession) -> None:
    settings = get_settings()
    payload: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "org_id": str(uuid.uuid4()),
        "firm_id": None,
        "permissions": [],
        "jti": "x",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "token_type": "refresh",
    }
    token = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(TokenInvalidError, match="not found"):
        identity_service.refresh_token(db_session, refresh_token=token)


# ──────────────────────────────────────────────────────────────────────
# MFA (TOTP)
# ──────────────────────────────────────────────────────────────────────


def test_enable_mfa_returns_provisioning_uri_and_persists_secret(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    user, _, _ = signed_up_user
    enrollment = identity_service.enable_mfa(db_session, user_id=user.user_id)
    assert enrollment.provisioning_uri.startswith("otpauth://totp/")
    assert (
        "Fabric%20ERP" in enrollment.provisioning_uri or "Fabric ERP" in enrollment.provisioning_uri
    )
    db_session.refresh(user)
    assert user.mfa_enabled is True
    assert user.mfa_secret is not None
    # Stored secret matches what was returned.
    assert user.mfa_secret.decode("utf-8") == enrollment.secret


def test_verify_totp_valid_code_returns_true(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    user, _, _ = signed_up_user
    enrollment = identity_service.enable_mfa(db_session, user_id=user.user_id)
    code = pyotp.TOTP(enrollment.secret).now()
    assert identity_service.verify_totp(db_session, user_id=user.user_id, code=code) is True


def test_verify_totp_wrong_code_returns_false(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    user, _, _ = signed_up_user
    identity_service.enable_mfa(db_session, user_id=user.user_id)
    assert identity_service.verify_totp(db_session, user_id=user.user_id, code="000000") is False


def test_verify_totp_for_user_without_mfa_returns_false(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    user, _, _ = signed_up_user
    # No enable_mfa call.
    assert identity_service.verify_totp(db_session, user_id=user.user_id, code="123456") is False


def test_enable_mfa_for_unknown_user_raises(db_session: OrmSession) -> None:
    with pytest.raises(AppValidationError, match="not found"):
        identity_service.enable_mfa(db_session, user_id=uuid.uuid4())


# ──────────────────────────────────────────────────────────────────────
# Token TTLs match spec
# ──────────────────────────────────────────────────────────────────────


def test_access_token_ttl_is_15_minutes(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    _, org_id, password = signed_up_user
    pair = identity_service.login(
        db_session, email="owner@example.com", password=password, org_id=org_id
    )
    delta = pair.access_expires_at - datetime.datetime.now(tz=datetime.UTC)
    # Within 1s of 15 min; allow for clock drift / test latency.
    assert (
        datetime.timedelta(minutes=14, seconds=58)
        <= delta
        <= datetime.timedelta(minutes=15, seconds=2)
    )


def test_refresh_token_ttl_is_14_days(
    db_session: OrmSession, signed_up_user: tuple[AppUser, uuid.UUID, str]
) -> None:
    _, org_id, password = signed_up_user
    pair = identity_service.login(
        db_session, email="owner@example.com", password=password, org_id=org_id
    )
    delta = pair.refresh_expires_at - datetime.datetime.now(tz=datetime.UTC)
    assert (
        datetime.timedelta(days=13, hours=23, minutes=58)
        <= delta
        <= datetime.timedelta(days=14, seconds=2)
    )
