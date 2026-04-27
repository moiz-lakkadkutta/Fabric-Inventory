"""Inventory request / response schemas — StockAdjustment (TASK-023)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

AdjustmentDirection = Literal["INCREASE", "DECREASE", "COUNT_RESET"]


class StockAdjustmentRequest(BaseModel):
    """POST /stock-adjustments body."""

    firm_id: uuid.UUID
    item_id: uuid.UUID
    location_id: uuid.UUID
    lot_id: uuid.UUID | None = None

    # For INCREASE / DECREASE: absolute qty to move (must be > 0).
    # For COUNT_RESET: the desired on-hand qty after adjustment (>= 0).
    qty: Annotated[Decimal, Field(ge=Decimal("0"), description="Quantity (>= 0)")]
    direction: AdjustmentDirection

    reason: str | None = Field(default=None, max_length=255)
    txn_date: datetime.date | None = None

    # Unit cost for inbound stock. Only meaningful for INCREASE /
    # COUNT_RESET→increase paths; ignored for DECREASE.
    unit_cost: Annotated[
        Decimal | None,
        Field(default=None, description="Unit cost for inbound moves (INR). Defaults to 0."),
    ] = None


class StockAdjustmentResponse(BaseModel):
    """Returned for both create and GET-by-id."""

    stock_adjustment_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    item_id: uuid.UUID
    lot_id: uuid.UUID | None
    location_id: uuid.UUID
    qty_change: Decimal
    reason: str | None
    requires_approval: bool | None
    approved_by: uuid.UUID | None
    approved_at: datetime.datetime | None
    created_by: uuid.UUID | None
    created_at: datetime.datetime


class StockAdjustmentListResponse(BaseModel):
    """Paginated list of adjustment headers."""

    items: list[StockAdjustmentResponse]
    count: int
    limit: int
    offset: int
