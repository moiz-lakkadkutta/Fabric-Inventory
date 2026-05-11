"""Job-work ORM models (TASK-CUT-305 Half B).

Four tables, mirroring the Alembic migration ``task_cut_305_jobwork``:

  - ``JobWorkOrder``         — header row for a send-out challan.
  - ``JobWorkOrderLine``     — one item line on the JWO.
  - ``JobWorkReceipt``       — header row for a receive-back.
  - ``JobWorkReceiptLine``   — one item line on the receipt.

State machine on the JWO:

    DRAFT ─→ SENT ─→ PARTIAL_RECEIVED ─→ CLOSED
                                              │
                       └──── (open send-out, all lines fully accounted)
            └─→ CANCELLED  (allowed from SENT iff zero receipts posted)

PARTIAL_RECEIVED is a denormalised marker — the service flips it when the
first ``job_work_receipt`` lands, and CLOSED when ``sum(qty_received +
qty_wastage) == qty_sent`` across all lines.

Receipts are POSTED on insert; VOID is reserved for the Wave-5 reversal
flow (the cutover-plan's CUT-401 may or may not surface a UI for it).
The service does not implement VOID in this task; the column exists so
the future migration can land without ORM drift.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

from sqlalchemy import (
    Date,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .mixins import SoftDeleteMixin, TimestampMixin

_UUID_DEFAULT = func.gen_random_uuid()


class JobWorkOrderStatus(enum.StrEnum):
    """JWO header lifecycle. See module docstring for the state-machine."""

    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIAL_RECEIVED = "PARTIAL_RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class JobWorkReceiptStatus(enum.StrEnum):
    """JW receipt lifecycle. Only POSTED is used in v1; VOID is reserved."""

    POSTED = "POSTED"
    VOID = "VOID"


_JWO_STATUS_PG = PG_ENUM(
    JobWorkOrderStatus, name="job_work_order_status", create_type=False, native_enum=True
)
_JWR_STATUS_PG = PG_ENUM(
    JobWorkReceiptStatus,
    name="job_work_receipt_status",
    create_type=False,
    native_enum=True,
)


class JobWorkOrder(Base, TimestampMixin, SoftDeleteMixin):
    """Send-out challan header. One row per "we shipped X to karigar Y on date Z"."""

    __tablename__ = "job_work_order"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="job_work_order_org_firm_series_number_key",
        ),
    )

    job_work_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    karigar_party_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="RESTRICT"),
        nullable=False,
    )
    series: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    challan_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    status: Mapped[JobWorkOrderStatus] = mapped_column(
        _JWO_STATUS_PG,
        nullable=False,
        server_default=text("'SENT'::job_work_order_status"),
    )
    operation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_return_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    from_location_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("location.location_id", ondelete="RESTRICT"),
        nullable=False,
    )
    to_location_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("location.location_id", ondelete="RESTRICT"),
        nullable=False,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )


class JobWorkOrderLine(Base, TimestampMixin, SoftDeleteMixin):
    """One item line on a JWO. Carries running tally of receipts + wastage."""

    __tablename__ = "job_work_order_line"
    __table_args__ = (
        UniqueConstraint(
            "job_work_order_id",
            "line_no",
            name="job_work_order_line_order_lineno_key",
        ),
    )

    job_work_order_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_work_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("job_work_order.job_work_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lot.lot_id", ondelete="RESTRICT"),
        nullable=True,
    )
    qty_sent: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    uom: Mapped[str] = mapped_column(String(20), nullable=False)
    qty_received: Mapped[Any] = mapped_column(
        Numeric(15, 4), nullable=False, server_default=text("0")
    )
    qty_wastage: Mapped[Any] = mapped_column(
        Numeric(15, 4), nullable=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobWorkReceipt(Base, TimestampMixin, SoftDeleteMixin):
    """Receive-back header. One row per "karigar returned goods on date D against JWO X"."""

    __tablename__ = "job_work_receipt"

    job_work_receipt_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_work_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("job_work_order.job_work_order_id", ondelete="RESTRICT"),
        nullable=False,
    )
    receipt_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    status: Mapped[JobWorkReceiptStatus] = mapped_column(
        _JWR_STATUS_PG,
        nullable=False,
        server_default=text("'POSTED'::job_work_receipt_status"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )


class JobWorkReceiptLine(Base, TimestampMixin, SoftDeleteMixin):
    """One item line on a JW receipt. Carries finished + wastage qty.

    ``qty_received`` is the qty that came back AS goods (will move back to
    MAIN inventory). ``qty_wastage`` is the qty consumed in processing
    (lost / scrapped at karigar). Their sum cannot exceed the JWO line's
    open quantity — the service enforces this invariant.
    """

    __tablename__ = "job_work_receipt_line"
    __table_args__ = (
        UniqueConstraint(
            "job_work_receipt_id",
            "line_no",
            name="job_work_receipt_line_receipt_lineno_key",
        ),
    )

    job_work_receipt_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_work_receipt_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("job_work_receipt.job_work_receipt_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_work_order_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("job_work_order_line.job_work_order_line_id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty_received: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    qty_wastage: Mapped[Any] = mapped_column(
        Numeric(15, 4), nullable=False, server_default=text("0")
    )
    uom: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "JobWorkOrder",
    "JobWorkOrderLine",
    "JobWorkOrderStatus",
    "JobWorkReceipt",
    "JobWorkReceiptLine",
    "JobWorkReceiptStatus",
]
