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
from app.models import GRN, GRNLine, POLine, PurchaseOrder
from app.models.procurement import GRNStatus, PurchaseOrderStatus
from app.routers.auth import _validate_idempotency_key
from app.schemas.procurement import (
    GRNCreateRequest,
    GRNLineResponse,
    GRNListResponse,
    GRNResponse,
    POCreateRequest,
    POLineResponse,
    POListResponse,
    POResponse,
)
from app.service import procurement_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/purchase-orders", tags=["procurement", "po"])
grn_router = APIRouter(prefix="/grns", tags=["procurement", "grn"])


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


# ──────────────────────────────────────────────────────────────────────
# GRN endpoints — TASK-028
# ──────────────────────────────────────────────────────────────────────


def _grn_line_to_response(line: GRNLine) -> GRNLineResponse:
    return GRNLineResponse(
        grn_line_id=line.grn_line_id,
        grn_id=line.grn_id,
        item_id=line.item_id,
        po_line_id=line.po_line_id,
        qty_received=line.qty_received,
        rate=line.rate,
        lot_number=line.lot_number,
        line_sequence=line.line_sequence,
    )


def _grn_to_response(grn: GRN) -> GRNResponse:
    return GRNResponse(
        grn_id=grn.grn_id,
        org_id=grn.org_id,
        firm_id=grn.firm_id,
        series=grn.series,
        number=grn.number,
        party_id=grn.party_id,
        purchase_order_id=grn.purchase_order_id,
        grn_date=grn.grn_date,
        status=grn.status or GRNStatus.DRAFT.value,
        total_qty_received=grn.total_qty_received,
        total_amount=grn.total_amount,
        notes=grn.notes,
        lines=[_grn_line_to_response(line) for line in grn.lines],
        created_at=grn.created_at,
        updated_at=grn.updated_at,
    )


@grn_router.post(
    "",
    response_model=GRNResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a GRN (DRAFT — no stock posting yet)",
)
def create_grn(
    body: GRNCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.grn.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> GRNResponse:
    _validate_idempotency_key(idempotency_key)
    grn = procurement_service.create_grn(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        party_id=body.party_id,
        grn_date=body.grn_date,
        series=body.series,
        purchase_order_id=body.purchase_order_id,
        lines=[
            {
                "item_id": line.item_id,
                "qty_received": line.qty_received,
                "rate": line.rate,
                "lot_number": line.lot_number,
                "po_line_id": line.po_line_id,
                "line_sequence": line.line_sequence,
            }
            for line in body.lines
        ],
        notes=body.notes,
        created_by=current_user.user_id,
    )
    return _grn_to_response(grn)


@grn_router.get(
    "",
    response_model=GRNListResponse,
    summary="List GRNs scoped to caller's org",
)
def list_grns(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.grn.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    purchase_order_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[GRNStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> GRNListResponse:
    grns = procurement_service.list_grns(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        purchase_order_id=purchase_order_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return GRNListResponse(
        items=[_grn_to_response(grn) for grn in grns],
        limit=limit,
        offset=offset,
        count=len(grns),
    )


@grn_router.get(
    "/{grn_id}",
    response_model=GRNResponse,
    summary="Get a GRN by id",
)
def get_grn(
    grn_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.grn.read"))],
) -> GRNResponse:
    grn = procurement_service.get_grn(db, org_id=current_user.org_id, grn_id=grn_id)
    return _grn_to_response(grn)


@grn_router.post(
    "/{grn_id}/receive",
    response_model=GRNResponse,
    summary="Receive a GRN (DRAFT → ACKNOWLEDGED) — posts stock + advances PO status",
)
def receive_grn(
    grn_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.grn.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> GRNResponse:
    _validate_idempotency_key(idempotency_key)
    grn = procurement_service.receive_grn(
        db, org_id=current_user.org_id, grn_id=grn_id, updated_by=current_user.user_id
    )
    return _grn_to_response(grn)


@grn_router.delete(
    "/{grn_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a DRAFT GRN (refused once received)",
)
def delete_grn(
    grn_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("purchase.grn.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    _validate_idempotency_key(idempotency_key)
    procurement_service.soft_delete_grn(
        db, org_id=current_user.org_id, grn_id=grn_id, deleted_by=current_user.user_id
    )
