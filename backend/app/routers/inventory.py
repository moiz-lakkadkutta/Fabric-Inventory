"""Inventory router — stock adjustment + location + lot endpoints.

Endpoints:
  POST /stock-adjustments        — create an adjustment           (TASK-023)
  GET  /stock-adjustments        — list adjustments with filters  (TASK-023)
  GET  /stock-adjustments/{id}   — get a single adjustment        (TASK-023)
  GET  /locations                — list firm locations            (TASK-CUT-204)
  GET  /lots                     — paginated list of lots         (TASK-TR-B02)
  GET  /lots/{lot_id}            — single lot with qty_on_hand    (TASK-TR-B02)

Permissions:
  inventory.adjustment.create  — create adjustment
  inventory.stock.read         — list + get adjustments + list locations
  inventory.lot.read           — list + get lots
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.models import Item, Location, Lot, StockAdjustment
from app.models.inventory import LocationType
from app.schemas.inventory import (
    LocationCreateRequest,
    LocationListResponse,
    LocationResponse,
    LotListResponse,
    LotResponse,
    StockAdjustmentListResponse,
    StockAdjustmentRequest,
    StockAdjustmentResponse,
)
from app.service import inventory_lots_service, inventory_service, stock_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/stock-adjustments", tags=["inventory", "stock-adjustment"])
locations_router = APIRouter(prefix="/locations", tags=["inventory", "location"])
lots_router = APIRouter(prefix="/lots", tags=["inventory", "lot"])


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


# ──────────────────────────────────────────────────────────────────────
# Locations — read list + create (TASK-CUT-204 + CUT-206)
#
# Needed by the FE Adjust-Stock dialog: CUT-204 added the read endpoint;
# CUT-206 adds the create endpoint after the wave-3 demo surfaced that a
# fresh-firm user has no FE path to lay down their first warehouse.
# Full Locations admin CRUD (rename, deactivate, multiple types) lands
# in a future admin-panel task.
# ──────────────────────────────────────────────────────────────────────


def _location_to_response(loc: Location) -> LocationResponse:
    return LocationResponse(
        location_id=loc.location_id,
        org_id=loc.org_id,
        firm_id=loc.firm_id,
        code=loc.code,
        name=loc.name,
        location_type=loc.location_type.value,
        is_active=loc.is_active,
    )


@locations_router.get(
    "",
    response_model=LocationListResponse,
    summary="List warehouse locations under the current org",
)
def list_locations(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("inventory.stock.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    include_inactive: Annotated[bool, Query()] = False,
) -> LocationListResponse:
    """List firm locations.

    The FE Adjust-Stock dialog calls this with `firm_id` set to the
    current session's firm. When omitted, returns every Location in the
    org (still RLS-scoped via current_user.org_id).
    """
    rows = inventory_service.list_locations(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        include_inactive=include_inactive,
    )
    return LocationListResponse(
        items=[_location_to_response(r) for r in rows],
        count=len(rows),
    )


@locations_router.post(
    "",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a warehouse location for the current firm",
)
def create_location(
    body: LocationCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("inventory.adjustment.create"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LocationResponse:
    """Create a new active Location for `body.firm_id`.

    The FE AdjustStockDialog opens with this when the firm has zero
    locations, so the user can lay down their first warehouse without
    bouncing to a separate masters page. Permission `inventory.adjustment.create`
    is reused (the same user creating the adjustment is the one creating
    the location); a finer-grained `inventory.location.create` permission
    can be split out later if a non-Owner role needs to manage warehouses
    without adjusting stock.
    """
    loc = inventory_service.create_location(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        code=body.code,
        name=body.name,
        location_type=LocationType(body.location_type),
    )
    return _location_to_response(loc)


# ──────────────────────────────────────────────────────────────────────
# Lots — read endpoints (TASK-TR-B02)
#
# The FE LotDetail screen and the InventoryList lots-count column have
# lived on the mock `frontend/src/lib/mock/inventory.ts` fixture since
# the click-dummy era. This pair of GETs is the BE foundation; lot
# creation already happens inside GRN / Receive-Back so there is no
# POST/PATCH here.
# ──────────────────────────────────────────────────────────────────────


def _lot_to_response(lot: Lot, item: Item, qty_on_hand: object) -> LotResponse:
    from decimal import Decimal

    return LotResponse(
        lot_id=lot.lot_id,
        org_id=lot.org_id,
        firm_id=lot.firm_id,
        item_id=lot.item_id,
        item_code=item.code,
        item_name=item.name,
        primary_uom=str(item.primary_uom.value),
        lot_number=lot.lot_number,
        supplier_lot_number=lot.supplier_lot_number,
        mfg_date=lot.mfg_date,
        expiry_date=lot.expiry_date,
        received_date=lot.received_date,
        primary_cost=Decimal(lot.primary_cost) if lot.primary_cost is not None else None,
        currency=lot.currency,
        grn_id=lot.grn_id,
        qty_on_hand=Decimal(qty_on_hand or 0),  # type: ignore[arg-type]
        created_at=lot.created_at,
        updated_at=lot.updated_at,
    )


@lots_router.get(
    "",
    response_model=LotListResponse,
    summary="List lots (paginated, RLS-scoped to current org)",
)
def list_lots(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("inventory.lot.read"))],
    firm_id: Annotated[uuid.UUID, Query(description="Filter by firm")],
    item_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query(description="Substring match on lot_number")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LotListResponse:
    """List lots for one firm. `firm_id` is required so an org with
    multiple firms doesn't accidentally pull cross-firm lots."""
    rows, total = inventory_lots_service.list_lots(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        item_id=item_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    items = [_lot_to_response(lot, item, qty) for lot, item, qty in rows]
    return LotListResponse(
        items=items,
        limit=limit,
        offset=offset,
        count=len(items),
        total_count=total,
    )


@lots_router.get(
    "/{lot_id}",
    response_model=LotResponse,
    summary="Get a lot by id (with item summary + live qty_on_hand)",
)
def get_lot(
    lot_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("inventory.lot.read"))],
) -> LotResponse:
    """Fetch a single lot. Returns 404 if the lot is missing or belongs
    to a different org (RLS also blocks the query — the explicit
    `org_id` check is a belt-and-braces second line)."""
    lot, item, qty = inventory_lots_service.get_lot(
        db,
        org_id=current_user.org_id,
        lot_id=lot_id,
    )
    return _lot_to_response(lot, item, qty)
