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
from . import (  # noqa: E402  (import after Base definition is required)
    banking,
    feature_flag,
    identity,
    inventory,
    masters,
    procurement,
    sales,
)
from .banking import (  # noqa: E402
    BankAccount,
    Cheque,
    ChequeStatus,
)
from .feature_flag import FeatureFlag  # noqa: E402
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
from .inventory import (  # noqa: E402
    Location,
    LocationType,
    Lot,
    StockAdjustment,
    StockLedger,
    StockPosition,
    StockStage,
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
from .procurement import (  # noqa: E402
    GRN,
    GRNLine,
    GRNStatus,
    PILine,
    POLine,
    PurchaseInvoice,
    PurchaseInvoiceLifecycleStatus,
    PurchaseOrder,
    PurchaseOrderStatus,
    VoucherStatus,
)
from .sales import (  # noqa: E402
    DCLine,
    DCStatus,
    DeliveryChallan,
    InvoiceLifecycleStatus,
    SalesInvoice,
    SalesOrder,
    SalesOrderStatus,
    SiLine,
    SOLine,
)

__all__ = [
    "GRN",
    "AppUser",
    "AuditByMixin",
    "AuditLog",
    "BankAccount",
    "Base",
    "Cheque",
    "ChequeStatus",
    "CoaGroup",
    "CostCentre",
    "CostCentreType",
    "DCLine",
    "DCStatus",
    "DeliveryChallan",
    "Device",
    "FeatureFlag",
    "Firm",
    "GRNLine",
    "GRNStatus",
    "Hsn",
    "InvoiceLifecycleStatus",
    "Item",
    "ItemType",
    "ItemUomAlt",
    "Ledger",
    "Location",
    "LocationType",
    "Lot",
    "Organization",
    "PILine",
    "POLine",
    "Party",
    "PartyAddress",
    "PartyBank",
    "PartyKyc",
    "Permission",
    "PriceList",
    "PriceListLine",
    "PurchaseInvoice",
    "PurchaseInvoiceLifecycleStatus",
    "PurchaseOrder",
    "PurchaseOrderStatus",
    "Role",
    "RolePermission",
    "SOLine",
    "SalesInvoice",
    "SalesOrder",
    "SalesOrderStatus",
    "Session",
    "SiLine",
    "Sku",
    "SoftDeleteMixin",
    "StockAdjustment",
    "StockLedger",
    "StockPosition",
    "StockStage",
    "SupplyClassification",
    "TaxStatus",
    "TimestampMixin",
    "TrackingType",
    "Uom",
    "UomType",
    "UserFirmScope",
    "UserRole",
    "VoucherStatus",
    "banking",
    "feature_flag",
    "identity",
    "inventory",
    "masters",
    "procurement",
    "sales",
]
