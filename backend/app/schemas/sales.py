"""Sales request/response schemas — SalesOrder + SOLine (TASK-032),
DC + DCLine (TASK-033), SalesInvoice + SiLine (T-INT-3 read).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.models.sales import InvoiceLifecycleStatus, SalesOrderStatus
from app.service.gst_service import VALID_GST_SLAB_RATES
from app.utils.gst_states import normalize_state_code


def _validate_state_code(v: str | None) -> str | None:
    """Strip whitespace and validate an Indian GST state code.

    Called by field_validator on every state-code field in sales request
    schemas. Returns the normalised code on success; raises ValueError
    (which Pydantic converts to a 422 ValidationError) on failure.
    """
    if v is None:
        return None
    normalised = normalize_state_code(v)
    if normalised is None:
        raise ValueError(
            f"Invalid Indian GST state code {v!r}. "
            "Must be a 2-character numeric code (e.g. '27') or a valid "
            "2-character alphabetic abbreviation (e.g. 'MH')."
        )
    return normalised


def _validate_gst_rate(v: Decimal | None) -> Decimal | None:
    """Enforce GST rate is a recognised statutory slab rate.

    Accepted: None (non-GST line) or one of {0, 0.25, 3, 5, 12, 18, 28}.
    Raises ValueError for any other value (→ Pydantic 422 ValidationError).

    CA-VALIDATED-PENDING: if the textile trade vertical uses special rates
    (e.g. 1.5%, 7.5% compensation cess), add them to VALID_GST_SLAB_RATES
    in gst_service.py — this validator references that single source of truth.
    """
    if v is None:
        return None
    normalised = Decimal(str(v))
    if normalised not in VALID_GST_SLAB_RATES:
        valid_str = ", ".join(str(r) for r in sorted(VALID_GST_SLAB_RATES))
        raise ValueError(
            f"GST rate {v} is not a recognised statutory slab rate. Valid rates: {valid_str}."
        )
    return normalised


class SOLineRequest(BaseModel):
    """One line in a create-SO request body."""

    item_id: uuid.UUID
    qty_ordered: Annotated[Decimal, Field(gt=0)]
    price: Annotated[Decimal, Field(ge=0)]
    sequence: int | None = None
    gst_rate: Decimal | None = None

    @field_validator("gst_rate", mode="before")
    @classmethod
    def validate_gst_rate(cls, v: object) -> object:
        """GST-2: enforce statutory slab rates on SO lines."""
        if v is None:
            return v
        return _validate_gst_rate(Decimal(str(v)))


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


# ──────────────────────────────────────────────────────────────────────
# Delivery Challan schemas — TASK-033
# ──────────────────────────────────────────────────────────────────────


class DCLineRequest(BaseModel):
    """One line in a create-DC request body."""

    item_id: uuid.UUID
    qty_dispatched: Annotated[Decimal, Field(gt=0)]
    price: Annotated[Decimal | None, Field(ge=0)] = None
    lot_id: uuid.UUID | None = None
    sequence: int | None = None


class DCLineResponse(BaseModel):
    dc_line_id: uuid.UUID
    delivery_challan_id: uuid.UUID
    item_id: uuid.UUID
    lot_id: uuid.UUID | None
    qty_dispatched: Decimal
    price: Decimal | None
    sequence: int | None


class DCCreateRequest(BaseModel):
    party_id: uuid.UUID
    firm_id: uuid.UUID
    dispatch_date: datetime.date
    series: str = Field(min_length=1, max_length=50)
    sales_order_id: uuid.UUID | None = None
    bill_to_address: str | None = None
    ship_to_address: str | None = None
    place_of_supply_state: str | None = Field(default=None, max_length=2)
    lines: list[DCLineRequest] = Field(min_length=1)

    @field_validator("place_of_supply_state", mode="before")
    @classmethod
    def validate_place_of_supply_state(cls, v: object) -> object:
        """GST-5: validate and normalise place_of_supply_state."""
        if v is None:
            return v
        return _validate_state_code(str(v))


class DCResponse(BaseModel):
    delivery_challan_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    sales_order_id: uuid.UUID | None
    party_id: uuid.UUID
    bill_to_address: str | None
    ship_to_address: str | None
    place_of_supply_state: str | None
    dispatch_date: datetime.date
    status: str
    total_qty: Decimal | None
    total_amount: Decimal | None
    lines: list[DCLineResponse]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class DCListResponse(BaseModel):
    items: list[DCResponse]
    limit: int
    offset: int
    count: int


# ──────────────────────────────────────────────────────────────────────
# Sales Invoice schemas — T-INT-3 read endpoints
# ──────────────────────────────────────────────────────────────────────


class SiLineResponse(BaseModel):
    si_line_id: uuid.UUID
    item_id: uuid.UUID
    item_name: str | None = None
    item_uom: str | None = None
    qty: Decimal
    price: Decimal
    line_amount: Decimal | None
    gst_rate: Decimal | None
    gst_amount: Decimal | None
    sequence: int | None


class SalesInvoiceListItem(BaseModel):
    """Trimmed list-page row — no lines, no addresses, no notes. The
    detail endpoint returns the full SalesInvoiceResponse.
    """

    sales_invoice_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    party_id: uuid.UUID
    party_name: str | None = None
    invoice_date: datetime.date
    due_date: datetime.date | None
    invoice_amount: Decimal | None
    # CUT-104 (P1-9): gst_amount on list rows lets the FE compute
    # subtotal = total - gst without fetching each row's detail.
    gst_amount: Decimal | None = None
    paid_amount: Decimal
    lifecycle_status: InvoiceLifecycleStatus
    place_of_supply_state: str | None
    created_at: datetime.datetime


class SalesInvoiceResponse(BaseModel):
    sales_invoice_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    party_id: uuid.UUID
    party_name: str | None = None
    delivery_challan_id: uuid.UUID | None
    salesperson_id: uuid.UUID | None
    invoice_date: datetime.date
    bill_to_address: str | None
    ship_to_address: str | None
    place_of_supply_state: str | None
    invoice_type: str | None
    invoice_amount: Decimal | None
    gst_amount: Decimal | None
    paid_amount: Decimal
    due_date: datetime.date | None
    lifecycle_status: InvoiceLifecycleStatus
    finalized_at: datetime.datetime | None
    tax_type: str | None
    round_off: Decimal
    notes: str | None
    lines: list[SiLineResponse]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SalesInvoiceListResponse(BaseModel):
    items: list[SalesInvoiceListItem]
    limit: int
    offset: int
    count: int


class SiLineCreateRequest(BaseModel):
    item_id: uuid.UUID
    # BL-02: upper bound prevents values that would overflow NUMERIC(15,4)
    # from reaching the DB (→ 422 instead of 500). 1e9 (₹1 billion) is a
    # generous sane ceiling well within the column's 11-digit integer range.
    qty: Annotated[Decimal, Field(gt=0, le=Decimal("1e9"))]
    price: Annotated[Decimal, Field(ge=0, le=Decimal("1e9"))]
    gst_rate: Decimal | None = None
    sequence: int | None = None

    @field_validator("gst_rate", mode="before")
    @classmethod
    def validate_gst_rate(cls, v: object) -> object:
        """GST-2: enforce statutory slab rates on SI lines."""
        if v is None:
            return v
        return _validate_gst_rate(Decimal(str(v)))


class SalesInvoiceCreateRequest(BaseModel):
    """Body for POST /v1/invoices. Money values are rupees on the wire
    (per CLAUDE.md). Frontend converts paise → rupees before submitting.
    """

    firm_id: uuid.UUID
    party_id: uuid.UUID
    invoice_date: datetime.date
    due_date: datetime.date | None = None
    series: str = Field(default="RT/2526", min_length=1, max_length=50)
    ship_to_state: str | None = Field(default=None, max_length=2)
    bill_to_address: str | None = None
    ship_to_address: str | None = None
    notes: str | None = None
    lines: list[SiLineCreateRequest] = Field(min_length=1)

    @field_validator("ship_to_state", mode="before")
    @classmethod
    def validate_ship_to_state(cls, v: object) -> object:
        """GST-1/GST-5: validate and normalise ship_to_state."""
        if v is None:
            return v
        return _validate_state_code(str(v))
