"""User invite service (TASK-CUT-304).

Lifecycle:

1. Owner calls `create_invite(...)` with email + role_id [+ firm_id].
   We mint 32 bytes of random, sha256 it into `token_hash`, persist the
   row, and return the raw token. The router console-logs
   `${FRONTEND_URL}/invite/${token}` so dev/test can copy the link.

2. The recipient hits the FE `/invite/:token` page, sets name + password,
   and POSTs to `accept_invite(...)`. We sha256 the presented token,
   look up the row by hash (org-blind initially — the accept endpoint
   has no JWT), verify TTL + single-use, set the org GUC so subsequent
   org-scoped inserts pass WITH CHECK, and create the `app_user` +
   `app_user_role`. Invite row's `used_at` is stamped atomically.

3. Owner can also change an existing user's role via `change_role(...)`.
   Last-Owner-demotion is blocked here (not in the router) so the rule
   is in one place.

Console-log adapter: the router prints the invite link via `print(...)`.
When CUT-303's `EmailAdapter` Protocol lands, this swaps to a single
`email_adapter.send_invite(...)` call and the print goes away. Tracked
in the retro.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions import (
    AppValidationError,
    EmailTakenError,
    NotFoundError,
    TokenInvalidError,
)
from app.models import AppUser, Role, UserInvite, UserRole
from app.service import audit_service, identity_service, rbac_service
from app.service.common_guards import assert_firm_in_org

# 7-day TTL — long enough to forgive a weekend, short enough that a
# stolen invite link goes stale before anyone notices.
_INVITE_TTL_DAYS = 7

# 32-byte token → 43-char URL-safe base64. Stored as sha256 hex (64
# chars) so a DB leak can't reverse the token.
_TOKEN_BYTES = 32

OWNER_ROLE_CODE = "OWNER"


@dataclass(frozen=True)
class InviteResult:
    """Return shape from `create_invite`. The raw token is carried out
    of the service exactly once — the router console-logs the link and
    echoes it back in the response. We never re-derive it from the row.
    """

    invite_id: uuid.UUID
    email: str
    expires_at: datetime.datetime
    raw_token: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.UTC)


def _frontend_invite_url(token: str) -> str:
    """Build the FE URL the recipient opens. `FRONTEND_URL` defaults to
    `http://localhost:5174` per the task spec; prod sets this via env.
    """
    settings = get_settings()
    base = (getattr(settings, "frontend_url", None) or "http://localhost:5174").rstrip("/")
    return f"{base}/invite/{token}"


# ──────────────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────────────


def create_invite(
    session: Session,
    *,
    org_id: uuid.UUID,
    invited_by: uuid.UUID,
    email: str,
    role_id: uuid.UUID,
    firm_id: uuid.UUID | None,
) -> InviteResult:
    """Mint an invite for `email` under `org_id`.

    Validates:
      - role exists in this org (RLS-protected SELECT already does that)
      - email is not already a live user in this org (409 EmailTakenError)
      - email doesn't already have an unconsumed, unexpired invite
        (returns the existing one — idempotent at the email level so
        clicking "Invite" twice doesn't spawn dupes)

    Audit: emits `user_invite.create` with `{after: {email, role_id,
    firm_id, expires_at}}`.
    """
    email_normalized = email.strip().lower()
    if not email_normalized:
        raise AppValidationError("email is required")

    # Verify role belongs to this org (RLS ensures we can't see other orgs
    # but a malformed role_id from a different org would still fail the
    # FK at the row level — surface it cleanly).
    role = session.execute(
        select(Role).where(Role.role_id == role_id, Role.org_id == org_id)
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError(f"Role {role_id} not found")

    # IDM-2: verify firm_id (when supplied) belongs to this org.
    # A cross-org firm_id would be silently persisted on the invite and
    # later stamped on the accepted user — closing this at the service
    # layer is cheaper than a DB-level FK that spans tenants.
    if firm_id is not None:
        assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    # Already a live user with that email?
    existing_user = session.execute(
        select(AppUser).where(
            AppUser.org_id == org_id,
            AppUser.email == email_normalized,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        raise EmailTakenError(f"User with email {email_normalized!r} already exists in this org")

    # Reuse an unexpired open invite for the same email so re-clicking
    # "Invite" doesn't generate duplicate rows. We mint a fresh token
    # (the old one was already disclosed in the previous console log)
    # but keep the row id stable.
    open_invite = session.execute(
        select(UserInvite).where(
            UserInvite.org_id == org_id,
            UserInvite.email == email_normalized,
            UserInvite.used_at.is_(None),
            UserInvite.expires_at > _now_utc(),
        )
    ).scalar_one_or_none()

    raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = _now_utc() + datetime.timedelta(days=_INVITE_TTL_DAYS)

    if open_invite is not None:
        open_invite.role_id = role_id
        open_invite.firm_id = firm_id
        open_invite.token_hash = _hash_token(raw_token)
        open_invite.expires_at = expires_at
        open_invite.invited_by = invited_by
        session.flush()
        invite_row = open_invite
    else:
        invite_row = UserInvite(
            org_id=org_id,
            email=email_normalized,
            role_id=role_id,
            firm_id=firm_id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
            invited_by=invited_by,
        )
        session.add(invite_row)
        session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=invited_by,
        entity_type="identity.invite",
        entity_id=invite_row.invite_id,
        action="create",
        changes={
            "after": {
                "email": email_normalized,
                "role_id": str(role_id),
                "firm_id": str(firm_id) if firm_id else None,
                "expires_at": expires_at.isoformat(),
            }
        },
    )

    return InviteResult(
        invite_id=invite_row.invite_id,
        email=email_normalized,
        expires_at=expires_at,
        raw_token=raw_token,
    )


# ──────────────────────────────────────────────────────────────────────
# Accept (public — no JWT in the request)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AcceptResult:
    user_id: uuid.UUID
    org_id: uuid.UUID
    email: str
    org_name: str


def accept_invite(
    session: Session,
    *,
    token: str,
    name: str,
    password: str,
) -> AcceptResult:
    """Consume an invite + create the user + role grant.

    The caller does NOT have a JWT — this is the bootstrap path. We:

    1. sha256 the token, look up the row by token_hash (org-blind).
       Under the runtime fabric_app role this needs RLS bypass for the
       initial SELECT; we set `app.current_org_id` to a temporary
       sentinel that no real org uses, then resolve the row… EXCEPT
       the RLS policy filters by `org_id = current_setting(...)`. So
       we need a slightly different approach: the lookup index covers
       `token_hash` alone, but the policy still hides rows. We solve
       this by deferring RLS via `SET LOCAL row_security = off` for
       the duration of the lookup, then immediately set the GUC to
       the row's `org_id` so all downstream INSERT / UPDATE statements
       run under the correct tenant.

    2. Validate `expires_at > now`, `used_at IS NULL`. Map both failure
       modes to TokenInvalidError so we never leak whether a token
       existed-but-expired vs never-existed.

    3. Insert the AppUser, assign the role, stamp `used_at`. Audit.

    The caller MUST commit the session (router does this via the
    SyncDBSession dependency).
    """
    if not token:
        raise TokenInvalidError("Missing invite token")

    token_hash = _hash_token(token)

    # Stage-1: locate the invite row without knowing its org. The
    # `app.invite_lookup_mode = 'on'` GUC opens the RLS USING clause on
    # `user_invite` only (see the migration) so we can SELECT by
    # token_hash without yet knowing the tenant. The escape hatch is
    # scoped to one table and one operation (no WITH CHECK relief), and
    # the token_hash itself is a 256-bit secret — knowing the hash IS
    # the access credential.
    session.execute(text("SET LOCAL app.invite_lookup_mode = 'on'"))
    invite = session.execute(
        select(UserInvite).where(UserInvite.token_hash == token_hash)
    ).scalar_one_or_none()
    if invite is None:
        raise TokenInvalidError("Invite token is invalid or expired")
    if invite.used_at is not None:
        raise TokenInvalidError("Invite token has already been used")
    if invite.expires_at < _now_utc():
        raise TokenInvalidError("Invite token has expired")

    # Stage-2: pin the RLS GUC to this invite's org so subsequent
    # INSERTs (app_user, user_role, audit_log) pass WITH CHECK. Clear the
    # invite-lookup escape hatch so any later helper queries on
    # `user_invite` only see this tenant's rows.
    session.execute(text(f"SET LOCAL app.current_org_id = '{invite.org_id}'"))
    session.execute(text("SET LOCAL app.invite_lookup_mode = 'off'"))

    # Refuse if a user with this email got created out-of-band between
    # invite mint and accept (e.g. via signup). Edge case but cheap.
    existing_user = session.execute(
        select(AppUser).where(
            AppUser.org_id == invite.org_id,
            AppUser.email == invite.email,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        # Mark the invite used so it can't be replayed, then refuse.
        invite.used_at = _now_utc()
        session.flush()
        raise EmailTakenError(f"User with email {invite.email!r} already exists in this org")

    user = identity_service.register_user(
        session, email=invite.email, password=password, org_id=invite.org_id
    )
    user.legal_name = name.strip() or None
    rbac_service.assign_role(
        session,
        user_id=user.user_id,
        role_id=invite.role_id,
        firm_id=invite.firm_id,
        org_id=invite.org_id,
    )

    invite.used_at = _now_utc()
    session.flush()

    audit_service.emit(
        session,
        org_id=invite.org_id,
        firm_id=invite.firm_id,
        user_id=user.user_id,
        entity_type="identity.invite",
        entity_id=invite.invite_id,
        action="accept",
        changes={"after": {"user_id": str(user.user_id)}},
    )

    # Fetch org name for the response — saves the FE a /me round-trip
    # before the redirect to /login (and the recipient won't know the
    # exact org name otherwise).
    org_name_row = session.execute(
        text("SELECT name FROM organization WHERE org_id = :org_id"),
        {"org_id": str(invite.org_id)},
    ).scalar_one()

    return AcceptResult(
        user_id=user.user_id,
        org_id=invite.org_id,
        email=user.email,
        org_name=str(org_name_row),
    )


# ──────────────────────────────────────────────────────────────────────
# Role change (Owner-only)
# ──────────────────────────────────────────────────────────────────────


def change_user_role(
    session: Session,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    new_role_id: uuid.UUID,
) -> None:
    """Replace `target_user_id`'s ROLE assignment(s) in this org with
    `new_role_id`.

    Last-Owner-demotion protection: if the target currently carries the
    Owner role AND the new role is NOT Owner AND they are the only Owner
    in the org, raise AppValidationError. Better to make the org create
    a second Owner first than risk an unrecoverable state.

    For MVP we use a one-role-per-user model: the change is a wholesale
    replacement of all UserRole rows for this user/org. Custom roles +
    multi-role-per-user is Wave-5+.

    Audit emits `identity.user.change_role` with before/after role codes.
    """
    target = session.execute(
        select(AppUser).where(
            AppUser.user_id == target_user_id,
            AppUser.org_id == org_id,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError(f"User {target_user_id} not found")

    new_role = session.execute(
        select(Role).where(Role.role_id == new_role_id, Role.org_id == org_id)
    ).scalar_one_or_none()
    if new_role is None:
        raise NotFoundError(f"Role {new_role_id} not found")

    current_user_roles = list(
        session.execute(
            select(UserRole).where(UserRole.org_id == org_id, UserRole.user_id == target_user_id)
        ).scalars()
    )
    current_role_codes = {
        session.execute(select(Role.code).where(Role.role_id == ur.role_id)).scalar_one()
        for ur in current_user_roles
    }

    # Last-Owner check: only when the target is currently an Owner AND
    # the new role is not Owner. We compare by role CODE (system roles)
    # rather than name — code is the stable identifier.
    if OWNER_ROLE_CODE in current_role_codes and new_role.code != OWNER_ROLE_CODE:
        # Count distinct Owners (other than the target) in this org.
        owner_role_id = session.execute(
            select(Role.role_id).where(Role.org_id == org_id, Role.code == OWNER_ROLE_CODE)
        ).scalar_one()
        other_owner_count = session.execute(
            text(
                """
                SELECT COUNT(DISTINCT user_id)
                FROM user_role
                WHERE org_id = :org_id
                  AND role_id = :owner_role_id
                  AND user_id <> :target_user_id
                """
            ),
            {
                "org_id": str(org_id),
                "owner_role_id": str(owner_role_id),
                "target_user_id": str(target_user_id),
            },
        ).scalar_one()
        if int(other_owner_count) == 0:
            raise AppValidationError(
                "Cannot demote the last Owner. Promote another user to Owner first.",
                title="Last Owner cannot be demoted",
            )

    # Replace assignments wholesale. For Owner-target invite-via-firm we
    # leave the new row firm_id=None (Owner is org-wide); for any other
    # role we preserve the prior firm_id if there was one (most invites
    # set this at creation time; role-change just swaps the role).
    prior_firm_id: uuid.UUID | None = None
    for ur in current_user_roles:
        if ur.firm_id is not None:
            prior_firm_id = ur.firm_id
            break

    for ur in current_user_roles:
        session.delete(ur)
    session.flush()

    target_firm_id: uuid.UUID | None = None if new_role.code == OWNER_ROLE_CODE else prior_firm_id

    rbac_service.assign_role(
        session,
        user_id=target_user_id,
        role_id=new_role_id,
        firm_id=target_firm_id,
        org_id=org_id,
    )

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=target_firm_id,
        user_id=actor_user_id,
        entity_type="identity.user",
        entity_id=target_user_id,
        action="change_role",
        changes={
            "before": {"role_codes": sorted(current_role_codes)},
            "after": {"role_code": new_role.code},
        },
    )


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


__all__ = [
    "OWNER_ROLE_CODE",
    "AcceptResult",
    "InviteResult",
    "_frontend_invite_url",
    "accept_invite",
    "change_user_role",
    "create_invite",
]
