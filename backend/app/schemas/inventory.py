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
        Field(
            default=None,
            ge=Decimal("0"),
            description="Unit cost for inbound moves (INR). Must be >= 0.",
        ),
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


# ──────────────────────────────────────────────────────────────────────
# Location read endpoint (TASK-CUT-204) — needed so the FE adjust-stock
# dialog can pick a destination warehouse. Read-only; CRUD lands in a
# future admin-panel task.
# ──────────────────────────────────────────────────────────────────────


LocationTypeLiteral = Literal[
    "WAREHOUSE", "GODOWN", "SHELF", "BIN", "IN_TRANSIT", "STAGING", "SCRAP"
]


class LocationResponse(BaseModel):
    """One Location row in the firm's warehouse catalog."""

    location_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    code: str
    name: str
    location_type: LocationTypeLiteral
    is_active: bool | None


class LocationListResponse(BaseModel):
    """List of Location rows under the current org / optional firm."""

    items: list[LocationResponse]
    count: int


class LocationCreateRequest(BaseModel):
    """POST /locations body — used by the FE AdjustStockDialog empty-state
    so a fresh-firm user can create their first warehouse without a
    separate masters page (CUT-206)."""

    firm_id: uuid.UUID
    code: Annotated[str, Field(min_length=1, max_length=32)]
    name: Annotated[str, Field(min_length=1, max_length=128)]
    location_type: LocationTypeLiteral = "WAREHOUSE"


# ──────────────────────────────────────────────────────────────────────
# Lots read endpoints (TASK-TR-B02). Read-only — lots are minted by GRN
# / Receive-Back flows. The FE LotDetail screen reads the singular get;
# the InventoryList page reads the list to show per-SKU lot counts.
# ──────────────────────────────────────────────────────────────────────


class LotResponse(BaseModel):
    """One Lot row with the eager-loaded item summary the FE needs.

    `qty_on_hand` is the live aggregate across all `stock_position` rows
    for this lot (sum over locations). It can be 0 for lots that have
    fully dispatched.
    """

    lot_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    item_id: uuid.UUID
    item_code: str
    item_name: str
    primary_uom: str
    lot_number: str
    supplier_lot_number: str | None
    mfg_date: datetime.date | None
    expiry_date: datetime.date | None
    received_date: datetime.date | None
    primary_cost: Decimal | None
    currency: str | None
    grn_id: uuid.UUID | None
    qty_on_hand: Decimal
    created_at: datetime.datetime
    updated_at: datetime.datetime


class LotListResponse(BaseModel):
    """Paginated list of lots — mirrors the BomListResponse shape."""

    items: list[LotResponse]
    limit: int
    offset: int
    count: int  # rows in this page
    total_count: int  # total matching rows across all pages
