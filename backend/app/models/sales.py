"""Sales-domain ORM models — SalesOrder, SOLine, DeliveryChallan, DCLine,
SalesInvoice, SiLine.

Mirrors `schema/ddl.sql` lines 1350-1433 (SO/DC) + 1435-1482 (SI).

SalesOrder state machine:
  DRAFT → CONFIRMED → PARTIAL_DC → FULLY_DISPATCHED → INVOICED | CANCELLED

DeliveryChallan state machine (TASK-033):
  DRAFT → ISSUED → ACKNOWLEDGED → IN_PROCESS → RETURNED | CLOSED

SalesInvoice lifecycle (T-INT-3 read; T-INT-4 create + finalize):
  DRAFT → CONFIRMED → FINALIZED → POSTED →
  PARTIALLY_PAID → PAID, OVERDUE, CANCELLED, DISCARDED

The `challan_status` Postgres enum in DDL is a free-form VARCHAR(50) in the
delivery_challan table; we constrain it via `DCStatus` StrEnum at the ORM
level (same pattern as GRNStatus).
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


class DCStatus(enum.StrEnum):
    """Delivery Challan lifecycle. DDL stores `status` as VARCHAR(50); we
    constrain values at the ORM level. DRAFT is before stock posting; ISSUED
    is post-stock-posting (the canonical 'dispatched' state). ACKNOWLEDGED
    means the customer signed off. IN_PROCESS, RETURNED, CLOSED are reserved
    for future edge flows (partial returns, job-work acknowledgement, etc.).
    """

    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROCESS = "IN_PROCESS"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"


class DeliveryChallan(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A Delivery Challan — header. Each DC belongs to a firm and optionally
    to a Sales Order (direct dispatches have NULL sales_order_id).

    State transitions live in `sales_service`; never write to `status`
    directly from outside that module. Stock is removed (outbound) on
    `issue_dc` (DRAFT → ISSUED).
    """

    __tablename__ = "delivery_challan"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="delivery_challan_org_id_firm_id_series_number_key",
        ),
    )

    delivery_challan_id: Mapped[uuid.UUID] = mapped_column(
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
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sales_order.sales_order_id", ondelete="SET NULL"),
        nullable=True,
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="RESTRICT"),
        nullable=False,
    )
    bill_to_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    ship_to_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    place_of_supply_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    dispatch_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    # DDL has VARCHAR(50) DEFAULT 'DRAFT'. Constrained to DCStatus values.
    status: Mapped[str | None] = mapped_column(
        String(50), server_default=text("'DRAFT'"), nullable=True
    )
    total_qty: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    total_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    # `delivery_challan.created_by` declared inline in DDL with FK.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    lines: Mapped[list[DCLine]] = relationship(
        back_populates="delivery_challan", cascade="all, delete-orphan"
    )


class DCLine(Base):
    """A single line on a Delivery Challan. Audit-sweep adds the standard
    audit columns on dc_line; we declare them for drift parity.
    """

    __tablename__ = "dc_line"

    dc_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    delivery_challan_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("delivery_challan.delivery_challan_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lot.lot_id", ondelete="SET NULL"),
        nullable=True,
    )
    qty_dispatched: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    price: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Audit-sweep columns (DDL DO block adds these on dc_line).
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    delivery_challan: Mapped[DeliveryChallan] = relationship(back_populates="lines")


# Re-exported for tests / introspection.
_unused_json = JSON


# ──────────────────────────────────────────────────────────────────────
# Sales Invoice — DDL `sales_invoice` + ALTER-extensions in lines 2138-2152.
# ──────────────────────────────────────────────────────────────────────


class VoucherStatus(enum.StrEnum):
    """Basic voucher status (DRAFT/POSTED/RECONCILED/VOIDED). Mirrors
    procurement.py's identically-named enum — same Postgres `voucher_status`
    type. We declare a parallel StrEnum here so callers don't have to
    import across domains.
    """

    DRAFT = "DRAFT"
    POSTED = "POSTED"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"


class InvoiceLifecycleStatus(enum.StrEnum):
    """Richer per-document lifecycle for sales invoices, layered on top
    of the basic `voucher_status` (which the DDL keeps as a parallel
    column for backwards compatibility). Bound to the
    `invoice_lifecycle_status` Postgres enum (DDL line 2020).
    """

    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    FINALIZED = "FINALIZED"
    POSTED = "POSTED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"
    DISCARDED = "DISCARDED"


_SALES_VOUCHER_STATUS_PG = PG_ENUM(
    VoucherStatus, name="voucher_status", create_type=False, native_enum=True
)
_SI_LIFECYCLE_STATUS_PG = PG_ENUM(
    InvoiceLifecycleStatus,
    name="invoice_lifecycle_status",
    create_type=False,
    native_enum=True,
)


class SalesInvoice(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """Customer invoice header. Lines hang off `lines`. State transitions
    live in `sales_service`; never write directly to `lifecycle_status`
    from outside that module.
    """

    __tablename__ = "sales_invoice"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="sales_invoice_org_id_firm_id_series_number_key",
        ),
    )

    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(
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
    delivery_challan_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("delivery_challan.delivery_challan_id", ondelete="SET NULL"),
        nullable=True,
    )
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    invoice_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    bill_to_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    ship_to_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    place_of_supply_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    invoice_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    gst_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    status: Mapped[VoucherStatus | None] = mapped_column(
        _SALES_VOUCHER_STATUS_PG,
        server_default=text("'DRAFT'::voucher_status"),
        nullable=True,
    )
    irn_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    eway_bill_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifecycle extensions (DDL ALTER lines 2138-2152).
    lifecycle_status: Mapped[InvoiceLifecycleStatus] = mapped_column(
        _SI_LIFECYCLE_STATUS_PG,
        server_default=text("'DRAFT'::invoice_lifecycle_status"),
        nullable=False,
    )
    finalized_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_amount: Mapped[Any] = mapped_column(
        Numeric(18, 2), server_default=text("0"), nullable=False
    )
    due_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    irn_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    irn_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    eway_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    revises_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sales_invoice.sales_invoice_id", ondelete="SET NULL"),
        nullable=True,
    )
    linked_mo_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("manufacturing_order.manufacturing_order_id", ondelete="SET NULL"),
        nullable=True,
    )
    cost_centre_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cost_centre.cost_centre_id", ondelete="SET NULL"),
        nullable=True,
    )
    tax_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    round_off: Mapped[Any] = mapped_column(Numeric(6, 2), server_default=text("0"), nullable=False)
    dispatched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    lines: Mapped[list[SiLine]] = relationship(
        back_populates="sales_invoice", cascade="all, delete-orphan"
    )


class SiLine(Base):
    """One sales-invoice line. Audit-sweep adds the standard columns;
    declared here for drift parity (matches PILine's pattern).
    """

    __tablename__ = "si_line"

    si_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sales_invoice.sales_invoice_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    price: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    line_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    gst_rate: Mapped[Any | None] = mapped_column(Numeric(5, 2), nullable=True)
    gst_amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Audit-sweep columns (DDL DO block adds these on si_line).
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sales_invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")


__all__ = [
    "DCLine",
    "DCStatus",
    "DeliveryChallan",
    "InvoiceLifecycleStatus",
    "SOLine",
    "SalesInvoice",
    "SalesOrder",
    "SalesOrderStatus",
    "SiLine",
    "VoucherStatus",
]
