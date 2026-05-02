"""Auth routes — signup, login, refresh, MFA verify, logout (TASK-008).

Sync handlers; FastAPI runs them in a threadpool. This matches the sync
service layer (`identity_service`, `rbac_service`) and avoids the
`asyncio.to_thread` wrapping the retros for those tasks discussed.

`Idempotency-Key` header is accepted on all mutating endpoints. Real
dedupe lands in TASK-017 (Redis-backed via `api_idempotency` table).
For now we only validate the header is a UUID v4 if present — clients
that send a key won't be rejected; the server just doesn't dedupe yet.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Cookie, Header, HTTPException, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.dependencies import CurrentUser, SyncDBSession
from app.exceptions import (
    AppValidationError,
    InvalidCredentialsError,
    TokenInvalidError,
)
from app.models import AppUser, Firm, Organization, Role
from app.models import Session as DbSession
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    MeResponse,
    MfaVerifyRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPairResponse,
)
from app.service import feature_flag_service, identity_service, rbac_service, seed_service

router = APIRouter(prefix="/auth", tags=["auth"])

# Per Q2 (hybrid token storage): refresh token in httpOnly Secure
# SameSite=Lax cookie; access token in memory on the frontend.
REFRESH_COOKIE_NAME = "fabric_refresh"


def _set_refresh_cookie(response: Response, refresh_token: str, *, max_age_seconds: int) -> None:
    """Write the refresh-token cookie. Secure=True except in dev so
    Playwright + curl over http://localhost still work without HTTPS.
    """
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=max_age_seconds,
        httponly=True,
        secure=settings.environment != "dev",
        samesite="lax",
        path="/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/auth")


def _seconds_until(when: datetime.datetime) -> int:
    delta = when - datetime.datetime.now(tz=datetime.UTC)
    return max(int(delta.total_seconds()), 0)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _validate_idempotency_key(idempotency_key: str | None) -> None:
    """Accept and validate the header shape; real dedupe lands in TASK-017.

    Clients can send any UUID string; we only confirm well-formed-ness so
    a malformed key surfaces a 422 here rather than a confusing 500 later.
    """
    if idempotency_key is None:
        return
    try:
        uuid.UUID(idempotency_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "validation_error", "detail": "Idempotency-Key must be a UUID"},
        ) from exc


def _resolve_org_by_name(session: SyncDBSession, org_name: str) -> Organization:
    org = session.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()
    if org is None:
        # Same generic message login uses — don't leak whether the org exists.
        raise InvalidCredentialsError("Invalid email or password")
    return org


def _make_firm_code(firm_name: str) -> str:
    """Auto-generate a firm code from the name. Uppercase alphanumerics,
    truncated to 10 chars (the DDL `firm.code` length limit). Adds a UUID
    suffix if the cleaned-up name is empty so we always satisfy the
    NOT-NULL + per-org-uniqueness constraints.
    """
    cleaned = "".join(c for c in firm_name.upper() if c.isalnum())[:10]
    if not cleaned:
        cleaned = uuid.uuid4().hex[:10].upper()
    return cleaned


# ──────────────────────────────────────────────────────────────────────
# Signup — public; orchestrates org + firm + user + RBAC + login
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create org + firm + Owner user; return tokens",
)
def signup(
    body: SignupRequest,
    db: SyncDBSession,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SignupResponse:
    _validate_idempotency_key(idempotency_key)

    # Org-name uniqueness is DB-enforced (organization.name UNIQUE). Surface
    # a clean 422 here rather than waiting for the IntegrityError.
    if db.execute(select(Organization).where(Organization.name == body.org_name)).first():
        raise AppValidationError(f"Organization {body.org_name!r} already exists")

    org = Organization(name=body.org_name, admin_email=body.email)
    db.add(org)
    db.flush()

    firm = Firm(
        org_id=org.org_id,
        code=_make_firm_code(body.firm_name),
        name=body.firm_name,
        has_gst=True,
    )
    db.add(firm)
    db.flush()

    rbac_service.seed_system_roles(db, org_id=org.org_id)
    seed_service.seed_system_catalog(db, org_id=org.org_id)
    roles_owner = db.execute(
        select(Role).where(Role.org_id == org.org_id, Role.code == "OWNER")
    ).scalar_one()

    user = identity_service.register_user(
        db, email=body.email, password=body.password, org_id=org.org_id
    )
    rbac_service.assign_role(
        db,
        user_id=user.user_id,
        role_id=roles_owner.role_id,
        firm_id=None,
        org_id=org.org_id,
    )

    pair = identity_service.issue_tokens(db, user=user, firm_id=None)
    _set_refresh_cookie(
        response,
        pair.refresh_token,
        max_age_seconds=_seconds_until(pair.refresh_expires_at),
    )
    return SignupResponse(
        user_id=user.user_id,
        org_id=org.org_id,
        firm_id=firm.firm_id,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
    )


# ──────────────────────────────────────────────────────────────────────
# Login — public
# ──────────────────────────────────────────────────────────────────────


@router.post("/login", response_model=LoginResponse, summary="Verify creds; gate on MFA")
def login(
    body: LoginRequest,
    db: SyncDBSession,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LoginResponse:
    _validate_idempotency_key(idempotency_key)
    org = _resolve_org_by_name(db, body.org_name)

    user = db.execute(
        select(AppUser).where(
            AppUser.org_id == org.org_id,
            AppUser.email == body.email,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if (
        user is None
        or not user.password_hash
        or not identity_service.verify_password(body.password, user.password_hash)
        or not user.is_active
        or user.is_suspended
    ):
        raise InvalidCredentialsError("Invalid email or password")

    if user.mfa_enabled:
        # Caller must follow up with POST /auth/mfa-verify (which re-presents
        # email+password alongside the TOTP code).
        return LoginResponse(requires_mfa=True, user_id=user.user_id)

    user.last_login_at = datetime.datetime.now(tz=datetime.UTC)
    db.flush()
    pair = identity_service.issue_tokens(db, user=user, firm_id=None)
    _set_refresh_cookie(
        response,
        pair.refresh_token,
        max_age_seconds=_seconds_until(pair.refresh_expires_at),
    )
    return LoginResponse(
        requires_mfa=False,
        user_id=user.user_id,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
    )


# ──────────────────────────────────────────────────────────────────────
# MFA verify — public (re-presents creds)
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/mfa-verify",
    response_model=TokenPairResponse,
    summary="Complete login with TOTP; returns tokens",
)
def mfa_verify(
    body: MfaVerifyRequest,
    db: SyncDBSession,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TokenPairResponse:
    _validate_idempotency_key(idempotency_key)
    org = _resolve_org_by_name(db, body.org_name)

    user = db.execute(
        select(AppUser).where(
            AppUser.org_id == org.org_id,
            AppUser.email == body.email,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if (
        user is None
        or not user.password_hash
        or not identity_service.verify_password(body.password, user.password_hash)
        or not user.is_active
        or user.is_suspended
    ):
        raise InvalidCredentialsError("Invalid email or password")

    if not user.mfa_enabled or user.mfa_secret is None:
        # Don't admit "MFA isn't on for that user"; treat as a generic auth fail.
        raise InvalidCredentialsError("Invalid email or password")

    if not identity_service.verify_totp(db, user_id=user.user_id, code=body.totp_code):
        raise InvalidCredentialsError("Invalid email or password")

    user.last_login_at = datetime.datetime.now(tz=datetime.UTC)
    db.flush()
    pair = identity_service.issue_tokens(db, user=user, firm_id=None)
    _set_refresh_cookie(
        response,
        pair.refresh_token,
        max_age_seconds=_seconds_until(pair.refresh_expires_at),
    )
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
    )


# ──────────────────────────────────────────────────────────────────────
# Refresh — public (the refresh token IS the auth)
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Exchange a refresh token for a new pair",
)
def refresh(
    body: RefreshRequest,
    db: SyncDBSession,
    response: Response,
    fabric_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TokenPairResponse:
    _validate_idempotency_key(idempotency_key)

    # Cookie takes precedence over body — the cookie is the canonical
    # transport per Q2; body remains accepted for the legacy path.
    refresh_token = fabric_refresh or body.refresh_token
    if not refresh_token:
        raise TokenInvalidError("Missing refresh token")

    try:
        pair = identity_service.refresh_token(db, refresh_token=refresh_token)
    except TokenInvalidError:
        # All token-invalid cases (expired, revoked, unknown, malformed) ->
        # uniform 401 to avoid information leakage.
        raise

    _set_refresh_cookie(
        response,
        pair.refresh_token,
        max_age_seconds=_seconds_until(pair.refresh_expires_at),
    )
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
    )


# ──────────────────────────────────────────────────────────────────────
# Logout — public; idempotent revocation
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Revoke the refresh token's session row",
)
def logout(
    body: LogoutRequest,
    db: SyncDBSession,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LogoutResponse:
    _validate_idempotency_key(idempotency_key)

    # Always clear the cookie even if revocation no-ops — local state
    # should match the user's intent.
    _clear_refresh_cookie(response)

    # Verify token before lookup so we don't admit row existence on garbage input.
    try:
        payload = identity_service.verify_jwt(body.refresh_token)
    except TokenInvalidError:
        # Idempotency: a logout call with an unknown / already-expired token
        # is a no-op success ("already logged out").
        return LogoutResponse(revoked=False)

    if payload.token_type != "refresh":  # noqa: S105 — JWT type discriminator
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "validation_error",
                "detail": "Expected refresh token, got access token",
            },
        )

    db_session_row = db.execute(
        select(DbSession).where(
            DbSession.user_id == payload.user_id,
            DbSession.refresh_token_hash == identity_service._hash_token(body.refresh_token),
        )
    ).scalar_one_or_none()
    if db_session_row is None or db_session_row.revoked_at is not None:
        return LogoutResponse(revoked=False)

    db_session_row.revoked_at = datetime.datetime.now(tz=datetime.UTC)
    db.flush()
    return LogoutResponse(revoked=True)


# ──────────────────────────────────────────────────────────────────────
# /auth/me — protected; returns the JWT payload as user-info
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the authenticated user's identity + permissions + flags",
)
def me(current_user: CurrentUser, db: SyncDBSession) -> MeResponse:
    """Reads the JWT payload (set by AuthMiddleware) plus per-firm feature
    flags from `feature_flag_service`. Frontend useAuth bootstrap-on-load
    consumes this.

    Requires a valid access token (refresh tokens are explicitly rejected
    by AuthMiddleware — only access tokens populate request.state.user).
    """
    flags: dict[str, bool] = (
        feature_flag_service.get_flags_for_firm(db, firm_id=current_user.firm_id)
        if current_user.firm_id is not None
        else {}
    )
    return MeResponse(
        user_id=current_user.user_id,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        permissions=list(current_user.permissions),
        flags=flags,
        token_expires_at=datetime.datetime.fromtimestamp(current_user.exp, tz=datetime.UTC),
    )
