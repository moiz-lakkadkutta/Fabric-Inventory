"""Inventory-domain ORM models — Lot, Location, StockLedger, StockPosition.

Mirrors `schema/ddl.sql` lines 575-674. The stock_ledger is append-only
by design (every movement is INSERT, never UPDATE/DELETE); stock_position
is the materialized current-state view kept in sync by the service
layer. The DDL declares `stock_position.atp_qty` as a STORED generated
column (`on_hand_qty - reserved_qty_mo - reserved_qty_so - in_transit_qty`)
— we mirror that with a server-side computed column declaration so
SELECTs see the live value.

Audit-sweep exempt: lot, location, stock_ledger, stock_position. The
ledger has its own `created_at` + hash-chain columns; positions are
mutated on every move so a `deleted_at` would be misleading.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
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
from .mixins import AuditByMixin, SoftDeleteMixin, TimestampMixin

_UUID_DEFAULT = func.gen_random_uuid()


# ──────────────────────────────────────────────────────────────────────
# Enum
# ──────────────────────────────────────────────────────────────────────


class LocationType(enum.StrEnum):
    WAREHOUSE = "WAREHOUSE"
    GODOWN = "GODOWN"
    SHELF = "SHELF"
    BIN = "BIN"
    IN_TRANSIT = "IN_TRANSIT"
    STAGING = "STAGING"
    SCRAP = "SCRAP"


class StockStage(enum.StrEnum):
    """Phase-3 manufacturing-stage enum, in DDL since TASK-004 baseline.

    The columns on `stock_ledger` (`from_stage`, `to_stage`) are nullable
    and unused in MVP but declared on the ORM for drift-gate parity.
    """

    RAW = "RAW"
    CUT = "CUT"
    AT_DYEING = "AT_DYEING"
    AT_PRINTING = "AT_PRINTING"
    AT_EMBROIDERY = "AT_EMBROIDERY"
    AT_HANDWORK = "AT_HANDWORK"
    AT_STITCHING = "AT_STITCHING"
    AT_WASHING = "AT_WASHING"
    AT_FINISHING = "AT_FINISHING"
    DYED = "DYED"
    EMBROIDERED = "EMBROIDERED"
    HANDWORKED = "HANDWORKED"
    STITCHED = "STITCHED"
    WASHED = "WASHED"
    QC_PENDING = "QC_PENDING"
    FINISHED = "FINISHED"
    PACKED = "PACKED"
    REWORK_QUEUE = "REWORK_QUEUE"
    SECONDS = "SECONDS"
    REJECTED = "REJECTED"
    SCRAP = "SCRAP"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"


_LOCATION_TYPE_PG = PG_ENUM(LocationType, name="location_type", create_type=False, native_enum=True)
_STOCK_STAGE_PG = PG_ENUM(StockStage, name="stock_stage", create_type=False, native_enum=True)


# ──────────────────────────────────────────────────────────────────────
# Lot
# ──────────────────────────────────────────────────────────────────────


class Lot(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A traceable batch of an item — one row per (firm, item, lot_number).

    Audit-sweep adds `created_by`, `updated_by`, `deleted_at` to every
    non-exempt tenant table; `lot` is non-exempt, so we inherit the full
    mixin set. The hash-chain pair (`prev_hash`, `this_hash`) is for the
    audit trail and lives outside the mixins.
    """

    __tablename__ = "lot"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "firm_id",
            "item_id",
            "lot_number",
            name="lot_org_id_firm_id_item_id_lot_number_key",
        ),
    )

    lot_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    lot_number: Mapped[str] = mapped_column(String(100), nullable=False)
    supplier_lot_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mfg_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    received_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    weight_kg: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    measured_length_m: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)
    cost_basis: Mapped[str | None] = mapped_column(String(50), nullable=True)
    primary_cost: Mapped[Any | None] = mapped_column(Numeric(15, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(
        String(3), server_default=text("'INR'"), nullable=True
    )
    grn_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


# ──────────────────────────────────────────────────────────────────────
# Location (warehouse / godown / shelf / bin / …)
# ──────────────────────────────────────────────────────────────────────


class Location(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A physical location inside a firm — warehouse, godown, shelf, etc."""

    __tablename__ = "location"
    __table_args__ = (UniqueConstraint("firm_id", "code", name="location_firm_id_code_key"),)

    location_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_type: Mapped[LocationType] = mapped_column(_LOCATION_TYPE_PG, nullable=False)
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )


# ──────────────────────────────────────────────────────────────────────
# Stock ledger — append-only audit row
# ──────────────────────────────────────────────────────────────────────


class StockLedger(Base):
    """Append-only stock-movement log. One row per inbound/outbound move.

    Service-layer rule: all writes go through `inventory_service.add_stock`
    / `remove_stock`. Direct UPDATEs / DELETEs on this table are a
    correctness bug — the position table is denormalized from this.
    """

    __tablename__ = "stock_ledger"

    stock_ledger_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
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
    location_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("location.location_id", ondelete="RESTRICT"),
        nullable=False,
    )
    txn_type: Mapped[str] = mapped_column(String(50), nullable=False)
    txn_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    qty_in: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    qty_out: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    unit_cost: Mapped[Any | None] = mapped_column(Numeric(15, 6), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase-3 manufacturing-stage hooks. Nullable; unused in MVP. Declared
    # here for ORM↔DDL drift parity since the DDL adds them on every install.
    from_stage: Mapped[StockStage | None] = mapped_column(_STOCK_STAGE_PG, nullable=True)
    to_stage: Mapped[StockStage | None] = mapped_column(_STOCK_STAGE_PG, nullable=True)
    # FK declared in DDL; not in ORM since `mo_operation` is Phase-3
    # (not modeled until manufacturing wave). The DB still enforces it.
    mo_operation_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


# ──────────────────────────────────────────────────────────────────────
# Stock position — denormalized current state
# ──────────────────────────────────────────────────────────────────────


class StockPosition(Base, AuditByMixin, SoftDeleteMixin):
    """One row per (org, firm, item, lot, location). `atp_qty` is a STORED
    generated column — Postgres recomputes it on every UPDATE.

    `on_hand_qty` = total inbound minus total outbound from `stock_ledger`.
    The service layer keeps this row in sync; never write a stock movement
    by hand without going through `inventory_service`.
    """

    __tablename__ = "stock_position"

    stock_position_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lot.lot_id", ondelete="CASCADE"),
        nullable=True,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    on_hand_qty: Mapped[Any] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=False
    )
    reserved_qty_mo: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    reserved_qty_so: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    in_transit_qty: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    # Generated column — Postgres recomputes on every UPDATE.
    atp_qty: Mapped[Any] = mapped_column(
        Numeric(15, 4),
        Computed(
            "on_hand_qty - reserved_qty_mo - reserved_qty_so - in_transit_qty",
            persisted=True,
        ),
        nullable=True,
    )
    current_cost: Mapped[Any | None] = mapped_column(Numeric(15, 6), nullable=True)
    as_of_date: Mapped[datetime.date] = mapped_column(
        Date, server_default=func.current_date(), nullable=False
    )
    # `updated_at` declared manually — DDL has it inline (no `created_at`),
    # so we can't use `TimestampMixin` (that adds both).
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "Location",
    "LocationType",
    "Lot",
    "StockLedger",
    "StockPosition",
    "StockStage",
]
