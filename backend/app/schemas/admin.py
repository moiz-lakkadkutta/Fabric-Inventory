"""Admin router request / response models (TASK-CUT-304).

Surface covered:

- GET /admin/users — list users with role + status
- POST /admin/invites — mint an invite + console-log the link
- POST /admin/invites/accept — consume an invite + create the user
- PATCH /admin/users/{user_id}/role — swap a user's role (with
  last-Owner-demotion protection)

All endpoints are gated by `admin.user.manage` per the RBAC catalog.
The accept endpoint is the one exception: it MUST run without a JWT
(the user hasn't logged in yet) and is exempt from the
Idempotency-Key middleware (the token IS the idempotency key —
it's single-use by construction).
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, EmailStr, Field


class AdminUserResponse(BaseModel):
    """One row in the admin users list — slim shape the FE table renders."""

    user_id: uuid.UUID
    email: EmailStr
    name: str | None = None
    role: str
    """Role display name (e.g. "Owner", "Salesperson"). Not the code."""
    role_id: uuid.UUID
    """Role identifier — the FE PATCHes this when changing role."""
    status: str
    """One of "ACTIVE" / "SUSPENDED" / "INACTIVE"."""
    last_login_at: datetime.datetime | None = None
    created_at: datetime.datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    count: int


class InviteCreateRequest(BaseModel):
    """Owner-initiated invite. `firm_id` is optional — omit for org-wide
    (Owner) invites; populate for per-firm roles like Salesperson.
    """

    email: EmailStr
    role_id: uuid.UUID
    firm_id: uuid.UUID | None = None


class InviteCreateResponse(BaseModel):
    invite_id: uuid.UUID
    email: EmailStr
    expires_at: datetime.datetime
    invite_link: str | None = None
    """Full FE URL the recipient opens.

    IDM-3: only populated in ``ENVIRONMENT=dev`` so the raw invite token
    does not travel over the API wire in staging/production (where it must
    arrive exclusively via the email adapter). Test code reads this field
    directly when running in dev mode; CI uses it too since CI sets
    ENVIRONMENT=dev.  In non-dev environments the field is absent from
    the JSON response (excluded when None via ``response_model_exclude_none``
    on the endpoint).
    """


class AcceptInviteRequest(BaseModel):
    """The invitee posts this from `/invite/:token`."""

    token: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=200)


class AcceptInviteResponse(BaseModel):
    """201 on success. Issues no tokens — the FE redirects to /login so
    the new user enters their freshly-set password and the standard login
    flow exercises bcrypt + MFA-enrollment paths. Decision recorded in
    `docs/retros/task-CUT-304.md`.

    `org_name` is echoed back so the login form can pre-fill the org
    field (the recipient is unlikely to know the exact org name).
    """

    user_id: uuid.UUID
    org_id: uuid.UUID
    email: EmailStr
    org_name: str


class UpdateUserRoleRequest(BaseModel):
    role_id: uuid.UUID


# ──────────────────────────────────────────────────────────────────────
# Custom-role CRUD (TASK-TR-B4)
# ──────────────────────────────────────────────────────────────────────


class PermissionCatalogEntry(BaseModel):
    """One row in the permission catalog — the FE renders these as
    checkbox leaves in the Role builder.
    """

    code: str
    """Full code, ``resource.action`` (e.g. ``sales.invoice.create``)."""
    resource: str
    action: str
    description: str | None = None


class PermissionCatalogModule(BaseModel):
    """A module bucket (``sales``, ``inventory``, etc.) groups related
    permission codes under a collapsible section in the UI.
    """

    module: str
    permissions: list[PermissionCatalogEntry]


class PermissionCatalogResponse(BaseModel):
    items: list[PermissionCatalogModule]


class CreateRoleRequest(BaseModel):
    """Owner-only — `code` must be lowercase alphanumeric + underscore;
    can't collide with a system role.
    """

    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    permissions: list[str] = Field(default_factory=list)


class UpdateRoleRequest(BaseModel):
    """All fields optional — supply only what's changing. `permissions`,
    if present, replaces the existing grant set entirely.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    permissions: list[str] | None = None


class RoleResponse(BaseModel):
    """Full role detail — used for both create + edit dialogs. Includes
    grants so the edit dialog can pre-check the boxes.
    """

    role_id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    is_system_role: bool
    permissions: list[str]
