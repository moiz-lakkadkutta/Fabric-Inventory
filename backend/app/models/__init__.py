"""SQLAlchemy declarative base + model registry.

`Base` is the single declarative base every model inherits from.
Models register themselves into `Base.metadata` at import time, so
importing `app.models` from `alembic/env.py` is what gates `autogenerate`.

Convention:
- One file per domain (identity.py, masters.py, …).
- Re-export the model classes here so `from app.models import AppUser`
  works without callers knowing the file layout.
- TimestampMixin / SoftDeleteMixin / AuditByMixin live here so domains
  declare audit columns once.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase

from .mixins import AuditByMixin, SoftDeleteMixin, TimestampMixin


class Base(DeclarativeBase):
    """All ORM models inherit from this single declarative base."""


# Re-export model classes lazily — import the modules so models register
# their tables into Base.metadata. Order matters: parents (Organization)
# before dependents (Firm, AppUser, ...).
from . import identity, masters  # noqa: E402  (import after Base definition is required)
from .identity import (  # noqa: E402
    AppUser,
    AuditLog,
    Device,
    Firm,
    Organization,
    Permission,
    Role,
    RolePermission,
    Session,
    UserFirmScope,
    UserRole,
)
from .masters import (  # noqa: E402
    CoaGroup,
    CostCentre,
    CostCentreType,
    Hsn,
    Item,
    ItemType,
    ItemUomAlt,
    Ledger,
    Party,
    PartyAddress,
    PartyBank,
    PartyKyc,
    PriceList,
    PriceListLine,
    Sku,
    SupplyClassification,
    TaxStatus,
    TrackingType,
    Uom,
    UomType,
)

__all__ = [
    "AppUser",
    "AuditByMixin",
    "AuditLog",
    "Base",
    "CoaGroup",
    "CostCentre",
    "CostCentreType",
    "Device",
    "Firm",
    "Hsn",
    "Item",
    "ItemType",
    "ItemUomAlt",
    "Ledger",
    "Organization",
    "Party",
    "PartyAddress",
    "PartyBank",
    "PartyKyc",
    "Permission",
    "PriceList",
    "PriceListLine",
    "Role",
    "RolePermission",
    "Session",
    "Sku",
    "SoftDeleteMixin",
    "SupplyClassification",
    "TaxStatus",
    "TimestampMixin",
    "TrackingType",
    "Uom",
    "UomType",
    "UserFirmScope",
    "UserRole",
    "identity",
    "masters",
]
