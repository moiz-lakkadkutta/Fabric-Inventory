"""Manufacturing masters service — Design / OperationMaster / CostCentre CRUD
(TASK-TR-A02).

Sync ``Session``-based, kw-only signatures, explicit ``org_id`` filter on
top of RLS (CLAUDE.md invariant; same pattern as
``masters_service.party_*`` and ``items_service.item_*``).

Three independent masters share this module so we have one place for
Manufacturing-domain CRUD. A03 / A04 will introduce BOM and Routing
services in separate modules (``bom_service.py`` / ``routing_service.py``)
to keep file sizes manageable.

Naming kept verbose (``create_design`` not ``create``) so call sites read
unambiguously when this module is imported next to the rest of the
service layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models.manufacturing import Design, OperationMaster, OperationType
from app.models.masters import CostCentre, CostCentreType
from app.service import audit_service
from app.service.common_guards import assert_firm_in_org

# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _assert_cost_centre_in_scope(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    cost_centre_id: uuid.UUID,
) -> None:
    """Verify ``cost_centre_id`` belongs to ``(org_id, firm_id)`` before it
    lands on a Design / OperationMaster row.

    Cost centres are firm-scoped (``cost_centre.firm_id`` is NOT NULL with
    a UNIQUE(firm_id, code) constraint), so a Design in firm A must not be
    able to point at a CC in firm B — even within the same org. RLS pins
    org-isolation at the DB layer; this check enforces firm-isolation at
    the service layer and turns what would otherwise be an opaque FK
    insert (passing RLS but breaking the firm invariant) into a clean
    422 the UI can display.
    """
    cc = session.execute(
        select(CostCentre).where(
            CostCentre.cost_centre_id == cost_centre_id,
            CostCentre.org_id == org_id,
            CostCentre.firm_id == firm_id,
            CostCentre.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if cc is None:
        raise AppValidationError(
            f"Cost centre {cost_centre_id} not found or belongs to a different org/firm."
        )


# ──────────────────────────────────────────────────────────────────────
# Design CRUD
# ──────────────────────────────────────────────────────────────────────


def create_design(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    code: str,
    name: str,
    description: str | None = None,
    cost_centre_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> Design:
    """Create a Design. ``code`` is unique per ``(firm_id, code)`` —
    DB-enforced via ``design_firm_id_code_key``; service catches early
    for a clean 422 instead of a raw IntegrityError.
    """
    assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    if not code:
        raise AppValidationError("Design code is required")
    if not name:
        raise AppValidationError("Design name is required")

    existing = session.execute(
        select(Design).where(
            Design.org_id == org_id,
            Design.firm_id == firm_id,
            Design.code == code,
            Design.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"Design with code {code!r} already exists in this firm scope")

    if cost_centre_id is not None:
        _assert_cost_centre_in_scope(
            session, org_id=org_id, firm_id=firm_id, cost_centre_id=cost_centre_id
        )

    design = Design(
        org_id=org_id,
        firm_id=firm_id,
        code=code,
        name=name,
        description=description,
        cost_centre_id=cost_centre_id,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(design)
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="manufacturing.design",
        entity_id=design.design_id,
        action="create",
        changes={"after": {"code": code, "name": name}},
    )
    return design


def get_design(session: Session, *, org_id: uuid.UUID, design_id: uuid.UUID) -> Design:
    """Defense-in-depth ``org_id`` filter on top of RLS."""
    design = session.execute(
        select(Design).where(
            Design.design_id == design_id,
            Design.org_id == org_id,
            Design.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if design is None:
        raise AppValidationError(f"Design {design_id} not found")
    return design


def list_designs(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Design]:
    """List designs. ``firm_id=None`` returns all designs in the org.

    ``search`` is a case-insensitive substring match on code or name.
    """
    stmt = select(Design).where(Design.org_id == org_id, Design.deleted_at.is_(None))
    if firm_id is not None:
        stmt = stmt.where(Design.firm_id == firm_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Design.code.ilike(like), Design.name.ilike(like)))
    stmt = stmt.order_by(Design.code).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def patch_design(
    session: Session,
    *,
    org_id: uuid.UUID,
    design_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    cost_centre_id: uuid.UUID | None = None,
    updated_by: uuid.UUID | None = None,
) -> Design:
    """PATCH semantics — only fields explicitly passed are updated. ``code`` is
    intentionally immutable; downstream BOMs / routings / MOs reference it.
    """
    design = get_design(session, org_id=org_id, design_id=design_id)
    if name is not None:
        if not name:
            raise AppValidationError("name cannot be empty")
        design.name = name
    if description is not None:
        design.description = description
    if cost_centre_id is not None:
        _assert_cost_centre_in_scope(
            session,
            org_id=org_id,
            firm_id=design.firm_id,
            cost_centre_id=cost_centre_id,
        )
        design.cost_centre_id = cost_centre_id

    design.updated_at = datetime.now(tz=UTC)
    if updated_by is not None:
        design.updated_by = updated_by
    session.flush()
    return design


def delete_design(
    session: Session,
    *,
    org_id: uuid.UUID,
    design_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Soft-delete. Idempotent on already-deleted rows."""
    design = session.execute(
        select(Design).where(Design.design_id == design_id, Design.org_id == org_id)
    ).scalar_one_or_none()
    if design is None:
        raise AppValidationError(f"Design {design_id} not found")
    if design.deleted_at is not None:
        return
    design.deleted_at = datetime.now(tz=UTC)
    if deleted_by is not None:
        design.updated_by = deleted_by
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# Operation Master CRUD
# ──────────────────────────────────────────────────────────────────────


