"""Auth service — registration, login, JWT issue/verify, refresh, MFA.

Tokens:
- Access JWT (HS256, 15-min TTL) carries `user_id`, `org_id`, `firm_id`,
  `permissions[]` (snapshotted from rbac_service at issue time), `jti`,
  `iat`, `exp`, `token_type="access"`.
- Refresh JWT (HS256, 14-day TTL) has the same shape but
  `token_type="refresh"`.
- A `session` row is created per token pair holding SHA-256 hashes of
  both tokens. `refresh_token` checks the row for `revoked_at IS NULL`
  and `expires_at > now`. The row's `expires_at` tracks the OUTER
  envelope (the refresh token's expiry — the session as a whole).

Crypto:
- Passwords: bcrypt cost factor 12.
- JWT: HS256 with `settings.jwt_secret`. RS256 + key rotation lands later.
- MFA: pyotp TOTP. Secret stored as plaintext bytes in
  `app_user.mfa_secret` BYTEA today; AES-GCM envelope encryption
  (architecture §5.4) is a future task — schema column doesn't change.

Out of scope (per the grand plan):
- Redis-backed refresh-token rotation + denylist → TASK-017.
- Real RBAC permission gate in routers → TASK-016.
- Session/device binding strictness → TASK-007 follow-up.
"""

from __future__ import annotations

import datetime
import hashlib
import uuid
from dataclasses import dataclass
from typing import Final, Literal

import bcrypt
import jwt
import pyotp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions import (
    AppValidationError,
    InvalidCredentialsError,
    TokenInvalidError,
)
from app.models import AppUser
from app.models import Session as DbSession
from app.service import rbac_service

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────


_ACCESS_TOKEN_TTL_SECONDS: Final[int] = 15 * 60  # 15 min
_REFRESH_TOKEN_TTL_SECONDS: Final[int] = 14 * 24 * 3600  # 14 days
_BCRYPT_ROUNDS: Final[int] = 12
_JWT_ALG: Final[str] = "HS256"  # RS256 + key rotation later.
_TOTP_ISSUER: Final[str] = "Fabric ERP"
_MIN_PASSWORD_LENGTH: Final[int] = 8


@dataclass(frozen=True)
class TokenPayload:
    user_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID | None
    permissions: tuple[str, ...]
    jti: str
    iat: int
    exp: int
    token_type: Literal["access", "refresh"]


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime.datetime
    refresh_expires_at: datetime.datetime


@dataclass(frozen=True)
class MfaEnrollment:
    secret: str  # base32 string, suitable for QR encoding
    provisioning_uri: str  # otpauth:// URI


# ──────────────────────────────────────────────────────────────────────
# Password hashing
# ──────────────────────────────────────────────────────────────────────


def hash_password(plaintext: str) -> str:
    if not plaintext:
        raise AppValidationError("Password cannot be empty")
    if len(plaintext) < _MIN_PASSWORD_LENGTH:
        raise AppValidationError(f"Password must be at least {_MIN_PASSWORD_LENGTH} characters")
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode(
        "utf-8"
    )


def verify_password(plaintext: str, hashed: str) -> bool:
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ──────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────


