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
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import AppValidationError
from app.models.manufacturing import (
    Bom,
    BomLine,
    Design,
    ManufacturingOrder,
    MaterialIssue,
    MaterialIssueLine,
    MoMaterialLine,
    MoOperation,
    MoOperationState,
    MoStatus,
    OperationMaster,
    OperationType,
    ProductionEvent,
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
    CanStartOperationResponse,
    CostCentreCreateRequest,
    CostCentreListResponse,
    CostCentreResponse,
    CostCentreUpdateRequest,
    DesignCreateRequest,
    DesignListResponse,
    DesignResponse,
    DesignUpdateRequest,
    KarigarAcknowledgeRequest,
    KarigarCloseRequest,
    KarigarDispatchRequest,
    KarigarOperationResponse,
    KarigarReceiveRequest,
    MaterialIssueCreateRequest,
    MaterialIssueLineResponse,
    MaterialIssueListResponse,
    MaterialIssueResponse,
    MoCompleteRequest,
    MoCompletionPreviewLedgerCodes,
    MoCompletionPreviewResponse,
    MoCreateRequest,
    MoListItem,
    MoListResponse,
    MoMaterialLineResponse,
    MoOperationResponse,
    MoResponse,
    MoTransitionRequest,
    OperationCompleteRequest,
    OperationDetailResponse,
    OperationMasterCreateRequest,
    OperationMasterListResponse,
    OperationMasterResponse,
    OperationMasterUpdateRequest,
    OperationProgressListResponse,
    OperationProgressResponse,
    OperationQtyInRequest,
    OperationQtyOutRequest,
    OperationStartRequest,
    ProductionEventResponse,
    QcOperationResponse,
    QcResultRequest,
    QcResultResponse,
    QcStartRequest,
    RoutingCreateRequest,
    RoutingEdgeResponse,
    RoutingEdgesUpdateRequest,
    RoutingListResponse,
    RoutingResponse,
)
from app.service import (
    bom_service,
    karigar_send_out_service,
    manufacturing_masters_service,
    material_issue_service,
    mo_completion_service,
    mo_service,
    operation_progress_service,
    qc_service,
    routing_flow_service,
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
        is_optional=bool(line.is_optional),
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
        planned_start_date=mo.planned_start_date,
        planned_end_date=mo.planned_end_date,
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
    body: MoTransitionRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    mo_service.release_mo(
        db,
        org_id=current_user.org_id,
        mo_id=mo_id,
        released_by=current_user.user_id,
        narration=body.narration if body is not None else None,
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
    body: MoTransitionRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    mo_service.start_mo(
        db,
        org_id=current_user.org_id,
        mo_id=mo_id,
        started_by=current_user.user_id,
        narration=body.narration if body is not None else None,
    )
    fresh = mo_service.get_mo(db, org_id=current_user.org_id, mo_id=mo_id)
    return _mo_to_response(fresh)


@mos_router.get(
    "/{mo_id}/completion-preview",
    response_model=MoCompletionPreviewResponse,
    summary=(
        "Preview the MO completion + WIP settlement that A11 would post "
        "(read-only) — TASK-TR-A11-FU"
    ),
    description=(
        "Read-only: returns the cost pool, per-unit cost, and loss "
        "breakdown that ``POST /manufacturing/mo/{id}/complete`` would "
        "post for the given ``produced_qty_target``, plus a list of "
        "``blocking_reasons`` populated when any pre-flight check fails "
        "(MO not IN_PROGRESS, an op not in {CLOSED, SKIPPED, CANCELLED}, "
        "ALL_OR_NONE policy mismatch, non-zero rework_qty, empty WIP "
        "cost pool, etc.). ``can_complete`` is False whenever "
        "``blocking_reasons`` is non-empty; the response is still 200 — "
        "the FE renders the numbers AND the reason in one round trip. "
        "No state changes, no GL writes, no audit emit."
    ),
)
def completion_preview(
    mo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.read"))],
    firm_id: Annotated[uuid.UUID, Query()],
    produced_qty_target: Annotated[Decimal, Query(gt=Decimal("0"))],
) -> MoCompletionPreviewResponse:
    # Firm-scoping defence-in-depth: when the session is firm-scoped
    # (admin tokens are not), the query param must match. Same posture
    # as ``complete_mo``'s body-side firm check.
    if current_user.firm_id is not None and firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")

    preview = mo_completion_service.preview_completion(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        mo_id=mo_id,
        produced_qty_target=Decimal(produced_qty_target),
    )
    return MoCompletionPreviewResponse(
        mo_id=preview.mo_id,
        status=preview.status,
        planned_qty=preview.planned_qty,
        produced_qty_target=preview.produced_qty_target,
        scrap_qty=preview.scrap_qty,
        wastage_qty=preview.wastage_qty,
        by_product_qty=preview.by_product_qty,
        rework_qty=preview.rework_qty,
        cost_pool=preview.cost_pool,
        unit_cost=preview.unit_cost,
        ledger_codes=MoCompletionPreviewLedgerCodes(
            inventory_dr=preview.inventory_ledger_code,
            wip_cr=preview.wip_ledger_code,
        ),
        can_complete=preview.can_complete,
        blocking_reasons=list(preview.blocking_reasons),
        policy=preview.policy,
    )


@mos_router.post(
    "/{mo_id}/complete",
    response_model=MoResponse,
    summary=(
        "Complete (IN_PROGRESS → COMPLETED) a manufacturing order with WIP settlement — TASK-TR-A11"
    ),
    description=(
        "Money-touching: drains the WIP cost pool into finished-goods "
        "inventory. Posts a balanced GL voucher (DR 1300 Inventory / "
        "CR 1310 Work-in-Process) for the full pool, inserts an inbound "
        "stock-ledger row for the finished item at the firm's MAIN "
        "warehouse with unit_cost = cost_pool / produced_qty, then "
        "flips the MO header to COMPLETED. With completion_policy="
        "ALL_OR_NONE (the default and only v1 policy) the request's "
        "produced_qty must equal planned_qty. All operations must be in "
        "{CLOSED, SKIPPED, CANCELLED} — REWORK QC verdicts block "
        "completion until the rework cycle finishes."
    ),
)
def complete_mo(
    mo_id: uuid.UUID,
    body: MoCompleteRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.mo.write"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    # Defense-in-depth: when the session has an explicit firm scope, the
    # body firm_id must match — same posture as create_mo and
    # issue_materials_for_mo.
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    mo_completion_service.complete_mo_with_settlement(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_id=mo_id,
        produced_qty=body.produced_qty,
        completed_by=current_user.user_id,
        narration=body.narration,
        series=body.series or "MOC",
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
    body: MoTransitionRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MoResponse:
    mo_service.close_mo(
        db,
        org_id=current_user.org_id,
        mo_id=mo_id,
        closed_by=current_user.user_id,
        narration=body.narration if body is not None else None,
    )
    fresh = mo_service.get_mo(db, org_id=current_user.org_id, mo_id=mo_id)
    return _mo_to_response(fresh)


# NOTE: ``POST /manufacturing/mo/{mo_id}/cancel`` is intentionally NOT
# wired in A05. The ``mo_status`` Postgres enum does not include a
# ``CANCELLED`` value (see ``MoStatus`` in ``app.models.manufacturing``),
# so a cancel endpoint would have nowhere to write to. A follow-up
# Alembic migration + service method will land in a separate task; the
# retro at ``docs/retros/task-tr-a05.md`` documents this gap.


# ──────────────────────────────────────────────────────────────────────
# Material issue endpoints (TASK-TR-A06)
# ──────────────────────────────────────────────────────────────────────


material_issues_router = APIRouter(
    prefix="/manufacturing", tags=["manufacturing", "material_issue"]
)


def _mi_line_to_response(line: MaterialIssueLine) -> MaterialIssueLineResponse:
    return MaterialIssueLineResponse(
        material_issue_line_id=line.material_issue_line_id,
        material_issue_id=line.material_issue_id,
        mo_material_line_id=line.mo_material_line_id,
        item_id=line.item_id,
        lot_id=line.lot_id,
        qty_issued=line.qty_issued,
        unit_cost=line.unit_cost,
        line_value=line.line_value,
        stock_ledger_id=line.stock_ledger_id,
    )


def _mi_to_response(mi: MaterialIssue) -> MaterialIssueResponse:
    return MaterialIssueResponse(
        material_issue_id=mi.material_issue_id,
        org_id=mi.org_id,
        firm_id=mi.firm_id,
        manufacturing_order_id=mi.manufacturing_order_id,
        series=mi.series,
        number=mi.number,
        issue_date=mi.issue_date,
        narration=mi.narration,
        voucher_id=mi.voucher_id,
        created_at=mi.created_at,
        updated_at=mi.updated_at,
        lines=[_mi_line_to_response(ln) for ln in mi.lines],
    )


@mos_router.post(
    "/{mo_id}/issue-materials",
    response_model=MaterialIssueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue raw materials from stock against a released MO (DR WIP / CR Inventory)",
)
def issue_materials_for_mo(
    mo_id: uuid.UUID,
    body: MaterialIssueCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.material_issue.write"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MaterialIssueResponse:
    # Defense-in-depth: when the session has an explicit firm scope, the
    # body firm_id must match — same pattern as create_mo.
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    service_lines = [
        material_issue_service.MaterialIssueLineInput(
            mo_material_line_id=ln.mo_material_line_id,
            qty_to_issue=ln.qty_to_issue,
            lot_id=ln.lot_id,
        )
        for ln in body.lines
    ]
    mi = material_issue_service.issue_materials(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_id=mo_id,
        lines=service_lines,
        issued_by=current_user.user_id,
        narration=body.narration,
        issue_date=body.issue_date,
        series=body.series or "MI",
    )
    # Re-fetch with eager-loaded lines for the response builder.
    fresh = material_issue_service.get_material_issue(
        db, org_id=current_user.org_id, issue_id=mi.material_issue_id
    )
    return _mi_to_response(fresh)


@mos_router.get(
    "/{mo_id}/material-issues",
    response_model=MaterialIssueListResponse,
    summary="List material issues against an MO",
)
def list_material_issues_for_mo(
    mo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.material_issue.read"))
    ],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MaterialIssueListResponse:
    # Need a firm_id to scope the list. Fall back to the session's
    # firm_id when the FE doesn't pass one (org-level tokens carry None).
    effective_firm_id = firm_id if firm_id is not None else current_user.firm_id
    if effective_firm_id is None:
        raise AppValidationError(
            "firm_id query param is required when the session is not firm-scoped."
        )
    items, total = material_issue_service.list_material_issues(
        db,
        org_id=current_user.org_id,
        firm_id=effective_firm_id,
        mo_id=mo_id,
        limit=limit,
        offset=offset,
    )
    return MaterialIssueListResponse(
        items=[_mi_to_response(mi) for mi in items],
        limit=limit,
        offset=offset,
        count=len(items),
        total_count=total,
    )


@material_issues_router.get(
    "/material-issues/{issue_id}",
    response_model=MaterialIssueResponse,
    summary="Get a single material issue by id (with per-component lines)",
)
def get_material_issue(
    issue_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.material_issue.read"))
    ],
) -> MaterialIssueResponse:
    mi = material_issue_service.get_material_issue(
        db, org_id=current_user.org_id, issue_id=issue_id
    )
    return _mi_to_response(mi)


# ──────────────────────────────────────────────────────────────────────
# Operation progress (TASK-TR-A07) — in-house operation lifecycle
# ──────────────────────────────────────────────────────────────────────
#
# Per-MO operation state machine: PENDING → IN_PROGRESS → CLOSED. POST
# endpoints carry ``firm_id`` for defense-in-depth on top of RLS; reads
# scope by ``current_user.org_id``. Idempotency-Key flows via the global
# ``IdempotencyMiddleware`` (no per-endpoint handling).

operation_progress_router = APIRouter(
    prefix="/manufacturing", tags=["manufacturing", "operation_progress"]
)


def _to_progress_response(op: MoOperation) -> OperationProgressResponse:
    """Render a ``MoOperation`` ORM row as the API-facing progress shape.

    Schema declares ``qty_in`` etc as non-optional ``Decimal`` (the
    column defaults are ``0`` once the MO is created so this is safe
    in practice), so coerce ``None`` → ``Decimal(0)`` defensively.
    """
    from decimal import Decimal

    return OperationProgressResponse(
        mo_operation_id=op.mo_operation_id,
        manufacturing_order_id=op.manufacturing_order_id,
        operation_master_id=op.operation_master_id,
        operation_sequence=op.operation_sequence,
        state=op.state,
        executor=op.executor,
        qty_in=Decimal(op.qty_in) if op.qty_in is not None else Decimal("0"),
        qty_out=Decimal(op.qty_out) if op.qty_out is not None else Decimal("0"),
        qty_rejected=Decimal(op.qty_rejected) if op.qty_rejected is not None else Decimal("0"),
        qty_byproduct=Decimal(op.qty_byproduct) if op.qty_byproduct is not None else Decimal("0"),
        qty_wastage=Decimal(op.qty_wastage) if op.qty_wastage is not None else Decimal("0"),
        start_date=op.start_date,
        end_date=op.end_date,
        created_at=op.created_at,
        updated_at=op.updated_at,
        version=op.version or 0,
    )


def _to_event_response(ev: ProductionEvent) -> ProductionEventResponse:
    return ProductionEventResponse(
        event_id=ev.event_id,
        event_type=ev.event_type,
        mo_operation_id=ev.mo_operation_id,
        manufacturing_order_id=ev.manufacturing_order_id,
        payload=dict(ev.payload) if ev.payload is not None else {},
        actor_user_id=ev.actor_user_id,
        occurred_at=ev.occurred_at,
    )


@operation_progress_router.post(
    "/mo-operations/{mo_operation_id}/start",
    response_model=OperationProgressResponse,
    summary="Start an in-house MO operation (PENDING → IN_PROGRESS)",
)
def start_operation(
    mo_operation_id: uuid.UUID,
    body: OperationStartRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation.progress"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OperationProgressResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = operation_progress_service.start_operation(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        started_by=current_user.user_id,
        narration=body.narration,
    )
    return _to_progress_response(op)


@operation_progress_router.post(
    "/mo-operations/{mo_operation_id}/qty-in",
    response_model=OperationProgressResponse,
    summary="Record qty_in (units received) on an in-progress MO operation",
)
def record_qty_in(
    mo_operation_id: uuid.UUID,
    body: OperationQtyInRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation.progress"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OperationProgressResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = operation_progress_service.record_qty_in(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        qty_in=body.qty_in,
        recorded_by=current_user.user_id,
        narration=body.narration,
    )
    return _to_progress_response(op)


@operation_progress_router.post(
    "/mo-operations/{mo_operation_id}/qty-out",
    response_model=OperationProgressResponse,
    summary="Record qty_out / scrap / byproduct / wastage on an in-progress MO operation",
)
def record_qty_out(
    mo_operation_id: uuid.UUID,
    body: OperationQtyOutRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation.progress"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OperationProgressResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = operation_progress_service.record_qty_out(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        qty_out=body.qty_out,
        qty_scrap=body.qty_scrap,
        qty_byproduct=body.qty_byproduct,
        qty_wastage=body.qty_wastage,
        recorded_by=current_user.user_id,
        narration=body.narration,
    )
    return _to_progress_response(op)


@operation_progress_router.post(
    "/mo-operations/{mo_operation_id}/complete",
    response_model=OperationProgressResponse,
    summary="Close an in-house MO operation (IN_PROGRESS → CLOSED)",
)
def complete_operation(
    mo_operation_id: uuid.UUID,
    body: OperationCompleteRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation.progress"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OperationProgressResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = operation_progress_service.complete_operation(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        completed_by=current_user.user_id,
        narration=body.narration,
    )
    return _to_progress_response(op)


@operation_progress_router.get(
    "/mo/{mo_id}/operations",
    response_model=OperationProgressListResponse,
    summary="List operations on an MO, ordered by sequence",
)
def list_mo_operations(
    mo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation.read"))
    ],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OperationProgressListResponse:
    effective_firm_id = firm_id if firm_id is not None else current_user.firm_id
    if effective_firm_id is None:
        raise AppValidationError(
            "firm_id query param is required when the session is not firm-scoped."
        )
    items, total = operation_progress_service.list_operations(
        db,
        org_id=current_user.org_id,
        firm_id=effective_firm_id,
        mo_id=mo_id,
        limit=limit,
        offset=offset,
    )
    return OperationProgressListResponse(
        items=[_to_progress_response(op) for op in items],
        limit=limit,
        offset=offset,
        count=len(items),
        total_count=total,
    )


@operation_progress_router.get(
    "/mo-operations/{mo_operation_id}",
    response_model=OperationDetailResponse,
    summary="Get one MO operation + its append-only production event log",
)
def get_mo_operation(
    mo_operation_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation.read"))
    ],
) -> OperationDetailResponse:
    op = operation_progress_service.get_operation(
        db, org_id=current_user.org_id, mo_operation_id=mo_operation_id
    )
    events = operation_progress_service.list_events_for_operation(
        db, org_id=current_user.org_id, mo_operation_id=mo_operation_id
    )
    return OperationDetailResponse(
        operation=_to_progress_response(op),
        events=[_to_event_response(ev) for ev in events],
    )


@operation_progress_router.get(
    "/mo-operations/{mo_operation_id}/can-start",
    response_model=CanStartOperationResponse,
    summary="Routing-DAG verdict: can this op start now?",
)
def can_start_mo_operation(
    mo_operation_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.operation.read"))
    ],
) -> CanStartOperationResponse:
    """TR-A09 — surface the edge-walking engine's verdict for an op so
    the FE can disable a "Start" button (or pre-flight a karigar
    dispatch) when an upstream edge is unsatisfied.

    Read-only. The state-machine guards inside ``start_operation`` /
    ``dispatch_to_karigar`` remain the source of truth: an over-eager
    POST would still get a 422 with the same reason.
    """
    op = operation_progress_service.get_operation(
        db, org_id=current_user.org_id, mo_operation_id=mo_operation_id
    )
    allowed, reason = routing_flow_service.can_start_operation(db, op=op)
    return CanStartOperationResponse(
        mo_operation_id=op.mo_operation_id,
        allowed=allowed,
        reason=reason,
    )


# ──────────────────────────────────────────────────────────────────────
# Karigar / job-work per-operation send-out (TASK-TR-A08)
# ──────────────────────────────────────────────────────────────────────
#
# Lifecycle:
#   PENDING → DISPATCHED → ACKNOWLEDGED → RECEIVED_PARTIAL ↔ RECEIVED_FULL → CLOSED
#
# Each transition emits an append-only ``ProductionEvent``. POST bodies
# carry ``firm_id`` for defense-in-depth on top of RLS; Idempotency-Key
# flows via the global ``IdempotencyMiddleware``.
#
# Permission split: ``manufacturing.karigar.dispatch`` covers dispatch +
# acknowledge (the outbound leg); ``manufacturing.karigar.receive`` covers
# the receive-back + close (the inbound leg — close finalises the return
# loop). Warehouse + Production Manager carry both today.

karigar_router = APIRouter(prefix="/manufacturing", tags=["manufacturing", "karigar"])


def _to_karigar_response(op: MoOperation) -> KarigarOperationResponse:
    """Render an ``MoOperation`` ORM row as the karigar-facing shape.

    Wider than ``OperationProgressResponse`` — also surfaces the
    karigar party + outward/inward challan ids the shop-floor view needs.
    """
    from decimal import Decimal

    return KarigarOperationResponse(
        mo_operation_id=op.mo_operation_id,
        manufacturing_order_id=op.manufacturing_order_id,
        operation_master_id=op.operation_master_id,
        operation_sequence=op.operation_sequence,
        state=op.state,
        executor=op.executor,
        karigar_party_id=op.karigar_party_id,
        outward_challan_id=op.outward_challan_id,
        inward_challan_id=op.inward_challan_id,
        qty_in=Decimal(op.qty_in) if op.qty_in is not None else Decimal("0"),
        qty_out=Decimal(op.qty_out) if op.qty_out is not None else Decimal("0"),
        qty_rejected=Decimal(op.qty_rejected) if op.qty_rejected is not None else Decimal("0"),
        qty_byproduct=Decimal(op.qty_byproduct) if op.qty_byproduct is not None else Decimal("0"),
        qty_wastage=Decimal(op.qty_wastage) if op.qty_wastage is not None else Decimal("0"),
        start_date=op.start_date,
        end_date=op.end_date,
        acknowledged_at=op.acknowledged_at,
        created_at=op.created_at,
        updated_at=op.updated_at,
    )


@karigar_router.post(
    "/mo-operations/{mo_operation_id}/dispatch-karigar",
    response_model=KarigarOperationResponse,
    summary="Dispatch a karigar (job-work) MO operation (PENDING/RECEIVED_FULL → DISPATCHED)",
)
def dispatch_karigar(
    mo_operation_id: uuid.UUID,
    body: KarigarDispatchRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.karigar.dispatch"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> KarigarOperationResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = karigar_send_out_service.dispatch_to_karigar(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        karigar_party_id=body.karigar_party_id,
        qty_dispatched=body.qty_dispatched,
        dispatch_date=body.dispatch_date,
        item_id=body.item_id,
        uom=body.uom,
        lot_id=body.lot_id,
        dispatched_by=current_user.user_id,
        narration=body.narration,
    )
    return _to_karigar_response(op)


@karigar_router.post(
    "/mo-operations/{mo_operation_id}/acknowledge-karigar",
    response_model=KarigarOperationResponse,
    summary="Acknowledge a karigar dispatch (DISPATCHED → ACKNOWLEDGED)",
)
def acknowledge_karigar(
    mo_operation_id: uuid.UUID,
    body: KarigarAcknowledgeRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.karigar.dispatch"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> KarigarOperationResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = karigar_send_out_service.acknowledge_karigar(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        acknowledged_by=current_user.user_id,
        narration=body.narration,
    )
    return _to_karigar_response(op)


@karigar_router.post(
    "/mo-operations/{mo_operation_id}/receive-karigar",
    response_model=KarigarOperationResponse,
    summary=(
        "Receive back from karigar "
        "(ACKNOWLEDGED/RECEIVED_PARTIAL → RECEIVED_PARTIAL or RECEIVED_FULL)"
    ),
)
def receive_karigar(
    mo_operation_id: uuid.UUID,
    body: KarigarReceiveRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.karigar.receive"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> KarigarOperationResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = karigar_send_out_service.receive_from_karigar(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        qty_received=body.qty_received,
        qty_scrap=body.qty_scrap,
        qty_byproduct=body.qty_byproduct,
        qty_wastage=body.qty_wastage,
        receipt_date=body.receipt_date,
        received_by=current_user.user_id,
        narration=body.narration,
    )
    return _to_karigar_response(op)


@karigar_router.post(
    "/mo-operations/{mo_operation_id}/close-karigar",
    response_model=KarigarOperationResponse,
    summary="Close a karigar MO operation (RECEIVED_FULL → CLOSED)",
)
def close_karigar(
    mo_operation_id: uuid.UUID,
    body: KarigarCloseRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("manufacturing.karigar.receive"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> KarigarOperationResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = karigar_send_out_service.close_karigar_operation(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        closed_by=current_user.user_id,
        narration=body.narration,
    )
    return _to_karigar_response(op)


# ──────────────────────────────────────────────────────────────────────
# QC inspection (TASK-TR-A10)
# ──────────────────────────────────────────────────────────────────────
#
# Lifecycle:
#   PENDING → QC_PENDING → CLOSED   (PASS verdict)
#                       └→ REWORK   (REWORK verdict — v1 stops here)
#
# QC ops DO NOT consume materials; they inspect the output of a single
# predecessor op. Strict conservation at ``record-qc-result``:
#   passed + rejected + byproduct + wastage + rework == predecessor.qty_out
#
# ``qty_rework`` lives on the ``QC_RESULT_RECORDED`` event payload, not
# a column — rework-op creation is A10-FU. The GET /qc-result endpoint
# surfaces the latest verdict + bucket breakdown by reading the event.
#
# Permission split: ``manufacturing.qc.write`` (mutations) +
# ``manufacturing.qc.read`` (reads). Granted to OWNER + Production
# Manager today; Accountant gets read-only for cost-roll-up.

qc_router = APIRouter(prefix="/manufacturing", tags=["manufacturing", "qc"])


def _qc_operation_type(
    db: SyncDBSession, op: MoOperation, org_id: uuid.UUID
) -> OperationType | None:
    """Resolve the ``operation_type`` for a MO operation via its
    catalogue ``operation_master``. ``MoOperation`` doesn't carry the
    type column; the catalogue is the source of truth.
    """
    from sqlalchemy import select as _select

    om = db.execute(
        _select(OperationMaster.operation_type).where(
            OperationMaster.operation_master_id == op.operation_master_id,
            OperationMaster.org_id == org_id,
            OperationMaster.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    return om


def _to_qc_response(
    op: MoOperation, *, operation_type: OperationType | None
) -> QcOperationResponse:
    """Render a ``MoOperation`` ORM row as the QC API-facing shape.

    Mirrors ``_to_progress_response`` plus ``operation_type``.
    """
    from decimal import Decimal as _Decimal

    return QcOperationResponse(
        mo_operation_id=op.mo_operation_id,
        manufacturing_order_id=op.manufacturing_order_id,
        operation_master_id=op.operation_master_id,
        operation_type=operation_type,
        operation_sequence=op.operation_sequence,
        state=op.state,
        executor=op.executor,
        qty_in=_Decimal(op.qty_in) if op.qty_in is not None else _Decimal("0"),
        qty_out=_Decimal(op.qty_out) if op.qty_out is not None else _Decimal("0"),
        qty_rejected=_Decimal(op.qty_rejected) if op.qty_rejected is not None else _Decimal("0"),
        qty_byproduct=_Decimal(op.qty_byproduct) if op.qty_byproduct is not None else _Decimal("0"),
        qty_wastage=_Decimal(op.qty_wastage) if op.qty_wastage is not None else _Decimal("0"),
        start_date=op.start_date,
        end_date=op.end_date,
        created_at=op.created_at,
        updated_at=op.updated_at,
        version=op.version or 0,
    )


@qc_router.post(
    "/mo-operations/{mo_operation_id}/start-qc",
    response_model=QcOperationResponse,
    summary="Start a QC inspection operation (PENDING → QC_PENDING)",
)
def start_qc(
    mo_operation_id: uuid.UUID,
    body: QcStartRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.qc.write"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> QcOperationResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = qc_service.start_qc_inspection(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        started_by=current_user.user_id,
        narration=body.narration,
    )
    op_type = _qc_operation_type(db, op, current_user.org_id)
    return _to_qc_response(op, operation_type=op_type)


@qc_router.post(
    "/mo-operations/{mo_operation_id}/record-qc-result",
    response_model=QcOperationResponse,
    summary="Record QC verdict on a QC_PENDING operation (→ CLOSED or REWORK)",
)
def record_qc_result(
    mo_operation_id: uuid.UUID,
    body: QcResultRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.qc.write"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> QcOperationResponse:
    if current_user.firm_id is not None and body.firm_id != current_user.firm_id:
        raise AppValidationError("firm_id must match the current session firm")
    op = qc_service.record_qc_result(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        mo_operation_id=mo_operation_id,
        qty_passed=body.qty_passed,
        qty_rejected=body.qty_rejected,
        qty_byproduct=body.qty_byproduct,
        qty_wastage=body.qty_wastage,
        qty_rework=body.qty_rework,
        narration=body.narration,
        recorded_by=current_user.user_id,
    )
    op_type = _qc_operation_type(db, op, current_user.org_id)
    return _to_qc_response(op, operation_type=op_type)


@qc_router.get(
    "/mo-operations/{mo_operation_id}/qc-result",
    response_model=QcResultResponse,
    summary="Latest QC verdict + bucket breakdown for a QC operation",
)
def get_qc_result(
    mo_operation_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("manufacturing.qc.read"))],
) -> QcResultResponse:
    """Read the most recent ``QC_RESULT_RECORDED`` event for the op.
    Returns ``recorded=False`` with zero buckets when QC has not been
    posted yet — the FE can render an "awaiting QC" state without a
    404. ``qty_rework`` is the load-bearing field, pulled off the event
    payload (no column lives on ``mo_operation``).
    """
    from decimal import Decimal as _Decimal

    event = qc_service.get_latest_qc_result(
        db, org_id=current_user.org_id, mo_operation_id=mo_operation_id
    )
    if event is None:
        return QcResultResponse(
            mo_operation_id=mo_operation_id,
            recorded=False,
            verdict=None,
            qty_passed=_Decimal("0"),
            qty_rejected=_Decimal("0"),
            qty_byproduct=_Decimal("0"),
            qty_wastage=_Decimal("0"),
            qty_rework=_Decimal("0"),
            predecessor_qty_out=_Decimal("0"),
            predecessor_mo_operation_id=None,
            occurred_at=None,
        )
    p = event.payload or {}

    def _dec(key: str) -> _Decimal:
        raw = p.get(key)
        return _Decimal(str(raw)) if raw is not None else _Decimal("0")

    pred_id_raw = p.get("predecessor_mo_operation_id")
    pred_id = uuid.UUID(str(pred_id_raw)) if pred_id_raw else None
    return QcResultResponse(
        mo_operation_id=mo_operation_id,
        recorded=True,
        verdict=p.get("verdict"),
        qty_passed=_dec("qty_passed"),
        qty_rejected=_dec("qty_rejected"),
        qty_byproduct=_dec("qty_byproduct"),
        qty_wastage=_dec("qty_wastage"),
        qty_rework=_dec("qty_rework"),
        predecessor_qty_out=_dec("predecessor_qty_out"),
        predecessor_mo_operation_id=pred_id,
        occurred_at=event.occurred_at,
    )