def create_operation_master(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    code: str,
    name: str,
    operation_type: OperationType | None = None,
    default_duration_mins: Decimal | None = None,
    cost_centre_id: uuid.UUID | None = None,
    is_active: bool = True,
    created_by: uuid.UUID | None = None,
) -> OperationMaster:
    """``code`` unique per ``(firm_id, code)`` — DB constraint
    ``operation_master_firm_id_code_key``."""
    assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    if not code:
        raise AppValidationError("Operation code is required")
    if not name:
        raise AppValidationError("Operation name is required")
    if default_duration_mins is not None and default_duration_mins < 0:
        raise AppValidationError("default_duration_mins cannot be negative")

    existing = session.execute(
        select(OperationMaster).where(
            OperationMaster.org_id == org_id,
            OperationMaster.firm_id == firm_id,
            OperationMaster.code == code,
            OperationMaster.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"Operation with code {code!r} already exists in this firm scope")

    if cost_centre_id is not None:
        _assert_cost_centre_in_scope(
            session, org_id=org_id, firm_id=firm_id, cost_centre_id=cost_centre_id
        )

    op = OperationMaster(
        org_id=org_id,
        firm_id=firm_id,
        code=code,
        name=name,
        operation_type=operation_type,
        default_duration_mins=default_duration_mins,
        cost_centre_id=cost_centre_id,
        is_active=is_active,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(op)
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="manufacturing.operation_master",
        entity_id=op.operation_master_id,
        action="create",
        changes={"after": {"code": code, "name": name}},
    )
    return op


def get_operation_master(
    session: Session, *, org_id: uuid.UUID, operation_master_id: uuid.UUID
) -> OperationMaster:
    op = session.execute(
        select(OperationMaster).where(
            OperationMaster.operation_master_id == operation_master_id,
            OperationMaster.org_id == org_id,
            OperationMaster.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if op is None:
        raise AppValidationError(f"Operation {operation_master_id} not found")
    return op


def list_operation_masters(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    operation_type: OperationType | None = None,
    is_active: bool | None = True,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[OperationMaster]:
    stmt = select(OperationMaster).where(
        OperationMaster.org_id == org_id, OperationMaster.deleted_at.is_(None)
    )
    if firm_id is not None:
        stmt = stmt.where(OperationMaster.firm_id == firm_id)
    if is_active is True:
        stmt = stmt.where(OperationMaster.is_active.is_(True))
    elif is_active is False:
        stmt = stmt.where(OperationMaster.is_active.is_(False))
    if operation_type is not None:
        stmt = stmt.where(OperationMaster.operation_type == operation_type)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(OperationMaster.code.ilike(like), OperationMaster.name.ilike(like)))
    stmt = stmt.order_by(OperationMaster.code).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def patch_operation_master(
    session: Session,
    *,
    org_id: uuid.UUID,
    operation_master_id: uuid.UUID,
    name: str | None = None,
    operation_type: OperationType | None = None,
    default_duration_mins: Decimal | None = None,
    cost_centre_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    updated_by: uuid.UUID | None = None,
) -> OperationMaster:
    op = get_operation_master(session, org_id=org_id, operation_master_id=operation_master_id)
    if name is not None:
        if not name:
            raise AppValidationError("name cannot be empty")
        op.name = name
    if operation_type is not None:
        op.operation_type = operation_type
    if default_duration_mins is not None:
        if default_duration_mins < 0:
            raise AppValidationError("default_duration_mins cannot be negative")
        op.default_duration_mins = default_duration_mins
    if cost_centre_id is not None:
        _assert_cost_centre_in_scope(
            session,
            org_id=org_id,
            firm_id=op.firm_id,
            cost_centre_id=cost_centre_id,
        )
        op.cost_centre_id = cost_centre_id
    if is_active is not None:
        op.is_active = is_active

    op.updated_at = datetime.now(tz=UTC)
    if updated_by is not None:
        op.updated_by = updated_by
    session.flush()
    return op


def delete_operation_master(
    session: Session,
    *,
    org_id: uuid.UUID,
    operation_master_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    op = session.execute(
        select(OperationMaster).where(
            OperationMaster.operation_master_id == operation_master_id,
            OperationMaster.org_id == org_id,
        )
    ).scalar_one_or_none()
    if op is None:
        raise AppValidationError(f"Operation {operation_master_id} not found")
    if op.deleted_at is not None:
        return
    op.deleted_at = datetime.now(tz=UTC)
    op.is_active = False
    if deleted_by is not None:
        op.updated_by = deleted_by
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# Cost Centre CRUD
# ──────────────────────────────────────────────────────────────────────


def create_cost_centre(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    code: str,
    name: str,
    cost_centre_type: CostCentreType | None = None,
    parent_cost_centre_id: uuid.UUID | None = None,
    is_active: bool = True,
    created_by: uuid.UUID | None = None,
) -> CostCentre:
    """``code`` unique per ``(firm_id, code)`` — DB constraint
    ``cost_centre_firm_id_code_key``."""
    assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    if not code:
        raise AppValidationError("Cost centre code is required")
    if not name:
        raise AppValidationError("Cost centre name is required")

    existing = session.execute(
        select(CostCentre).where(
            CostCentre.org_id == org_id,
            CostCentre.firm_id == firm_id,
            CostCentre.code == code,
            CostCentre.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(
            f"Cost centre with code {code!r} already exists in this firm scope"
        )

    # If a parent was supplied, verify it belongs to the same org AND firm
    # (defense in depth — RLS already enforces org, but cost centres are
    # firm-scoped so a sibling firm's CC must not become a parent of this
    # row). A typo from the UI deserves a clean 422 rather than a downstream
    # FK error or an orphan tree across firm boundaries.
    if parent_cost_centre_id is not None:
        parent = session.execute(
            select(CostCentre).where(
                CostCentre.cost_centre_id == parent_cost_centre_id,
                CostCentre.org_id == org_id,
                CostCentre.firm_id == firm_id,
                CostCentre.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if parent is None:
            raise AppValidationError(
                f"parent_cost_centre_id {parent_cost_centre_id} "
                "not found or belongs to a different org/firm."
            )

    cc = CostCentre(
        org_id=org_id,
        firm_id=firm_id,
        code=code,
        name=name,
        cost_centre_type=cost_centre_type,
        parent_cost_centre_id=parent_cost_centre_id,
        is_active=is_active,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(cc)
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="manufacturing.cost_centre",
        entity_id=cc.cost_centre_id,
        action="create",
        changes={"after": {"code": code, "name": name}},
    )
    return cc


def get_cost_centre(
    session: Session, *, org_id: uuid.UUID, cost_centre_id: uuid.UUID
) -> CostCentre:
    cc = session.execute(
        select(CostCentre).where(
            CostCentre.cost_centre_id == cost_centre_id,
            CostCentre.org_id == org_id,
            CostCentre.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if cc is None:
        raise AppValidationError(f"Cost centre {cost_centre_id} not found")
    return cc


def list_cost_centres(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    cost_centre_type: CostCentreType | None = None,
    is_active: bool | None = True,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CostCentre]:
    stmt = select(CostCentre).where(CostCentre.org_id == org_id, CostCentre.deleted_at.is_(None))
    if firm_id is not None:
        stmt = stmt.where(CostCentre.firm_id == firm_id)
    if is_active is True:
        stmt = stmt.where(CostCentre.is_active.is_(True))
    elif is_active is False:
        stmt = stmt.where(CostCentre.is_active.is_(False))
    if cost_centre_type is not None:
        stmt = stmt.where(CostCentre.cost_centre_type == cost_centre_type)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(CostCentre.code.ilike(like), CostCentre.name.ilike(like)))
    stmt = stmt.order_by(CostCentre.code).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def patch_cost_centre(
    session: Session,
    *,
    org_id: uuid.UUID,
    cost_centre_id: uuid.UUID,
    name: str | None = None,
    cost_centre_type: CostCentreType | None = None,
    parent_cost_centre_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    updated_by: uuid.UUID | None = None,
) -> CostCentre:
    cc = get_cost_centre(session, org_id=org_id, cost_centre_id=cost_centre_id)
    if name is not None:
        if not name:
            raise AppValidationError("name cannot be empty")
        cc.name = name
    if cost_centre_type is not None:
        cc.cost_centre_type = cost_centre_type
    if parent_cost_centre_id is not None:
        if parent_cost_centre_id == cost_centre_id:
            raise AppValidationError("cost centre cannot be its own parent")
        # Pin parent to the SAME firm as the child (A02 hardening) — cost
        # centres are firm-scoped, so a sibling firm's CC must not become
        # the parent of this row.
        parent = session.execute(
            select(CostCentre).where(
                CostCentre.cost_centre_id == parent_cost_centre_id,
                CostCentre.org_id == org_id,
                CostCentre.firm_id == cc.firm_id,
                CostCentre.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if parent is None:
            raise AppValidationError(
                f"parent_cost_centre_id {parent_cost_centre_id} "
                "not found or belongs to a different org/firm."
            )
        cc.parent_cost_centre_id = parent_cost_centre_id
    if is_active is not None:
        cc.is_active = is_active

    cc.updated_at = datetime.now(tz=UTC)
    if updated_by is not None:
        cc.updated_by = updated_by
    session.flush()
    return cc


def delete_cost_centre(
    session: Session,
    *,
    org_id: uuid.UUID,
    cost_centre_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    cc = session.execute(
        select(CostCentre).where(
            CostCentre.cost_centre_id == cost_centre_id, CostCentre.org_id == org_id
        )
    ).scalar_one_or_none()
    if cc is None:
        raise AppValidationError(f"Cost centre {cost_centre_id} not found")
    if cc.deleted_at is not None:
        return
    cc.deleted_at = datetime.now(tz=UTC)
    cc.is_active = False
    if deleted_by is not None:
        cc.updated_by = deleted_by
    session.flush()


__all__ = [
    "create_cost_centre",
    "create_design",
    "create_operation_master",
    "delete_cost_centre",
    "delete_design",
    "delete_operation_master",
    "get_cost_centre",
    "get_design",
    "get_operation_master",
    "list_cost_centres",
    "list_designs",
    "list_operation_masters",
    "patch_cost_centre",
    "patch_design",
    "patch_operation_master",
]
