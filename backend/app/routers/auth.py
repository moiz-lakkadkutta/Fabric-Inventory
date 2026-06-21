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
import json as _json
import uuid

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select, text

from app.config import get_settings
from app.dependencies import CurrentUser, SyncDBSession
from app.exceptions import (
    EmailTakenError,
    InvalidCredentialsError,
    InvalidResetTokenError,
    NotFoundError,
    PermissionDeniedError,
    TokenInvalidError,
)
from app.middleware.rate_limit import _client_ip, _get_redis, rate_limit
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
    inventory_service,
    password_reset_service,
    rbac_service,
    seed_service,
)
from app.utils.crypto import encrypt_pii, generate_dek, wrap_dek

router = APIRouter(prefix="/auth", tags=["auth"])


# ──────────────────────────────────────────────────────────────────────
# DOS-01 — Rate-limit deps for credential endpoints.
#
# Login / MFA-verify are keyed on (IP + email) so:
#   - An attacker can't exhaust one victim's budget from many IPs.
#   - An attacker can't rotate emails from one IP to bypass per-IP limits.
# Signup / reset are IP-keyed (signup: no existing account context;
# reset: token is the auth factor, no email in the request body).
# ──────────────────────────────────────────────────────────────────────


async def _ip_email_key(request: Request) -> str:
    """Rate-limit key combining (IP + email) for credential endpoints.

    Reads the JSON body to extract ``email``. FastAPI/Starlette caches
    the raw body bytes after the first read so the route handler sees the
    same body when it runs its Pydantic validation.
    """
    ip = _client_ip(request)
    try:
        body_bytes = await request.body()
        data = _json.loads(body_bytes)
        email = str(data.get("email", "")).lower().strip()
    except Exception:
        email = ""
    return f"{ip}:{email}"


# 10 login / MFA attempts per 60s per (IP + email) — generous enough for a
# fat-fingered human (~10 fast retries), tight enough to block automated
# credential stuffing. The forgot-password endpoint already has 5/60s;
# we're slightly looser here because MFA codes have a 30s window and a
# user might retry twice per window (old code / new code).
_LOGIN_RATE_LIMIT = rate_limit(
    bucket="auth.login",
    max_requests=10,
    window_seconds=60,
    key_func=_ip_email_key,
)

_MFA_RATE_LIMIT = rate_limit(
    bucket="auth.mfa_verify",
    max_requests=10,
    window_seconds=60,
    key_func=_ip_email_key,
)

# Signup: 3 per hour per IP. Creating accounts at scale is the classic
# trial-account-spam / resource-exhaustion vector.
_SIGNUP_RATE_LIMIT = rate_limit(
    bucket="auth.signup",
    max_requests=3,
    window_seconds=3600,
)

# Password reset consumption: 5 per 60s per IP. Same order of magnitude as
# forgot; the token itself provides most of the security — this just prevents
# brute-force against a short token format.
_RESET_RATE_LIMIT = rate_limit(
    bucket="auth.reset",
    max_requests=5,
    window_seconds=60,
)


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


