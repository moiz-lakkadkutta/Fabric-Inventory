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
from app.exceptions import AppValidationError
from app.models.manufacturing import (
    Bom,
    BomLine,
    Design,
    ManufacturingOrder,
    MoMaterialLine,
    MoOperation,
    MoOperationState,
    MoStatus,
    OperationMaster,
    OperationType,
    Routing,
    RoutingEdge,
    RoutingEdgeType,
)
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
    MoCreateRequest,
    MoListItem,
    MoListResponse,
    MoMaterialLineResponse,
    MoOperationResponse,
    MoResponse,
    OperationMasterCreateRequest,
    OperationMasterListResponse,
    OperationMasterResponse,
    OperationMasterUpdateRequest,
    RoutingCreateRequest,
    RoutingEdgeResponse,
    RoutingEdgesUpdateRequest,
    RoutingListResponse,
    RoutingResponse,
)
from app.service import (
    bom_service,
    manufacturing_masters_service,
    mo_service,
    routing_service,
)
from app.service.identity_service import TokenPayload

designs_router = APIRouter(prefix="/designs", tags=["manufacturing", "design"])
operation_masters_router = APIRouter(
    prefix="/operation-masters", tags=["manufacturing", "operation_master"]
)
cost_centres_router = APIRouter(prefix="/cost-centres", tags=["manufacturing", "cost_centre"])
boms_router = APIRouter(prefix="/boms", tags=["manufacturing", "bom"])
routings_router = APIRouter(prefix="/routings", tags=["manufacturing", "routing"])
mos_router = APIRouter(prefix="/manufacturing/mo", tags=["manufacturing", "mo"])


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
    # The model column `is_optional` is `bool | None` (DB default FALSE),
    # but the service always sets it on create. Coerce defensively so
    # the response shape can advertise a non-nullable `bool`.
    return BomLineResponse(
        bom_line_id=line.bom_line_id,
        bom_id=line.bom_id,
        item_id=line.item_id,
        qty_required=line.qty_required,
        uom=line.uom,
        is_optional=bool(line.is_optional),
        part_role=line.part_role,
        sequence=line.sequence,
    )


