"""Receipt request / response schemas — T-INT-5."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ReceiptCreateRequest(BaseModel):
    """POST /v1/receipts body. Money is rupees (Decimal-as-string) on
    the wire per CLAUDE.md.
    """

    party_id: uuid.UUID
    amount: Annotated[Decimal, Field(gt=0)]
    receipt_date: datetime.date
    mode: Literal["CASH", "BANK"] = "CASH"
    reference: str | None = Field(default=None, max_length=255)
    series: str = Field(default="RCT/2526", min_length=1, max_length=50)


class ReceiptAllocationItem(BaseModel):
    sales_invoice_id: uuid.UUID
    amount: Decimal


class ReceiptResponse(BaseModel):
    voucher_id: uuid.UUID
    series: str
    number: str
    voucher_date: datetime.date
    amount: Decimal
    party_id: uuid.UUID | None = None
    mode: str | None = None
    allocations: list[ReceiptAllocationItem] = Field(default_factory=list)
    unallocated: Decimal = Decimal("0")
    narration: str | None
    created_at: datetime.datetime


class ReceiptListItem(BaseModel):
    voucher_id: uuid.UUID
    series: str
    number: str
    voucher_date: datetime.date
    amount: Decimal
    narration: str | None
    created_at: datetime.datetime


class ReceiptListResponse(BaseModel):
    items: list[ReceiptListItem]
    limit: int
    offset: int
    count: int
