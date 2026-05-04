"""Accounting-domain ORM models — Voucher + VoucherLine.

Mirrors `schema/ddl.sql` lines 1568-1613 + the `voucher_type` and
`journal_line_type` Postgres enums (lines 32 + 34).

Voucher is the GL header; VoucherLine carries the DR/CR splits. The
DDL exempts `voucher_line` from the audit-sweep (it's an append-only
ledger table — no updated_at, no deleted_at).

Service layer (`accounting_service`) is the only writer. Never insert
voucher rows directly from a router — vouchers must always be created
as part of a balanced (DR == CR) bundle so the trial balance holds.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
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
from .mixins import SoftDeleteMixin

_UUID_DEFAULT = func.gen_random_uuid()


class VoucherType(enum.StrEnum):
    SALES_INVOICE = "SALES_INVOICE"
    PURCHASE_INVOICE = "PURCHASE_INVOICE"
    PAYMENT = "PAYMENT"
    RECEIPT = "RECEIPT"
    JOURNAL = "JOURNAL"
    CONTRA = "CONTRA"
    DEBIT_NOTE = "DEBIT_NOTE"
    CREDIT_NOTE = "CREDIT_NOTE"
    OPENING_BAL = "OPENING_BAL"


class JournalLineType(enum.StrEnum):
    DR = "DR"
    CR = "CR"


class VoucherStatus(enum.StrEnum):
    """Re-declares the `voucher_status` enum binding for accounting.

    Same Postgres type as `procurement.VoucherStatus` and
    `sales.VoucherStatus`; declared here to avoid cross-domain import.
    """

    DRAFT = "DRAFT"
    POSTED = "POSTED"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"


_VOUCHER_TYPE_PG = PG_ENUM(VoucherType, name="voucher_type", create_type=False, native_enum=True)
_JOURNAL_LINE_TYPE_PG = PG_ENUM(
    JournalLineType, name="journal_line_type", create_type=False, native_enum=True
)
_VOUCHER_STATUS_PG = PG_ENUM(
    VoucherStatus, name="voucher_status", create_type=False, native_enum=True
)


class Voucher(Base, SoftDeleteMixin):
    """GL voucher header. Lines hang off `lines`. Status defaults to
    DRAFT in DDL; service layer flips to POSTED once the voucher is
    durably persisted (writes are append-only after that).
    """

    __tablename__ = "voucher"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="voucher_org_id_firm_id_series_number_key",
        ),
    )

    voucher_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    voucher_type: Mapped[VoucherType] = mapped_column(_VOUCHER_TYPE_PG, nullable=False)
    series: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    voucher_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[VoucherStatus | None] = mapped_column(
        _VOUCHER_STATUS_PG,
        server_default=text("'DRAFT'::voucher_status"),
        nullable=True,
    )
    cost_centre_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cost_centre.cost_centre_id", ondelete="SET NULL"),
        nullable=True,
    )
    total_debit: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    total_credit: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    # Audit-sweep adds updated_by on `voucher` (not in the exempt list);
    # no inline FK on this column in DDL, so plain UUID is faithful.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    lines: Mapped[list[VoucherLine]] = relationship(
        back_populates="voucher", cascade="all, delete-orphan"
    )


class VoucherLine(Base):
    """One DR or CR split line. DDL exempts `voucher_line` from the
    audit-sweep — append-only ledger, no updated_at, no deleted_at.
    """

    __tablename__ = "voucher_line"

    voucher_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    voucher_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("voucher.voucher_id", ondelete="CASCADE"),
        nullable=False,
    )
    ledger_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ledger.ledger_id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_type: Mapped[JournalLineType] = mapped_column(_JOURNAL_LINE_TYPE_PG, nullable=False)
    amount: Mapped[Any] = mapped_column(Numeric(15, 2), nullable=False)
    cost_centre_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cost_centre.cost_centre_id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    voucher: Mapped[Voucher] = relationship(back_populates="lines")


__all__ = [
    "JournalLineType",
    "Voucher",
    "VoucherLine",
    "VoucherStatus",
    "VoucherType",
]