def _bom_to_response(bom: Bom) -> BomResponse:
    # `version_number` and `is_active` are nullable on the ORM model
    # (server defaults 1 / TRUE), but the service always sets them on
    # create. Coerce defensively so the response can advertise non-null.
    return BomResponse(
        bom_id=bom.bom_id,
        org_id=bom.org_id,
        firm_id=bom.firm_id,
        design_id=bom.design_id,
        finished_item_id=bom.finished_item_id,
        version_number=bom.version_number if bom.version_number is not None else 1,
        is_active=bool(bom.is_active),
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
    items, total = bom_service.list_boms(
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
        total_count=total,
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


# ──────────────────────────────────────────────────────────────────────
# Routing endpoints (TASK-TR-A04)
# ──────────────────────────────────────────────────────────────────────


def _routing_edge_to_response(edge: RoutingEdge) -> RoutingEdgeResponse:
    # ``edge_type`` is nullable on the ORM (server default
    # ``'FINISH_TO_START'::routing_edge_type``) but the service always
    # sets it on create. Coerce defensively so the wire shape can
    # advertise a non-nullable enum.
    return RoutingEdgeResponse(
        routing_edge_id=edge.routing_edge_id,
        routing_id=edge.routing_id,
        from_operation_id=edge.from_operation_id,
        to_operation_id=edge.to_operation_id,
        edge_type=edge.edge_type if edge.edge_type is not None else RoutingEdgeType.FINISH_TO_START,
        threshold_qty=edge.threshold_qty,
        threshold_pct=edge.threshold_pct,
        sequence=edge.sequence,
    )


def _routing_to_response(routing: Routing) -> RoutingResponse:
    return RoutingResponse(
        routing_id=routing.routing_id,
        org_id=routing.org_id,
        firm_id=routing.firm_id,
        design_id=routing.design_id,
        code=routing.code,
        version_number=routing.version_number if routing.version_number is not None else 1,
        is_active=bool(routing.is_active),
        created_at=routing.created_at,
        updated_at=routing.updated_at,
        deleted_at=routing.deleted_at,
        edges=[_routing_edge_to_response(e) for e in routing.edges],
    )


@routings_router.post(
    "",
    response_model=RoutingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a routing (operation DAG for a design)",
)
def create_routing(
    body: RoutingCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.routing.write"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RoutingResponse:
    # Defense-in-depth: when the session has an explicit firm scope, the
    # body firm_id must match (a stale FE token shouldn't be able to
    # cross-write). When the session is org-level (signup-issued tokens
    # carry ``firm_id=None``), defer to the design-composition + RLS
    # checks in the service — same pattern as the BOM router.
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")

    service_edges = [
        routing_service.RoutingEdgeInput(
            from_operation_id=e.from_operation_id,
            to_operation_id=e.to_operation_id,
            edge_type=e.edge_type,
            threshold_qty=e.threshold_qty,
            threshold_pct=e.threshold_pct,
            sequence=e.sequence,
        )
        for e in body.edges
    ]
    routing = routing_service.create_routing(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        design_id=body.design_id,
        code=body.code,
        edges=service_edges,
        created_by=current_user.user_id,
    )
    return _routing_to_response(routing)


@routings_router.get(
    "",
    response_model=RoutingListResponse,
    summary="List routings (RLS-scoped to current org)",
)
def list_routings(
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.routing.read"))
    ],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    design_id: Annotated[uuid.UUID | None, Query()] = None,
    active_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RoutingListResponse:
    items, total = routing_service.list_routings(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        design_id=design_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return RoutingListResponse(
        items=[_routing_to_response(r) for r in items],
        limit=limit,
        offset=offset,
        count=len(items),
        total_count=total,
    )


@routings_router.get(
    "/{routing_id}",
    response_model=RoutingResponse,
    summary="Get a routing by id (with edges)",
)
def get_routing(
    routing_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.routing.read"))
    ],
) -> RoutingResponse:
    routing = routing_service.get_routing(db, org_id=current_user.org_id, routing_id=routing_id)
    return _routing_to_response(routing)


@routings_router.patch(
    "/{routing_id}/edges",
    response_model=RoutingResponse,
    summary="Replace a routing's edge set atomically (re-validates the DAG)",
)
def update_routing_edges(
    routing_id: uuid.UUID,
    body: RoutingEdgesUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.routing.write"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RoutingResponse:
    service_edges = [
        routing_service.RoutingEdgeInput(
            from_operation_id=e.from_operation_id,
            to_operation_id=e.to_operation_id,
            edge_type=e.edge_type,
            threshold_qty=e.threshold_qty,
            threshold_pct=e.threshold_pct,
            sequence=e.sequence,
        )
        for e in body.edges
    ]
    routing = routing_service.update_routing_edges(
        db,
        org_id=current_user.org_id,
        routing_id=routing_id,
        edges=service_edges,
        updated_by=current_user.user_id,
    )
    return _routing_to_response(routing)


@routings_router.delete(
    "/{routing_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a routing (refused if referenced by an active MO)",
)
def delete_routing(
    routing_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.routing.write"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    routing_service.delete_routing(
        db,
        org_id=current_user.org_id,
        routing_id=routing_id,
        deleted_by=current_user.user_id,
    )


# ──────────────────────────────────────────────────────────────────────
# Manufacturing Order endpoints (TASK-TR-A05)
# ──────────────────────────────────────────────────────────────────────


def _mo_material_line_to_response(line: MoMaterialLine) -> MoMaterialLineResponse:
    # ``qty_issued`` / ``qty_scrap`` are nullable on the ORM (server
    # defaults 0) but ``mo_service.create_mo`` always sets them. Coerce
    # defensively so the wire shape can advertise non-null Decimals.
    from decimal import Decimal as _Decimal

    return MoMaterialLineResponse(
        mo_material_line_id=line.mo_material_line_id,
        manufacturing_order_id=line.manufacturing_order_id,
        item_id=line.item_id,
        qty_required=line.qty_required if line.qty_required is not None else _Decimal("0"),
        qty_issued=line.qty_issued if line.qty_issued is not None else _Decimal("0"),
        qty_scrap=line.qty_scrap if line.qty_scrap is not None else _Decimal("0"),
    )


def _mo_operation_to_response(op: MoOperation) -> MoOperationResponse:
    return MoOperationResponse(
        mo_operation_id=op.mo_operation_id,
        manufacturing_order_id=op.manufacturing_order_id,
        operation_master_id=op.operation_master_id,
        operation_sequence=op.operation_sequence,
        state=op.state if op.state is not None else MoOperationState.PENDING,
        executor=op.executor,
        qty_in=op.qty_in,
        qty_out=op.qty_out,
    )


def _mo_to_response(mo: ManufacturingOrder) -> MoResponse:
    return MoResponse(
        manufacturing_order_id=mo.manufacturing_order_id,
        org_id=mo.org_id,
        firm_id=mo.firm_id,
        series=mo.series,
        number=mo.number,
        design_id=mo.design_id,
        finished_item_id=mo.finished_item_id,
        bom_id=mo.bom_id,
        routing_id=mo.routing_id,
        status=mo.status if mo.status is not None else MoStatus.DRAFT,
        mo_date=mo.mo_date,
        planned_qty=mo.planned_qty,
        produced_qty=mo.produced_qty,
        scrap_qty=mo.scrap_qty,
        closed_at=mo.closed_at,
        created_at=mo.created_at,
        updated_at=mo.updated_at,
        deleted_at=mo.deleted_at,
        material_lines=[_mo_material_line_to_response(line) for line in mo.material_lines],
        operations=sorted(
            (_mo_operation_to_response(op) for op in mo.operations),
            key=lambda r: r.operation_sequence if r.operation_sequence is not None else 0,
        ),
    )


def _mo_to_list_item(mo: ManufacturingOrder) -> MoListItem:
    return MoListItem(
        manufacturing_order_id=mo.manufacturing_order_id,
        org_id=mo.org_id,
        firm_id=mo.firm_id,
        series=mo.series,
        number=mo.number,
        design_id=mo.design_id,
        finished_item_id=mo.finished_item_id,
        status=mo.status if mo.status is not None else MoStatus.DRAFT,
        mo_date=mo.mo_date,
        planned_qty=mo.planned_qty,
        created_at=mo.created_at,
    )


@mos_router.post(
    "",
    response_model=MoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a manufacturing order (materializes lines from BOM + ops from routing)",
)
def create_mo(
    body: MoCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.write"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    # Defense-in-depth: when the session has an explicit firm scope, the
    # body firm_id must match — same pattern as the routing router.
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")

    series = body.series or "MO"
    mo = mo_service.create_mo(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        design_id=body.design_id,
        finished_item_id=body.finished_item_id,
        qty_to_produce=body.qty_to_produce,
        bom_id=body.bom_id,
        routing_id=body.routing_id,
        planned_start_date=body.planned_start_date,
        planned_end_date=body.planned_end_date,
        narration=body.narration,
        series=series,
        created_by=current_user.user_id,
    )
    # Re-fetch with eager-loaded children for the response builder.
    fresh = mo_service.get_mo(db, org_id=current_user.org_id, mo_id=mo.manufacturing_order_id)
    return _mo_to_response(fresh)


@mos_router.get(
    "",
    response_model=MoListResponse,
    summary="List manufacturing orders (RLS-scoped to current org)",
)
def list_mos(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[MoStatus | None, Query(alias="status")] = None,
    design_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MoListResponse:
    items, total = mo_service.list_mos(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        status=status_filter,
        design_id=design_id,
        limit=limit,
        offset=offset,
    )
    return MoListResponse(
        items=[_mo_to_list_item(m) for m in items],
        limit=limit,
        offset=offset,
        count=len(items),
        total_count=total,
    )


@mos_router.get(
    "/{mo_id}",
    response_model=MoResponse,
    summary="Get a manufacturing order by id (with material lines + operations)",
)
def get_mo(
    mo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.read"))],
) -> MoResponse:
    mo = mo_service.get_mo(db, org_id=current_user.org_id, mo_id=mo_id)
    return _mo_to_response(mo)


@mos_router.post(
    "/{mo_id}/release",
    response_model=MoResponse,
    summary="Release a DRAFT manufacturing order",
)
def release_mo(
    mo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.write"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    mo_service.release_mo(
        db, org_id=current_user.org_id, mo_id=mo_id, released_by=current_user.user_id
    )
    fresh = mo_service.get_mo(db, org_id=current_user.org_id, mo_id=mo_id)
    return _mo_to_response(fresh)


@mos_router.post(
    "/{mo_id}/start",
    response_model=MoResponse,
    summary="Start (RELEASED → IN_PROGRESS) a manufacturing order",
)
def start_mo(
    mo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.write"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    mo_service.start_mo(
        db, org_id=current_user.org_id, mo_id=mo_id, started_by=current_user.user_id
    )
    fresh = mo_service.get_mo(db, org_id=current_user.org_id, mo_id=mo_id)
    return _mo_to_response(fresh)


@mos_router.post(
    "/{mo_id}/complete",
    response_model=MoResponse,
    summary="Complete (IN_PROGRESS → COMPLETED) a manufacturing order",
)
def complete_mo(
    mo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.write"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    mo_service.complete_mo(
        db, org_id=current_user.org_id, mo_id=mo_id, completed_by=current_user.user_id
    )
    fresh = mo_service.get_mo(db, org_id=current_user.org_id, mo_id=mo_id)
    return _mo_to_response(fresh)


@mos_router.post(
    "/{mo_id}/close",
    response_model=MoResponse,
    summary="Close (COMPLETED → CLOSED) a manufacturing order — MO becomes immutable",
)
def close_mo(
    mo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.write"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    mo_service.close_mo(db, org_id=current_user.org_id, mo_id=mo_id, closed_by=current_user.user_id)
    fresh = mo_service.get_mo(db, org_id=current_user.org_id, mo_id=mo_id)
    return _mo_to_response(fresh)


# NOTE: ``POST /manufacturing/mo/{mo_id}/cancel`` is intentionally NOT
# wired in A05. The ``mo_status`` Postgres enum does not include a
# ``CANCELLED`` value (see ``MoStatus`` in ``app.models.manufacturing``),
# so a cancel endpoint would have nowhere to write to. A follow-up
# Alembic migration + service method will land in a separate task; the
# retro at ``docs/retros/task-tr-a05.md`` documents this gap.
