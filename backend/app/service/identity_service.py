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
- MFA: pyotp TOTP. Secret is AES-256-GCM-encrypted at rest under the
  org's DEK (same envelope as `party.gstin` / `bank_account.account_number`)
  via `app.utils.crypto.encrypt_pii`. Legacy plaintext-bytes rows written
  before TR-SEC1's review fix-pass are read transparently via the
  version-byte fallback and upgrade on the next write.

Out of scope (per the grand plan):
- Redis-backed refresh-token rotation + denylist → TASK-017.
- Real RBAC permission gate in routers → TASK-016.
- Session/device binding strictness → TASK-007 follow-up.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Final, Literal

import bcrypt
import jwt
import pyotp
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions import (
    AppValidationError,
    InvalidCredentialsError,
    MfaAlreadyEnabledError,
    TokenInvalidError,
)
from app.models import AppUser
from app.models import Session as DbSession
from app.service import rbac_service
from app.utils import crypto

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────


_ACCESS_TOKEN_TTL_SECONDS: Final[int] = 15 * 60  # 15 min
_REFRESH_TOKEN_TTL_SECONDS: Final[int] = 14 * 24 * 3600  # 14 days
_BCRYPT_ROUNDS: Final[int] = 12
_JWT_ALG: Final[str] = "HS256"  # RS256 + key rotation later.
_TOTP_ISSUER: Final[str] = "Fabric ERP"
_MIN_PASSWORD_LENGTH: Final[int] = 8
# TOTP replay guard: TTL for used-code Redis keys (covers 3 x 30s windows = 90s)
_TOTP_REPLAY_TTL: Final[int] = 90

