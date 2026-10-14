"""Q01-03 — MFA is mandatory for admin-class principals.

CLAUDE.md: "MFA (TOTP, optional for users; mandatory for Admin)". "Admin" is
decided by PERMISSION, never by role name: a user is admin-class when ANY of
their role assignments (org-wide or any firm) grants one of
``MFA_MANDATORY_PERMISSIONS`` — the privilege-administration capabilities,
i.e. the ones that decide who can do what. That covers the system OWNER role
and any custom delegate (e.g. an office manager holding ``admin.user.manage``).

Enforcement (when ``MFA_REQUIRED_FOR_ADMIN`` is on and the user has not
enrolled TOTP):

* ``POST /auth/login`` withholds the token pair and returns a short-lived
  ``mfa_enrollment`` token instead (``identity_service.issue_mfa_enrollment_token``).
  It carries no permissions and no firm, has no session row / refresh token,
  and ``dependencies.get_current_user`` admits it ONLY on
  ``ENROLLMENT_TOKEN_ROUTES``.
* A FULL access token the user already holds (signup, a pre-rollout session,
  a refresh of one) is gated the same way by ``get_current_user``: only
  ``GATED_ACCESS_TOKEN_ROUTES`` answer; everything else is 403
  ``MFA_ENROLLMENT_REQUIRED``. ``/auth/switch-firm`` is allowed there because
  the FE's post-signup single-firm auto-switch calls it, and its output is a
  token for the same user, so it stays gated.
* Once ``/auth/mfa/confirm`` flips ``mfa_enabled``, the gate lifts for full
  tokens and the next login goes through ``/auth/mfa-verify``. An
  enrolment token never becomes a full token.
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Permission, RolePermission, UserRole

# Privilege administration: assigning roles / inviting (admin.user.manage) and
# redefining what roles grant (identity.role.create/update/delete).
MFA_MANDATORY_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {
        "admin.user.manage",
        "identity.role.create",
        "identity.role.update",
        "identity.role.delete",
    }
)

# Route templates (``scope["route"].path``) an enrolment-only token may call.
ENROLLMENT_TOKEN_ROUTES: Final[frozenset[str]] = frozenset(
    {"/auth/mfa/setup", "/auth/mfa/confirm", "/auth/me", "/auth/logout"}
)

# Route templates a FULL access token of an unenrolled admin may call.
GATED_ACCESS_TOKEN_ROUTES: Final[frozenset[str]] = ENROLLMENT_TOKEN_ROUTES | {"/auth/switch-firm"}


def is_enforced() -> bool:
    """The policy switch (``MFA_REQUIRED_FOR_ADMIN``, secure default True;
    may only be False when ENVIRONMENT=dev). Tests patch this seam."""
    return get_settings().mfa_required_for_admin


def is_admin_class(session: Session, *, user_id: uuid.UUID) -> bool:
    """True when any of the user's role assignments, in any firm or
    org-wide, grants an MFA-mandatory permission."""
    mandatory = [tuple(code.rsplit(".", 1)) for code in sorted(MFA_MANDATORY_PERMISSIONS)]
    hit = session.execute(
        select(UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            UserRole.user_id == user_id,
            tuple_(Permission.resource, Permission.action).in_(mandatory),
        )
        .limit(1)
    ).first()
    return hit is not None


def enrollment_required(session: Session, *, user_id: uuid.UUID, mfa_enabled: bool) -> bool:
    """Must this user enrol TOTP before getting full access?"""
    if mfa_enabled or not is_enforced():
        return False
    return is_admin_class(session, user_id=user_id)
