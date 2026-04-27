"""Banking-domain ORM models — BankAccount and Cheque.

Mirrors `schema/ddl.sql` lines covering `bank_account` and `cheque`.

Both tables went through the DDL audit-sweep which adds `deleted_at`,
`created_by`, `updated_by` to all non-exempt tenant-scoped tables.
The DDL explicitly declares `created_at` and `updated_at` in the CREATE
TABLE; the audit-sweep adds the missing three.  We use `AuditByMixin`
(for `created_by` / `updated_by`) and `SoftDeleteMixin` (for `deleted_at`).
`TimestampMixin` is NOT used — instead `created_at` / `updated_at` are
declared inline here, matching the DDL's explicit column order exactly.

PII: `account_number` is `BYTEA` in the DDL; route through
`app.utils.crypto` helpers (same pattern as Party.gstin/pan/phone).

Postgres ENUMs used here:
- `cheque_status` — declared in DDL; bound with `create_type=False`.
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
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .mixins import AuditByMixin, SoftDeleteMixin

_UUID_DEFAULT = func.gen_random_uuid()


# ──────────────────────────────────────────────────────────────────────
# Postgres enum bindings
# ──────────────────────────────────────────────────────────────────────


class ChequeStatus(enum.StrEnum):
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    BOUNCED = "BOUNCED"
    POST_DATED = "POST_DATED"
    STOPPED = "STOPPED"
    CANCELLED = "CANCELLED"


_CHEQUE_STATUS_PG = PG_ENUM(ChequeStatus, name="cheque_status", create_type=False, native_enum=True)


# ──────────────────────────────────────────────────────────────────────
# BankAccount
# ──────────────────────────────────────────────────────────────────────


class BankAccount(Base, AuditByMixin, SoftDeleteMixin):
    """A firm's bank account linked to a GL ledger.

    `account_number` is `BYTEA` (PII — encrypted via `app.utils.crypto`).
    """

    __tablename__ = "bank_account"

    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    ledger_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ledger.ledger_id", ondelete="RESTRICT"),
        nullable=False,
    )
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_number: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ifsc_code: Mapped[str | None] = mapped_column(String(11), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    balance: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    last_reconciled_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    cheques: Mapped[list[Cheque]] = relationship(
        back_populates="bank_account", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"BankAccount(bank_account_id={self.bank_account_id!r}, bank_name={self.bank_name!r})"
        )


# ──────────────────────────────────────────────────────────────────────
# Cheque
# ──────────────────────────────────────────────────────────────────────


class Cheque(Base, AuditByMixin, SoftDeleteMixin):
    """A cheque issued or received, linked to a bank account and optionally a voucher."""

    __tablename__ = "cheque"
    __table_args__ = (
        UniqueConstraint(
            "firm_id",
            "bank_account_id",
            "cheque_number",
            name="cheque_firm_id_bank_account_id_cheque_number_key",
        ),
    )

    cheque_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bank_account.bank_account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    cheque_number: Mapped[str] = mapped_column(String(20), nullable=False)
    cheque_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    payee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Any | None] = mapped_column(Numeric(15, 2), nullable=True)
    status: Mapped[ChequeStatus | None] = mapped_column(
        _CHEQUE_STATUS_PG, server_default="ISSUED", nullable=True
    )
    clearing_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    bounce_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # voucher.voucher_id FK is DB-level only; the `voucher` table is not yet
    # modeled in the ORM (ships in TASK-055). Declare the column without an ORM
    # FK ref — same pattern as `firm.primary_godown_id` in identity.py.
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    bank_account: Mapped[BankAccount] = relationship(back_populates="cheques")

    def __repr__(self) -> str:
        return (
            f"Cheque(cheque_id={self.cheque_id!r}, "
            f"cheque_number={self.cheque_number!r}, status={self.status!r})"
        )
