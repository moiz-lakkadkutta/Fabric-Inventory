"""RBAC service — system role seeding, permission checks, role assignment.

Exposes:

- `seed_system_permissions(session, org_id)`
- `seed_system_roles(session, org_id)`
- `assign_role(session, user_id, role_id, firm_id, org_id, actor_user_id=None)`
- `get_user_permissions(session, user_id, firm_id)`
- `has_permission(session, user_id, firm_id, permission_code)`
- `create_custom_role(session, org_id, code, name, permission_codes, description)`
- `update_custom_role(session, org_id, role_id, name=, description=, permission_codes=)`
- `delete_custom_role(session, org_id, role_id)`
- `list_system_permission_catalog()` — static catalog grouped by module
- `list_org_permissions(session, org_id)` — Permission rows for the org

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
from typing import Final, TypedDict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError, PermissionDeniedError
from app.models import AppUser, Permission, Role, RolePermission, UserRole
from app.service import audit_service

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
    ("identity.role", "delete", "Soft-delete custom roles"),
    # Masters
    ("masters.party", "create", "Create parties (customer/supplier/karigar/transporter)"),
    ("masters.party", "update", "Update parties"),
    ("masters.party", "read", "View parties"),
    (
        "masters.party.pii",
        "read",
        "View raw (unmasked) PII on parties: GSTIN, PAN, phone",
    ),
    ("masters.item", "create", "Create items / SKUs"),
    ("masters.item", "update", "Update items / SKUs"),
    ("masters.item", "read", "View items / SKUs"),
    ("masters.coa", "manage", "Manage chart of accounts"),
    # Sales
    ("sales.quote", "create", "Create sales quotations"),
    ("sales.order", "create", "Create sales orders"),
    ("sales.dc", "create", "Create delivery challans"),
    ("sales.dc", "read", "View delivery challans"),
    ("sales.dc", "approve", "Issue / acknowledge / soft-delete delivery challans"),
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
    ("purchase.invoice", "create", "Create draft purchase invoices"),
    ("purchase.invoice", "post", "Post purchase invoices"),
    ("purchase.invoice", "read", "View purchase invoices"),
    ("purchase.invoice", "void", "Void posted purchase invoices"),
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
    # Banking
    ("banking.bank", "create", "Create bank accounts / cheques"),
    ("banking.bank", "read", "View bank accounts / cheques"),
    ("banking.bank", "update", "Update bank accounts / cheques"),
    # Bank reconciliation (TASK-TR-B3) — match imported bank-statement
    # rows against posted RECEIPT/PAYMENT vouchers + create unmatched
    # rows as new vouchers. Read-only preview is gated by
    # accounting.voucher.read; confirming a match (mutates the
    # ``bank_reconciled_at`` stamp) needs this permission.
    (
        "accounting.bank_recon",
        "confirm",
        "Confirm bank-statement matches and create unmatched-as-voucher entries",
    ),
    # Admin
    ("admin.firm", "manage", "Manage firm settings"),
    ("admin.audit", "read", "View audit log"),
    # CRYPTO-01: verify the org's audit-log hash chain integrity.
    # Granted to OWNER via _ALL_PERMS; also added to ACCOUNTANT so
    # the accountant can run chain-integrity checks during period close.
    ("admin.audit", "verify", "Verify the integrity of the org's audit log hash chain"),
    ("admin.user", "manage", "Assign roles to users"),
    # Sales order — read + approve added in TASK-032
    ("sales.order", "read", "View sales orders"),
    ("sales.order", "approve", "Approve / cancel sales orders"),
    # COA admin endpoints (TASK-040)
    ("accounting.coa", "read", "View chart of accounts groups and ledgers"),
    ("accounting.coa", "update", "Create and update custom COA groups and ledgers"),
    # Dashboard (T-INT-2) — KPI bundle + activity feed.
    ("dashboard", "read", "View dashboard KPIs and activity"),
    # Job-work (TASK-CUT-305) — send-out / receive-back / ITC-04.
    ("jobwork.order", "create", "Create job-work send-out orders"),
    ("jobwork.order", "read", "View job-work orders and receipts"),
    ("jobwork.report", "read", "View ITC-04 and other job-work reports"),
    # Migrations (TASK-CUT-402) — upload + approve external-source data
    # imports (Vyapar today; Tally / generic Excel later).
    ("admin.migrations", "read", "View migration uploads and reconciliation reports"),
    (
        "admin.migrations",
        "approve",
        "Approve migration uploads (commits parties + opening balances)",
    ),
    # Manufacturing masters (TASK-TR-A02) — Design, Operation Master,
    # Cost Centre CRUD. BOM + routing + MO permissions land in A03/A04+.
    ("manufacturing.design", "create", "Create designs"),
    ("manufacturing.design", "update", "Update designs"),
    ("manufacturing.design", "read", "View designs"),
    ("manufacturing.design", "delete", "Soft-delete designs"),
    ("manufacturing.operation_master", "create", "Create operation masters"),
    ("manufacturing.operation_master", "update", "Update operation masters"),
    ("manufacturing.operation_master", "read", "View operation masters"),
    ("manufacturing.operation_master", "delete", "Soft-delete operation masters"),
    ("manufacturing.cost_centre", "create", "Create cost centres"),
    ("manufacturing.cost_centre", "update", "Update cost centres"),
    ("manufacturing.cost_centre", "read", "View cost centres"),
    ("manufacturing.cost_centre", "delete", "Soft-delete cost centres"),
    # BOM (TASK-TR-A03) — versioned bill of materials per (design,
    # finished_item). Edits flow through "create new version" (A03b will
    # add header / line PATCH); these permissions cover create / read /
    # activate / soft-delete.
    ("manufacturing.bom", "create", "Create BOMs (auto-bumps version per finished item)"),
    ("manufacturing.bom", "update", "Activate a BOM (demotes prior actives)"),
    ("manufacturing.bom", "read", "View BOMs and their lines"),
    ("manufacturing.bom", "delete", "Soft-delete BOMs"),
    # Routing (TASK-TR-A04) — operation DAG per design. Edits flow
    # through "replace edges" (atomic re-validation); a single
    # ``write`` permission covers create / update / soft-delete because
    # routing changes are inseparable from re-validating the DAG. Read
    # is split so Salesperson / Accountant can see routings (needed for
    # quoting + cost roll-up) without write access.
    ("manufacturing.routing", "write", "Create / update / soft-delete routings"),
    ("manufacturing.routing", "read", "View routings and their edges"),
    # Manufacturing Order (TASK-TR-A05) — MO header lifecycle. Each
    # mutation (create / release / start / complete / close) shares the
    # ``write`` permission; ``read`` is split so Accountants /
    # Salespeople can view MOs (for cost-roll-up + production-status
    # visibility) without write access.
    (
        "manufacturing.mo",
        "write",
        "Create / release / start / complete / close manufacturing orders",
    ),
    ("manufacturing.mo", "read", "View manufacturing orders and their lines + operations"),
    # Material issue (TASK-TR-A06) — money-touching outbound stock move
    # against a released MO. ``write`` covers the POST that decrements
    # stock + bumps ``qty_issued`` + posts the WIP voucher. Read is
    # split so Accountants can drill into WIP postings without the write
    # bit.
    (
        "manufacturing.material_issue",
        "write",
        "Issue raw materials from stock against a manufacturing order",
    ),
    (
        "manufacturing.material_issue",
        "read",
        "View material issues posted against manufacturing orders",
    ),
    # Operation progress (TASK-TR-A07) — per-MO operation lifecycle
    # (start / qty-in / qty-out / complete). ``progress`` covers every
    # mutating endpoint; ``read`` is split so Accountants can drill into
    # the production-event log for cost-roll-up without write access.
    (
        "manufacturing.operation",
        "progress",
        "Start / record qty in/out / complete in-house operations on an MO",
    ),
    (
        "manufacturing.operation",
        "read",
        "View MO operations + their production event log",
    ),
    # Karigar / job-work per-operation lifecycle (TASK-TR-A08). Split
    # off from ``manufacturing.operation.progress`` because dispatch ships
    # physical goods OUT to an external karigar and receive-back posts
    # stock IN — both stock-touching, and Warehouse staff (who already
    # carry ``jobwork.order.create``) should be able to drive them on
    # behalf of Production. The receive bit is separate from dispatch so
    # a "receive-only" reception clerk role is possible later; today both
    # ride alongside ``jobwork.order.create`` on Warehouse + Production
    # Manager.
    (
        "manufacturing.karigar",
        "dispatch",
        "Dispatch a karigar (job-work) operation — mints outward challan + sets MoOperation",
    ),
    (
        "manufacturing.karigar",
        "receive",
        "Receive back from a karigar operation — mints inward challan + updates MoOperation",
    ),
    # QC inspection operation (TASK-TR-A10). Split off from
    # ``manufacturing.operation.progress`` because QC has its own
    # state machine (PENDING → QC_PENDING → CLOSED / REWORK) and the
    # verdict has cost-roll-up consequences (A11) that warrant a
    # dedicated permission slug. A "QC Inspector" system role is not
    # in scope for v1 — OWNER + Production Manager carry both.
    (
        "manufacturing.qc",
        "write",
        "Start / record verdict on a QC inspection operation",
    ),
    (
        "manufacturing.qc",
        "read",
        "View QC operation state + latest verdict + bucket breakdown",
    ),
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
                "masters.party.pii.read",
                "masters.item.read",
                "masters.coa.manage",
                "accounting.coa.read",
                "accounting.coa.update",
                "sales.invoice.read",
                "purchase.invoice.read",
                "purchase.invoice.post",
                "inventory.stock.read",
                # TR-B02: Accountant needs lot read access for stock-valuation
                # drilldown (per-lot cost basis x on-hand qty).
                "inventory.lot.read",
                "accounting.voucher.post",
                "accounting.voucher.read",
                "accounting.report.view",
                "accounting.period.close",
                "banking.bank.read",
                "banking.bank.create",
                # TR-B3: Accountants reconcile bank statements monthly.
                "accounting.bank_recon.confirm",
                "admin.audit.read",
                # CRYPTO-01: Accountant needs verify to run chain-integrity
                # checks during period close audit procedures.
                "admin.audit.verify",
                "sales.order.read",
                "dashboard.read",
                "jobwork.order.read",
                "jobwork.report.read",
                # Manufacturing masters — Accountants need read everywhere
                # (cost-centre ties to GL postings) but no create/update.
                "manufacturing.design.read",
                "manufacturing.operation_master.read",
                "manufacturing.cost_centre.read",
                "manufacturing.cost_centre.create",
                "manufacturing.cost_centre.update",
                "manufacturing.cost_centre.delete",
                # BOM (A03) — Accountant reads only; cost-centre-tied
                # GL postings need BOM visibility, no editing.
                "manufacturing.bom.read",
                # Routing (A04) — Accountant reads only; routing edges
                # tie to per-operation cost accrual on the MO ledger.
                "manufacturing.routing.read",
                # MO (A05) — Accountant reads only; cost roll-up + WIP
                # ledger drilldown need MO visibility, no editing.
                "manufacturing.mo.read",
                # Material issue (A06) — Accountant reads only; needs to
                # drill into the DR WIP / CR Inventory voucher's source
                # MI document. No write.
                "manufacturing.material_issue.read",
                # Operation progress (A07) — Accountant reads only; the
                # production_event log is the audit trail for WIP cost
                # accrual. No write.
                "manufacturing.operation.read",
                # QC (A10) — Accountant reads only; QC verdict + bucket
                # breakdown feeds A11 WIP cost settlement. No write.
                "manufacturing.qc.read",
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
                "masters.party.pii.read",
                "masters.item.read",
                "sales.quote.create",
                "sales.order.create",
                "sales.dc.create",
                "sales.dc.read",
                "sales.invoice.create",
                "sales.invoice.finalize",
                "sales.invoice.read",
                "sales.return.create",
                "inventory.stock.read",
                # TR-B02: Salespeople need to see which lot is going out
                # of a DC/invoice — same read class as inventory.stock.
                "inventory.lot.read",
                "sales.order.read",
                "dashboard.read",
                # Manufacturing masters — Salesperson needs to look up
                # designs + operations when quoting, but no write and no
                # cost-centre visibility (financial classification).
                "manufacturing.design.read",
                "manufacturing.operation_master.read",
                # BOM (A03) — Salesperson reads only; quoting needs to
                # know which BOM (and therefore which components / cost)
                # backs a finished item. No write.
                "manufacturing.bom.read",
                # Routing (A04) — Salesperson reads only; visible for
                # quoting context (which operation chain backs a
                # design), no write. NB: deny is the security test the
                # service test suite locks in.
                "manufacturing.routing.read",
            }
        ),
    ),
    (
        "WAREHOUSE",
        "Warehouse",
        "GRN, stock movements, delivery challans, job-work send-out/receive.",
        frozenset(
            {
                "masters.item.read",
                "masters.party.read",
                "masters.party.pii.read",
                "purchase.po.read",
                "purchase.grn.create",
                "purchase.grn.read",
                "purchase.grn.approve",
                "inventory.stock.read",
                "inventory.adjustment.create",
                "inventory.transfer.create",
                "inventory.lot.read",
                "sales.dc.create",
                "sales.dc.read",
                "sales.dc.approve",
                "jobwork.order.create",
                "jobwork.order.read",
                # Karigar (A08) — Warehouse runs the dispatch dock + the
                # receive-back counter; they already own the
                # jobwork.order.create permission for the same physical
                # workflow, so karigar dispatch/receive ride alongside.
                # ``manufacturing.operation.read`` lets them see the MO
                # operation row they're acting on.
                "manufacturing.karigar.dispatch",
                "manufacturing.karigar.receive",
                "manufacturing.operation.read",
            }
        ),
    ),
    (
        "PRODUCTION_MANAGER",
        "Production Manager",
        "MOs, dispatch, receive, QC, job-work tracking.",
        frozenset(
            {
                "masters.item.read",
                "masters.party.read",
                "masters.party.pii.read",
                "inventory.stock.read",
                "inventory.lot.read",
                "jobwork.order.create",
                "jobwork.order.read",
                "jobwork.report.read",
                # Manufacturing masters — Production Manager runs the
                # shop floor: create/update Designs + OperationMasters;
                # cost-centre is read-only (Accountant / Owner edits the
                # financial side).
                "manufacturing.design.create",
                "manufacturing.design.update",
                "manufacturing.design.read",
                "manufacturing.design.delete",
                "manufacturing.operation_master.create",
                "manufacturing.operation_master.update",
                "manufacturing.operation_master.read",
                "manufacturing.operation_master.delete",
                "manufacturing.cost_centre.read",
                # BOM (A03) — Production Manager owns BOM lifecycle:
                # create new versions, activate, soft-delete, read.
                "manufacturing.bom.create",
                "manufacturing.bom.update",
                "manufacturing.bom.read",
                "manufacturing.bom.delete",
                # Routing (A04) — Production Manager owns routing
                # lifecycle (create / replace edges / soft-delete + read).
                "manufacturing.routing.write",
                "manufacturing.routing.read",
                # MO (A05) — Production Manager owns the MO lifecycle:
                # create / release / start / complete / close + read.
                "manufacturing.mo.write",
                "manufacturing.mo.read",
                # Material issue (A06) — Production Manager owns
                # stock-issue against MOs (drives the shop floor).
                "manufacturing.material_issue.write",
                "manufacturing.material_issue.read",
                # Operation progress (A07) — Production Manager drives
                # the shop floor: start / record qty / complete per-op
                # progress for in-house operations.
                "manufacturing.operation.progress",
                "manufacturing.operation.read",
                # Karigar (A08) — Production Manager dispatches /
                # acknowledges / receives back per-operation send-outs
                # to external job-work contractors.
                "manufacturing.karigar.dispatch",
                "manufacturing.karigar.receive",
                # QC (A10) — Production Manager runs the QC inspection
                # (start / record verdict). Read for the FE workflow.
                "manufacturing.qc.write",
                "manufacturing.qc.read",
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
    actor_user_id: uuid.UUID | None = None,
) -> UserRole:
    """Create a UserRole row. Idempotent on (user, role, firm) — `firm_id=None`
    means org-level scope (one-of-a-kind per user/role pair, enforced by the
    partial unique index `uq_user_role_user_role_firm`).

    `actor_user_id` is the operator who triggered this assignment (used for
    audit). None is acceptable for bootstrap paths where no human actor exists.
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
    # TS-05/IDM-5: bump the user's permissions_version so any outstanding
    # JWT carrying the old pv is rejected on the very next request.
    session.execute(
        update(AppUser)
        .where(AppUser.user_id == user_id)
        .values(permissions_version=AppUser.permissions_version + 1)
    )
    session.flush()
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=actor_user_id,
        entity_type="UserRole",
        entity_id=user_role.user_role_id,
        action="role_assign",
        changes={"user_id": str(user_id), "role_id": str(role_id)},
    )
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


