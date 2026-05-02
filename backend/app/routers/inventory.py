"""Inventory router — stock adjustment endpoints (TASK-023).

Endpoints:
  POST /stock-adjustments        — create an adjustment
  GET  /stock-adjustments        — list adjustments with optional filters
  GET  /stock-adjustments/{id}   — get a single adjustment

Permissions:
  inventory.adjustment.create  — create
  inventory.stock.read         — list + get
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.models import StockAdjustment
from app.schemas.inventory import (
    StockAdjustmentListResponse,
    StockAdjustmentRequest,
    StockAdjustmentResponse,
)
from app.service import stock_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/stock-adjustments", tags=["inventory", "stock-adjustment"])


def _adj_to_response(adj: StockAdjustment) -> StockAdjustmentResponse:
    return StockAdjustmentResponse(
        stock_adjustment_id=adj.stock_adjustment_id,
        org_id=adj.org_id,
        firm_id=adj.firm_id,
        item_id=adj.item_id,
        lot_id=adj.lot_id,
        location_id=adj.location_id,
        qty_change=adj.qty_change,
        reason=adj.reason,
        requires_approval=adj.requires_approval,
        approved_by=adj.approved_by,
        approved_at=adj.approved_at,
        created_by=adj.created_by,
        created_at=adj.created_at,
    )


@router.post(
    "",
    response_model=StockAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a stock adjustment",
)
def create_stock_adjustment(
    body: StockAdjustmentRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("inventory.adjustment.create"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StockAdjustmentResponse:
    """Create a stock adjustment.

    - **INCREASE**: add `qty` units to on-hand stock at (item, location[, lot]).
    - **DECREASE**: remove `qty` units; raises 422 if insufficient stock.
    - **COUNT_RESET**: set on-hand to `qty`; auto-computes delta direction.
    """
    adj, _ledger = stock_service.create_adjustment(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        item_id=body.item_id,
        location_id=body.location_id,
        qty=body.qty,
        direction=body.direction,
        reason=body.reason,
        lot_id=body.lot_id,
        txn_date=body.txn_date,
        adjusted_by=current_user.user_id,
        unit_cost=body.unit_cost,
    )
    return _adj_to_response(adj)


@router.get(
    "",
    response_model=StockAdjustmentListResponse,
    summary="List stock adjustments",
)
def list_stock_adjustments(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("inventory.stock.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    item_id: Annotated[uuid.UUID | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    from_date: Annotated[datetime.date | None, Query()] = None,
    to_date: Annotated[datetime.date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StockAdjustmentListResponse:
    """List stock adjustment headers with optional filters."""
    rows = stock_service.list_adjustments(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return StockAdjustmentListResponse(
        items=[_adj_to_response(r) for r in rows],
        count=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{adjustment_id}",
    response_model=StockAdjustmentResponse,
    summary="Get a stock adjustment by id",
)
def get_stock_adjustment(
    adjustment_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("inventory.stock.read"))],
) -> StockAdjustmentResponse:
    """Fetch a single stock adjustment header."""
    from app.exceptions import AppValidationError

    adj = stock_service.get_adjustment(db, org_id=current_user.org_id, adjustment_id=adjustment_id)
    if adj is None:
        raise AppValidationError(f"Stock adjustment {adjustment_id} not found")
    return _adj_to_response(adj)
