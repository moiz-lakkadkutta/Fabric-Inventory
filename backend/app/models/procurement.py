"""Procurement-domain ORM models — PurchaseOrder, POLine, GRN, GRNLine.

Mirrors `schema/ddl.sql` lines 755-840. PO has a state machine
(`DRAFT → APPROVED/CONFIRMED → PARTIAL_GRN → FULLY_RECEIVED` or `CANCELLED`)
encoded in the `purchase_order_status` Postgres ENUM. Document numbering
is composite: `(series, number)` with `(org_id, firm_id, series, number)`
uniqueness — gapless per FY is enforced at the service layer.

GRN status is a free-form VARCHAR in DDL; we constrain it via
`GRNStatus` StrEnum at the ORM level: `DRAFT → ACKNOWLEDGED → CLOSED`,
plus `RETURNED` and `IN_PROCESS` for variants. The GRN posting flow
(receive_grn) calls `inventory_service.add_stock` to move qty into
position; the PO state machine advances based on cumulative
qty_received vs qty_ordered per po_line.

Purchase Invoice lands in TASK-029.
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .mixins import AuditByMixin, SoftDeleteMixin, TimestampMixin

_UUID_DEFAULT = func.gen_random_uuid()


class PurchaseOrderStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CONFIRMED = "CONFIRMED"
    PARTIAL_GRN = "PARTIAL_GRN"
    FULLY_RECEIVED = "FULLY_RECEIVED"
    CANCELLED = "CANCELLED"


_PO_STATUS_PG = PG_ENUM(
    PurchaseOrderStatus,
    name="purchase_order_status",
    create_type=False,
    native_enum=True,
)


class PurchaseOrder(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A purchase order to a supplier — header row, lines hang off `lines`.

    State transitions live in `procurement_service`; never write directly
    to `status` from outside that module.
    """

    __tablename__ = "purchase_order"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="purchase_order_org_id_firm_id_series_number_key",
        ),
    )

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
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
    po_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    delivery_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[PurchaseOrderStatus | None] = mapped_column(
        _PO_STATUS_PG,
        server_default=text("'DRAFT'::purchase_order_status"),
        nullable=True,
    )
    total_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `purchase_order.created_by` is declared inline in the DDL (with FK).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    lines: Mapped[list[POLine]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class POLine(Base):
    """A single line on a purchase order. Audit-sweep covers `created_at`,
    `updated_at`, `created_by`, `updated_by`, `deleted_at` (the DDL DO
    block runs on po_line); we inherit the mixin set so the ORM knows
    about them.
    """

    __tablename__ = "po_line"

    po_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("purchase_order.purchase_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty_ordered: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    qty_received: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    rate: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    line_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    taxes_applicable: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    line_sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Audit-sweep adds these on po_line; declare for drift parity.
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class GRNStatus(enum.StrEnum):
    """GRN lifecycle. The DDL stores `status` as VARCHAR(50); we constrain
    values at the ORM level. `DRAFT` is the staging step before stock
    posting; `ACKNOWLEDGED` is post-stock-posting (the canonical "GRN
    received" state). `RETURNED` and `IN_PROCESS` are reserved for
    edge flows (return-to-supplier, in-process consumption); not driven
    by MVP service code.
    """

    DRAFT = "DRAFT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROCESS = "IN_PROCESS"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"


class GRN(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A Goods Received Note — header. Each GRN belongs to a firm and
    optionally to a PO (direct stock receipts have NULL purchase_order_id).

    State transitions live in `procurement_service`; never write to
    `status` directly from outside that module.
    """

    __tablename__ = "grn"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="grn_org_id_firm_id_series_number_key",
        ),
    )

    grn_id: Mapped[uuid.UUID] = mapped_column(
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
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("purchase_order.purchase_order_id", ondelete="SET NULL"),
        nullable=True,
    )
    grn_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    # DDL has VARCHAR(50) DEFAULT 'DRAFT'. We constrain to GRNStatus values
    # at the ORM/service level but the column type stays String for parity.
    status: Mapped[str | None] = mapped_column(
        String(50), server_default=text("'DRAFT'"), nullable=True
    )
    total_qty_received: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    total_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `grn.created_by` declared inline in the DDL with FK.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    lines: Mapped[list[GRNLine]] = relationship(back_populates="grn", cascade="all, delete-orphan")


class GRNLine(Base):
    """A single line on a GRN. `po_line_id` is added by TASK-028 migration —
    nullable so direct (no-PO) GRNs work too. Audit-sweep adds the standard
    audit columns; we declare them for drift parity.
    """

    __tablename__ = "grn_line"

    grn_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    grn_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("grn.grn_id", ondelete="CASCADE"),
        nullable=False,
    )
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("po_line.po_line_id", ondelete="SET NULL"),
        nullable=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty_received: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    weight_kg: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    measured_length_m: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rate: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    line_sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Audit-sweep columns (DDL DO block adds these on grn_line).
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    grn: Mapped[GRN] = relationship(back_populates="lines")


# Re-exported for tests / introspection.
_unused_json = JSON


__all__ = [
    "GRN",
    "GRNLine",
    "GRNStatus",
    "POLine",
    "PurchaseOrder",
    "PurchaseOrderStatus",
]
