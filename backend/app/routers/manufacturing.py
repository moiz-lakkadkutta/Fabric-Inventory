"""Manufacturing routers — Design / OperationMaster / CostCentre CRUD
(TASK-TR-A02) + BOM lifecycle (TASK-TR-A03).

Sibling routers exported from this module so OpenAPI groups each
resource cleanly:

  - ``designs_router``           — ``/designs``
  - ``operation_masters_router`` — ``/operation-masters``
  - ``cost_centres_router``      — ``/cost-centres``
  - ``boms_router``              — ``/boms``

Permission gates per the rbac_service catalog:
``manufacturing.<entity>.{create,update,read,delete}``.

Soft-delete uses the same permission as update — deletes are a form of
update; hard-deletes are out of scope by policy (same pattern as
``masters.party`` / ``masters.item``).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.models.manufacturing import Bom, BomLine, Design, OperationMaster, OperationType
from app.models.masters import CostCentre, CostCentreType
from app.schemas.manufacturing import (
    BomCreateRequest,
    BomLineResponse,
    BomListResponse,
    BomResponse,
    CostCentreCreateRequest,
    CostCentreListResponse,
    CostCentreResponse,
    CostCentreUpdateRequest,
    DesignCreateRequest,
    DesignListResponse,
    DesignResponse,
    DesignUpdateRequest,
    OperationMasterCreateRequest,
    OperationMasterListResponse,
    OperationMasterResponse,
    OperationMasterUpdateRequest,
)
from app.service import bom_service, manufacturing_masters_service
from app.service.identity_service import TokenPayload

designs_router = APIRouter(prefix="/designs", tags=["manufacturing", "design"])
operation_masters_router = APIRouter(
    prefix="/operation-masters", tags=["manufacturing", "operation_master"]
)
cost_centres_router = APIRouter(prefix="/cost-centres", tags=["manufacturing", "cost_centre"])
boms_router = APIRouter(prefix="/boms", tags=["manufacturing", "bom"])


# ──────────────────────────────────────────────────────────────────────
# Response builders
# ──────────────────────────────────────────────────────────────────────


def _design_to_response(design: Design) -> DesignResponse:
    return DesignResponse(
        design_id=design.design_id,
        org_id=design.org_id,
        firm_id=design.firm_id,
        code=design.code,
        name=design.name,
        description=design.description,
        cost_centre_id=design.cost_centre_id,
        created_at=design.created_at,
        updated_at=design.updated_at,
        deleted_at=design.deleted_at,
    )


def _op_to_response(op: OperationMaster) -> OperationMasterResponse:
    return OperationMasterResponse(
        operation_master_id=op.operation_master_id,
        org_id=op.org_id,
        firm_id=op.firm_id,
        code=op.code,
        name=op.name,
        operation_type=op.operation_type,
        default_duration_mins=op.default_duration_mins,
        cost_centre_id=op.cost_centre_id,
        is_active=op.is_active,
        created_at=op.created_at,
        updated_at=op.updated_at,
        deleted_at=op.deleted_at,
    )


def _cc_to_response(cc: CostCentre) -> CostCentreResponse:
    return CostCentreResponse(
        cost_centre_id=cc.cost_centre_id,
        org_id=cc.org_id,
        firm_id=cc.firm_id,
        code=cc.code,
        name=cc.name,
        cost_centre_type=cc.cost_centre_type,
        parent_cost_centre_id=cc.parent_cost_centre_id,
        is_active=cc.is_active,
        created_at=cc.created_at,
        updated_at=cc.updated_at,
        deleted_at=cc.deleted_at,
    )


def _bom_line_to_response(line: BomLine) -> BomLineResponse:
    return BomLineResponse(
        bom_line_id=line.bom_line_id,
        bom_id=line.bom_id,
        item_id=line.item_id,
        qty_required=line.qty_required,
        uom=line.uom,
        is_optional=line.is_optional,
        part_role=line.part_role,
        sequence=line.sequence,
    )


def _bom_to_response(bom: Bom) -> BomResponse:
    return BomResponse(
        bom_id=bom.bom_id,
        org_id=bom.org_id,
        firm_id=bom.firm_id,
        design_id=bom.design_id,
        finished_item_id=bom.finished_item_id,
        version_number=bom.version_number,
        is_active=bom.is_active,
        created_at=bom.created_at,
        updated_at=bom.updated_at,
        deleted_at=bom.deleted_at,
        lines=[_bom_line_to_response(line) for line in bom.lines],
    )


# ──────────────────────────────────────────────────────────────────────
# Design endpoints
# ──────────────────────────────────────────────────────────────────────


@designs_router.post(
    "",
    response_model=DesignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a design",
)
def create_design(
    body: DesignCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.design.create"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DesignResponse:
    design = manufacturing_masters_service.create_design(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        code=body.code,
        name=body.name,
        description=body.description,
        cost_centre_id=body.cost_centre_id,
        created_by=current_user.user_id,
    )
    return _design_to_response(design)


@designs_router.get(
    "",
    response_model=DesignListResponse,
    summary="List designs (RLS-scoped to current org)",
)
def list_designs(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.design.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DesignListResponse:
    items = manufacturing_masters_service.list_designs(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    return DesignListResponse(
        items=[_design_to_response(d) for d in items],
        limit=limit,
        offset=offset,
        count=len(items),
    )


@designs_router.get(
    "/{design_id}",
    response_model=DesignResponse,
    summary="Get a design by id",
)
def get_design(
    design_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.design.read"))],
) -> DesignResponse:
    design = manufacturing_masters_service.get_design(
        db, org_id=current_user.org_id, design_id=design_id
    )
    return _design_to_response(design)


@designs_router.patch(
    "/{design_id}",
    response_model=DesignResponse,
    summary="Update a design (PATCH — partial)",
)
def patch_design(
    design_id: uuid.UUID,
    body: DesignUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.design.update"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DesignResponse:
    design = manufacturing_masters_service.patch_design(
        db,
        org_id=current_user.org_id,
        design_id=design_id,
        name=body.name,
        description=body.description,
        cost_centre_id=body.cost_centre_id,
        updated_by=current_user.user_id,
    )
    return _design_to_response(design)


@designs_router.delete(
    "/{design_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a design",
)
def delete_design(
    design_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.design.delete"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    manufacturing_masters_service.delete_design(
        db,
        org_id=current_user.org_id,
        design_id=design_id,
        deleted_by=current_user.user_id,
    )


# ──────────────────────────────────────────────────────────────────────
# Operation Master endpoints
# ──────────────────────────────────────────────────────────────────────


@operation_masters_router.post(
    "",
    response_model=OperationMasterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an operation master",
)
def create_operation_master(
    body: OperationMasterCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload,
        Depends(require_permission("manufacturing.operation_master.create")),
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OperationMasterResponse:
    op = manufacturing_masters_service.create_operation_master(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        code=body.code,
        name=body.name,
        operation_type=body.operation_type,
        default_duration_mins=body.default_duration_mins,
        cost_centre_id=body.cost_centre_id,
        is_active=body.is_active,
        created_by=current_user.user_id,
    )
    return _op_to_response(op)


@operation_masters_router.get(
    "",
    response_model=OperationMasterListResponse,
    summary="List operation masters (RLS-scoped to current org)",
)
def list_operation_masters(
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation_master.read"))
    ],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    operation_type: Annotated[OperationType | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = True,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OperationMasterListResponse:
    items = manufacturing_masters_service.list_operation_masters(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        operation_type=operation_type,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return OperationMasterListResponse(
        items=[_op_to_response(o) for o in items],
        limit=limit,
        offset=offset,
        count=len(items),
    )


@operation_masters_router.get(
    "/{operation_master_id}",
    response_model=OperationMasterResponse,
    summary="Get an operation master by id",
)
def get_operation_master(
    operation_master_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation_master.read"))
    ],
) -> OperationMasterResponse:
    op = manufacturing_masters_service.get_operation_master(
        db, org_id=current_user.org_id, operation_master_id=operation_master_id
    )
    return _op_to_response(op)


@operation_masters_router.patch(
    "/{operation_master_id}",
    response_model=OperationMasterResponse,
    summary="Update an operation master (PATCH — partial)",
)
def patch_operation_master(
    operation_master_id: uuid.UUID,
    body: OperationMasterUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload,
        Depends(require_permission("manufacturing.operation_master.update")),
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OperationMasterResponse:
    op = manufacturing_masters_service.patch_operation_master(
        db,
        org_id=current_user.org_id,
        operation_master_id=operation_master_id,
        name=body.name,
        operation_type=body.operation_type,
        default_duration_mins=body.default_duration_mins,
        cost_centre_id=body.cost_centre_id,
        is_active=body.is_active,
        updated_by=current_user.user_id,
    )
    return _op_to_response(op)


@operation_masters_router.delete(
    "/{operation_master_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an operation master",
)
def delete_operation_master(
    operation_master_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload,
        Depends(require_permission("manufacturing.operation_master.delete")),
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    manufacturing_masters_service.delete_operation_master(
        db,
        org_id=current_user.org_id,
        operation_master_id=operation_master_id,
        deleted_by=current_user.user_id,
    )


# ──────────────────────────────────────────────────────────────────────
# Cost Centre endpoints
# ──────────────────────────────────────────────────────────────────────


@cost_centres_router.post(
    "",
    response_model=CostCentreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a cost centre",
)
def create_cost_centre(
    body: CostCentreCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.cost_centre.create"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CostCentreResponse:
    cc = manufacturing_masters_service.create_cost_centre(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        code=body.code,
        name=body.name,
        cost_centre_type=body.cost_centre_type,
        parent_cost_centre_id=body.parent_cost_centre_id,
        is_active=body.is_active,
        created_by=current_user.user_id,
    )
    return _cc_to_response(cc)


@cost_centres_router.get(
    "",
    response_model=CostCentreListResponse,
    summary="List cost centres (RLS-scoped to current org)",
)
def list_cost_centres(
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.cost_centre.read"))
    ],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    cost_centre_type: Annotated[CostCentreType | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = True,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CostCentreListResponse:
    items = manufacturing_masters_service.list_cost_centres(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        cost_centre_type=cost_centre_type,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return CostCentreListResponse(
        items=[_cc_to_response(c) for c in items],
        limit=limit,
        offset=offset,
        count=len(items),
    )


@cost_centres_router.get(
    "/{cost_centre_id}",
    response_model=CostCentreResponse,
    summary="Get a cost centre by id",
)
def get_cost_centre(
    cost_centre_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.cost_centre.read"))
    ],
) -> CostCentreResponse:
    cc = manufacturing_masters_service.get_cost_centre(
        db, org_id=current_user.org_id, cost_centre_id=cost_centre_id
    )
    return _cc_to_response(cc)


@cost_centres_router.patch(
    "/{cost_centre_id}",
    response_model=CostCentreResponse,
    summary="Update a cost centre (PATCH — partial)",
)
def patch_cost_centre(
    cost_centre_id: uuid.UUID,
    body: CostCentreUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.cost_centre.update"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CostCentreResponse:
    cc = manufacturing_masters_service.patch_cost_centre(
        db,
        org_id=current_user.org_id,
        cost_centre_id=cost_centre_id,
        name=body.name,
        cost_centre_type=body.cost_centre_type,
        parent_cost_centre_id=body.parent_cost_centre_id,
        is_active=body.is_active,
        updated_by=current_user.user_id,
    )
    return _cc_to_response(cc)


@cost_centres_router.delete(
    "/{cost_centre_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a cost centre",
)
def delete_cost_centre(
    cost_centre_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.cost_centre.delete"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    manufacturing_masters_service.delete_cost_centre(
        db,
        org_id=current_user.org_id,
        cost_centre_id=cost_centre_id,
        deleted_by=current_user.user_id,
    )


# ──────────────────────────────────────────────────────────────────────
# BOM endpoints (TASK-TR-A03)
# ──────────────────────────────────────────────────────────────────────


@boms_router.post(
    "",
    response_model=BomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a BOM (auto-bumps version per finished item)",
)
def create_bom(
    body: BomCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.bom.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BomResponse:
    service_lines = [
        bom_service.BomLineInput(
            item_id=line.item_id,
            qty_required=line.qty_required,
            uom=line.uom,
            is_optional=line.is_optional,
            part_role=line.part_role,
            sequence=line.sequence,
        )
        for line in body.lines
    ]
    bom = bom_service.create_bom(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        design_id=body.design_id,
        finished_item_id=body.finished_item_id,
        lines=service_lines,
        created_by=current_user.user_id,
    )
    return _bom_to_response(bom)


@boms_router.get(
    "",
    response_model=BomListResponse,
    summary="List BOMs (RLS-scoped to current org)",
)
def list_boms(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.bom.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    design_id: Annotated[uuid.UUID | None, Query()] = None,
    finished_item_id: Annotated[uuid.UUID | None, Query()] = None,
    active_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BomListResponse:
    items, _total = bom_service.list_boms(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        design_id=design_id,
        finished_item_id=finished_item_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return BomListResponse(
        items=[_bom_to_response(b) for b in items],
        limit=limit,
        offset=offset,
        count=len(items),
    )


@boms_router.get(
    "/{bom_id}",
    response_model=BomResponse,
    summary="Get a BOM by id (with lines)",
)
def get_bom(
    bom_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.bom.read"))],
) -> BomResponse:
    bom = bom_service.get_bom(db, org_id=current_user.org_id, bom_id=bom_id)
    return _bom_to_response(bom)


@boms_router.post(
    "/{bom_id}/activate",
    response_model=BomResponse,
    summary="Activate a BOM (demotes other versions in the same partition)",
)
def activate_bom(
    bom_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.bom.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BomResponse:
    bom = bom_service.activate_bom(
        db,
        org_id=current_user.org_id,
        bom_id=bom_id,
        actor_user_id=current_user.user_id,
    )
    return _bom_to_response(bom)


@boms_router.delete(
    "/{bom_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a BOM (promotes next version if the deleted one was active)",
)
def delete_bom(
    bom_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.bom.delete"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    bom_service.delete_bom(
        db,
        org_id=current_user.org_id,
        bom_id=bom_id,
        actor_user_id=current_user.user_id,
    )