def get_role_permission_codes(
    session: Session,
    *,
    role_id: uuid.UUID,
) -> set[str]:
    """Return the set of permission codes granted to `role_id`.

    Used by the privilege-ceiling check in invite_service to compare
    an invited role's permission set against the actor's effective perms.
    """
    rows = session.execute(
        select(Permission.resource, Permission.action)
        .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
        .where(RolePermission.role_id == role_id)
    ).all()
    return {f"{r}.{a}" for r, a in rows}


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
    actor_user_id: uuid.UUID | None = None,
    actor_firm_id: uuid.UUID | None = None,
) -> Role:
    """Create a non-system role with the given permission grants.

    Validates:
      - `code` and `name` are non-empty.
      - `code` doesn't collide with a system role code.
      - Every entry in `permission_codes` exists for this org.
      - (PRIV-1) If `actor_user_id` is set, `permission_codes ⊆ actor's
        effective permissions` — a caller cannot grant perms they don't hold.
        When `actor_user_id is None` (system/seed path) the check is skipped.

    `actor_user_id` is used for audit and for the ceiling check.
    `actor_firm_id` scopes the actor's permission lookup (pass the firm the
    caller authenticated against; None = org-level only).
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

    # PRIV-1: permission ceiling — a caller cannot grant permissions they don't
    # themselves hold. Derive the actor's effective perms SERVER-SIDE (not from
    # the JWT which can be stale). Skip only for the trusted seed/system path
    # where actor_user_id is None (no human actor to check against).
    if actor_user_id is not None:
        actor_effective = get_user_permissions(
            session, user_id=actor_user_id, firm_id=actor_firm_id
        )
        offending = sorted(set(requested) - actor_effective)
        if offending:
            raise PermissionDeniedError(f"Cannot grant permissions you don't hold: {offending}")

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

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=None,
        user_id=actor_user_id,
        entity_type="Role",
        entity_id=role.role_id,
        action="role_create",
        changes={"code": code, "name": name, "permissions": list(requested)},
    )
    return role


def update_system_role(*_args: object, **_kwargs: object) -> None:
    """System roles are immutable for MVP. Surface a clear error rather than
    a silent success path so callers can adopt a Phase-2 mutable-roles model
    without changing call sites.
    """
    raise PermissionDeniedError("System roles are immutable for MVP")


def update_custom_role(
    session: Session,
    *,
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    permission_codes: Iterable[str] | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_firm_id: uuid.UUID | None = None,
) -> Role:
    """Update name/description/permission grants on a non-system role.

    `permission_codes`, when provided, is treated as the new full set —
    grants are replaced (delete-then-insert). When ``None``, grants are
    left untouched.

    Validates:
      - Role exists in this org and is not soft-deleted.
      - Role is not a system role (system roles are immutable).
      - `name`, when provided, is non-empty.
      - Every entry in `permission_codes` exists for this org.
      - (PRIV-1) If `actor_user_id` is set and `permission_codes` is
        provided, `permission_codes ⊆ actor's effective permissions`.
    """
    role = session.execute(
        select(Role).where(
            Role.role_id == role_id,
            Role.org_id == org_id,
            Role.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if role is None:
        raise AppValidationError(f"Role {role_id} not found in this organization")
    if role.is_system_role:
        raise PermissionDeniedError("System roles are immutable for MVP")

    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise AppValidationError("Role `name` cannot be empty")
        role.name = stripped
    if description is not None:
        role.description = description or None

    if permission_codes is not None:
        perms = {
            f"{p.resource}.{p.action}": p
            for p in session.execute(
                select(Permission).where(Permission.org_id == org_id)
            ).scalars()
        }
        requested = list(permission_codes)
        unknown = sorted({c for c in requested if c not in perms})
        if unknown:
            raise AppValidationError(f"Unknown permission codes: {unknown}")

        # PRIV-1: ceiling check — actor cannot update a role to include
        # permissions they don't themselves hold. Skip for system/seed path
        # (actor_user_id is None).
        if actor_user_id is not None:
            actor_effective = get_user_permissions(
                session, user_id=actor_user_id, firm_id=actor_firm_id
            )
            offending = sorted(set(requested) - actor_effective)
            if offending:
                raise PermissionDeniedError(f"Cannot grant permissions you don't hold: {offending}")

        # Replace grants — delete-then-insert. Cleaner than diffing, and
        # `role_permission` is exempt from audit so the churn doesn't
        # bloat the audit log.
        existing_grants = list(
            session.execute(
                select(RolePermission).where(RolePermission.role_id == role.role_id)
            ).scalars()
        )
        for g in existing_grants:
            session.delete(g)
        session.flush()
        new_grants = [
            RolePermission(
                org_id=org_id,
                role_id=role.role_id,
                permission_id=perms[c].permission_id,
            )
            for c in requested
        ]
        if new_grants:
            session.add_all(new_grants)
            session.flush()

        # TS-05/IDM-5: bump permissions_version on every user who holds
        # this role so their outstanding JWTs become stale immediately.
        affected_user_ids = list(
            session.execute(
                select(UserRole.user_id).where(UserRole.role_id == role.role_id)
            ).scalars()
        )
        if affected_user_ids:
            session.execute(
                update(AppUser)
                .where(AppUser.user_id.in_(affected_user_ids))
                .values(permissions_version=AppUser.permissions_version + 1)
            )
            session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=None,
        user_id=actor_user_id,
        entity_type="Role",
        entity_id=role.role_id,
        action="role_update",
        changes={
            "name": name,
            "permission_codes": list(permission_codes) if permission_codes is not None else None,
        },
    )
    return role


def delete_custom_role(
    session: Session,
    *,
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Soft-delete a non-system role.

    Validates:
      - Role exists in this org and isn't already deleted.
      - Role is not a system role.
      - No live `UserRole` rows reference it — refuse delete if users are
        still assigned (Admin must reassign first; saves us from leaving
        users with zero effective permissions).

    `actor_user_id` is used for audit; None is accepted for system paths.
    """
    role = session.execute(
        select(Role).where(
            Role.role_id == role_id,
            Role.org_id == org_id,
            Role.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if role is None:
        raise AppValidationError(f"Role {role_id} not found in this organization")
    if role.is_system_role:
        raise PermissionDeniedError("System roles cannot be deleted")

    assigned_count = (
        session.execute(select(UserRole).where(UserRole.role_id == role_id)).scalars().first()
    )
    if assigned_count is not None:
        raise AppValidationError(
            "Cannot delete a role with users still assigned — reassign users first"
        )

    import datetime as _dt

    role.deleted_at = _dt.datetime.now(_dt.UTC)
    session.flush()
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=None,
        user_id=actor_user_id,
        entity_type="Role",
        entity_id=role.role_id,
        action="role_delete",
        changes={"code": role.code, "name": role.name},
    )


# ──────────────────────────────────────────────────────────────────────
# Permission catalog (FE consumes for the Role builder)
# ──────────────────────────────────────────────────────────────────────


def _module_for_resource(resource: str) -> str:
    """Map a permission `resource` (e.g. ``sales.invoice``) to a UI module
    bucket (``sales``). The bucket is just the first dotted segment.
    """
    return resource.split(".", 1)[0]


class PermissionCatalogEntryDict(TypedDict):
    code: str
    resource: str
    action: str
    description: str


class PermissionCatalogModuleDict(TypedDict):
    module: str
    permissions: list[PermissionCatalogEntryDict]


def list_system_permission_catalog() -> list[PermissionCatalogModuleDict]:
    """Returns the static catalog the FE renders in the Role builder.

    Shape: a list of ``{module, permissions: [{code, resource, action, description}]}``
    entries, ordered by the canonical module sequence so the UI is stable.
    The list comes straight from `_SYSTEM_PERMISSIONS` so adding a new
    permission to the catalog automatically surfaces here.
    """
    # Canonical module order — mirrors the sequence in `_SYSTEM_PERMISSIONS`
    # rather than alphabetic so related groups stay adjacent in the UI.
    seen_modules: list[str] = []
    grouped: dict[str, list[PermissionCatalogEntryDict]] = {}
    for resource, action, description in _SYSTEM_PERMISSIONS:
        module = _module_for_resource(resource)
        if module not in grouped:
            grouped[module] = []
            seen_modules.append(module)
        grouped[module].append(
            PermissionCatalogEntryDict(
                code=f"{resource}.{action}",
                resource=resource,
                action=action,
                description=description,
            )
        )
    return [
        PermissionCatalogModuleDict(module=module, permissions=grouped[module])
        for module in seen_modules
    ]
