"""Auth routes — signup, login, refresh, MFA verify, logout.

Sync handlers; FastAPI runs them in a threadpool. This matches the sync
service layer (`identity_service`, `rbac_service`) and avoids the
`asyncio.to_thread` wrapping the retros for those tasks discussed.

`Idempotency-Key` is enforced + dedup'd by `IdempotencyMiddleware`
(see `app/middleware/idempotency.py`). Routes still declare the header
parameter so OpenAPI documents the requirement; the per-router
validator was removed in T-INT-1b.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response, status
from sqlalchemy import select, text

from app.config import get_settings
from app.dependencies import CurrentUser, SyncDBSession
from app.exceptions import (
    AppValidationError,
    EmailTakenError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
    TokenInvalidError,
)
from app.middleware.rate_limit import rate_limit
from app.models import AppUser, Firm, Organization, Role
from app.models import Session as DbSession
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    MeFirmRef,
    MeResponse,
    MfaVerifyRequest,
    RefreshRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SignupRequest,
    SignupResponse,
    SwitchFirmRequest,
    SwitchFirmResponse,
    TokenPairResponse,
)
from app.service import (
    audit_service,
    feature_flag_service,
    identity_service,
    password_reset_service,
    rbac_service,
    seed_service,
)
from app.utils.crypto import encrypt_pii, generate_dek, wrap_dek

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


def _resolve_org_by_name(session: SyncDBSession, org_name: str) -> Organization:
    org = session.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()
    if org is None:
        # Same generic message login uses — don't leak whether the org exists.
        raise InvalidCredentialsError("Invalid email or password")
    # Seed the RLS GUC for the rest of this request so subsequent queries
    # against org-scoped tables (app_user, session, etc.) can see this
    # org's rows. Pre-INT-9 the runtime role bypassed RLS, so unset GUC
    # was harmless; under fabric_app the policy hides every row when the
    # GUC is unset, which would make login appear to fail with
    # "user not found" even when credentials are correct.
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))
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

    # Per /grill-me Q6: the multi-tenancy model is per-org email scoping.
    # Same email + different org → 201 (intentional). Same email + SAME
    # org → 409 USER_EMAIL_TAKEN (this is a real collision, not a generic
    # validation failure). Org-name uniqueness then catches the
    # different-email/same-org case at 422.
    existing_org = db.execute(
        select(Organization).where(Organization.name == body.org_name)
    ).scalar_one_or_none()
    if existing_org is not None:
        # Need to check inside that org for the email; signup hasn't set
        # the GUC yet, so seed it for the lookup.
        db.execute(text(f"SET LOCAL app.current_org_id = '{existing_org.org_id}'"))
        existing_user = db.execute(
            select(AppUser).where(
                AppUser.org_id == existing_org.org_id,
                AppUser.email == body.email,
                AppUser.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if existing_user is not None:
            raise EmailTakenError(f"User with email {body.email!r} already exists in this org")
        # Email is new under an existing org name → still an org-name dup.
        raise AppValidationError(f"Organization {body.org_name!r} already exists")

    # Pre-mint the org_id and SET the RLS GUC BEFORE inserting. Under INT-9
    # the runtime role is `fabric_app` (NOBYPASSRLS); WITH CHECK clauses
    # evaluate `current_setting('app.current_org_id')` at INSERT time and
    # raise if the GUC isn't set. Signup is the bootstrap case — there's
    # no current org yet — so we generate the id, declare it via SET, then
    # insert. Every subsequent INSERT in this transaction (firm, roles,
    # ledgers, user) inherits the GUC and passes WITH CHECK.
    new_org_id = uuid.uuid4()
    db.execute(text(f"SET LOCAL app.current_org_id = '{new_org_id}'"))

    # TASK-TR-SEC1: every org owns a Data Encryption Key, minted here
    # and wrapped with the master KEK before INSERT. Same row format
    # `crypto.wrap_dek` produces — interchangeable with backfill rows.
    dek = generate_dek()
    org = Organization(
        org_id=new_org_id,
        name=body.org_name,
        admin_email=body.email,
        encrypted_dek=wrap_dek(dek, org_id=new_org_id),
    )
    db.add(org)
    db.flush()

    firm = Firm(
        org_id=org.org_id,
        code=_make_firm_code(body.firm_name),
        name=body.firm_name,
        has_gst=body.gstin is not None,
        state_code=body.state_code.upper(),
        # Real AES-GCM encryption now — was a UTF-8 stub before
        # TASK-TR-SEC1. The DEK was minted on the line above, no DB
        # round-trip needed.
        gstin=encrypt_pii(body.gstin, dek=dek, org_id=new_org_id) if body.gstin else None,
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

    audit_service.emit(
        db,
        org_id=org.org_id,
        firm_id=firm.firm_id,
        user_id=user.user_id,
        entity_type="auth.session",
        entity_id=user.user_id,
        action="signup",
        changes={
            "after": {
                "org_name": body.org_name,
                "firm_name": body.firm_name,
                "email": body.email,
            }
        },
    )
    db.flush()

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

    # Available firms — mirrors /auth/me logic so login can return the
    # same shape and the FE doesn't need a follow-up round-trip. Owners
    # (org-wide roles) see every firm in their org; that's the typical
    # dogfood + early-customer shape.
    firms = list(
        db.execute(
            select(Firm)
            .where(Firm.org_id == user.org_id, Firm.deleted_at.is_(None))
            .order_by(Firm.created_at.asc())
        ).scalars()
    )
    auto_firm_id = firms[0].firm_id if len(firms) == 1 else None

    pair = identity_service.issue_tokens(db, user=user, firm_id=auto_firm_id)
    _set_refresh_cookie(
        response,
        pair.refresh_token,
        max_age_seconds=_seconds_until(pair.refresh_expires_at),
    )

    audit_service.emit(
        db,
        org_id=user.org_id,
        firm_id=auto_firm_id,
        user_id=user.user_id,
        entity_type="auth.session",
        entity_id=user.user_id,
        action="login",
        changes={"after": {"firm_id": str(auto_firm_id) if auto_firm_id else None}},
    )
    db.flush()

    return LoginResponse(
        requires_mfa=False,
        user_id=user.user_id,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
        org_id=user.org_id,
        firm_id=auto_firm_id,
        available_firms=[MeFirmRef(firm_id=f.firm_id, code=f.code, name=f.name) for f in firms],
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

    audit_service.emit(
        db,
        org_id=user.org_id,
        firm_id=None,
        user_id=user.user_id,
        entity_type="auth.session",
        entity_id=user.user_id,
        action="login",
        changes={"after": {"mfa": True}},
    )
    db.flush()

    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
    )


# ──────────────────────────────────────────────────────────────────────
# Forgot / reset password — public, exempt from Idempotency-Key (CUT-303)
# ──────────────────────────────────────────────────────────────────────


# Per-IP sliding window: 5 requests per 60s, 6th gets 429 + Retry-After.
# Per CUT-501a brief / CUT-303 retro follow-up #1. Threshold is generous
# vs legitimate use (a user fat-fingering their own email + retrying
# under typical latency lands well under 5/min) but tight against the
# email-pump abuse vector.
_FORGOT_RATE_LIMIT = rate_limit(bucket="auth.forgot", max_requests=5, window_seconds=60)


@router.post(
    "/forgot",
    response_model=ForgotPasswordResponse,
    summary="Request a password reset link (no enumeration leak)",
    responses={
        429: {
            "description": "Rate limit exceeded — see Retry-After header.",
        },
    },
    dependencies=[Depends(_FORGOT_RATE_LIMIT)],
)
def forgot_password(body: ForgotPasswordRequest, db: SyncDBSession) -> ForgotPasswordResponse:
    """Issue a reset link if the email matches a real user in the named
    org; no-op otherwise. The 200 response is uniform either way so a
    caller can't probe which emails are registered.

    No JWT required (it's the lost-password recovery flow), no
    Idempotency-Key required (exempt list in IdempotencyMiddleware so
    a normal "request again" works without the FE minting a UUID).
    """
    password_reset_service.request_reset(db, email=body.email, org_name=body.org_name)
    db.flush()
    return ForgotPasswordResponse(ok=True)


@router.post(
    "/reset",
    response_model=ResetPasswordResponse,
    summary="Consume a reset link and set a new password",
)
def reset_password(body: ResetPasswordRequest, db: SyncDBSession) -> ResetPasswordResponse:
    """Validate the token + rotate the user's password. All failure
    modes (unknown / expired / consumed / malformed) collapse to a
    single 400 ``INVALID_RESET_TOKEN`` so the response never reveals
    WHICH branch tripped.

    The audit emit records the password rotation against the user;
    no PII (email / new password) is captured in the changes blob.
    """
    user = password_reset_service.consume(
        db,
        token=body.token,
        org_name=body.org_name,
        new_password=body.new_password,
    )
    audit_service.emit(
        db,
        org_id=user.org_id,
        firm_id=None,
        user_id=user.user_id,
        entity_type="auth.password",
        entity_id=user.user_id,
        action="reset",
    )
    db.flush()
    return ResetPasswordResponse(ok=True)


# ──────────────────────────────────────────────────────────────────────
# Refresh — public (the refresh token IS the auth)
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Exchange a refresh token for a new pair",
)
def refresh(
    db: SyncDBSession,
    response: Response,
    body: RefreshRequest | None = None,
    fabric_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TokenPairResponse:

    # Cookie-only refresh is the canonical path; body remains accepted for
    # back-compat with existing CLI / tests. INT-10 makes the body itself
    # optional so the FE silent-refresh-on-401 path doesn't need to send
    # an empty `{}` placeholder. Idempotency-Key is also no longer required
    # (the refresh middleware exempt list handles it) — refresh is
    # intrinsically idempotent because tokens rotate on each call.
    refresh_token = fabric_refresh or (body.refresh_token if body else None)
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
    db: SyncDBSession,
    response: Response,
    body: LogoutRequest | None = None,
    fabric_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LogoutResponse:

    # Always clear the cookie even if revocation no-ops — local state
    # should match the user's intent.
    _clear_refresh_cookie(response)

    # Body takes precedence when explicitly provided so callers can still
    # detect "access token mistakenly sent" (a 400 case). When body is
    # absent, fall back to the HttpOnly cookie (the canonical path now
    # that the FE never sees the token). When neither, no-op.
    refresh_token = body.refresh_token if body and body.refresh_token else fabric_refresh
    if not refresh_token:
        # Nothing to revoke; cookie already cleared above. Idempotent no-op.
        return LogoutResponse(revoked=False)

    # Verify token before lookup so we don't admit row existence on garbage input.
    try:
        payload = identity_service.verify_jwt(refresh_token)
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

    # Seed RLS GUC so the session lookup works under fabric_app
    # (NOBYPASSRLS) — pre-INT-9 the runtime role bypassed RLS.
    db.execute(text(f"SET LOCAL app.current_org_id = '{payload.org_id}'"))

    db_session_row = db.execute(
        select(DbSession).where(
            DbSession.user_id == payload.user_id,
            DbSession.refresh_token_hash == identity_service._hash_token(refresh_token),
        )
    ).scalar_one_or_none()
    if db_session_row is None or db_session_row.revoked_at is not None:
        return LogoutResponse(revoked=False)

    db_session_row.revoked_at = datetime.datetime.now(tz=datetime.UTC)
    db.flush()

    audit_service.emit(
        db,
        org_id=payload.org_id,
        firm_id=payload.firm_id,
        user_id=payload.user_id,
        entity_type="auth.session",
        entity_id=payload.user_id,
        action="logout",
    )
    db.flush()

    return LogoutResponse(revoked=True)


# ──────────────────────────────────────────────────────────────────────
# Switch firm — protected; reissues tokens with a new firm_id (Q3)
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/switch-firm",
    response_model=SwitchFirmResponse,
    summary="Switch the active firm; reissues access + refresh tokens",
)
def switch_firm(
    body: SwitchFirmRequest,
    db: SyncDBSession,
    response: Response,
    current_user: CurrentUser,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SwitchFirmResponse:
    """Reissue token pair with `firm_id` set to the requested firm. RLS
    is reset on the next request from the new JWT.

    Failure modes:
      - Cross-org switch (firm.org_id != current_user.org_id) → 404
        (RLS-style, no leak about firm existence in another org).
      - User has zero permissions for the requested firm → 403
        PERMISSION_DENIED. We don't issue empty-permission tokens.
    """
    firm = db.execute(
        select(Firm).where(
            Firm.firm_id == body.firm_id,
            Firm.org_id == current_user.org_id,
            Firm.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if firm is None:
        # 404 not 403 — same posture as RLS leakage protection.
        raise NotFoundError(f"Firm {body.firm_id} not found.")

    permissions = rbac_service.get_user_permissions(
        db, user_id=current_user.user_id, firm_id=firm.firm_id
    )
    if not permissions:
        raise PermissionDeniedError(
            f"User has no roles assigned for firm {firm.name!r}.",
            title="No access to that firm",
        )

    user = db.execute(select(AppUser).where(AppUser.user_id == current_user.user_id)).scalar_one()

    pair = identity_service.issue_tokens(db, user=user, firm_id=firm.firm_id)
    _set_refresh_cookie(
        response,
        pair.refresh_token,
        max_age_seconds=_seconds_until(pair.refresh_expires_at),
    )

    # Audit the switch — diff the firm context.
    audit_service.emit(
        db,
        org_id=current_user.org_id,
        firm_id=firm.firm_id,
        user_id=current_user.user_id,
        entity_type="auth.session",
        entity_id=current_user.user_id,
        action="switch_firm",
        changes={
            "before": {"firm_id": str(current_user.firm_id) if current_user.firm_id else None},
            "after": {"firm_id": str(firm.firm_id)},
        },
    )
    db.flush()

    # Invalidate the per-firm flag cache so the next /me call re-resolves.
    feature_flag_service.invalidate_firm(firm.firm_id)

    return SwitchFirmResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
        firm_id=firm.firm_id,
    )


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
    # `resolve_flags_for_firm` overlays `FLAG_DEFAULTS` onto the raw DB
    # rows so default-on modules (e.g. `manufacturing.enabled`) light up
    # without a backfill migration. /me is the runtime-gating boundary;
    # the admin toggle UI continues to use the raw `get_flags_for_firm`.
    flags: dict[str, bool] = (
        feature_flag_service.resolve_flags_for_firm(db, firm_id=current_user.firm_id)
        if current_user.firm_id is not None
        else {}
    )
    # Available firms — Owners (org-wide roles) see every firm in their
    # org; non-Owner refinement (UserFirmScope filtering) lands when
    # other roles actually need it. For dogfood + early friendly-customer
    # this matches the typical "one Owner per org" shape.
    firms = list(
        db.execute(
            select(Firm)
            .where(Firm.org_id == current_user.org_id, Firm.deleted_at.is_(None))
            .order_by(Firm.created_at.asc())
        ).scalars()
    )
    # Email lookup — CUT-004: the FE topbar / user menu reads identity
    # from /auth/me. JWT carries user_id only; email lives in app_user.
    user_row = db.execute(
        select(AppUser).where(AppUser.user_id == current_user.user_id)
    ).scalar_one()

    return MeResponse(
        user_id=current_user.user_id,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        email=user_row.email,
        permissions=list(current_user.permissions),
        flags=flags,
        available_firms=[MeFirmRef(firm_id=f.firm_id, code=f.code, name=f.name) for f in firms],
        token_expires_at=datetime.datetime.fromtimestamp(current_user.exp, tz=datetime.UTC),
    )
