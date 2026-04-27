"""Procurement request/response schemas — PurchaseOrder + POLine (TASK-027)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.models.procurement import PurchaseOrderStatus


class POLineRequest(BaseModel):
    """One line in a create-PO request body."""

    item_id: uuid.UUID
    qty_ordered: Annotated[Decimal, Field(gt=0)]
    rate: Annotated[Decimal, Field(ge=0)]
    line_sequence: int | None = None
    notes: str | None = None
    taxes_applicable: dict[str, Any] | None = None


class POLineResponse(BaseModel):
    po_line_id: uuid.UUID
    item_id: uuid.UUID
    qty_ordered: Decimal
    qty_received: Decimal | None
    rate: Decimal
    line_amount: Decimal | None
    line_sequence: int | None
    taxes_applicable: dict[str, Any] | None
    notes: str | None


class POCreateRequest(BaseModel):
    party_id: uuid.UUID
    firm_id: uuid.UUID
    po_date: datetime.date
    delivery_date: datetime.date | None = None
    series: str = Field(min_length=1, max_length=50)
    notes: str | None = None
    lines: list[POLineRequest] = Field(min_length=1)


class POResponse(BaseModel):
    purchase_order_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    party_id: uuid.UUID
    po_date: datetime.date
    delivery_date: datetime.date | None
    status: PurchaseOrderStatus
    total_amount: Decimal | None
    notes: str | None
    lines: list[POLineResponse]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class POListResponse(BaseModel):
    items: list[POResponse]
    limit: int
    offset: int
    count: int
