"""Masters-domain ORM models — Party, Item, SKU, UOM, HSN, CoA, PriceList, CostCentre.

Mirrors `schema/ddl.sql` lines 285-569 plus the post-DDL audit_sweep
(adds `updated_at`/`created_by`/`updated_by`/`deleted_at` to every
non-exempt tenant table). Exempt-from-audit-sweep masters tables:

    uom, hsn, item_uom_alt   (catalog / pure join)

Everything else gets `TimestampMixin + AuditByMixin + SoftDeleteMixin`.

Postgres ENUMs declared in DDL are bound here with `create_type=False`
so Alembic doesn't try to recreate them. Five enum types from masters:
`tax_status`, `item_type`, `tracking_type`, `supply_classification`,
`uom_type`, `cost_centre_type`.

The drift gate (`tests/test_orm_ddl_drift.py`) now also covers these
tables — adding/changing a column without updating both ddl.sql and
this file fails CI.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .mixins import AuditByMixin, SoftDeleteMixin, TimestampMixin

_UUID_DEFAULT = func.gen_random_uuid()


# ──────────────────────────────────────────────────────────────────────
# Postgres enum bindings (DDL owns DDL CREATE TYPE; we just bind columns).
# ──────────────────────────────────────────────────────────────────────


class TaxStatus(enum.StrEnum):
    REGULAR = "REGULAR"
    COMPOSITION = "COMPOSITION"
    UNREGISTERED = "UNREGISTERED"
    CONSUMER = "CONSUMER"
    OVERSEAS = "OVERSEAS"


class ItemType(enum.StrEnum):
    RAW = "RAW"
    SEMI_FINISHED = "SEMI_FINISHED"
    FINISHED = "FINISHED"
    SERVICE = "SERVICE"
    CONSUMABLE = "CONSUMABLE"
    BY_PRODUCT = "BY_PRODUCT"
    SCRAP = "SCRAP"


class TrackingType(enum.StrEnum):
    NONE = "NONE"
    BATCH = "BATCH"
    LOT = "LOT"
    SERIAL = "SERIAL"


class UomType(enum.StrEnum):
    METER = "METER"
    PIECE = "PIECE"
    KG = "KG"
    LITER = "LITER"
    SET = "SET"
    GROSS = "GROSS"
    DOZEN = "DOZEN"
    ROLL = "ROLL"
    BUNDLE = "BUNDLE"
    OTHER = "OTHER"


class SupplyClassification(enum.StrEnum):
    SIMPLE = "SIMPLE"
    COMPOSITE_PRINCIPAL = "COMPOSITE_PRINCIPAL"
    COMPOSITE_ANCILLARY = "COMPOSITE_ANCILLARY"
    MIXED = "MIXED"


class CostCentreType(enum.StrEnum):
    OUTLET = "OUTLET"
    CHANNEL = "CHANNEL"
    SEASON = "SEASON"
    DESIGNER = "DESIGNER"
    SALESPERSON = "SALESPERSON"
    DEPARTMENT = "DEPARTMENT"


_TAX_STATUS_PG = PG_ENUM(TaxStatus, name="tax_status", create_type=False, native_enum=True)
_ITEM_TYPE_PG = PG_ENUM(ItemType, name="item_type", create_type=False, native_enum=True)
_TRACKING_TYPE_PG = PG_ENUM(TrackingType, name="tracking_type", create_type=False, native_enum=True)
_UOM_TYPE_PG = PG_ENUM(UomType, name="uom_type", create_type=False, native_enum=True)
_SUPPLY_CLASS_PG = PG_ENUM(
    SupplyClassification, name="supply_classification", create_type=False, native_enum=True
)
_COST_CENTRE_TYPE_PG = PG_ENUM(
    CostCentreType, name="cost_centre_type", create_type=False, native_enum=True
)


# ──────────────────────────────────────────────────────────────────────
# Party + sub-tables
# ──────────────────────────────────────────────────────────────────────


class Party(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "party"
    __table_args__ = (
        UniqueConstraint("org_id", "firm_id", "code", name="party_org_id_firm_id_code_key"),
    )

    party_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    party_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_supplier: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    is_customer: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    is_karigar: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    is_transporter: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    tax_status: Mapped[TaxStatus] = mapped_column(
        _TAX_STATUS_PG, server_default=text("'UNREGISTERED'::tax_status"), nullable=False
    )
    gstin: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    pan: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    aadhaar_last_4: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_sez: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    is_export: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    account_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    credit_days: Mapped[int | None] = mapped_column(
        SmallInteger, server_default=text("0"), nullable=True
    )
    credit_limit: Mapped[Any | None] = mapped_column(
        Numeric(15, 2), server_default=text("0"), nullable=True
    )
    charge_overdue_interest: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    price_list_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Override AuditByMixin's plain UUID columns to add the FK refs that
    # `party.created_by`/`updated_by` declare inline in the DDL (not the
    # generic audit_sweep version).
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

    addresses: Mapped[list[PartyAddress]] = relationship(
        back_populates="party", cascade="all, delete-orphan"
    )
    banks: Mapped[list[PartyBank]] = relationship(
        back_populates="party", cascade="all, delete-orphan"
    )
    kyc: Mapped[list[PartyKyc]] = relationship(back_populates="party", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"Party(party_id={self.party_id!r}, code={self.code!r}, name={self.name!r})"


class PartyAddress(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "party_address"

    party_address_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="CASCADE"),
        nullable=False,
    )
    address_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_line_1: Mapped[str] = mapped_column(Text, nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), server_default="IN", nullable=True)
    is_primary: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    latitude: Mapped[Any | None] = mapped_column(Numeric(10, 8), nullable=True)
    longitude: Mapped[Any | None] = mapped_column(Numeric(11, 8), nullable=True)

    party: Mapped[Party] = relationship(back_populates="addresses")


class PartyBank(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "party_bank"

    party_bank_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="CASCADE"),
        nullable=False,
    )
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_holder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_number: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ifsc_code: Mapped[str | None] = mapped_column(String(11), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_primary: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    upi_id: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    party: Mapped[Party] = relationship(back_populates="banks")


class PartyKyc(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "party_kyc"

    party_kyc_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="CASCADE"),
        nullable=False,
    )
    kyc_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gstin_verified_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pan_verified_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bank_verified_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    msme_udyam_number: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    last_kyc_refresh_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    party: Mapped[Party] = relationship(back_populates="kyc")


# ──────────────────────────────────────────────────────────────────────
# Item / SKU / UOM / HSN
# ──────────────────────────────────────────────────────────────────────


class Item(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "item"
    __table_args__ = (
        UniqueConstraint("org_id", "firm_id", "code", name="item_org_id_firm_id_code_key"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[ItemType] = mapped_column(_ITEM_TYPE_PG, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_uom: Mapped[UomType] = mapped_column(_UOM_TYPE_PG, nullable=False)
    tracking: Mapped[TrackingType | None] = mapped_column(
        _TRACKING_TYPE_PG, server_default=text("'NONE'::tracking_type"), nullable=True
    )
    has_variants: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    parent_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="SET NULL"),
        nullable=True,
    )
    variant_axes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    gst_rate: Mapped[Any | None] = mapped_column(Numeric(5, 2), nullable=True)
    supply_classification: Mapped[SupplyClassification | None] = mapped_column(
        _SUPPLY_CLASS_PG,
        server_default=text("'SIMPLE'::supply_classification"),
        nullable=True,
    )
    has_expiry: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    allow_negative: Mapped[str | None] = mapped_column(
        String(50), server_default="NEVER", nullable=True
    )
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # `item.created_by`/`updated_by` declare FK refs inline in the DDL.
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

    skus: Mapped[list[Sku]] = relationship(back_populates="item", cascade="all, delete-orphan")
    uom_alts: Mapped[list[ItemUomAlt]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Item(item_id={self.item_id!r}, code={self.code!r}, name={self.name!r})"


class Sku(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "sku"
    __table_args__ = (
        UniqueConstraint("org_id", "firm_id", "code", name="sku_org_id_firm_id_code_key"),
    )

    sku_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    variant_attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    barcode_ean13: Mapped[str | None] = mapped_column(String(13), nullable=True)
    default_cost: Mapped[Any | None] = mapped_column(Numeric(15, 4), nullable=True)

    item: Mapped[Item] = relationship(back_populates="skus")


class Uom(Base):
    """Global catalog of UOM types (METER, KG, PIECE, …). Audit-sweep exempt."""

    __tablename__ = "uom"

    uom_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    uom_type: Mapped[UomType] = mapped_column(_UOM_TYPE_PG, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ItemUomAlt(Base):
    """Item-specific UOM conversion (e.g. meter → roll = 50). Audit-sweep exempt."""

    __tablename__ = "item_uom_alt"
    __table_args__ = (
        UniqueConstraint(
            "item_id", "from_uom", "to_uom", name="item_uom_alt_item_id_from_uom_to_uom_key"
        ),
    )

    item_uom_alt_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_uom: Mapped[UomType] = mapped_column(_UOM_TYPE_PG, nullable=False)
    to_uom: Mapped[UomType] = mapped_column(_UOM_TYPE_PG, nullable=False)
    conversion_factor: Mapped[Any] = mapped_column(Numeric(15, 6), nullable=False)
    is_fixed: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    item: Mapped[Item] = relationship(back_populates="uom_alts")


class Hsn(Base):
    """Global HSN catalog. Audit-sweep exempt."""

    __tablename__ = "hsn"

    hsn_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    hsn_code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    gst_rate: Mapped[Any | None] = mapped_column(Numeric(5, 2), nullable=True)
    is_rcm_applicable: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ──────────────────────────────────────────────────────────────────────
# Chart of Accounts: CoaGroup → Ledger
# ──────────────────────────────────────────────────────────────────────


class CoaGroup(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """Chart of accounts hierarchy node. Indian-style CoA (Asset / Liability / …)."""

    __tablename__ = "coa_group"
    __table_args__ = (UniqueConstraint("org_id", "code", name="coa_group_org_id_code_key"),)

    coa_group_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_group_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("coa_group.coa_group_id", ondelete="RESTRICT"),
        nullable=True,
    )
    is_system_group: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )

    ledgers: Mapped[list[Ledger]] = relationship(back_populates="coa_group")


class Ledger(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """A GL account (e.g. "Cash", "Sales Revenue", "Sundry Debtors / Acme Co")."""

    __tablename__ = "ledger"
    __table_args__ = (
        UniqueConstraint("org_id", "firm_id", "code", name="ledger_org_id_firm_id_code_key"),
    )

    ledger_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ledger_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    coa_group_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("coa_group.coa_group_id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_control_account: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="SET NULL"),
        nullable=True,
    )
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    opening_balance: Mapped[Any | None] = mapped_column(
        Numeric(15, 2), server_default=text("0"), nullable=True
    )
    opening_balance_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    # `ledger.created_by`/`updated_by` declare FK refs inline in the DDL.
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

    coa_group: Mapped[CoaGroup] = relationship(back_populates="ledgers")


# ──────────────────────────────────────────────────────────────────────
# Pricing
# ──────────────────────────────────────────────────────────────────────


class PriceList(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "price_list"
    __table_args__ = (
        UniqueConstraint("org_id", "firm_id", "code", name="price_list_org_id_firm_id_code_key"),
    )

    price_list_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    valid_from: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    is_party_specific: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("party.party_id", ondelete="CASCADE"),
        nullable=True,
    )

    lines: Mapped[list[PriceListLine]] = relationship(
        back_populates="price_list", cascade="all, delete-orphan"
    )


class PriceListLine(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "price_list_line"

    price_list_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    price_list_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("price_list.price_list_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("item.item_id", ondelete="RESTRICT"),
        nullable=False,
    )
    sku_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sku.sku_id", ondelete="SET NULL"),
        nullable=True,
    )
    selling_price: Mapped[Any] = mapped_column(Numeric(15, 4), nullable=False)
    min_qty: Mapped[Any | None] = mapped_column(
        Numeric(15, 4), server_default=text("0"), nullable=True
    )
    currency: Mapped[str | None] = mapped_column(String(3), server_default="INR", nullable=True)

    price_list: Mapped[PriceList] = relationship(back_populates="lines")


# ──────────────────────────────────────────────────────────────────────
# Cost Centre
# ──────────────────────────────────────────────────────────────────────


class CostCentre(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "cost_centre"
    __table_args__ = (UniqueConstraint("firm_id", "code", name="cost_centre_firm_id_code_key"),)

    cost_centre_id: Mapped[uuid.UUID] = mapped_column(
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
    cost_centre_type: Mapped[CostCentreType | None] = mapped_column(
        _COST_CENTRE_TYPE_PG, nullable=True
    )
    parent_cost_centre_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cost_centre.cost_centre_id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
