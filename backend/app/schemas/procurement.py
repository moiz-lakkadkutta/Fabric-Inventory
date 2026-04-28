"""Procurement request/response schemas — PO + POLine (TASK-027), GRN + GRNLine (TASK-028)."""

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


class GRNLineRequest(BaseModel):
    item_id: uuid.UUID
    qty_received: Annotated[Decimal, Field(gt=0)]
    rate: Annotated[Decimal | None, Field(ge=0)] = None
    lot_number: str | None = Field(default=None, max_length=100)
    po_line_id: uuid.UUID | None = None
    line_sequence: int | None = None


class GRNLineResponse(BaseModel):
    grn_line_id: uuid.UUID
    grn_id: uuid.UUID
    item_id: uuid.UUID
    po_line_id: uuid.UUID | None
    qty_received: Decimal
    rate: Decimal | None
    lot_number: str | None
    line_sequence: int | None


class GRNCreateRequest(BaseModel):
    party_id: uuid.UUID
    firm_id: uuid.UUID
    grn_date: datetime.date
    series: str = Field(min_length=1, max_length=50)
    purchase_order_id: uuid.UUID | None = None
    notes: str | None = None
    lines: list[GRNLineRequest] = Field(min_length=1)


class GRNResponse(BaseModel):
    grn_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    party_id: uuid.UUID
    purchase_order_id: uuid.UUID | None
    grn_date: datetime.date
    status: str
    total_qty_received: Decimal | None
    total_amount: Decimal | None
    notes: str | None
    lines: list[GRNLineResponse]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class GRNListResponse(BaseModel):
    items: list[GRNResponse]
    limit: int
    offset: int
    count: int


# ──────────────────────────────────────────────────────────────────────
# Purchase Invoice — TASK-029
# ──────────────────────────────────────────────────────────────────────


class PILineRequest(BaseModel):
    item_id: uuid.UUID
    qty: Annotated[Decimal, Field(gt=0)]
    rate: Annotated[Decimal, Field(ge=0)]
    gst_rate: Annotated[Decimal | None, Field(ge=0, le=100)] = None
    line_sequence: int | None = None


class PILineResponse(BaseModel):
    pi_line_id: uuid.UUID
    purchase_invoice_id: uuid.UUID
    item_id: uuid.UUID
    qty: Decimal | None
    rate: Decimal | None
    line_amount: Decimal | None
    gst_rate: Decimal | None
    gst_amount: Decimal | None
    line_sequence: int | None


class PICreateRequest(BaseModel):
    party_id: uuid.UUID
    firm_id: uuid.UUID
    invoice_date: datetime.date
    series: str = Field(min_length=1, max_length=50)
    grn_id: uuid.UUID | None = None
    rcm_applicable: bool = False
    due_date: datetime.date | None = None
    notes: str | None = None
    lines: list[PILineRequest] = Field(min_length=1)


class PIResponse(BaseModel):
    purchase_invoice_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    party_id: uuid.UUID
    grn_id: uuid.UUID | None
    invoice_date: datetime.date
    invoice_amount: Decimal | None
    gst_amount: Decimal | None
    rcm_applicable: bool | None
    status: str
    lifecycle_status: str
    paid_amount: Decimal
    due_date: datetime.date | None
    notes: str | None
    lines: list[PILineResponse]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class PIListResponse(BaseModel):
    items: list[PIResponse]
    limit: int
    offset: int
    count: int