def _resolve_org_by_name(session: SyncDBSession, org_name: str) -> Organization | None:
    """Return the Organization row for ``org_name``, or ``None`` if not found.

    Returns None instead of raising so callers can run dummy bcrypt BEFORE
    raising InvalidCredentialsError — otherwise the ~1ms org-lookup response
    is distinguishable from the ~100ms bcrypt response by timing, leaking
    whether an org name exists (DOS-02 / API-7-03).

    When the org IS found, seeds the RLS GUC so subsequent queries against
    org-scoped tables (app_user, session, etc.) can see this org's rows.
    Under fabric_app (NOBYPASSRLS) the GUC must be set before any org-scoped
    SELECT, otherwise the policy hides every row.
    """
    org = session.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()
    if org is None:
        return None
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
    dependencies=[Depends(_SIGNUP_RATE_LIMIT)],
)
def signup(
    body: SignupRequest,
    db: SyncDBSession,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SignupResponse:

    # Per /grill-me Q6: the multi-tenancy model is per-org email scoping.
    # Same email + different org → 201 (intentional). Any collision under
    # an EXISTING org name (whether the email collides too or not) collapses
    # to a single generic 409 — IDM-6: don't reveal WHICH field collided or
    # echo the submitted value in the error message.
    existing_org = db.execute(
        select(Organization).where(Organization.name == body.org_name)
    ).scalar_one_or_none()
    if existing_org is not None:
        # IDM-6: collapse both branches (email collision AND org-only collision)
        # to ONE generic 409 so a caller cannot probe whether a given email is
        # already registered under an org, nor confirm the org's existence
        # independently of the email. Neither the email nor the org name is
        # echoed in the error detail.
        raise EmailTakenError("An account with those credentials already exists")

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

    # TASK-TR-C1: every fresh signup gets a default Location so the
    # inventory/jobwork/GRN/stock-issue flows have somewhere to anchor
    # against from minute one. Without this, the first user is stranded
    # on every "pick a location" dropdown until they manually create one,
    # and there is no FE path to do that on a brand-new org. Re-uses the
    # existing `get_or_create_default_location` helper so the seeded row
    # is identical to the one `inventory_service.add_stock` lazily
    # creates today (code='MAIN', type=WAREHOUSE) — keeps the implicit
    # contract from inventory_service intact.
    inventory_service.get_or_create_default_location(db, org_id=org.org_id, firm_id=firm.firm_id)

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


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Verify creds; gate on MFA",
    dependencies=[Depends(_LOGIN_RATE_LIMIT)],
)
def login(
    body: LoginRequest,
    db: SyncDBSession,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LoginResponse:
    org = _resolve_org_by_name(db, body.org_name)
    if org is None:
        # DOS-02 / API-7-03 — Timing oracle: run dummy bcrypt even when the
        # org name doesn't exist so the ~1ms org-missing response is not
        # distinguishable from the ~100ms wrong-password response by timing.
        # Without this, an attacker can enumerate valid org names via latency.
        identity_service.verify_password(body.password, identity_service.DUMMY_BCRYPT_HASH)
        raise InvalidCredentialsError("Invalid email or password")

    user = db.execute(
        select(AppUser).where(
            AppUser.org_id == org.org_id,
            AppUser.email == body.email,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    # DOS-02 / API-7-03 — Timing oracle: always run bcrypt regardless of
    # whether the user was found. When the user doesn't exist we verify the
    # supplied password against a pre-computed dummy hash so response latency
    # is indistinguishable from the "wrong password" path.
    hash_to_check = (
        user.password_hash
        if (user is not None and user.password_hash)
        else identity_service.DUMMY_BCRYPT_HASH
    )
    bcrypt_ok = identity_service.verify_password(body.password, hash_to_check)

    credentials_ok = (
        user is not None
        and bool(user.password_hash)
        and bcrypt_ok
        and user.is_active
        and not user.is_suspended
    )

    if not credentials_ok:
        # CRYPTO-02: emit a login_failed audit event so security monitoring
        # can detect credential-stuffing campaigns. We have org context even
        # when the user wasn't found (org was resolved above).
        #
        # PII: the email is NOT stored in the audit blob — it is attacker-
        # supplied plaintext that would accumulate victim emails in the audit
        # table. The reset path already omits email for the same reason.
        #
        # We call db.commit() (not just flush()) BEFORE raising so the audit
        # row persists despite the exception. The dependency's session context
        # manager calls session.rollback() on exception — which is a safe
        # no-op after a successful commit.
        audit_service.emit(
            db,
            org_id=org.org_id,
            firm_id=None,
            user_id=user.user_id if user is not None else None,
            entity_type="auth.session",
            entity_id=user.user_id if user is not None else org.org_id,
            action="login_failed",
            changes={"after": {}},
        )
        db.commit()
        raise InvalidCredentialsError("Invalid email or password")

    # Narrow type: credentials_ok is True iff user is not None.
    assert user is not None  # type narrowing for mypy

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
    dependencies=[Depends(_MFA_RATE_LIMIT)],
)
def mfa_verify(
    body: MfaVerifyRequest,
    db: SyncDBSession,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TokenPairResponse:
    org = _resolve_org_by_name(db, body.org_name)
    if org is None:
        # DOS-02 / API-7-03 — Timing oracle: same unknown-org dummy-bcrypt
        # pattern as the login handler — see login for the full rationale.
        identity_service.verify_password(body.password, identity_service.DUMMY_BCRYPT_HASH)
        raise InvalidCredentialsError("Invalid email or password")

    user = db.execute(
        select(AppUser).where(
            AppUser.org_id == org.org_id,
            AppUser.email == body.email,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    # DOS-02: always run bcrypt — see login handler comment.
    hash_to_check = (
        user.password_hash
        if (user is not None and user.password_hash)
        else identity_service.DUMMY_BCRYPT_HASH
    )
    bcrypt_ok = identity_service.verify_password(body.password, hash_to_check)

    credentials_ok = (
        user is not None
        and bool(user.password_hash)
        and bcrypt_ok
        and user.is_active
        and not user.is_suspended
    )

    if not credentials_ok:
        # CRYPTO-02: audit failed MFA verify attempt (same commit-before-raise
        # pattern as login — see login handler comment above).
        # PII: email omitted from changes.after — see login handler comment.
        audit_service.emit(
            db,
            org_id=org.org_id,
            firm_id=None,
            user_id=user.user_id if user is not None else None,
            entity_type="auth.session",
            entity_id=user.user_id if user is not None else org.org_id,
            action="login_failed",
            changes={"after": {"mfa_stage": True}},
        )
        db.commit()
        raise InvalidCredentialsError("Invalid email or password")

    # Narrow type: credentials_ok is True iff user is not None.
    assert user is not None  # type narrowing for mypy

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
    dependencies=[Depends(_RESET_RATE_LIMIT)],
)
def reset_password(body: ResetPasswordRequest, db: SyncDBSession) -> ResetPasswordResponse:
    """Validate the token + rotate the user's password. All failure
    modes (unknown / expired / consumed / malformed) collapse to a
    single 400 ``INVALID_RESET_TOKEN`` so the response never reveals
    WHICH branch tripped.

    TS-06 — timing oracle: the happy path calls bcrypt (inside
    ``password_reset_service.consume`` → ``hash_password``). The error
    path previously returned fast without doing any crypto work, leaking
    whether the token was valid via response latency. We now always call
    ``verify_password`` against the module-level dummy hash on the error
    path so timing is flat regardless of token validity.

    The audit emit records the password rotation against the user;
    no PII (email / new password) is captured in the changes blob.
    """
    try:
        user = password_reset_service.consume(
            db,
            token=body.token,
            org_name=body.org_name,
            new_password=body.new_password,
        )
    except InvalidResetTokenError:
        # TS-06: run equivalent bcrypt work so the error path is not
        # distinguishably faster than the success path.
        identity_service.verify_password(body.new_password, identity_service.DUMMY_BCRYPT_HASH)
        raise

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
async def logout(
    db: SyncDBSession,
    response: Response,
    body: LogoutRequest | None = None,
    fabric_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
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

    # TS-04: jti denylist — push the access token's jti to Redis so
    # subsequent requests using the same access token return 401 immediately,
    # rather than waiting for the 15-minute TTL to expire.
    # The access token is expected in the Authorization header (the client
    # sends it alongside the refresh token at logout). If absent or
    # already-expired, we skip silently — idempotent and safe.
    if authorization and authorization.startswith("Bearer "):
        _access_raw = authorization.removeprefix("Bearer ").strip()
        try:
            _access_payload = identity_service.verify_jwt(_access_raw)
            if _access_payload.token_type == "access":  # noqa: S105 — discriminator
                _remaining = int(
                    _access_payload.exp - datetime.datetime.now(tz=datetime.UTC).timestamp()
                )
                if _remaining > 0:
                    _redis = _get_redis()
                    if _redis is not None:
                        await _redis.setex(f"jti:{_access_payload.jti}", _remaining, "1")
        except TokenInvalidError:
            # Already expired or invalid — no need to denylist; skip silently.
            pass

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
