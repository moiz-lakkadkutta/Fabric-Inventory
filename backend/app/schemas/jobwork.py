"""Job-work request / response schemas (TASK-CUT-305 Half B).

Shapes the HTTP boundary for the four endpoints:

  - POST /job-work-orders               → JobWorkOrderResponse
  - POST /job-work-orders/{id}/receive  → JobWorkReceiptResponse
  - GET  /job-work-orders               → JobWorkOrderListResponse
  - GET  /job-work-orders/{id}          → JobWorkOrderResponse (with lines + receipts)
  - GET  /reports/itc04?period=         → ITC04Report

Money is not present in JWO at this layer — job-work send-outs are a
stock move, not a money move. Wastage is recorded as qty, not value;
the cost basis is carried implicitly by the inventory weighted-avg
when the goods return to MAIN inventory.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ──────────────────────────────────────────────────────────────────────
# Create send-out
# ──────────────────────────────────────────────────────────────────────


JobWorkOrderStatusLiteral = Literal["DRAFT", "SENT", "PARTIAL_RECEIVED", "CLOSED", "CANCELLED"]
JobWorkReceiptStatusLiteral = Literal["POSTED", "VOID"]


class JobWorkOrderLineRequest(BaseModel):
    """One line of a new JWO."""

    item_id: uuid.UUID
    lot_id: uuid.UUID | None = None
    qty_sent: Annotated[Decimal, Field(gt=Decimal("0"))]
    uom: Annotated[str, Field(min_length=1, max_length=20)]
    notes: str | None = Field(default=None, max_length=512)


class JobWorkOrderCreateRequest(BaseModel):
    """POST /job-work-orders body."""

    firm_id: uuid.UUID
    karigar_party_id: uuid.UUID
    challan_date: datetime.date
    operation: str | None = Field(default=None, max_length=100)
    expected_return_date: datetime.date | None = None
    notes: str | None = Field(default=None, max_length=1024)

    # Series defaults to JW/<FY> in the service when omitted.
    series: str | None = Field(default=None, max_length=50)

    # Lines: at least one. UI sends the array; service assigns line_no.
    lines: Annotated[list[JobWorkOrderLineRequest], Field(min_length=1)]


# ──────────────────────────────────────────────────────────────────────
# Receive back
# ──────────────────────────────────────────────────────────────────────


class JobWorkReceiptLineRequest(BaseModel):
    """One line of a receive-back. ``job_work_order_line_id`` MUST belong
    to the parent JWO; the service validates this and rejects with 422
    on mismatch.

    Either ``qty_received`` OR ``qty_wastage`` (or both) MUST be > 0 so
    the receipt isn't a no-op.
    """

    job_work_order_line_id: uuid.UUID
    qty_received: Annotated[Decimal, Field(ge=Decimal("0"))] = Decimal("0")
    qty_wastage: Annotated[Decimal, Field(ge=Decimal("0"))] = Decimal("0")
    notes: str | None = Field(default=None, max_length=512)


class JobWorkReceiveRequest(BaseModel):
    """POST /job-work-orders/{id}/receive body."""

    receipt_date: datetime.date
    notes: str | None = Field(default=None, max_length=1024)
    lines: Annotated[list[JobWorkReceiptLineRequest], Field(min_length=1)]


# ──────────────────────────────────────────────────────────────────────
# Response shapes
# ──────────────────────────────────────────────────────────────────────


class JobWorkOrderLineResponse(BaseModel):
    """One line on a JWO header response."""

    model_config = ConfigDict(from_attributes=True)

    job_work_order_line_id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    lot_id: uuid.UUID | None
    qty_sent: Decimal
    qty_received: Decimal
    qty_wastage: Decimal
    uom: str
    notes: str | None


class JobWorkOrderResponse(BaseModel):
    """One JWO on a list or detail response.

    Lines are populated on GET-by-id; on the list response, lines is an
    empty list (saves a join on the hot path). The FE list page only
    needs the header fields anyway.
    """

    model_config = ConfigDict(from_attributes=True)

    job_work_order_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    karigar_party_id: uuid.UUID
    series: str
    number: str
    challan_date: datetime.date
    status: JobWorkOrderStatusLiteral
    operation: str | None
    expected_return_date: datetime.date | None
    notes: str | None
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
    lines: list[JobWorkOrderLineResponse] = Field(default_factory=list)


class JobWorkOrderListResponse(BaseModel):
    """Paginated list of JWO headers."""

    items: list[JobWorkOrderResponse]
    count: int
    limit: int
    offset: int


class JobWorkReceiptLineResponse(BaseModel):
    """One line on a receipt response."""

    model_config = ConfigDict(from_attributes=True)

    job_work_receipt_line_id: uuid.UUID
    line_no: int
    job_work_order_line_id: uuid.UUID
    item_id: uuid.UUID
    qty_received: Decimal
    qty_wastage: Decimal
    uom: str
    notes: str | None


class JobWorkReceiptResponse(BaseModel):
    """One receipt header. Returned by POST /receive and the future GET."""

    model_config = ConfigDict(from_attributes=True)

    job_work_receipt_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    job_work_order_id: uuid.UUID
    receipt_date: datetime.date
    status: JobWorkReceiptStatusLiteral
    notes: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    lines: list[JobWorkReceiptLineResponse] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# ITC-04 report
# ──────────────────────────────────────────────────────────────────────


class ITC04SendOutRow(BaseModel):
    """One send-out challan row in the ITC-04 export.

    Field selection mirrors the official ITC-04 quarterly form (Table 4):
    challan number/date, GSTIN + name of karigar, item description,
    HSN, qty, uom, taxable value (zero for v1 — job-work is not invoiced
    at the send-out step in textile trade), nature of job.
    """

    job_work_order_id: uuid.UUID
    challan_no: str  # e.g. JW/2025-26/0001
    challan_date: datetime.date
    karigar_party_id: uuid.UUID
    karigar_name: str
    karigar_gstin: str | None
    item_id: uuid.UUID
    item_name: str
    hsn: str | None
    qty_sent: Decimal
    uom: str
    nature_of_job: str | None  # JWO.operation


class ITC04ReceiveRow(BaseModel):
    """One receive-back challan row in the ITC-04 export (Table 5A/5B).

    ``original_challan_no`` points back to the send-out so the GST portal
    can cross-reference. Wastage is broken out for compliance — ITC-04
    Table 5B (job-worker's premises) reports wastage separately from
    received qty.
    """

    job_work_receipt_id: uuid.UUID
    receipt_date: datetime.date
    original_challan_no: str
    original_challan_date: datetime.date
    karigar_party_id: uuid.UUID
    karigar_name: str
    karigar_gstin: str | None
    item_id: uuid.UUID
    item_name: str
    hsn: str | None
    qty_received: Decimal
    qty_wastage: Decimal
    uom: str


class ITC04Report(BaseModel):
    """ITC-04 data envelope.

    ``period`` echoes the user's request. ``YYYY-MM`` → monthly cut;
    ``YYYY-QN`` (Q1=Apr-Jun) → quarterly cut. Quarterly is just a
    sum/concat of three months — same row shape, wider window.
    """

    period: str
    firm_id: uuid.UUID
    from_date: datetime.date
    to_date: datetime.date
    send_outs: list[ITC04SendOutRow] = Field(default_factory=list)
    receipts: list[ITC04ReceiveRow] = Field(default_factory=list)
    # Convenience counters for the FE summary card.
    total_send_outs: int = 0
    total_receipts: int = 0


__all__ = [
    "ITC04ReceiveRow",
    "ITC04Report",
    "ITC04SendOutRow",
    "JobWorkOrderCreateRequest",
    "JobWorkOrderLineRequest",
    "JobWorkOrderLineResponse",
    "JobWorkOrderListResponse",
    "JobWorkOrderResponse",
    "JobWorkOrderStatusLiteral",
    "JobWorkReceiptLineRequest",
    "JobWorkReceiptLineResponse",
    "JobWorkReceiptResponse",
    "JobWorkReceiptStatusLiteral",
    "JobWorkReceiveRequest",
]
