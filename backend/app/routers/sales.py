"""Sales routers — Sales Order CRUD + state machine (TASK-032).

Sync handlers (FastAPI threadpool). Permission gates per the rbac_service
catalog: `sales.order.{create,read,approve}`. Cancel and soft-delete go
through `sales.order.approve` since they're administrative state changes.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.models import SalesOrder, SOLine
from app.models.sales import SalesOrderStatus
from app.routers.auth import _validate_idempotency_key
from app.schemas.sales import (
    SOCreateRequest,
    SOLineResponse,
    SOListResponse,
    SOResponse,
)
from app.service import sales_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/sales-orders", tags=["sales", "so"])


def _line_to_response(line: SOLine) -> SOLineResponse:
    return SOLineResponse(
        so_line_id=line.so_line_id,
        item_id=line.item_id,
        qty_ordered=line.qty_ordered,
        qty_dispatched=line.qty_dispatched,
        price=line.price,
        line_amount=line.line_amount,
        gst_rate=line.gst_rate,
        sequence=line.sequence,
    )


def _so_to_response(so: SalesOrder) -> SOResponse:
    return SOResponse(
        sales_order_id=so.sales_order_id,
        org_id=so.org_id,
        firm_id=so.firm_id,
        series=so.series,
        number=so.number,
        party_id=so.party_id,
        so_date=so.so_date,
        delivery_date=so.delivery_date,
        status=so.status or SalesOrderStatus.DRAFT,
        total_amount=so.total_amount,
        notes=so.notes,
        lines=[_line_to_response(line) for line in so.lines],
        created_at=so.created_at,
        updated_at=so.updated_at,
    )


@router.post(
    "",
    response_model=SOResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Sales Order",
)
def create_so(
    body: SOCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.order.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SOResponse:
    _validate_idempotency_key(idempotency_key)
    so = sales_service.create_so(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        party_id=body.party_id,
        so_date=body.so_date,
        series=body.series,
        lines=[
            {
                "item_id": line.item_id,
                "qty_ordered": line.qty_ordered,
                "price": line.price,
                "sequence": line.sequence,
                "gst_rate": line.gst_rate,
            }
            for line in body.lines
        ],
        delivery_date=body.delivery_date,
        notes=body.notes,
        created_by=current_user.user_id,
    )
    return _so_to_response(so)


@router.get(
    "",
    response_model=SOListResponse,
    summary="List sales orders for the caller's org",
)
def list_sos(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.order.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    party_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[SalesOrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SOListResponse:
    sos = sales_service.list_sos(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        party_id=party_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return SOListResponse(
        items=[_so_to_response(so) for so in sos],
        limit=limit,
        offset=offset,
        count=len(sos),
    )


@router.get(
    "/{so_id}",
    response_model=SOResponse,
    summary="Get a Sales Order by id",
)
def get_so(
    so_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.order.read"))],
) -> SOResponse:
    so = sales_service.get_so(db, org_id=current_user.org_id, so_id=so_id)
    return _so_to_response(so)


@router.post(
    "/{so_id}/confirm",
    response_model=SOResponse,
    summary="Confirm a draft SO (DRAFT → CONFIRMED)",
)
def confirm_so(
    so_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.order.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SOResponse:
    _validate_idempotency_key(idempotency_key)
    so = sales_service.confirm_so(
        db, org_id=current_user.org_id, so_id=so_id, updated_by=current_user.user_id
    )
    return _so_to_response(so)


@router.post(
    "/{so_id}/cancel",
    response_model=SOResponse,
    summary="Cancel a SO (refused if any DC posted)",
)
def cancel_so(
    so_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.order.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SOResponse:
    _validate_idempotency_key(idempotency_key)
    so = sales_service.cancel_so(
        db, org_id=current_user.org_id, so_id=so_id, updated_by=current_user.user_id
    )
    return _so_to_response(so)


@router.delete(
    "/{so_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a SO (DRAFT or CANCELLED only)",
)
def delete_so(
    so_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.order.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    _validate_idempotency_key(idempotency_key)
    sales_service.soft_delete_so(
        db, org_id=current_user.org_id, so_id=so_id, deleted_by=current_user.user_id
    )
