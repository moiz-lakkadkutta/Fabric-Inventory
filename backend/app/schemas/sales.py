"""Sales request/response schemas — SalesOrder + SOLine (TASK-032)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from app.models.sales import SalesOrderStatus


class SOLineRequest(BaseModel):
    """One line in a create-SO request body."""

    item_id: uuid.UUID
    qty_ordered: Annotated[Decimal, Field(gt=0)]
    price: Annotated[Decimal, Field(ge=0)]
    sequence: int | None = None
    gst_rate: Decimal | None = None


class SOLineResponse(BaseModel):
    so_line_id: uuid.UUID
    item_id: uuid.UUID
    qty_ordered: Decimal
    qty_dispatched: Decimal | None
    price: Decimal
    line_amount: Decimal | None
    gst_rate: Decimal | None
    sequence: int | None


class SOCreateRequest(BaseModel):
    party_id: uuid.UUID
    firm_id: uuid.UUID
    so_date: datetime.date
    delivery_date: datetime.date | None = None
    series: str = Field(min_length=1, max_length=50)
    notes: str | None = None
    lines: list[SOLineRequest] = Field(min_length=1)


class SOResponse(BaseModel):
    sales_order_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    party_id: uuid.UUID
    so_date: datetime.date
    delivery_date: datetime.date | None
    status: SalesOrderStatus
    total_amount: Decimal | None
    notes: str | None
    lines: list[SOLineResponse]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SOListResponse(BaseModel):
    items: list[SOResponse]
    limit: int
    offset: int
    count: int