def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    org_id: uuid.UUID,
) -> AppUser:
    """Create an AppUser. Caller wires role assignment via `rbac_service`.

    Raises `AppValidationError` for empty fields, weak passwords, or duplicate
    email within the same org. Email uniqueness is also DB-enforced via the
    `app_user_org_id_email_key` unique constraint.
    """
    if not email:
        raise AppValidationError("email is required")

    existing = session.execute(
        select(AppUser).where(AppUser.org_id == org_id, AppUser.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"User with email {email!r} already exists in this org")

    user = AppUser(
        org_id=org_id,
        email=email,
        password_hash=hash_password(password),
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


# ──────────────────────────────────────────────────────────────────────
# JWT issue + verify
# ──────────────────────────────────────────────────────────────────────


def _hash_token(token: str) -> str:
    """SHA-256 hex digest. Stored in session.access_token_hash / refresh_token_hash."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.UTC)


def _issue_jwt(
    *,
    user: AppUser,
    firm_id: uuid.UUID | None,
    permissions: list[str],
    token_type: Literal["access", "refresh"],
    ttl_seconds: int,
) -> tuple[str, datetime.datetime, str]:
    """Returns (encoded_jwt, expires_at, jti)."""
    settings = get_settings()
    now = _now_utc()
    exp = now + datetime.timedelta(seconds=ttl_seconds)
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user.user_id),
        "org_id": str(user.org_id),
        "firm_id": str(firm_id) if firm_id is not None else None,
        "permissions": permissions,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "token_type": token_type,
    }
    encoded = jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALG)
    return encoded, exp, jti


def issue_tokens(
    session: Session,
    *,
    user: AppUser,
    firm_id: uuid.UUID | None,
) -> TokenPair:
    """Generate access + refresh tokens. Persists a `session` row holding
    the SHA-256 hash of both tokens + the refresh expiry as the outer
    envelope.
    """
    permissions = sorted(
        rbac_service.get_user_permissions(session, user_id=user.user_id, firm_id=firm_id)
    )
    access_jwt, access_exp, _ = _issue_jwt(
        user=user,
        firm_id=firm_id,
        permissions=permissions,
        token_type="access",  # noqa: S106 — JWT type discriminator, not a credential
        ttl_seconds=_ACCESS_TOKEN_TTL_SECONDS,
    )
    refresh_jwt, refresh_exp, _ = _issue_jwt(
        user=user,
        firm_id=firm_id,
        permissions=permissions,
        token_type="refresh",  # noqa: S106 — JWT type discriminator, not a credential
        ttl_seconds=_REFRESH_TOKEN_TTL_SECONDS,
    )
    db_session_row = DbSession(
        org_id=user.org_id,
        user_id=user.user_id,
        access_token_hash=_hash_token(access_jwt),
        refresh_token_hash=_hash_token(refresh_jwt),
        expires_at=refresh_exp,
    )
    session.add(db_session_row)
    session.flush()
    return TokenPair(
        access_token=access_jwt,
        refresh_token=refresh_jwt,
        access_expires_at=access_exp,
        refresh_expires_at=refresh_exp,
    )


def verify_jwt(token: str) -> TokenPayload:
    """Decode and validate. Raises `TokenInvalidError` on any failure
    (bad signature, expired, malformed payload).
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALG])
    except jwt.ExpiredSignatureError as exc:
        raise TokenInvalidError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError(f"Invalid token: {exc}") from exc

    try:
        return TokenPayload(
            user_id=uuid.UUID(payload["sub"]),
            org_id=uuid.UUID(payload["org_id"]),
            firm_id=uuid.UUID(payload["firm_id"]) if payload.get("firm_id") else None,
            permissions=tuple(payload.get("permissions", [])),
            jti=str(payload["jti"]),
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
            token_type=payload.get("token_type", "access"),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenInvalidError(f"Token payload malformed: {exc}") from exc


# ──────────────────────────────────────────────────────────────────────
# Login + refresh
# ──────────────────────────────────────────────────────────────────────


def login(
    session: Session,
    *,
    email: str,
    password: str,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
) -> TokenPair:
    """Verify credentials, issue tokens, persist session row, update
    `last_login_at`.

    Always raises `InvalidCredentialsError` on failure with a generic
    message — never leak whether the email is registered or whether the
    password was wrong vs the account being suspended.
    """
    user = session.execute(
        select(AppUser).where(
            AppUser.org_id == org_id,
            AppUser.email == email,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if user is None or not user.password_hash:
        raise InvalidCredentialsError("Invalid email or password")
    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid email or password")
    if not user.is_active or user.is_suspended:
        raise InvalidCredentialsError("Invalid email or password")

    user.last_login_at = _now_utc()
    session.flush()
    return issue_tokens(session, user=user, firm_id=firm_id)


def refresh_token(session: Session, *, refresh_token: str) -> TokenPair:
    """Validate a refresh token, revoke the old session row, issue a fresh pair.

    Raises `TokenInvalidError` for missing/expired/revoked tokens or if the
    presented token is an access token.
    """
    payload = verify_jwt(refresh_token)
    if payload.token_type != "refresh":  # noqa: S105 — JWT type discriminator
        raise TokenInvalidError("Expected refresh token, got access token")

    db_session_row = session.execute(
        select(DbSession).where(
            DbSession.user_id == payload.user_id,
            DbSession.refresh_token_hash == _hash_token(refresh_token),
        )
    ).scalar_one_or_none()
    if db_session_row is None:
        raise TokenInvalidError("Refresh token not found")
    if db_session_row.revoked_at is not None:
        raise TokenInvalidError("Refresh token has been revoked")
    if db_session_row.expires_at < _now_utc():
        raise TokenInvalidError("Refresh token has expired")

    user = session.execute(
        select(AppUser).where(AppUser.user_id == payload.user_id)
    ).scalar_one_or_none()
    if user is None or not user.is_active or user.is_suspended:
        raise TokenInvalidError("User is no longer active")

    db_session_row.revoked_at = _now_utc()
    session.flush()
    return issue_tokens(session, user=user, firm_id=payload.firm_id)


# ──────────────────────────────────────────────────────────────────────
# MFA (TOTP)
# ──────────────────────────────────────────────────────────────────────


def enable_mfa(session: Session, *, user_id: uuid.UUID) -> MfaEnrollment:
    """Generate a TOTP secret, persist it, return secret + provisioning URI.

    UI calls this at "enable MFA" → renders the URI as a QR. User scans
    with Google Authenticator / 1Password / etc. → next time they log in,
    the router calls `verify_totp` with the 6-digit code.
    """
    user = session.execute(
        select(AppUser).where(AppUser.user_id == user_id, AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None:
        raise AppValidationError(f"User {user_id} not found")

    secret = pyotp.random_base32()
    user.mfa_secret = secret.encode("utf-8")
    user.mfa_enabled = True

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name=_TOTP_ISSUER)

    session.flush()
    return MfaEnrollment(secret=secret, provisioning_uri=provisioning_uri)


def verify_totp(session: Session, *, user_id: uuid.UUID, code: str) -> bool:
    """Verify a 6-digit TOTP code. Returns True/False; doesn't raise.

    Uses `valid_window=1` to accept the previous + next 30s slot, which is
    standard for TOTP and forgives small clock skew between server + phone.
    """
    user = session.execute(
        select(AppUser).where(AppUser.user_id == user_id, AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None or user.mfa_secret is None:
        return False
    secret_raw = user.mfa_secret
    secret = secret_raw.decode("utf-8") if isinstance(secret_raw, bytes) else str(secret_raw)
    totp = pyotp.TOTP(secret)
    return bool(totp.verify(code, valid_window=1))
