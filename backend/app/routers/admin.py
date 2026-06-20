"""Admin router — user list, invites, role changes (TASK-CUT-304).

Endpoints:
  GET    /admin/users                       — list users in this org
  POST   /admin/invites                     — Owner mints an invite
  POST   /admin/invites/accept              — invitee consumes (PUBLIC, no JWT)
  PATCH  /admin/users/{user_id}/role        — Owner swaps a user's role

All authenticated endpoints require the `admin.user.manage` permission
per the RBAC catalog (`backend/app/service/rbac_service.py`).

The `/admin/invites/accept` endpoint is the one exception: the invitee
doesn't have a session yet. AuthMiddleware is a pass-through today, but
the idempotency middleware enforces an Idempotency-Key on POST
unconditionally — we add `/admin/invites/accept` to
`IDEMPOTENT_BY_DESIGN_PATHS` for that reason. The invite token IS the
idempotency key (single-use, sha256-hashed in DB).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import SyncDBSession, require_permission
from app.exceptions import NotFoundError
from app.models import AppUser, Permission, Role, RolePermission, UserRole
from app.schemas.admin import (
    AcceptInviteRequest,
    AcceptInviteResponse,
    AdminUserListResponse,
    AdminUserResponse,
    CreateRoleRequest,
    InviteCreateRequest,
    InviteCreateResponse,
    PermissionCatalogEntry,
    PermissionCatalogModule,
    PermissionCatalogResponse,
    RoleResponse,
    UpdateRoleRequest,
    UpdateUserRoleRequest,
)
from app.service import invite_service, rbac_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/admin", tags=["admin"])


# ──────────────────────────────────────────────────────────────────────
# GET /admin/users — list users with role + status
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="List users in this organization with their role + status",
)
def list_users(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.user.manage"))],
) -> AdminUserListResponse:
    """Return every non-deleted user in the current org with the role
    that surfaces in the Admin UI.

    For MVP each user carries exactly one role (the role-change endpoint
    enforces that). If somehow multiple rows exist for a user, we pick
    the first by role name alphabetically so the table is stable.
    """
    rows = list(
        db.execute(
            select(AppUser)
            .where(AppUser.org_id == current_user.org_id, AppUser.deleted_at.is_(None))
            .order_by(AppUser.created_at.asc())
        ).scalars()
    )

    # Pull the (user, role) join once so we don't N+1.
    role_lookup_rows = list(
        db.execute(
            select(UserRole.user_id, Role.role_id, Role.name, Role.code)
            .join(Role, Role.role_id == UserRole.role_id)
            .where(UserRole.org_id == current_user.org_id)
            .order_by(Role.name.asc())
        ).all()
    )
    user_to_role: dict[uuid.UUID, tuple[uuid.UUID, str, str]] = {}
    for user_id, role_id, role_name, role_code in role_lookup_rows:
        # Skip if we already picked a role for this user — the order_by
        # makes the choice stable (first alphabetic role wins on ties).
        if user_id not in user_to_role:
            user_to_role[user_id] = (role_id, role_name, role_code)

    items: list[AdminUserResponse] = []
    for u in rows:
        role_tuple = user_to_role.get(u.user_id)
        if role_tuple is None:
            # User with zero role assignments — surfaces in the table
            # with a placeholder so the Admin can spot + fix it. We
            # still emit the row because hiding it is more confusing
            # than seeing "(no role)".
            role_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
            role_name = "(no role)"
        else:
            role_id, role_name, _role_code = role_tuple

        if u.is_suspended:
            status_str = "SUSPENDED"
        elif u.is_active is False:
            status_str = "INACTIVE"
        else:
            status_str = "ACTIVE"

        items.append(
            AdminUserResponse(
                user_id=u.user_id,
                email=u.email,
                name=u.legal_name,
                role=role_name,
                role_id=role_id,
                status=status_str,
                last_login_at=u.last_login_at,
                created_at=u.created_at,
            )
        )

    return AdminUserListResponse(items=items, count=len(items))


# ──────────────────────────────────────────────────────────────────────
# POST /admin/invites — mint an invite + console-log the link
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/invites",
    response_model=InviteCreateResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user by email to this organization",
)
def create_invite(
    body: InviteCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.user.manage"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> InviteCreateResponse:
    """Owner-initiated invite. Persists a single-use, 7-day token.

    IDM-3: the raw invite token is NOT returned in the response body in
    staging/production — it must travel exclusively via the email adapter
    so it never appears in API logs or browser history. In dev mode
    (ENVIRONMENT=dev) the invite link is included in the response as a
    testing convenience (existing test_admin_invites.py relies on it).
    The stdout print is likewise gated to dev.

    When CUT-303's EmailAdapter ships, this swaps to a single
    `email_adapter.send_invite(...)` call.
    """
    result = invite_service.create_invite(
        db,
        org_id=current_user.org_id,
        invited_by=current_user.user_id,
        email=body.email,
        role_id=body.role_id,
        firm_id=body.firm_id,
    )

    # IDM-3: gate the invite link to dev mode only.
    settings = get_settings()
    invite_link: str | None = None
    if settings.environment == "dev":
        invite_link = invite_service._frontend_invite_url(result.raw_token)
        # Console-log adapter: dev/test reads this off stdout or capsys.
        # Gated to dev so production logs never carry raw tokens.
        print(f"[invite] {result.email}: {invite_link}", flush=True)

    return InviteCreateResponse(
        invite_id=result.invite_id,
        email=result.email,
        expires_at=result.expires_at,
        invite_link=invite_link,
    )


# ──────────────────────────────────────────────────────────────────────
# POST /admin/invites/accept — PUBLIC (no JWT)
#
# The invitee posts here from `/invite/:token`. AuthMiddleware is a
# pass-through today so this route is naturally public; we just don't
# add a require_permission dep. The idempotency middleware is bypassed
# via the IDEMPOTENT_BY_DESIGN_PATHS allowlist (see middleware/idempotency.py)
# so the recipient doesn't need to mint a UUID — the invite token is
# the idempotency key by construction (single-use).
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/invites/accept",
    response_model=AcceptInviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Consume an invite token: create the user and assign their role",
)
def accept_invite(
    body: AcceptInviteRequest,
    db: SyncDBSession,
) -> AcceptInviteResponse:
    """Public endpoint. Validates token, creates app_user + user_role,
    stamps the invite as used. Returns user identity + org name so the
    FE can redirect to /login with the org name pre-filled.

    Decision: we do NOT issue a session here. The user redirects to
    /login and types their freshly-set password. That keeps the
    "newly-bcrypted password actually unlocks the account" check in the
    happy path and exercises MFA enrollment when the org later
    requires it. Trade-off recorded in docs/retros/task-CUT-304.md.
    """
    result = invite_service.accept_invite(
        db, token=body.token, name=body.name, password=body.password
    )
    return AcceptInviteResponse(
        user_id=result.user_id,
        org_id=result.org_id,
        email=result.email,
        org_name=result.org_name,
    )


# ──────────────────────────────────────────────────────────────────────
# PATCH /admin/users/{user_id}/role — Owner-only role swap
# ──────────────────────────────────────────────────────────────────────


@router.patch(
    "/users/{user_id}/role",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Replace a user's role assignment(s) with the given role",
)
def update_user_role(
    user_id: uuid.UUID,
    body: UpdateUserRoleRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.user.manage"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    """Swap a user's role. Last-Owner-demotion blocked at the service
    layer with 422 VALIDATION_ERROR.
    """
    # Refuse if the user doesn't exist in this org — the service raises
    # NotFound, but we want a 404 not a 403 (RLS already isolates orgs).
    target = db.execute(
        select(AppUser).where(
            AppUser.user_id == user_id,
            AppUser.org_id == current_user.org_id,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError(f"User {user_id} not found")

    invite_service.change_user_role(
        db,
        org_id=current_user.org_id,
        actor_user_id=current_user.user_id,
        target_user_id=user_id,
        new_role_id=body.role_id,
    )
    return None


# ──────────────────────────────────────────────────────────────────────
# GET /admin/roles — list system roles so the FE can render a dropdown
#
# Surface needed by `InviteUserDialog` + the role-change <select> on the
# users table. Permission-gated on `admin.user.manage` for parity.
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/roles",
    summary="List roles available for assignment in this org",
)
def list_roles(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.user.manage"))],
) -> dict[str, list[dict[str, object]]]:
    """Returns `{ items: [{ role_id, code, name, description, is_system_role }, ...] }`.

    Untyped envelope (dict) keeps the spec simple for the MVP admin
    surface; codegen still picks up the path. Switch to a Pydantic
    response model when this surfaces in OpenAPI consumers other than
    AdminHub.
    """
    rows = list(
        db.execute(
            select(Role)
            .where(Role.org_id == current_user.org_id, Role.deleted_at.is_(None))
            .order_by(Role.is_system_role.desc(), Role.name.asc())
        ).scalars()
    )
    items: list[dict[str, object]] = [
        {
            "role_id": str(r.role_id),
            "code": r.code,
            "name": r.name,
            "description": r.description,
            "is_system_role": bool(r.is_system_role),
        }
        for r in rows
    ]
    return {"items": items}


# ──────────────────────────────────────────────────────────────────────
# Permission catalog + Custom role CRUD (TASK-TR-B4)
#
# The catalog endpoint is the single source of truth the Role-builder UI
# reads to render checkbox groups. Gated on `identity.role.read` so the
# same permission that lets users view roles also lets them see what
# permissions exist (consistent with the role-detail endpoint below).
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/permissions",
    response_model=PermissionCatalogResponse,
    summary="List the system permission catalog grouped by module",
)
def list_permission_catalog(
    current_user: Annotated[TokenPayload, Depends(require_permission("identity.role.read"))],
) -> PermissionCatalogResponse:
    """Return the static catalog the Role builder renders.

    Static — does not hit the DB. Permission rows in `permission` are
    seeded per-org from this same catalog by `seed_system_permissions`,
    so this endpoint and the org's actual permission set are guaranteed
    to align after signup.
    """
    _ = current_user  # auth-only; dependency enforces the perm gate
    catalog = rbac_service.list_system_permission_catalog()
    return PermissionCatalogResponse(
        items=[
            PermissionCatalogModule(
                module=group["module"],
                permissions=[PermissionCatalogEntry(**perm) for perm in group["permissions"]],
            )
            for group in catalog
        ]
    )


def _load_role_with_permissions(
    db: Session,
    *,
    org_id: uuid.UUID,
    role_id: uuid.UUID,
) -> RoleResponse:
    """Helper — returns a `RoleResponse` for an existing role + grants."""
    role = db.execute(
        select(Role).where(
            Role.role_id == role_id,
            Role.org_id == org_id,
            Role.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError(f"Role {role_id} not found")
    grant_rows = list(
        db.execute(
            select(Permission.resource, Permission.action)
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .where(RolePermission.role_id == role_id)
        ).all()
    )
    grants = sorted(f"{r}.{a}" for r, a in grant_rows)
    return RoleResponse(
        role_id=role.role_id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system_role=bool(role.is_system_role),
        permissions=grants,
    )


@router.get(
    "/roles/{role_id}",
    response_model=RoleResponse,
    summary="Get a role's full detail (incl. permission grants)",
)
def get_role(
    role_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("identity.role.read"))],
) -> RoleResponse:
    """Return the role + its current permission grants. Used by the Role
    builder edit dialog to pre-check the boxes.
    """
    return _load_role_with_permissions(db, org_id=current_user.org_id, role_id=role_id)


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role with permission grants",
)
def create_role(
    body: CreateRoleRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("identity.role.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RoleResponse:
    """Owner-only — mints a non-system role with the given grants.

    Service-layer validation handles:
      - empty code/name
      - colliding code with a system role (OWNER / ACCOUNTANT / …)
      - unknown permission codes
    """
    role = rbac_service.create_custom_role(
        db,
        org_id=current_user.org_id,
        code=body.code,
        name=body.name,
        permission_codes=body.permissions,
        description=body.description,
    )
    return _load_role_with_permissions(db, org_id=current_user.org_id, role_id=role.role_id)


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    summary="Update a custom role's name / description / permission grants",
)
def update_role(
    role_id: uuid.UUID,
    body: UpdateRoleRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("identity.role.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RoleResponse:
    """Owner-only — mutates fields supplied in the body; `permissions`,
    when supplied, replaces the existing grant set.

    System roles refuse with 403 PERMISSION_DENIED (service raises).
    """
    rbac_service.update_custom_role(
        db,
        org_id=current_user.org_id,
        role_id=role_id,
        name=body.name,
        description=body.description,
        permission_codes=body.permissions,
    )
    return _load_role_with_permissions(db, org_id=current_user.org_id, role_id=role_id)


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a custom role",
)
def delete_role(
    role_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("identity.role.delete"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    """Owner-only — soft-deletes a non-system role. Refuses if users are
    still assigned (service raises 422 — Admin must reassign first).
    """
    rbac_service.delete_custom_role(
        db,
        org_id=current_user.org_id,
        role_id=role_id,
    )
    return None


# Sentinel — keeps the linter happy when imports are reorganised.
_ = text
