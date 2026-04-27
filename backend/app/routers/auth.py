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

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select

from app.dependencies import SyncDBSession
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
    MfaVerifyRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPairResponse,
)
from app.service import identity_service, rbac_service

router = APIRouter(prefix="/auth", tags=["auth"])


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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TokenPairResponse:
    _validate_idempotency_key(idempotency_key)
    try:
        pair = identity_service.refresh_token(db, refresh_token=body.refresh_token)
    except TokenInvalidError:
        # All token-invalid cases (expired, revoked, unknown, malformed) ->
        # uniform 401 to avoid information leakage.
        raise
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LogoutResponse:
    _validate_idempotency_key(idempotency_key)

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
