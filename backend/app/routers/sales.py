"""Sales routers — Sales Order CRUD + state machine (TASK-032) + Delivery Challan (TASK-033).

Sync handlers (FastAPI threadpool). Permission gates per the rbac_service
catalog:
- SO: `sales.order.{create,read,approve}`
- DC: `sales.dc.{create,read,approve}`

Cancel and soft-delete go through the respective `.approve` permission since
they are administrative state changes.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.models import DCLine, DeliveryChallan, SalesOrder, SOLine
from app.models.sales import DCStatus, SalesOrderStatus
from app.routers.auth import _validate_idempotency_key
from app.schemas.sales import (
    DCCreateRequest,
    DCLineResponse,
    DCListResponse,
    DCResponse,
    SOCreateRequest,
    SOLineResponse,
    SOListResponse,
    SOResponse,
)
from app.service import sales_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/sales-orders", tags=["sales", "so"])
dc_router = APIRouter(prefix="/delivery-challans", tags=["sales", "dc"])


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


# ──────────────────────────────────────────────────────────────────────
# Delivery Challan endpoints — TASK-033
# ──────────────────────────────────────────────────────────────────────


def _dc_line_to_response(line: DCLine) -> DCLineResponse:
    return DCLineResponse(
        dc_line_id=line.dc_line_id,
        delivery_challan_id=line.delivery_challan_id,
        item_id=line.item_id,
        lot_id=line.lot_id,
        qty_dispatched=line.qty_dispatched,
        price=line.price,
        sequence=line.sequence,
    )


def _dc_to_response(dc: DeliveryChallan) -> DCResponse:
    return DCResponse(
        delivery_challan_id=dc.delivery_challan_id,
        org_id=dc.org_id,
        firm_id=dc.firm_id,
        series=dc.series,
        number=dc.number,
        sales_order_id=dc.sales_order_id,
        party_id=dc.party_id,
        bill_to_address=dc.bill_to_address,
        ship_to_address=dc.ship_to_address,
        place_of_supply_state=dc.place_of_supply_state,
        dispatch_date=dc.dispatch_date,
        status=dc.status or DCStatus.DRAFT.value,
        total_qty=dc.total_qty,
        total_amount=dc.total_amount,
        lines=[_dc_line_to_response(line) for line in dc.lines],
        created_at=dc.created_at,
        updated_at=dc.updated_at,
    )


@dc_router.post(
    "",
    response_model=DCResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Delivery Challan (DRAFT — no stock posting yet)",
)
def create_dc(
    body: DCCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.dc.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DCResponse:
    _validate_idempotency_key(idempotency_key)
    dc = sales_service.create_dc(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        party_id=body.party_id,
        dispatch_date=body.dispatch_date,
        series=body.series,
        sales_order_id=body.sales_order_id,
        bill_to_address=body.bill_to_address,
        ship_to_address=body.ship_to_address,
        place_of_supply_state=body.place_of_supply_state,
        lines=[
            {
                "item_id": line.item_id,
                "qty_dispatched": line.qty_dispatched,
                "price": line.price,
                "lot_id": line.lot_id,
                "sequence": line.sequence,
            }
            for line in body.lines
        ],
        created_by=current_user.user_id,
    )
    return _dc_to_response(dc)


@dc_router.get(
    "",
    response_model=DCListResponse,
    summary="List Delivery Challans scoped to caller's org",
)
def list_dcs(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.dc.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    sales_order_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[DCStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DCListResponse:
    dcs = sales_service.list_dcs(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        sales_order_id=sales_order_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return DCListResponse(
        items=[_dc_to_response(dc) for dc in dcs],
        limit=limit,
        offset=offset,
        count=len(dcs),
    )


@dc_router.get(
    "/{dc_id}",
    response_model=DCResponse,
    summary="Get a Delivery Challan by id",
)
def get_dc(
    dc_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.dc.read"))],
) -> DCResponse:
    dc = sales_service.get_dc(db, org_id=current_user.org_id, dc_id=dc_id)
    return _dc_to_response(dc)


@dc_router.post(
    "/{dc_id}/issue",
    response_model=DCResponse,
    summary="Issue a DC (DRAFT → ISSUED) — posts stock removal + advances SO status",
)
def issue_dc(
    dc_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.dc.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DCResponse:
    _validate_idempotency_key(idempotency_key)
    dc = sales_service.issue_dc(
        db, org_id=current_user.org_id, dc_id=dc_id, updated_by=current_user.user_id
    )
    return _dc_to_response(dc)


@dc_router.delete(
    "/{dc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a DRAFT DC (refused once issued)",
)
def delete_dc(
    dc_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("sales.dc.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    _validate_idempotency_key(idempotency_key)
    sales_service.soft_delete_dc(
        db, org_id=current_user.org_id, dc_id=dc_id, deleted_by=current_user.user_id
    )
