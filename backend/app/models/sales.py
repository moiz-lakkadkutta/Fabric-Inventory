"""Sales-domain ORM models — SalesOrder, SOLine.

Mirrors `schema/ddl.sql` lines 1350-1391. SalesOrder has a state machine
(`DRAFT → CONFIRMED → PARTIAL_DC → FULLY_DISPATCHED → INVOICED` or `CANCELLED`)
encoded in the `sales_order_status` Postgres ENUM. Document numbering
is composite: `(series, number)` with `(org_id, firm_id, series, number)`
uniqueness — gapless per FY is enforced at the service layer.

Delivery Challan (TASK-033) and Sales Invoice (TASK-034) will extend this
module rather than duplicate the same imports. PARTIAL_DC / FULLY_DISPATCHED /
INVOICED transitions are reserved for those tasks.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .mixins import AuditByMixin, SoftDeleteMixin, TimestampMixin

_UUID_DEFAULT = func.gen_random_uuid()


class SalesOrderStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PARTIAL_DC = "PARTIAL_DC"
    FULLY_DISPATCHED = "FULLY_DISPATCHED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


_SO_STATUS_PG = PG_ENUM(
    SalesOrderStatus,
    name="sales_order_status",
    create_type=False,
    native_enum=True,
)


class SalesOrder(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A sales order from a customer — header row, lines hang off `lines`.

    State transitions live in `sales_service`; never write directly
    to `status` from outside that module.
    """

    __tablename__ = "sales_order"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="sales_order_org_id_firm_id_series_number_key",
        ),
    )

    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    series: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Optional FK to quotation (Phase-2; quotation table not yet modeled).
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # Optional FK to the salesperson user (ON DELETE SET NULL in DDL).
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    so_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    delivery_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[SalesOrderStatus | None] = mapped_column(
        _SO_STATUS_PG,
        server_default=text("'DRAFT'::sales_order_status"),
        nullable=True,
    )
    total_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `sales_order.created_by` is declared inline in the DDL (with FK).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    lines: Mapped[list[SOLine]] = relationship(
        back_populates="sales_order", cascade="all, delete-orphan"
    )


class SOLine(Base):
    """A single line on a sales order. Audit-sweep covers `updated_at`,
    `created_by`, `updated_by`, `deleted_at` (the DDL DO block runs on
    so_line); we inherit the mixin set so the ORM knows about them.
    """

    __tablename__ = "so_line"

    so_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sales_order.sales_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty_ordered: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    qty_dispatched: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    price: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    line_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    gst_rate: Mapped[Any | None] = mapped_column(Numeric(5, 2), nullable=True)
    sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Audit-sweep adds these on so_line; declare for drift parity.
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sales_order: Mapped[SalesOrder] = relationship(back_populates="lines")


# Re-exported for tests / introspection.
_unused_json = JSON


__all__ = [
    "SOLine",
    "SalesOrder",
    "SalesOrderStatus",
]
