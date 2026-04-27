"""Procurement routers — Purchase Order CRUD + state machine (TASK-027).

Sync handlers (FastAPI threadpool). Permission gates per the rbac_service
catalog: `purchase.po.{create,read,approve}`. Cancel and soft-delete go
through `purchase.po.approve` since they're administrative state changes.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.models import POLine, PurchaseOrder
from app.models.procurement import PurchaseOrderStatus
from app.routers.auth import _validate_idempotency_key
from app.schemas.procurement import (
    POCreateRequest,
    POLineResponse,
    POListResponse,
    POResponse,
)
from app.service import procurement_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/purchase-orders", tags=["procurement", "po"])


def _line_to_response(line: POLine) -> POLineResponse:
    return POLineResponse(
        po_line_id=line.po_line_id,
        item_id=line.item_id,
        qty_ordered=line.qty_ordered,
        qty_received=line.qty_received,
        rate=line.rate,
        line_amount=line.line_amount,
        line_sequence=line.line_sequence,
        taxes_applicable=line.taxes_applicable,
        notes=line.notes,
    )


def _po_to_response(po: PurchaseOrder) -> POResponse:
    return POResponse(
        purchase_order_id=po.purchase_order_id,
        org_id=po.org_id,
        firm_id=po.firm_id,
        series=po.series,
        number=po.number,
        party_id=po.party_id,
        po_date=po.po_date,
        delivery_date=po.delivery_date,
        status=po.status or PurchaseOrderStatus.DRAFT,
        total_amount=po.total_amount,
        notes=po.notes,
        lines=[_line_to_response(line) for line in po.lines],
        created_at=po.created_at,
        updated_at=po.updated_at,
    )


@router.post(
    "",
    response_model=POResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Purchase Order",
)
def create_po(
    body: POCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.po.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> POResponse:
    _validate_idempotency_key(idempotency_key)
    po = procurement_service.create_po(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        party_id=body.party_id,
        po_date=body.po_date,
        series=body.series,
        lines=[
            {
                "item_id": line.item_id,
                "qty_ordered": line.qty_ordered,
                "rate": line.rate,
                "line_sequence": line.line_sequence,
                "taxes_applicable": line.taxes_applicable,
                "notes": line.notes,
            }
            for line in body.lines
        ],
        delivery_date=body.delivery_date,
        notes=body.notes,
        created_by=current_user.user_id,
    )
    return _po_to_response(po)


@router.get(
    "",
    response_model=POListResponse,
    summary="List purchase orders for the caller's org",
)
def list_pos(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.po.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    party_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[PurchaseOrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> POListResponse:
    pos = procurement_service.list_pos(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        party_id=party_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return POListResponse(
        items=[_po_to_response(po) for po in pos],
        limit=limit,
        offset=offset,
        count=len(pos),
    )


@router.get(
    "/{po_id}",
    response_model=POResponse,
    summary="Get a Purchase Order by id",
)
def get_po(
    po_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.po.read"))],
) -> POResponse:
    po = procurement_service.get_po(db, org_id=current_user.org_id, po_id=po_id)
    return _po_to_response(po)


@router.post(
    "/{po_id}/approve",
    response_model=POResponse,
    summary="Approve a draft PO (DRAFT → APPROVED)",
)
def approve_po(
    po_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.po.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> POResponse:
    _validate_idempotency_key(idempotency_key)
    po = procurement_service.approve_po(
        db, org_id=current_user.org_id, po_id=po_id, updated_by=current_user.user_id
    )
    return _po_to_response(po)


@router.post(
    "/{po_id}/confirm",
    response_model=POResponse,
    summary="Confirm an approved or draft PO (→ CONFIRMED)",
)
def confirm_po(
    po_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.po.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> POResponse:
    _validate_idempotency_key(idempotency_key)
    po = procurement_service.confirm_po(
        db, org_id=current_user.org_id, po_id=po_id, updated_by=current_user.user_id
    )
    return _po_to_response(po)


@router.post(
    "/{po_id}/cancel",
    response_model=POResponse,
    summary="Cancel a PO (refused if any GRN posted)",
)
def cancel_po(
    po_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.po.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> POResponse:
    _validate_idempotency_key(idempotency_key)
    po = procurement_service.cancel_po(
        db, org_id=current_user.org_id, po_id=po_id, updated_by=current_user.user_id
    )
    return _po_to_response(po)


@router.delete(
    "/{po_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a PO (DRAFT or CANCELLED only)",
)
def delete_po(
    po_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.po.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    _validate_idempotency_key(idempotency_key)
    procurement_service.soft_delete_po(
        db, org_id=current_user.org_id, po_id=po_id, deleted_by=current_user.user_id
    )
