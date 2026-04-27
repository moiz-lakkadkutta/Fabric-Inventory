"""RBAC service — system role seeding, permission checks, role assignment.

Exposes:

- `seed_system_permissions(session, org_id)`
- `seed_system_roles(session, org_id)`
- `assign_role(session, user_id, role_id, firm_id, org_id)`
- `get_user_permissions(session, user_id, firm_id)`
- `has_permission(session, user_id, firm_id, permission_code)`
- `create_custom_role(session, org_id, code, name, permission_codes, description)`

Conventions:

- Permission codes are `"resource.action"` strings (e.g., `sales.invoice.finalize`).
- System roles are immutable (`is_system_role=True`). Their seed is idempotent
  — calling `seed_system_roles` twice is a no-op.
- A user's effective permission set is the union over every role assigned
  to them, scoped to the firm OR org-level (`firm_id IS NULL`).
- `create_custom_role` is for Owner-only callers; the router that wraps it
  enforces that gate via `has_permission(..., "identity.role.create")`.
- System roles can't be re-coded by a custom role (same code → ValidationError).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError, PermissionDeniedError
from app.models import Permission, Role, RolePermission, UserRole

# ──────────────────────────────────────────────────────────────────────
# System catalog — drives both seeding and the permission set we accept.
#
# Adding a new permission: append a row here. Seed is idempotent, so
# every existing org picks up new permissions on next signup-path call.
# Existing orgs won't auto-receive them; surface a one-shot reseed
# helper if/when that's needed.
# ──────────────────────────────────────────────────────────────────────


# (resource, action, description)
_SYSTEM_PERMISSIONS: Final[tuple[tuple[str, str, str], ...]] = (
    # Identity / admin
    ("identity.user", "create", "Create users in this organization"),
    ("identity.user", "update", "Update users in this organization"),
    ("identity.user", "read", "View users in this organization"),
    ("identity.role", "create", "Create custom roles"),
    ("identity.role", "update", "Update custom roles"),
    ("identity.role", "read", "View roles + permissions"),
    # Masters
    ("masters.party", "create", "Create parties (customer/supplier/karigar/transporter)"),
    ("masters.party", "update", "Update parties"),
    ("masters.party", "read", "View parties"),
    ("masters.item", "create", "Create items / SKUs"),
    ("masters.item", "update", "Update items / SKUs"),
    ("masters.item", "read", "View items / SKUs"),
    ("masters.coa", "manage", "Manage chart of accounts"),
    # Sales
    ("sales.quote", "create", "Create sales quotations"),
    ("sales.order", "create", "Create sales orders"),
    ("sales.dc", "create", "Create delivery challans"),
    ("sales.invoice", "create", "Create draft sales invoices"),
    ("sales.invoice", "finalize", "Finalize sales invoices"),
    ("sales.invoice", "cancel", "Cancel finalized invoices"),
    ("sales.invoice", "read", "View sales invoices"),
    ("sales.return", "create", "Create credit notes / sales returns"),
    # Purchase
    ("purchase.po", "create", "Create purchase orders"),
    ("purchase.po", "approve", "Approve purchase orders"),
    ("purchase.po", "read", "View purchase orders"),
    ("purchase.grn", "create", "Create goods received notes (GRN)"),
    ("purchase.grn", "read", "View goods received notes"),
    ("purchase.grn", "approve", "Receive / acknowledge / cancel GRNs"),
    ("purchase.invoice", "post", "Post purchase invoices"),
    ("purchase.invoice", "read", "View purchase invoices"),
    # Inventory
    ("inventory.stock", "read", "View stock positions"),
    ("inventory.adjustment", "create", "Create stock adjustments"),
    ("inventory.transfer", "create", "Create stock transfers between godowns"),
    ("inventory.lot", "read", "View lot details"),
    # Accounting
    ("accounting.voucher", "post", "Post journal vouchers / payments / receipts"),
    ("accounting.voucher", "read", "View vouchers"),
    ("accounting.report", "view", "View P&L, BS, TB, ageing reports"),
    ("accounting.period", "close", "Close accounting periods"),
    # Admin
    ("admin.firm", "manage", "Manage firm settings"),
    ("admin.audit", "read", "View audit log"),
    ("admin.user", "manage", "Assign roles to users"),
    # Sales order — read + approve added in TASK-032
    ("sales.order", "read", "View sales orders"),
    ("sales.order", "approve", "Approve / cancel sales orders"),
)


_ALL_PERMS: Final[frozenset[str]] = frozenset(f"{r}.{a}" for r, a, _ in _SYSTEM_PERMISSIONS)


# (code, name, description, permission_codes)
_SYSTEM_ROLES: Final[tuple[tuple[str, str, str, frozenset[str]], ...]] = (
    (
        "OWNER",
        "Owner",
        "Full access to everything in the organization.",
        _ALL_PERMS,
    ),
    (
        "ACCOUNTANT",
        "Accountant",
        "Books, vouchers, reports, period close.",
        frozenset(
            {
                "identity.user.read",
                "identity.role.read",
                "masters.party.read",
                "masters.item.read",
                "masters.coa.manage",
                "sales.invoice.read",
                "purchase.invoice.read",
                "purchase.invoice.post",
                "inventory.stock.read",
                "accounting.voucher.post",
                "accounting.voucher.read",
                "accounting.report.view",
                "accounting.period.close",
                "admin.audit.read",
                "sales.order.read",
            }
        ),
    ),
    (
        "SALESPERSON",
        "Salesperson",
        "Quotes, orders, invoices, customer ledger.",
        frozenset(
            {
                "masters.party.create",
                "masters.party.update",
                "masters.party.read",
                "masters.item.read",
                "sales.quote.create",
                "sales.order.create",
                "sales.dc.create",
                "sales.invoice.create",
                "sales.invoice.finalize",
                "sales.invoice.read",
                "sales.return.create",
                "inventory.stock.read",
                "sales.order.read",
            }
        ),
    ),
    (
        "WAREHOUSE",
        "Warehouse",
        "GRN, stock movements, delivery challans.",
        frozenset(
            {
                "masters.item.read",
                "masters.party.read",
                "purchase.po.read",
                "purchase.grn.create",
                "purchase.grn.read",
                "purchase.grn.approve",
                "inventory.stock.read",
                "inventory.adjustment.create",
                "inventory.transfer.create",
                "inventory.lot.read",
                "sales.dc.create",
            }
        ),
    ),
    (
        "PRODUCTION_MANAGER",
        "Production Manager",
        "MOs, dispatch, receive, QC. Phase-3 surface — minimal MVP perms.",
        frozenset(
            {
                "masters.item.read",
                "masters.party.read",
                "inventory.stock.read",
                "inventory.lot.read",
            }
        ),
    ),
)


SYSTEM_ROLE_CODES: Final[frozenset[str]] = frozenset(code for code, *_ in _SYSTEM_ROLES)


# ──────────────────────────────────────────────────────────────────────
# Seeding (idempotent)
# ──────────────────────────────────────────────────────────────────────


def seed_system_permissions(session: Session, *, org_id: uuid.UUID) -> dict[str, Permission]:
    """Insert any system permissions missing for this org. Idempotent.

    Returns the full {code: Permission} mapping for `org_id` afterwards.
    """
    existing = {
        f"{p.resource}.{p.action}": p
        for p in session.execute(
            select(Permission).where(
                Permission.org_id == org_id, Permission.is_system_permission.is_(True)
            )
        ).scalars()
    }
    to_create: list[Permission] = []
    for resource, action, description in _SYSTEM_PERMISSIONS:
        code = f"{resource}.{action}"
        if code in existing:
            continue
        to_create.append(
            Permission(
                org_id=org_id,
                resource=resource,
                action=action,
                description=description,
                is_system_permission=True,
            )
        )
    if to_create:
        session.add_all(to_create)
        session.flush()
        for perm in to_create:
            existing[f"{perm.resource}.{perm.action}"] = perm
    return existing


def seed_system_roles(session: Session, *, org_id: uuid.UUID) -> dict[str, Role]:
    """Idempotent: ensure all 5 system roles exist with their permission grants.

    Returns {role_code: Role}.
    """
    perms = seed_system_permissions(session, org_id=org_id)

    existing_roles = {
        r.code: r
        for r in session.execute(
            select(Role).where(Role.org_id == org_id, Role.is_system_role.is_(True))
        ).scalars()
    }

    for code, name, description, perm_codes in _SYSTEM_ROLES:
        role = existing_roles.get(code)
        if role is None:
            role = Role(
                org_id=org_id,
                code=code,
                name=name,
                description=description,
                is_system_role=True,
            )
            session.add(role)
            session.flush()
            existing_roles[code] = role

        existing_grants = {
            rp.permission_id
            for rp in session.execute(
                select(RolePermission).where(RolePermission.role_id == role.role_id)
            ).scalars()
        }
        new_grants: list[RolePermission] = []
        for perm_code in perm_codes:
            perm = perms.get(perm_code)
            if perm is None:
                # Forward-compat: role references a perm not yet seeded.
                continue
            if perm.permission_id in existing_grants:
                continue
            new_grants.append(
                RolePermission(
                    org_id=org_id,
                    role_id=role.role_id,
                    permission_id=perm.permission_id,
                )
            )
        if new_grants:
            session.add_all(new_grants)
            session.flush()

    return existing_roles


# ──────────────────────────────────────────────────────────────────────
# Assignment + checks
# ──────────────────────────────────────────────────────────────────────


def assign_role(
    session: Session,
    *,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    firm_id: uuid.UUID | None,
    org_id: uuid.UUID,
) -> UserRole:
    """Create a UserRole row. Idempotent on (user, role, firm) — `firm_id=None`
    means org-level scope (one-of-a-kind per user/role pair, enforced by the
    partial unique index `uq_user_role_user_role_firm`).
    """
    where = [UserRole.user_id == user_id, UserRole.role_id == role_id]
    if firm_id is None:
        where.append(UserRole.firm_id.is_(None))
    else:
        where.append(UserRole.firm_id == firm_id)
    existing = session.execute(select(UserRole).where(*where)).scalar_one_or_none()
    if existing is not None:
        return existing
    user_role = UserRole(org_id=org_id, user_id=user_id, role_id=role_id, firm_id=firm_id)
    session.add(user_role)
    session.flush()
    return user_role


def get_user_permissions(
    session: Session,
    *,
    user_id: uuid.UUID,
    firm_id: uuid.UUID | None,
) -> set[str]:
    """Effective permission codes for `user_id` in the firm scope.

    Includes both firm-scoped roles (`UserRole.firm_id == firm_id`) and
    org-level roles (`UserRole.firm_id IS NULL`). When `firm_id` is None
    only org-level roles apply.
    """
    role_filters = [UserRole.user_id == user_id]
    if firm_id is None:
        role_filters.append(UserRole.firm_id.is_(None))
    else:
        role_filters.append((UserRole.firm_id == firm_id) | (UserRole.firm_id.is_(None)))
    role_ids_q = select(UserRole.role_id).where(*role_filters)

    rows = session.execute(
        select(Permission.resource, Permission.action)
        .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
        .where(RolePermission.role_id.in_(role_ids_q))
    ).all()
    return {f"{r}.{a}" for r, a in rows}


def has_permission(
    session: Session,
    *,
    user_id: uuid.UUID,
    firm_id: uuid.UUID | None,
    permission_code: str,
) -> bool:
    """Boolean check — does `user_id` carry `permission_code` in `firm_id`?"""
    return permission_code in get_user_permissions(session, user_id=user_id, firm_id=firm_id)


# ──────────────────────────────────────────────────────────────────────
# Custom roles
# ──────────────────────────────────────────────────────────────────────


def create_custom_role(
    session: Session,
    *,
    org_id: uuid.UUID,
    code: str,
    name: str,
    permission_codes: Iterable[str],
    description: str | None = None,
) -> Role:
    """Create a non-system role with the given permission grants.

    Validates:
      - `code` and `name` are non-empty.
      - `code` doesn't collide with a system role code.
      - Every entry in `permission_codes` exists for this org.

    The Owner-only gate lives in the router that calls this — services
    don't enforce permissions on themselves (that would be circular).
    """
    if not code or not name:
        raise AppValidationError("Custom role requires both `code` and `name`")
    if code in SYSTEM_ROLE_CODES:
        raise AppValidationError(f"{code!r} is reserved for a system role")

    perms = {
        f"{p.resource}.{p.action}": p
        for p in session.execute(select(Permission).where(Permission.org_id == org_id)).scalars()
    }
    requested = list(permission_codes)
    unknown = sorted({c for c in requested if c not in perms})
    if unknown:
        raise AppValidationError(f"Unknown permission codes: {unknown}")

    role = Role(
        org_id=org_id,
        code=code,
        name=name,
        description=description,
        is_system_role=False,
    )
    session.add(role)
    session.flush()

    grants = [
        RolePermission(org_id=org_id, role_id=role.role_id, permission_id=perms[c].permission_id)
        for c in requested
    ]
    if grants:
        session.add_all(grants)
        session.flush()
    return role


def update_system_role(*_args: object, **_kwargs: object) -> None:
    """System roles are immutable for MVP. Surface a clear error rather than
    a silent success path so callers can adopt a Phase-2 mutable-roles model
    without changing call sites.
    """
    raise PermissionDeniedError("System roles are immutable for MVP")