# DOS-02 / API-7-03 — Timing oracle: unknown-user path must NOT skip bcrypt.
#
# When a login attempt fails because the user does not exist, the original code
# short-circuited before calling bcrypt, making the response ~100ms faster than a
# "user found, wrong password" response. An attacker can distinguish "email not
# registered" from "wrong password" by measuring response latency.
#
# Fix: always call `verify_password()` — even when no user was found — against this
# pre-computed dummy hash. The dummy hash is computed ONCE at module import (single
# ~100ms cost) and reused for every unknown-user attempt, normalising timing.
#
# The hash is for an internal sentinel value that MUST NOT match any real password.
# It is exposed as a module-level public constant so auth.py and the reset path can
# both reference it without duplicating the sentinel logic.
DUMMY_BCRYPT_HASH: Final[str] = bcrypt.hashpw(
    b"_fabric_dummy_sentinel_for_timing_normalisation_",
    bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
).decode("utf-8")


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
    # TS-05/IDM-5: permissions_version claim — must match the user's live
    # `permissions_version` column on every authenticated request. Tokens
    # issued before this field existed carry pv=0; since the DB default for
    # new users is 1, those legacy tokens are REJECTED as stale (not silently
    # accepted). Re-authenticate to receive a fresh token with the correct pv.
    pv: int = 0


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
        # TS-05/IDM-5: embed the user's current permissions_version so
        # per-request middleware can reject tokens issued before a role change.
        "pv": user.permissions_version,
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
            # TS-05/IDM-5: default to 0 for tokens issued before this claim
            # existed so old tokens don't crash but ARE caught by the per-request
            # check (user.permissions_version starts at 1 by DB default).
            pv=int(payload.get("pv", 0)),
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

    # The refresh request bypasses the JWT-driven RLS plumbing in
    # `dependencies.get_db_sync` (no Authorization header). Seed the
    # GUC ourselves now that the token has identified the org. Without
    # this, the session/app_user lookups below return zero rows under
    # `fabric_app` (NOBYPASSRLS) and refresh fails to find its own
    # session row.
    session.execute(text(f"SET LOCAL app.current_org_id = '{payload.org_id}'"))

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

    M1 fix: the TOTP shared secret is encrypted at rest via the org's
    DEK (AES-256-GCM, same envelope used for `party.gstin` etc.). The
    previous implementation persisted it as bare UTF-8 bytes, which
    made a DB-only read into a TOTP-forgery primitive.
    """
    user = session.execute(
        select(AppUser).where(AppUser.user_id == user_id, AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None:
        raise AppValidationError(f"User {user_id} not found")

    secret = pyotp.random_base32()
    dek = crypto.get_org_dek(session, org_id=user.org_id)
    user.mfa_secret = crypto.encrypt_pii(secret, dek=dek, org_id=user.org_id)
    user.mfa_enabled = True

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name=_TOTP_ISSUER)

    session.flush()
    return MfaEnrollment(secret=secret, provisioning_uri=provisioning_uri)


def prepare_mfa_enrollment(session: Session, *, user_id: uuid.UUID) -> MfaEnrollment:
    """Generate and persist a TOTP secret, but do NOT set mfa_enabled=True.

    The caller must follow up with verify_totp + explicit `user.mfa_enabled = True`
    (POST /auth/mfa/confirm) to activate MFA for the user. This two-step flow
    ensures the user has successfully scanned the QR code and generated a valid
    code before MFA is enforced on login.

    Unlike `enable_mfa`, calling this function does not gate the user's next
    login behind TOTP — it only provisions the secret so the confirm step can
    verify it.
    """
    user = session.execute(
        select(AppUser).where(AppUser.user_id == user_id, AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None:
        raise AppValidationError(f"User {user_id} not found")

    # Cycle-2 Fix 1: block re-enrollment when MFA is already active.
    # A stolen access token must not be able to overwrite the live mfa_secret
    # and rebind the victim's authenticator. The admin must explicitly reset MFA
    # (e.g. via a future admin endpoint) before re-enrollment is permitted.
    if user.mfa_enabled:
        raise MfaAlreadyEnabledError(
            "MFA already enabled; contact an admin to reset before re-enrolling"
        )

    secret = pyotp.random_base32()
    dek = crypto.get_org_dek(session, org_id=user.org_id)
    user.mfa_secret = crypto.encrypt_pii(secret, dek=dek, org_id=user.org_id)
    # NOTE: deliberately do NOT set user.mfa_enabled = True here.
    # mfa_enabled is set in the confirm step after the user validates the code.

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name=_TOTP_ISSUER)

    session.flush()
    return MfaEnrollment(secret=secret, provisioning_uri=provisioning_uri)


def _run_totp_replay_check(
    redis_client: Any, replay_key: str, *, close_after: bool = False
) -> bool:
    """Sync wrapper: check Redis for TOTP replay and mark the code as used.

    Returns True if the code has already been used (replay detected).
    Returns False if it's the first use (marks the key in Redis).
    Returns False on any Redis error (fail-open convention).

    Uses asyncio.run() because the Redis client is async and this service
    function is sync (called from sync FastAPI handlers in a threadpool).
    In a threadpool there is no running event loop, so asyncio.run() is safe.

    close_after=True: call `await redis_client.aclose()` in a finally block
    after the operation. Set this when the caller built a fresh client from
    URL (production path). Do NOT set it for the test-injected client (shared
    across tests) — closing it would break other tests.
    """

    async def _do() -> bool:
        try:
            already = await redis_client.exists(replay_key)
            if already:
                return True
            await redis_client.setex(replay_key, _TOTP_REPLAY_TTL, "1")
            return False
        finally:
            if close_after:
                await redis_client.aclose()

    # Check for a running event loop (async context — shouldn't happen for sync
    # handlers but guard against it). Fail-open: no replay protection in async ctx.
    try:
        asyncio.get_running_loop()
        return False  # fail-open in async context
    except RuntimeError:
        pass  # no running loop — safe to use asyncio.run()

    try:
        return asyncio.run(_do())
    except Exception:
        return False  # fail-open on any Redis error


def verify_totp(session: Session, *, user_id: uuid.UUID, code: str) -> bool:
    """Verify a 6-digit TOTP code. Returns True/False; doesn't raise.

    Uses `valid_window=1` to accept the previous + next 30s slot, which is
    standard for TOTP and forgives small clock skew between server + phone.

    IDM-4 replay guard: after a successful pyotp verification, a Redis key
    `totp:used:<user_id>:<code>` is SET with a 90s TTL. A second call with
    the same code within that window returns False. Redis-None → fail-open
    (no replay tracking, same dev-fallback convention as rate limiting).

    M1 fix: the persisted `mfa_secret` bytes are AES-GCM ciphertext under
    the org's DEK; decrypt before passing to pyotp. The legacy
    plaintext-bytes path is handled transparently by `decrypt_pii` (the
    version-byte discriminator falls back to UTF-8 decode for pre-fix
    rows), so existing enrolments keep working.
    """
    user = session.execute(
        select(AppUser).where(AppUser.user_id == user_id, AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None or user.mfa_secret is None:
        return False
    dek = crypto.get_org_dek(session, org_id=user.org_id)
    secret = crypto.decrypt_pii(user.mfa_secret, dek=dek, org_id=user.org_id)
    if secret is None:
        return False
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return False

    # IDM-4: TOTP replay guard.
    # Key the used-code by (user_id, code string) with _TOTP_REPLAY_TTL (90s).
    # This rejects any replay within the 3-slot window (prev/current/next x 30s).
    #
    # Cycle-2 Fix 3: close fresh clients after use to prevent FD leaks.
    # _get_redis() returns either the test-injected client (_test_redis_client, shared
    # across tests — must NOT be closed) or a freshly-built aioredis client from URL
    # (production — must be closed so asyncio.run()'s loop teardown doesn't orphan
    # the connection pool). We detect this by checking whether _test_redis_client is set.
    # Lazy imports to avoid circular dependency (rate_limit imports config which imports settings)
    from app.middleware.rate_limit import (
        _get_redis,
        _is_test_redis_injected,
    )

    redis = _get_redis()
    if redis is not None:
        replay_key = f"totp:used:{user_id}:{code}"
        # close_after=True only when freshly built from URL (no injected test client).
        # The injected fakeredis is shared; closing it between calls breaks other tests.
        _close_after = not _is_test_redis_injected()
        is_replay = _run_totp_replay_check(redis, replay_key, close_after=_close_after)
        if is_replay:
            return False

    return True
